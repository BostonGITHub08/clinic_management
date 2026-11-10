from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ClinicDoctor(models.Model):
    _name = 'clinic.doctor'
    _description = 'Doctor'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    doctor_ref = fields.Char(string="Doctor ID", readonly=True, copy=False, default='New')
    user_id = fields.Many2one('res.users', string="Related User", help="Gives this user the Doctor access rights.")
    department_id = fields.Many2one('clinic.department', tracking=True)
    specialization_id = fields.Many2one('clinic.specialization', tracking=True)
    qualification = fields.Char(string="Qualifications")
    experience_years = fields.Integer(string="Experience (Years)")
    phone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()
    consultation_fee = fields.Monetary(currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    available_day_ids = fields.Many2many('clinic.weekday', string="Available Days",
                                         default=lambda self: self.env['clinic.weekday'].search([('code', '<', 6)]))
    work_from = fields.Float(string="Working From", default=9.0)
    work_to = fields.Float(string="Working To", default=17.0)
    color = fields.Integer()
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    appointment_ids = fields.One2many('clinic.appointment', 'doctor_id', string="Appointments")
    patient_ids = fields.Many2many('clinic.patient', compute='_compute_patients', string="Patients")
    appointment_count = fields.Integer(compute='_compute_counts')
    patient_count = fields.Integer(compute='_compute_patients')
    admission_count = fields.Integer(compute='_compute_counts')
    today_appointment_count = fields.Integer(compute='_compute_counts')

    def _compute_patients(self):
        for doctor in self:
            admissions = self.env['clinic.admission'].search([('doctor_id', '=', doctor.id)])
            doctor.patient_ids = doctor.appointment_ids.patient_id | admissions.patient_id
            doctor.patient_count = len(doctor.patient_ids)

    def _compute_counts(self):
        today = fields.Date.context_today(self)
        for doctor in self:
            doctor.appointment_count = len(doctor.appointment_ids)
            doctor.today_appointment_count = len(doctor.appointment_ids.filtered(
                lambda a: a.appointment_date and fields.Datetime.context_timestamp(a, a.appointment_date).date() == today
                and a.state not in ('cancelled', 'no_show')))
            doctor.admission_count = self.env['clinic.admission'].search_count([('doctor_id', '=', doctor.id)])

    @api.constrains('work_from', 'work_to')
    def _check_working_hours(self):
        for doctor in self:
            if not (0 <= doctor.work_from < doctor.work_to <= 24):
                raise ValidationError(self.env._("Working hours must be between 00:00 and 24:00 and 'From' must be before 'To'."))

    @api.constrains('consultation_fee')
    def _check_fee(self):
        if any(doctor.consultation_fee < 0 for doctor in self):
            raise ValidationError(self.env._("The consultation fee cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('doctor_ref', 'New') == 'New':
                vals['doctor_ref'] = self.env['ir.sequence'].next_by_code('clinic.doctor') or 'New'
        doctors = super().create(vals_list)
        doctors._grant_doctor_access()
        return doctors

    def write(self, vals):
        res = super().write(vals)
        if 'user_id' in vals:
            self._grant_doctor_access()
        return res

    def _grant_doctor_access(self):
        group = self.env.ref('clinic_management.group_clinic_doctor')
        users = self.user_id.filtered(lambda u: group not in u.all_group_ids)
        if users:
            users.sudo().write({'group_ids': [(4, group.id)]})

    def _open_related(self, model, name, domain, view_mode='list,form'):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': view_mode,
            'domain': domain,
            'context': {'default_doctor_id': self.id},
        }

    def action_view_appointments(self):
        self.ensure_one()
        return self._open_related('clinic.appointment', self.env._("Appointments"), [('doctor_id', '=', self.id)], 'calendar,list,form')

    def action_view_patients(self):
        self.ensure_one()
        action = self._open_related('clinic.patient', self.env._("Patients"), [('id', 'in', self.patient_ids.ids)], 'kanban,list,form')
        action['context'] = {}
        return action

    def action_view_admissions(self):
        self.ensure_one()
        return self._open_related('clinic.admission', self.env._("Admissions"), [('doctor_id', '=', self.id)])
