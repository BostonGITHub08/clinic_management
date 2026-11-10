from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

FREQUENCY_PER_DAY = {
    'once': 1, 'twice': 2, 'thrice': 3, 'four': 4, 'bedtime': 1, 'sos': 1, 'weekly': 1 / 7,
}


class ClinicPrescription(models.Model):
    _name = 'clinic.prescription'
    _description = 'Prescription'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'clinic.billing.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string="Reference", readonly=True, copy=False, default='New')
    patient_id = fields.Many2one('clinic.patient', required=True, tracking=True, index=True)
    doctor_id = fields.Many2one('clinic.doctor', required=True, tracking=True, index=True)
    date = fields.Date(string="Prescription Date", default=fields.Date.context_today, required=True)
    consultation_id = fields.Many2one('clinic.consultation', string="Consultation", index=True,
                                      domain="[('patient_id', '=', patient_id)]")
    admission_id = fields.Many2one('clinic.admission', string="Admission", index=True,
                                   domain="[('patient_id', '=', patient_id)]")
    line_ids = fields.One2many('clinic.prescription.line', 'prescription_id', string="Medicines", copy=True)
    notes = fields.Text()
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('dispensed', 'Dispensed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    picking_id = fields.Many2one('stock.picking', string="Delivery", readonly=True, copy=False)
    amount_total = fields.Monetary(compute='_compute_amount_total', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for prescription in self:
            prescription.amount_total = sum(prescription.line_ids.mapped('subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.prescription') or 'New'
        prescriptions = super().create(vals_list)
        discharge_id = self.env.context.get('clinic_discharge_id')
        if discharge_id:
            self.env['clinic.discharge'].browse(discharge_id).prescription_id = prescriptions[:1]
        return prescriptions

    def unlink(self):
        if any(prescription.state not in ('draft', 'cancelled') for prescription in self):
            raise UserError(self.env._("Only draft or cancelled prescriptions can be deleted."))
        return super().unlink()

    def action_confirm(self):
        for prescription in self:
            if prescription.state != 'draft':
                raise UserError(self.env._("Only draft prescriptions can be confirmed."))
            if not prescription.line_ids:
                raise UserError(self.env._("Please add at least one medicine to %s.", prescription.name))
        self.state = 'confirmed'

    def action_dispense(self):
        """Deliver the medicines from stock through a standard Inventory delivery order."""
        for prescription in self:
            if prescription.state != 'confirmed':
                raise UserError(self.env._("Only confirmed prescriptions can be dispensed."))
            stock_lines = prescription.line_ids.filtered(lambda l: l.product_id.is_storable and l.quantity > 0)
            if stock_lines:
                warehouse = self.env['stock.warehouse'].search([('company_id', '=', prescription.company_id.id)], limit=1)
                if not warehouse:
                    raise UserError(self.env._("No warehouse found for company %s.", prescription.company_id.name))
                picking_type = warehouse.out_type_id
                source = picking_type.default_location_src_id
                dest = self.env.ref('stock.stock_location_customers')
                picking = self.env['stock.picking'].create({
                    'picking_type_id': picking_type.id,
                    'partner_id': prescription.patient_id.partner_id.id,
                    'origin': prescription.name,
                    'location_id': source.id,
                    'location_dest_id': dest.id,
                    'company_id': prescription.company_id.id,
                    'move_ids': [(0, 0, {
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'product_uom': line.product_id.uom_id.id,
                        'location_id': source.id,
                        'location_dest_id': dest.id,
                        'company_id': prescription.company_id.id,
                    }) for line in stock_lines],
                })
                picking.action_confirm()
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
                prescription.picking_id = picking
            prescription.state = 'dispensed'

    def action_cancel(self):
        if any(prescription.state == 'dispensed' for prescription in self):
            raise UserError(self.env._("Dispensed prescriptions cannot be cancelled. Return the delivery in Inventory instead."))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.filtered(lambda p: p.state == 'cancelled').state = 'draft'

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Delivery"),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }

    def _get_invoice_lines(self):
        return [self._invoice_line(line.product_id, self.env._("%(medicine)s (%(ref)s)", medicine=line.product_id.display_name, ref=self.name),
                                   line.quantity, line.price_unit)
                for line in self.line_ids if line.quantity]

    def action_create_invoice(self):
        for prescription in self:
            if prescription.state not in ('confirmed', 'dispensed'):
                raise UserError(self.env._("Please confirm the prescription before invoicing."))
            if prescription.admission_id.state == 'admitted':
                raise UserError(self.env._("This prescription belongs to admission %s and will be billed on its invoice.",
                                           prescription.admission_id.name))
        return super().action_create_invoice()


class ClinicPrescriptionLine(models.Model):
    _name = 'clinic.prescription.line'
    _description = 'Prescription Line'

    prescription_id = fields.Many2one('clinic.prescription', required=True, ondelete='cascade', index=True)
    patient_id = fields.Many2one(related='prescription_id.patient_id', store=True)
    doctor_id = fields.Many2one(related='prescription_id.doctor_id', store=True)
    date = fields.Date(related='prescription_id.date', store=True)
    state = fields.Selection(related='prescription_id.state', store=True)
    company_id = fields.Many2one(related='prescription_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string="Medicine", required=True,
                                 domain="[('is_medicine', '=', True)]")
    medicine_category_id = fields.Many2one(related='product_id.medicine_category_id', store=True)
    dosage = fields.Char(help="e.g. 1 tablet, 5 ml")
    frequency = fields.Selection([
        ('once', 'Once a day'),
        ('twice', 'Twice a day'),
        ('thrice', 'Three times a day'),
        ('four', 'Four times a day'),
        ('bedtime', 'At bedtime'),
        ('sos', 'When needed (SOS)'),
        ('weekly', 'Once a week'),
    ], default='twice', required=True)
    duration = fields.Integer(string="Duration (Days)", default=5)
    quantity = fields.Float(compute='_compute_quantity', store=True, readonly=False)
    instructions = fields.Char(help="e.g. After meals")
    price_unit = fields.Float(string="Unit Price", compute='_compute_price', store=True, readonly=False)
    subtotal = fields.Float(compute='_compute_subtotal', store=True)
    qty_available = fields.Float(related='product_id.qty_available', string="In Stock")

    @api.depends('frequency', 'duration')
    def _compute_quantity(self):
        for line in self:
            line.quantity = max(1, round(FREQUENCY_PER_DAY.get(line.frequency, 1) * (line.duration or 1)))

    @api.depends('product_id')
    def _compute_price(self):
        for line in self:
            line.price_unit = line.product_id.lst_price

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.constrains('duration', 'quantity', 'price_unit')
    def _check_values(self):
        for line in self:
            if line.duration < 0 or line.quantity < 0 or line.price_unit < 0:
                raise ValidationError(self.env._("Duration, quantity and price cannot be negative."))
