from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    clinic_patient_id = fields.Many2one('clinic.patient', string="Patient", index=True, copy=False, readonly=True)
