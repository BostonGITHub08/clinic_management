from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicConsultation(models.Model):
    _name = 'clinic.consultation'
    _description = 'OPD Consultation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    appointment_id = fields.Many2one('clinic.appointment', readonly=True, copy=False)
    patient_id = fields.Many2one('clinic.patient', required=True, tracking=True, index=True)
    patient_age = fields.Char(related='patient_id.age_display')
    patient_gender = fields.Selection(related='patient_id.gender')
    patient_allergies = fields.Text(related='patient_id.allergies')
    doctor_id = fields.Many2one('clinic.doctor', required=True, tracking=True, index=True)
    date = fields.Datetime(string="Check-in Time", default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Checked In'),
        ('in_progress', 'In Consultation'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)

    # vital signs
    temperature = fields.Float(string="Temperature (°C)", digits=(4, 1))
    bp_systolic = fields.Integer(string="BP Systolic")
    bp_diastolic = fields.Integer(string="BP Diastolic")
    blood_pressure = fields.Char(compute='_compute_blood_pressure')
    pulse = fields.Integer(string="Pulse (bpm)")
    respiratory_rate = fields.Integer(string="Respiratory Rate")
    weight = fields.Float(string="Weight (kg)", digits=(5, 1))
    height = fields.Float(string="Height (cm)", digits=(5, 1))
    bmi = fields.Float(string="BMI", compute='_compute_bmi', store=True, digits=(4, 1))
    spo2 = fields.Integer(string="Oxygen Saturation (%)")

    symptoms = fields.Text()
    diagnosis = fields.Text(tracking=True)
    doctor_notes = fields.Html()
    treatment_plan = fields.Text()
    follow_up_date = fields.Date()
    follow_up_appointment_id = fields.Many2one('clinic.appointment', readonly=True, copy=False)
    prescription_ids = fields.One2many('clinic.prescription', 'consultation_id')
    lab_request_ids = fields.One2many('clinic.lab.request', 'consultation_id')
    prescription_count = fields.Integer(compute='_compute_counts')
    lab_request_count = fields.Integer(compute='_compute_counts')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.depends('weight', 'height')
    def _compute_bmi(self):
        for consultation in self:
            height_m = consultation.height / 100.0
            consultation.bmi = consultation.weight / (height_m * height_m) if height_m else 0.0

    @api.depends('bp_systolic', 'bp_diastolic')
    def _compute_blood_pressure(self):
        for consultation in self:
            consultation.blood_pressure = (
                f"{consultation.bp_systolic}/{consultation.bp_diastolic}"
                if consultation.bp_systolic and consultation.bp_diastolic else False)

    def _compute_counts(self):
        for consultation in self:
            consultation.prescription_count = len(consultation.prescription_ids)
            consultation.lab_request_count = len(consultation.lab_request_ids)

    @api.constrains('temperature', 'pulse', 'spo2', 'weight', 'height', 'bp_systolic', 'bp_diastolic')
    def _check_vitals(self):
        for c in self:
            if c.temperature and not 30 <= c.temperature <= 45:
                raise ValidationError(self.env._("Temperature must be between 30 and 45 °C."))
            if c.spo2 and not 0 < c.spo2 <= 100:
                raise ValidationError(self.env._("Oxygen saturation must be between 1 and 100%."))
            if any(v < 0 for v in (c.pulse, c.weight, c.height, c.bp_systolic, c.bp_diastolic)):
                raise ValidationError(self.env._("Vital signs cannot be negative."))

    @api.constrains('follow_up_date', 'date')
    def _check_follow_up(self):
        for consultation in self:
            if consultation.follow_up_date and consultation.follow_up_date < consultation.date.date():
                raise ValidationError(self.env._("The follow-up date cannot be before the consultation date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.consultation') or 'New'
        return super().create(vals_list)

    def action_start(self):
        for consultation in self.filtered(lambda c: c.state == 'draft'):
            consultation.state = 'in_progress'
            if consultation.appointment_id.state in ('confirmed', 'checked_in'):
                consultation.appointment_id.state = 'in_consultation'

    def action_done(self):
        for consultation in self:
            if consultation.state in ('done', 'cancelled'):
                raise UserError(self.env._("Consultation %s is already closed.", consultation.name))
            if not consultation.diagnosis:
                raise UserError(self.env._("Please enter a diagnosis before completing consultation %s.", consultation.name))
            consultation.state = 'done'
            consultation._create_follow_up_appointment()
            if not self.env.context.get('from_appointment') and consultation.appointment_id.state in ('checked_in', 'in_consultation'):
                consultation.appointment_id.state = 'done'

    def _create_follow_up_appointment(self):
        self.ensure_one()
        if not self.follow_up_date or self.follow_up_appointment_id:
            return
        self.follow_up_appointment_id = self.env['clinic.appointment']._schedule_follow_up(
            self.patient_id, self.doctor_id, self.follow_up_date, self.company_id,
            self.env._("Follow-up of %s", self.name))

    def action_cancel(self):
        self.filtered(lambda c: c.state != 'done').write({'state': 'cancelled'})

    def _new_document_action(self, model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'form',
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
                'default_consultation_id': self.id,
            },
        }

    def action_create_prescription(self):
        return self._new_document_action('clinic.prescription', self.env._("New Prescription"))

    def action_create_lab_request(self):
        return self._new_document_action('clinic.lab.request', self.env._("New Lab Request"))

    def _related_action(self, model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [('consultation_id', '=', self.id)],
            'context': {'default_patient_id': self.patient_id.id, 'default_doctor_id': self.doctor_id.id,
                        'default_consultation_id': self.id},
        }

    def action_view_prescriptions(self):
        return self._related_action('clinic.prescription', self.env._("Prescriptions"))

    def action_view_lab_requests(self):
        return self._related_action('clinic.lab.request', self.env._("Lab Requests"))
