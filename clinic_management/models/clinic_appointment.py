from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_datetime


class ClinicAppointment(models.Model):
    _name = 'clinic.appointment'
    _description = 'Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'clinic.billing.mixin']
    _order = 'appointment_date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', required=True, tracking=True, index=True)
    patient_phone = fields.Char(related='patient_id.phone')
    patient_age = fields.Char(related='patient_id.age_display')
    doctor_id = fields.Many2one('clinic.doctor', required=True, tracking=True, index=True, check_company=True)
    department_id = fields.Many2one('clinic.department', compute='_compute_department', store=True, readonly=False)
    appointment_date = fields.Datetime(string="Date & Time", required=True, tracking=True, default=fields.Datetime.now)
    duration = fields.Float(default=lambda self: self.env.company.clinic_appointment_duration or 0.5)
    end_datetime = fields.Datetime(string="End", compute='_compute_end_datetime', store=True)
    appointment_type = fields.Selection([
        ('new', 'New Consultation'),
        ('follow_up', 'Follow-up'),
        ('checkup', 'Routine Check-up'),
        ('emergency', 'Emergency'),
    ], string="Type", default='new', required=True)
    symptoms = fields.Text()
    notes = fields.Text()
    consultation_fee = fields.Monetary(compute='_compute_fee', store=True, readonly=False, currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('in_consultation', 'In Consultation'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ], default='draft', required=True, tracking=True, index=True)
    priority = fields.Selection([('0', 'Normal'), ('1', 'Urgent')], default='0')
    consultation_id = fields.Many2one('clinic.consultation', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    color = fields.Integer(related='doctor_id.color')

    @api.depends('doctor_id')
    def _compute_department(self):
        for appointment in self:
            if appointment.doctor_id.department_id:
                appointment.department_id = appointment.doctor_id.department_id

    @api.depends('doctor_id')
    def _compute_fee(self):
        for appointment in self:
            appointment.consultation_fee = appointment.doctor_id.consultation_fee

    @api.depends('appointment_date', 'duration')
    def _compute_end_datetime(self):
        for appointment in self:
            appointment.end_datetime = appointment.appointment_date and (
                appointment.appointment_date + timedelta(hours=appointment.duration or 0.0))

    @api.constrains('duration', 'consultation_fee')
    def _check_values(self):
        for appointment in self:
            if appointment.duration <= 0:
                raise ValidationError(self.env._("The appointment duration must be positive."))
            if appointment.consultation_fee < 0:
                raise ValidationError(self.env._("The consultation fee cannot be negative."))

    @api.constrains('doctor_id', 'appointment_date', 'end_datetime', 'state')
    def _check_doctor_conflict(self):
        for appointment in self.filtered(lambda a: a.state not in ('cancelled', 'no_show')):
            conflict = self.search([
                ('id', '!=', appointment.id),
                ('doctor_id', '=', appointment.doctor_id.id),
                ('state', 'not in', ('cancelled', 'no_show')),
                ('appointment_date', '<', appointment.end_datetime),
                ('end_datetime', '>', appointment.appointment_date),
            ], limit=1)
            if conflict:
                raise ValidationError(self.env._(
                    "%(doctor)s already has appointment %(ref)s for %(patient)s at %(time)s.",
                    doctor=appointment.doctor_id.name, ref=conflict.name,
                    patient=conflict.patient_id.name, time=format_datetime(self.env, conflict.appointment_date)))

    @api.constrains('doctor_id', 'appointment_date', 'duration')
    def _check_doctor_availability(self):
        if self.env.context.get('clinic_skip_availability'):
            return
        for appointment in self.filtered(lambda a: a.state in ('draft', 'confirmed')):
            doctor = appointment.doctor_id
            if not appointment.company_id.clinic_check_doctor_availability or not doctor.available_day_ids:
                continue
            local_start = fields.Datetime.context_timestamp(appointment, appointment.appointment_date)
            start_hour = local_start.hour + local_start.minute / 60.0
            if local_start.weekday() not in doctor.available_day_ids.mapped('code'):
                raise ValidationError(self.env._(
                    "%(doctor)s is not available on %(day)s. Available days: %(days)s.",
                    doctor=doctor.name, day=local_start.strftime('%A'),
                    days=", ".join(doctor.available_day_ids.mapped('name'))))
            if start_hour < doctor.work_from or start_hour + appointment.duration > doctor.work_to:
                raise ValidationError(self.env._(
                    "The appointment is outside the working hours of %(doctor)s (%(start)s - %(end)s).",
                    doctor=doctor.name, start=self._float_to_time(doctor.work_from), end=self._float_to_time(doctor.work_to)))

    @staticmethod
    def _float_to_time(value):
        return f"{int(value):02d}:{round((value % 1) * 60):02d}"

    @api.model
    def _schedule_follow_up(self, patient, doctor, date, company, note):
        """Create a follow-up appointment in the doctor's first free slot of ``date``."""
        hour = doctor.work_from or 9.0
        local_dt = datetime.combine(date, time(int(hour), int(round((hour % 1) * 60))))
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        start = tz.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)
        duration = company.clinic_appointment_duration or 0.5
        busy = self.search([
            ('doctor_id', '=', doctor.id), ('state', 'not in', ('cancelled', 'no_show')), ('end_datetime', '>', start),
        ], order='appointment_date')
        for existing in busy:
            if existing.appointment_date < start + timedelta(hours=duration):
                start = max(start, existing.end_datetime)
        return self.with_context(clinic_skip_availability=True).create({
            'patient_id': patient.id,
            'doctor_id': doctor.id,
            'appointment_date': start,
            'duration': duration,
            'appointment_type': 'follow_up',
            'notes': note,
            'company_id': company.id,
        })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.appointment') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(appointment.state not in ('draft', 'cancelled') for appointment in self):
            raise UserError(self.env._("Only draft or cancelled appointments can be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------ workflow
    def _check_state(self, allowed):
        for appointment in self:
            if appointment.state not in allowed:
                raise UserError(self.env._("This action is not allowed for appointment %(ref)s in state '%(state)s'.",
                                           ref=appointment.name,
                                           state=dict(self._fields['state'].selection)[appointment.state]))

    def action_confirm(self):
        self._check_state(('draft',))
        self.state = 'confirmed'

    def action_check_in(self):
        self._check_state(('draft', 'confirmed'))
        for appointment in self:
            if not appointment.consultation_id:
                appointment.consultation_id = self.env['clinic.consultation'].create({
                    'appointment_id': appointment.id,
                    'patient_id': appointment.patient_id.id,
                    'doctor_id': appointment.doctor_id.id,
                    'symptoms': appointment.symptoms,
                    'company_id': appointment.company_id.id,
                })
        self.state = 'checked_in'

    def action_start_consultation(self):
        self.ensure_one()
        if self.state in ('draft', 'confirmed'):
            self.action_check_in()
        self._check_state(('checked_in', 'in_consultation'))
        self.state = 'in_consultation'
        if self.consultation_id.state == 'draft':
            self.consultation_id.state = 'in_progress'
        return self.action_view_consultation()

    def action_done(self):
        self._check_state(('checked_in', 'in_consultation'))
        self.consultation_id.filtered(lambda c: c.state != 'done').with_context(from_appointment=True).action_done()
        self.state = 'done'

    def action_cancel(self):
        self._check_state(('draft', 'confirmed', 'checked_in'))
        self.consultation_id.filtered(lambda c: c.state != 'done').write({'state': 'cancelled'})
        self.state = 'cancelled'

    def action_no_show(self):
        self._check_state(('draft', 'confirmed'))
        self.state = 'no_show'

    def action_reset_draft(self):
        self._check_state(('cancelled', 'no_show'))
        self.state = 'draft'

    def action_view_consultation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Consultation"),
            'res_model': 'clinic.consultation',
            'res_id': self.consultation_id.id,
            'view_mode': 'form',
        }

    def _get_invoice_lines(self):
        if not self.consultation_fee:
            return []
        product = self.company_id._clinic_product('consultation')
        return [self._invoice_line(
            product, self.env._("Consultation - %(doctor)s (%(ref)s)", doctor=self.doctor_id.name, ref=self.name),
            1, self.consultation_fee)]

    def action_create_invoice(self):
        self._check_state(('checked_in', 'in_consultation', 'done'))
        return super().action_create_invoice()
