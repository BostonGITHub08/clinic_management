from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicLabTestCategory(models.Model):
    _name = 'clinic.lab.test.category'
    _description = 'Lab Test Category'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    test_type_ids = fields.One2many('clinic.lab.test.type', 'category_id')
    active = fields.Boolean(default=True)


class ClinicLabTestType(models.Model):
    _name = 'clinic.lab.test.type'
    _description = 'Lab Test'
    _order = 'category_id, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    category_id = fields.Many2one('clinic.lab.test.category', required=True)
    price = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    sample_type = fields.Selection([
        ('blood', 'Blood'), ('urine', 'Urine'), ('stool', 'Stool'), ('swab', 'Swab'),
        ('imaging', 'Imaging'), ('other', 'Other'),
    ], default='blood')
    normal_range = fields.Char()
    unit = fields.Char()
    active = fields.Boolean(default=True)


class ClinicLabRequest(models.Model):
    _name = 'clinic.lab.request'
    _description = 'Lab Test Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'clinic.billing.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', required=True, tracking=True, index=True)
    patient_age = fields.Char(related='patient_id.age_display')
    patient_gender = fields.Selection(related='patient_id.gender')
    doctor_id = fields.Many2one('clinic.doctor', string="Referred By", required=True, tracking=True, index=True)
    consultation_id = fields.Many2one('clinic.consultation', index=True, domain="[('patient_id', '=', patient_id)]")
    admission_id = fields.Many2one('clinic.admission', index=True, domain="[('patient_id', '=', patient_id)]")
    request_date = fields.Datetime(default=fields.Datetime.now, required=True)
    test_date = fields.Datetime(string="Test Date", tracking=True)
    technician_id = fields.Many2one('res.users', string="Technician", tracking=True)
    line_ids = fields.One2many('clinic.lab.request.line', 'request_id', string="Tests", copy=True)
    attachment_ids = fields.Many2many('ir.attachment', 'clinic_lab_request_attachment_rel', 'request_id',
                                      'attachment_id', string="Attachments")
    notes = fields.Text(string="Clinical Notes")
    state = fields.Selection([
        ('draft', 'Requested'),
        ('in_progress', 'Sample Collected'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, string="Test Status")
    amount_total = fields.Monetary(compute='_compute_amount_total', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.depends('line_ids.price')
    def _compute_amount_total(self):
        for request in self:
            request.amount_total = sum(request.line_ids.mapped('price'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.lab.request') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(request.state not in ('draft', 'cancelled') for request in self):
            raise UserError(self.env._("Only requested or cancelled lab tests can be deleted."))
        return super().unlink()

    def action_collect_sample(self):
        for request in self:
            if request.state != 'draft':
                raise UserError(self.env._("The sample has already been collected for %s.", request.name))
            if not request.line_ids:
                raise UserError(self.env._("Please add at least one test to %s.", request.name))
        self.write({'state': 'in_progress', 'test_date': fields.Datetime.now(), 'technician_id': self.env.uid})

    def action_done(self):
        for request in self:
            if request.state != 'in_progress':
                raise UserError(self.env._("Collect the sample before completing %s.", request.name))
            missing = request.line_ids.filtered(lambda l: not l.result)
            if missing:
                raise UserError(self.env._("Please enter the results of: %s", ", ".join(missing.test_type_id.mapped('name'))))
        self.state = 'done'

    def action_cancel(self):
        if any(request.state == 'done' for request in self):
            raise UserError(self.env._("Completed lab requests cannot be cancelled."))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.filtered(lambda r: r.state == 'cancelled').state = 'draft'

    def action_print_report(self):
        return self.env.ref('esl_clinic_management.action_report_lab').report_action(self)

    def _get_invoice_lines(self):
        product = self.company_id._clinic_product('lab')
        return [self._invoice_line(product, self.env._("Lab Test: %(test)s (%(ref)s)", test=line.test_type_id.name, ref=self.name),
                                   1, line.price)
                for line in self.line_ids if line.price]

    def action_create_invoice(self):
        for request in self:
            if request.state == 'cancelled':
                raise UserError(self.env._("Cancelled lab requests cannot be invoiced."))
            if request.admission_id.state == 'admitted':
                raise UserError(self.env._("This lab request belongs to admission %s and will be billed on its invoice.",
                                           request.admission_id.name))
        return super().action_create_invoice()


class ClinicLabRequestLine(models.Model):
    _name = 'clinic.lab.request.line'
    _description = 'Lab Test Result'

    request_id = fields.Many2one('clinic.lab.request', required=True, ondelete='cascade', index=True)
    patient_id = fields.Many2one(related='request_id.patient_id', store=True)
    request_date = fields.Datetime(related='request_id.request_date', store=True)
    state = fields.Selection(related='request_id.state', store=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    test_type_id = fields.Many2one('clinic.lab.test.type', string="Test", required=True)
    category_id = fields.Many2one(related='test_type_id.category_id', store=True)
    result = fields.Char()
    unit = fields.Char(compute='_compute_from_test', store=True, readonly=False)
    normal_range = fields.Char(compute='_compute_from_test', store=True, readonly=False)
    is_abnormal = fields.Boolean(string="Abnormal")
    remarks = fields.Char()
    price = fields.Float(compute='_compute_from_test', store=True, readonly=False)

    @api.depends('test_type_id')
    def _compute_from_test(self):
        for line in self:
            line.unit = line.test_type_id.unit
            line.normal_range = line.test_type_id.normal_range
            line.price = line.test_type_id.price

    @api.constrains('price')
    def _check_price(self):
        if any(line.price < 0 for line in self):
            raise ValidationError(self.env._("The test price cannot be negative."))
