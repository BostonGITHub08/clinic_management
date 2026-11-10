from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicDischarge(models.Model):
    _name = 'clinic.discharge'
    _description = 'Patient Discharge'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'discharge_date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    admission_id = fields.Many2one('clinic.admission', required=True, index=True,
                                   domain="[('state', '=', 'admitted')]", tracking=True)
    patient_id = fields.Many2one(related='admission_id.patient_id', store=True, index=True)
    admission_date = fields.Datetime(related='admission_id.admission_date')
    bed_id = fields.Many2one(related='admission_id.bed_id')
    doctor_id = fields.Many2one('clinic.doctor', required=True, tracking=True)
    discharge_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    discharge_type = fields.Selection([
        ('recovered', 'Recovered'),
        ('improved', 'Improved'),
        ('referred', 'Referred'),
        ('lama', 'Left Against Medical Advice'),
        ('deceased', 'Deceased'),
    ], default='recovered', required=True)
    final_diagnosis = fields.Text(tracking=True)
    treatment_summary = fields.Html()
    discharge_instructions = fields.Html()
    prescription_id = fields.Many2one('clinic.prescription', string="Discharge Medicines",
                                      domain="[('patient_id', '=', patient_id)]")
    follow_up_date = fields.Date()
    follow_up_appointment_id = fields.Many2one('clinic.appointment', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string="Approved By", readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Doctor Approved'),
        ('done', 'Discharged'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.constrains('admission_id', 'state')
    def _check_unique(self):
        for discharge in self.filtered(lambda d: d.state != 'cancelled'):
            if self.search_count([('id', '!=', discharge.id), ('admission_id', '=', discharge.admission_id.id),
                                  ('state', '!=', 'cancelled')]):
                raise ValidationError(self.env._("Admission %s already has a discharge record.", discharge.admission_id.name))

    @api.constrains('discharge_date', 'admission_id')
    def _check_dates(self):
        for discharge in self:
            if discharge.discharge_date < discharge.admission_id.admission_date:
                raise ValidationError(self.env._("The discharge date cannot be before the admission date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.discharge') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(discharge.state == 'done' for discharge in self):
            raise UserError(self.env._("Completed discharges cannot be deleted."))
        return super().unlink()

    def action_approve(self):
        if not self.env.user.has_group('clinic_management.group_clinic_doctor'):
            raise UserError(self.env._("Only doctors can approve a discharge."))
        for discharge in self:
            if discharge.state != 'draft':
                raise UserError(self.env._("Only draft discharges can be approved."))
            if not discharge.final_diagnosis:
                raise UserError(self.env._("Please enter the final diagnosis before approval."))
        self.write({'state': 'approved', 'approved_by_id': self.env.uid, 'approval_date': fields.Datetime.now()})

    def action_discharge(self):
        for discharge in self:
            if discharge.state != 'approved':
                raise UserError(self.env._("The discharge must be approved by a doctor first."))
            admission = discharge.admission_id
            if admission.state != 'admitted':
                raise UserError(self.env._("Admission %s is not in admitted state.", admission.name))
            admission._release_bed()
            admission.write({'state': 'discharged', 'discharge_date': discharge.discharge_date})
            discharge.state = 'done'
            discharge._create_follow_up_appointment()

    def action_cancel(self):
        if any(discharge.state == 'done' for discharge in self):
            raise UserError(self.env._("Completed discharges cannot be cancelled."))
        self.write({'state': 'cancelled', 'approved_by_id': False, 'approval_date': False})

    def action_reset_draft(self):
        self.filtered(lambda d: d.state in ('approved', 'cancelled')).write(
            {'state': 'draft', 'approved_by_id': False, 'approval_date': False})

    def _create_follow_up_appointment(self):
        for discharge in self.filtered(lambda d: d.follow_up_date and not d.follow_up_appointment_id):
            discharge.follow_up_appointment_id = self.env['clinic.appointment']._schedule_follow_up(
                discharge.patient_id, discharge.doctor_id, discharge.follow_up_date, discharge.company_id,
                self.env._("Post-discharge follow-up (%s)", discharge.name))

    def action_create_prescription(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Discharge Medicines"),
            'res_model': 'clinic.prescription',
            'view_mode': 'form',
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
                'default_admission_id': self.admission_id.id,
                'clinic_discharge_id': self.id,
            },
        }

    def action_print_report(self):
        return self.env.ref('clinic_management.action_report_discharge').report_action(self)
