from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.tools import format_datetime


class ClinicDashboard(models.AbstractModel):
    _name = 'clinic.dashboard'
    _description = 'Clinic Dashboard'

    @api.model
    def _get_period(self, period, date_from, date_to):
        today = fields.Date.context_today(self)
        if period == 'week':
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=6)
        if period == 'month':
            start = today.replace(day=1)
            return start, start + relativedelta(months=1, days=-1)
        if period == 'custom' and date_from and date_to:
            start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
            return (start, end) if start <= end else (end, start)
        return today, today

    @api.model
    def _to_utc(self, day):
        """Start of ``day`` in the user's timezone, expressed as naive UTC (for Datetime fields)."""
        tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def get_dashboard_data(self, period='today', date_from=None, date_to=None):
        start, end = self._get_period(period, date_from, date_to)
        # string values keep the domains JSON-serializable for the client
        start_dt = fields.Datetime.to_string(self._to_utc(start))
        end_dt = fields.Datetime.to_string(self._to_utc(end + timedelta(days=1)))
        start_d, end_d = fields.Date.to_string(start), fields.Date.to_string(end)
        company_dom = [('company_id', 'in', self.env.companies.ids)]
        Appointment = self.env['clinic.appointment']
        Admission = self.env['clinic.admission']
        Bed = self.env['clinic.bed']
        Move = self.env['account.move'].sudo()

        appt_period_dom = company_dom + [('appointment_date', '>=', start_dt), ('appointment_date', '<', end_dt)]
        new_patient_dom = company_dom + [('create_date', '>=', start_dt), ('create_date', '<', end_dt)]
        discharge_dom = company_dom + [('state', '=', 'done'), ('discharge_date', '>=', start_dt), ('discharge_date', '<', end_dt)]
        invoice_dom = company_dom + [('clinic_patient_id', '!=', False), ('state', '=', 'posted'),
                                     ('move_type', 'in', ('out_invoice', 'out_refund'))]
        revenue_dom = invoice_dom + [('invoice_date', '>=', start_d), ('invoice_date', '<=', end_d)]
        pending_dom = invoice_dom + [('move_type', '=', 'out_invoice'), ('amount_residual', '>', 0)]

        bed_counts = {state: count for state, count in Bed._read_group(company_dom, ['state'], ['__count'])}
        kpis = {
            'total_patients': self.env['clinic.patient'].search_count(company_dom),
            'new_patients': self.env['clinic.patient'].search_count(new_patient_dom),
            'appointments': Appointment.search_count(appt_period_dom + [('state', 'not in', ('cancelled', 'no_show'))]),
            'admitted': Admission.search_count(company_dom + [('state', '=', 'admitted')]),
            'available_beds': bed_counts.get('available', 0),
            'occupied_beds': bed_counts.get('occupied', 0),
            'maintenance_beds': bed_counts.get('maintenance', 0),
            'discharges': self.env['clinic.discharge'].search_count(discharge_dom),
            'doctors': self.env['clinic.doctor'].search_count(company_dom),
            'revenue': sum(Move.search(revenue_dom).mapped('amount_total_signed')),
            'pending': sum(Move.search(pending_dom).mapped('amount_residual_signed')),
            'pending_count': Move.search_count(pending_dom),
        }
        total_beds = sum(bed_counts.values())
        kpis['occupancy_rate'] = round(100.0 * kpis['occupied_beds'] / total_beds, 1) if total_beds else 0.0

        return {
            'period': {'start': start_d, 'end': end_d},
            'domains': {
                'appointments': appt_period_dom + [('state', 'not in', ('cancelled', 'no_show'))],
                'new_patients': new_patient_dom,
                'discharges': discharge_dom,
                'revenue': revenue_dom,
                'pending': pending_dom,
            },
            'currency_id': self.env.company.currency_id.id,
            'kpis': kpis,
            'charts': {
                'revenue': self._chart_monthly_revenue(invoice_dom, end),
                'appointments': self._chart_weekly_appointments(company_dom, start, end),
                'admissions': self._chart_admissions(company_dom, end),
                'beds': {
                    'labels': [self.env._("Available"), self.env._("Occupied"), self.env._("Maintenance")],
                    'values': [kpis['available_beds'], kpis['occupied_beds'], kpis['maintenance_beds']],
                },
            },
            'bed_overview': self._bed_overview(company_dom),
            'recent_appointments': self._appointment_rows(Appointment.search(appt_period_dom, order='appointment_date desc', limit=6)),
            'upcoming_appointments': self._appointment_rows(Appointment.search(
                company_dom + [('appointment_date', '>=', fields.Datetime.to_string(fields.Datetime.now())),
                               ('state', 'in', ('draft', 'confirmed'))],
                order='appointment_date asc', limit=6)),
            'recent_patients': [{
                'id': p.id, 'name': p.name, 'ref': p.patient_ref, 'gender': p.gender or '',
                'age': p.age_display or '', 'phone': p.phone or '',
                'date': format_datetime(self.env, p.create_date, dt_format='medium'),
            } for p in self.env['clinic.patient'].search(company_dom, order='create_date desc', limit=6)],
        }

    @api.model
    def _appointment_rows(self, appointments):
        states = dict(appointments._fields['state']._description_selection(self.env))
        return [{
            'id': a.id, 'name': a.name, 'patient': a.patient_id.name, 'doctor': a.doctor_id.name,
            'date': format_datetime(self.env, a.appointment_date, dt_format='short'),
            'state': a.state, 'state_label': states.get(a.state),
        } for a in appointments]

    @api.model
    def _chart_monthly_revenue(self, invoice_dom, end):
        first = end.replace(day=1) - relativedelta(months=11)
        months = [first + relativedelta(months=i) for i in range(12)]
        groups = self.env['account.move'].sudo()._read_group(
            invoice_dom + [('invoice_date', '>=', first), ('invoice_date', '<=', end)],
            ['invoice_date:month'], ['amount_total_signed:sum'])
        totals = {month.strftime('%Y-%m'): amount for month, amount in groups if month}
        return {
            'labels': [m.strftime('%b %Y') for m in months],
            'values': [totals.get(m.strftime('%Y-%m'), 0.0) for m in months],
        }

    @api.model
    def _chart_weekly_appointments(self, company_dom, start, end):
        """Current week (Mon-Sun) when today is in the period, otherwise the last 7 days of the period."""
        today = fields.Date.context_today(self)
        first = today - timedelta(days=today.weekday()) if start <= today <= end else end - timedelta(days=6)
        days = [first + timedelta(days=i) for i in range(7)]
        end = days[-1]
        appointments = self.env['clinic.appointment'].search(company_dom + [
            ('appointment_date', '>=', self._to_utc(days[0])), ('appointment_date', '<', self._to_utc(end + timedelta(days=1))),
        ])
        scheduled = dict.fromkeys(days, 0)
        completed = dict.fromkeys(days, 0)
        for appointment in appointments:
            day = fields.Datetime.context_timestamp(self, appointment.appointment_date).date()
            if day in scheduled and appointment.state not in ('cancelled', 'no_show'):
                scheduled[day] += 1
                if appointment.state == 'done':
                    completed[day] += 1
        return {
            'labels': [d.strftime('%a %d') for d in days],
            'scheduled': [scheduled[d] for d in days],
            'completed': [completed[d] for d in days],
        }

    @api.model
    def _chart_admissions(self, company_dom, end):
        first = end.replace(day=1) - relativedelta(months=5)
        months = [first + relativedelta(months=i) for i in range(6)]
        start_dt, end_dt = self._to_utc(first), self._to_utc(end.replace(day=1) + relativedelta(months=1))
        admissions = self.env['clinic.admission'].search(company_dom + [
            ('state', 'in', ('admitted', 'discharged')), ('admission_date', '>=', start_dt), ('admission_date', '<', end_dt)])
        discharges = self.env['clinic.admission'].search(company_dom + [
            ('state', '=', 'discharged'), ('discharge_date', '>=', start_dt), ('discharge_date', '<', end_dt)])

        def count_by_month(records, field):
            counts = {}
            for record in records:
                key = fields.Datetime.context_timestamp(self, record[field]).strftime('%Y-%m')
                counts[key] = counts.get(key, 0) + 1
            return counts

        admitted, discharged = count_by_month(admissions, 'admission_date'), count_by_month(discharges, 'discharge_date')
        return {
            'labels': [m.strftime('%b %Y') for m in months],
            'admissions': [admitted.get(m.strftime('%Y-%m'), 0) for m in months],
            'discharges': [discharged.get(m.strftime('%Y-%m'), 0) for m in months],
        }

    @api.model
    def _bed_overview(self, company_dom):
        rows = []
        for category in self.env['clinic.room.category'].search(company_dom):
            beds = self.env['clinic.bed'].search(company_dom + [('category_id', '=', category.id)])
            total = len(beds)
            occupied = len(beds.filtered(lambda b: b.state == 'occupied'))
            rows.append({
                'id': category.id, 'name': category.name, 'total': total, 'occupied': occupied,
                'available': len(beds.filtered(lambda b: b.state == 'available')),
                'rate': round(100.0 * occupied / total) if total else 0,
            })
        return rows
