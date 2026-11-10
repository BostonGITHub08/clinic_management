from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    clinic_appointment_duration = fields.Float(related='company_id.clinic_appointment_duration', readonly=False)
    clinic_check_doctor_availability = fields.Boolean(related='company_id.clinic_check_doctor_availability', readonly=False)
    clinic_admission_fee = fields.Float(related='company_id.clinic_admission_fee', readonly=False)
    clinic_consultation_product_id = fields.Many2one(related='company_id.clinic_consultation_product_id', readonly=False)
    clinic_admission_product_id = fields.Many2one(related='company_id.clinic_admission_product_id', readonly=False)
    clinic_bed_product_id = fields.Many2one(related='company_id.clinic_bed_product_id', readonly=False)
    clinic_lab_product_id = fields.Many2one(related='company_id.clinic_lab_product_id', readonly=False)
