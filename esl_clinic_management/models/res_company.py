from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    clinic_appointment_duration = fields.Float(string="Default Appointment Duration", default=0.5)
    clinic_check_doctor_availability = fields.Boolean(string="Check Doctor Availability", default=True)
    clinic_admission_fee = fields.Float(string="Admission Fee", default=0.0)
    clinic_consultation_product_id = fields.Many2one('product.product', string="Consultation Product")
    clinic_admission_product_id = fields.Many2one('product.product', string="Admission Product")
    clinic_bed_product_id = fields.Many2one('product.product', string="Room & Bed Product")
    clinic_lab_product_id = fields.Many2one('product.product', string="Laboratory Product")

    def _clinic_product(self, kind):
        """Return the billing product configured for ``kind``, falling back to the module default."""
        self.ensure_one()
        product = self[f'clinic_{kind}_product_id']
        if not product:
            product = self.env.ref(f'esl_clinic_management.product_clinic_{kind}', raise_if_not_found=False)
        return product
