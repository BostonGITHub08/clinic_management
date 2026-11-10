import math

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicAdmission(models.Model):
    _name = 'clinic.admission'
    _description = 'Patient Admission (IPD)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'clinic.billing.mixin']
    _order = 'admission_date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', required=True, tracking=True, index=True)
    patient_age = fields.Char(related='patient_id.age_display')
    patient_gender = fields.Selection(related='patient_id.gender')
    doctor_id = fields.Many2one('clinic.doctor', string="Attending Doctor", required=True, tracking=True, index=True)
    department_id = fields.Many2one('clinic.department', compute='_compute_department', store=True, readonly=False)
    admission_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    discharge_date = fields.Datetime(readonly=True, copy=False, tracking=True)
    admission_type = fields.Selection([
        ('emergency', 'Emergency'),
        ('planned', 'Planned'),
        ('surgery', 'Surgery'),
        ('maternity', 'Maternity'),
        ('observation', 'Observation'),
    ], default='planned', required=True)
    diagnosis = fields.Text(string="Provisional Diagnosis")
    room_id = fields.Many2one('clinic.room', tracking=True, check_company=True)
    bed_id = fields.Many2one('clinic.bed', tracking=True, check_company=True,
                             domain="[('state', '=', 'available'), ('room_id', '=?', room_id)]")
    bed_rate = fields.Monetary(string="Daily Bed Charge", compute='_compute_bed_rate', store=True, readonly=False,
                               currency_field='currency_id')
    notes = fields.Html(string="Admission Notes")
    responsible_staff_id = fields.Many2one('clinic.staff', string="Responsible Staff")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('admitted', 'Admitted'),
        ('discharged', 'Discharged'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)
    stay_days = fields.Integer(string="Length of Stay (Days)", compute='_compute_stay_days')
    service_line_ids = fields.One2many('clinic.admission.service', 'admission_id', string="Additional Services")
    prescription_ids = fields.One2many('clinic.prescription', 'admission_id')
    lab_request_ids = fields.One2many('clinic.lab.request', 'admission_id')
    discharge_ids = fields.One2many('clinic.discharge', 'admission_id', string="Discharges")
    discharge_id = fields.Many2one('clinic.discharge', compute='_compute_discharge')
    prescription_count = fields.Integer(compute='_compute_counts')
    lab_request_count = fields.Integer(compute='_compute_counts')
    discount = fields.Float(string="Discount (%)")
    currency_id = fields.Many2one(related='company_id.currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.depends('doctor_id')
    def _compute_department(self):
        for admission in self:
            if admission.doctor_id.department_id:
                admission.department_id = admission.doctor_id.department_id

    @api.depends('bed_id')
    def _compute_bed_rate(self):
        for admission in self:
            admission.bed_rate = admission.bed_id.daily_charge

    @api.depends('admission_date', 'discharge_date', 'state')
    def _compute_stay_days(self):
        now = fields.Datetime.now()
        for admission in self:
            if admission.state in ('admitted', 'discharged') and admission.admission_date:
                end = admission.discharge_date or now
                admission.stay_days = max(1, math.ceil((end - admission.admission_date).total_seconds() / 86400))
            else:
                admission.stay_days = 0

    def _compute_discharge(self):
        for admission in self:
            admission.discharge_id = admission.discharge_ids.filtered(lambda d: d.state != 'cancelled')[:1]

    def _compute_counts(self):
        for admission in self:
            admission.prescription_count = len(admission.prescription_ids)
            admission.lab_request_count = len(admission.lab_request_ids)

    @api.onchange('room_id')
    def _onchange_room_id(self):
        if self.bed_id and self.bed_id.room_id != self.room_id:
            self.bed_id = False

    @api.onchange('bed_id')
    def _onchange_bed_id(self):
        if self.bed_id:
            self.room_id = self.bed_id.room_id

    @api.constrains('bed_id', 'state')
    def _check_bed(self):
        for admission in self.filtered(lambda a: a.state == 'admitted' and a.bed_id):
            other = self.search([('id', '!=', admission.id), ('bed_id', '=', admission.bed_id.id), ('state', '=', 'admitted')], limit=1)
            if other:
                raise ValidationError(self.env._("Bed %(bed)s is already occupied by %(patient)s (%(ref)s).",
                                                 bed=admission.bed_id.display_name, patient=other.patient_id.name, ref=other.name))

    @api.constrains('patient_id', 'state')
    def _check_patient(self):
        for admission in self.filtered(lambda a: a.state == 'admitted'):
            if self.search_count([('id', '!=', admission.id), ('patient_id', '=', admission.patient_id.id), ('state', '=', 'admitted')]):
                raise ValidationError(self.env._("%s is already admitted.", admission.patient_id.name))

    @api.constrains('discount', 'bed_rate')
    def _check_amounts(self):
        for admission in self:
            if not 0 <= admission.discount <= 100:
                raise ValidationError(self.env._("The discount must be between 0 and 100%."))
            if admission.bed_rate < 0:
                raise ValidationError(self.env._("The bed charge cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.admission') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if 'bed_id' in vals:
            admitted = self.filtered(lambda a: a.state == 'admitted')
            if admitted and not vals['bed_id']:
                raise UserError(self.env._("An admitted patient must keep a bed. Select another bed instead."))
            new_bed = self.env['clinic.bed'].browse(vals['bed_id'])
            if admitted and new_bed:
                if len(admitted) > 1:
                    raise UserError(self.env._("A bed can only be assigned to one admission."))
                if new_bed.admission_id and new_bed.admission_id != admitted:
                    raise UserError(self.env._("Bed %s is already occupied.", new_bed.display_name))
                if new_bed.under_maintenance:
                    raise UserError(self.env._("Bed %s is under maintenance.", new_bed.display_name))
                admitted.bed_id.filtered(lambda b: b.admission_id == admitted).sudo().admission_id = False
                vals.setdefault('room_id', new_bed.room_id.id)
            res = super().write(vals)
            if admitted and new_bed:
                new_bed.sudo().admission_id = admitted
            return res
        return super().write(vals)

    def unlink(self):
        if any(admission.state not in ('draft', 'cancelled') for admission in self):
            raise UserError(self.env._("Only draft or cancelled admissions can be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------ workflow
    def action_admit(self):
        for admission in self:
            if admission.state != 'draft':
                raise UserError(self.env._("Only draft admissions can be admitted."))
            bed = admission.bed_id
            if not bed:
                raise UserError(self.env._("Please select a bed for %s.", admission.patient_id.name))
            if bed.state != 'available':
                raise UserError(self.env._("Bed %(bed)s is not available (%(state)s).", bed=bed.display_name,
                                           state=dict(bed._fields['state'].selection)[bed.state]))
            admission.write({'state': 'admitted', 'room_id': bed.room_id.id})
            bed.sudo().admission_id = admission

    def action_cancel(self):
        for admission in self:
            if admission.state != 'draft':
                raise UserError(self.env._("Only draft admissions can be cancelled."))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.filtered(lambda a: a.state == 'cancelled').state = 'draft'

    def _release_bed(self):
        for admission in self:
            if admission.bed_id.admission_id == admission:
                admission.bed_id.sudo().admission_id = False

    def action_discharge(self):
        """Open (or create) the discharge record of this admission."""
        self.ensure_one()
        if self.state != 'admitted' and not self.discharge_id:
            raise UserError(self.env._("Only admitted patients can be discharged."))
        discharge = self.discharge_id or self.env['clinic.discharge'].create({
            'admission_id': self.id,
            'doctor_id': self.doctor_id.id,
            'final_diagnosis': self.diagnosis,
            'company_id': self.company_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Discharge"),
            'res_model': 'clinic.discharge',
            'res_id': discharge.id,
            'view_mode': 'form',
        }

    def _related_action(self, model, name):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': [('admission_id', '=', self.id)],
            'context': {'default_patient_id': self.patient_id.id, 'default_doctor_id': self.doctor_id.id,
                        'default_admission_id': self.id},
        }

    def action_view_prescriptions(self):
        return self._related_action('clinic.prescription', self.env._("Prescriptions"))

    def action_view_lab_requests(self):
        return self._related_action('clinic.lab.request', self.env._("Lab Requests"))

    # ------------------------------------------------------------------ billing
    def _get_invoice_lines(self):
        company = self.company_id
        lines = []
        if company.clinic_admission_fee:
            lines.append(self._invoice_line(company._clinic_product('admission'),
                                            self.env._("Admission Charges (%s)", self.name), 1,
                                            company.clinic_admission_fee, self.discount))
        if self.bed_rate:
            lines.append(self._invoice_line(company._clinic_product('bed'),
                                            self.env._("Room & Bed Charges - %(bed)s (%(days)s days)",
                                                       bed=self.bed_id.display_name, days=self.stay_days),
                                            self.stay_days, self.bed_rate, self.discount))
        for service in self.service_line_ids:
            lines.append(self._invoice_line(service.product_id, service.name, service.quantity,
                                            service.price_unit, self.discount))
        for prescription in self.prescription_ids.filtered(lambda p: p.state in ('confirmed', 'dispensed') and not p.invoice_id):
            lines += [dict(line, discount=self.discount) for line in prescription._get_invoice_lines()]
        for lab in self.lab_request_ids.filtered(lambda r: r.state != 'cancelled' and not r.invoice_id):
            lines += [dict(line, discount=self.discount) for line in lab._get_invoice_lines()]
        return lines

    def _clinic_create_invoice(self):
        move = super()._clinic_create_invoice()
        self.prescription_ids.filtered(lambda p: p.state in ('confirmed', 'dispensed') and not p.invoice_id).invoice_id = move
        self.lab_request_ids.filtered(lambda r: r.state != 'cancelled' and not r.invoice_id).invoice_id = move
        return move


class ClinicAdmissionService(models.Model):
    _name = 'clinic.admission.service'
    _description = 'Admission Additional Service'

    admission_id = fields.Many2one('clinic.admission', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', string="Service", required=True,
                                 domain="[('sale_ok', '=', True)]")
    name = fields.Char(string="Description", compute='_compute_from_product', store=True, readonly=False, required=True, precompute=True)
    date = fields.Date(default=fields.Date.context_today)
    quantity = fields.Float(default=1.0)
    price_unit = fields.Float(string="Unit Price", compute='_compute_from_product', store=True, readonly=False, precompute=True)
    subtotal = fields.Float(compute='_compute_subtotal')

    @api.depends('product_id')
    def _compute_from_product(self):
        for line in self:
            line.name = line.product_id.display_name
            line.price_unit = line.product_id.lst_price

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.constrains('quantity', 'price_unit')
    def _check_values(self):
        if any(line.quantity <= 0 or line.price_unit < 0 for line in self):
            raise ValidationError(self.env._("Service quantity must be positive and price cannot be negative."))
