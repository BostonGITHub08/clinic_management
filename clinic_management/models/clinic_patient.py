from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

BLOOD_GROUPS = [
    ('a+', 'A+'), ('a-', 'A-'), ('b+', 'B+'), ('b-', 'B-'),
    ('ab+', 'AB+'), ('ab-', 'AB-'), ('o+', 'O+'), ('o-', 'O-'),
]


class ClinicPatient(models.Model):
    _name = 'clinic.patient'
    _description = 'Patient'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}
    _order = 'id desc'
    _rec_names_search = ['name', 'patient_ref', 'phone', 'email']

    partner_id = fields.Many2one('res.partner', string="Related Partner", required=True, ondelete='restrict', index=True)
    patient_ref = fields.Char(string="Patient ID", readonly=True, copy=False, default='New', index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')], tracking=True)
    date_of_birth = fields.Date(tracking=True)
    age = fields.Integer(string="Age (Years)", compute='_compute_age')
    age_display = fields.Char(string="Age", compute='_compute_age')
    blood_group = fields.Selection(BLOOD_GROUPS, tracking=True)
    emergency_contact_name = fields.Char(string="Emergency Contact")
    emergency_contact_phone = fields.Char(string="Emergency Phone")
    emergency_contact_relation = fields.Char(string="Relation")
    medical_history = fields.Html()
    allergies = fields.Text()
    disease_ids = fields.Many2many('clinic.disease', string="Existing Diseases")
    document_ids = fields.Many2many('ir.attachment', 'clinic_patient_attachment_rel', 'patient_id', 'attachment_id', string="Documents")

    appointment_ids = fields.One2many('clinic.appointment', 'patient_id', string="Appointments")
    consultation_ids = fields.One2many('clinic.consultation', 'patient_id', string="Visits")
    admission_ids = fields.One2many('clinic.admission', 'patient_id', string="Admissions")
    prescription_ids = fields.One2many('clinic.prescription', 'patient_id', string="Prescriptions")
    lab_request_ids = fields.One2many('clinic.lab.request', 'patient_id', string="Lab Requests")
    appointment_count = fields.Integer(compute='_compute_counts')
    consultation_count = fields.Integer(compute='_compute_counts')
    admission_count = fields.Integer(compute='_compute_counts')
    prescription_count = fields.Integer(compute='_compute_counts')
    lab_request_count = fields.Integer(compute='_compute_counts')
    invoice_count = fields.Integer(compute='_compute_invoice_data')
    amount_due = fields.Monetary(compute='_compute_invoice_data', currency_field='currency_id')
    last_visit_date = fields.Datetime(compute='_compute_counts')
    current_admission_id = fields.Many2one('clinic.admission', compute='_compute_current_admission')
    is_admitted = fields.Boolean(compute='_compute_current_admission', search='_search_is_admitted')

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for patient in self:
            if patient.date_of_birth:
                delta = relativedelta(today, patient.date_of_birth)
                patient.age = delta.years
                patient.age_display = self.env._("%(y)sy %(m)sm", y=delta.years, m=delta.months)
            else:
                patient.age = 0
                patient.age_display = False

    def _compute_counts(self):
        for patient in self:
            patient.appointment_count = len(patient.appointment_ids)
            patient.consultation_count = len(patient.consultation_ids)
            patient.admission_count = len(patient.admission_ids)
            patient.prescription_count = len(patient.prescription_ids)
            patient.lab_request_count = len(patient.lab_request_ids)
            patient.last_visit_date = max(patient.consultation_ids.mapped('date'), default=False)

    def _compute_invoice_data(self):
        moves = self.env['account.move'].sudo().search([
            ('clinic_patient_id', 'in', self.ids), ('move_type', '=', 'out_invoice'), ('state', '!=', 'cancel'),
        ])
        for patient in self:
            patient_moves = moves.filtered(lambda m: m.clinic_patient_id == patient)
            patient.invoice_count = len(patient_moves)
            patient.amount_due = sum(patient_moves.filtered(lambda m: m.state == 'posted').mapped('amount_residual'))

    def _compute_current_admission(self):
        for patient in self:
            admission = patient.admission_ids.filtered(lambda a: a.state == 'admitted')[:1]
            patient.current_admission_id = admission
            patient.is_admitted = bool(admission)

    def _search_is_admitted(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        admitted = self.env['clinic.admission'].search([('state', '=', 'admitted')]).patient_id
        positive = (operator == '=') == value
        return [('id', 'in' if positive else 'not in', admitted.ids)]

    @api.depends('name', 'patient_ref')
    def _compute_display_name(self):
        for patient in self:
            ref = patient.patient_ref if patient.patient_ref and patient.patient_ref != 'New' else ''
            patient.display_name = f"[{ref}] {patient.name}" if ref else (patient.name or '')

    @api.constrains('date_of_birth')
    def _check_date_of_birth(self):
        for patient in self:
            if patient.date_of_birth and patient.date_of_birth > fields.Date.context_today(self):
                raise ValidationError(self.env._("Date of birth cannot be in the future."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('patient_ref', 'New') == 'New':
                vals['patient_ref'] = self.env['ir.sequence'].next_by_code('clinic.patient') or 'New'
        patients = super().create(vals_list)
        patients.document_ids.write({'res_model': self._name})
        for patient in patients:
            patient.document_ids.write({'res_id': patient.id})
        return patients

    def _open_related(self, model, name, view_mode='list,form'):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': view_mode,
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }

    def action_view_appointments(self):
        return self._open_related('clinic.appointment', self.env._("Appointments"), 'list,form,calendar')

    def action_view_consultations(self):
        return self._open_related('clinic.consultation', self.env._("Visits"))

    def action_view_admissions(self):
        return self._open_related('clinic.admission', self.env._("Admissions"))

    def action_view_prescriptions(self):
        return self._open_related('clinic.prescription', self.env._("Prescriptions"))

    def action_view_lab_requests(self):
        return self._open_related('clinic.lab.request', self.env._("Lab Requests"))

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Invoices"),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('clinic_patient_id', '=', self.id), ('move_type', '=', 'out_invoice')],
            'context': {'default_move_type': 'out_invoice', 'create': False},
        }

    def action_book_appointment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("New Appointment"),
            'res_model': 'clinic.appointment',
            'view_mode': 'form',
            'context': {'default_patient_id': self.id},
        }
