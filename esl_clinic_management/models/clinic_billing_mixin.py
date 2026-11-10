from odoo import Command, fields, models
from odoo.exceptions import UserError


class ClinicBillingMixin(models.AbstractModel):
    """Shared invoicing behaviour for clinic documents (appointments, admissions, ...)."""
    _name = 'clinic.billing.mixin'
    _description = 'Clinic Billing Mixin'

    invoice_id = fields.Many2one('account.move', string="Invoice", copy=False, readonly=True)
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', string="Payment Status")

    def _get_invoice_lines(self):
        """Return a list of invoice line value dicts. Must be overridden."""
        return []

    def _clinic_create_invoice(self):
        self.ensure_one()
        if self.invoice_id and self.invoice_id.state != 'cancel':
            raise UserError(self.env._("An invoice already exists for %s.", self.display_name))
        lines = self._get_invoice_lines()
        if not lines:
            raise UserError(self.env._("There is nothing to invoice for %s.", self.display_name))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.partner_id.id,
            'clinic_patient_id': self.patient_id.id,
            'invoice_origin': self.name,
            'company_id': self.company_id.id,
            'invoice_line_ids': [Command.create(line) for line in lines],
        })
        self.invoice_id = move
        return move

    def action_create_invoice(self):
        self._clinic_create_invoice()
        return self.action_view_invoice()

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Invoice"),
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('account.view_move_form').id, 'form')],
        }

    def _invoice_line(self, product, name, quantity, price_unit, discount=0.0):
        if not product:
            raise UserError(self.env._("Please configure the clinic billing products in Clinic > Configuration > Settings."))
        return {
            'product_id': product.id,
            'name': name,
            'quantity': quantity,
            'price_unit': price_unit,
            'discount': discount,
        }
