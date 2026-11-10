from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_medicine = fields.Boolean(string="Is a Medicine")
    medicine_category_id = fields.Many2one('clinic.medicine.category')
    medicine_form = fields.Selection([
        ('tablet', 'Tablet'),
        ('capsule', 'Capsule'),
        ('syrup', 'Syrup'),
        ('injection', 'Injection'),
        ('ointment', 'Ointment'),
        ('drops', 'Drops'),
        ('inhaler', 'Inhaler'),
        ('other', 'Other'),
    ], string="Form")
    strength = fields.Char(help="e.g. 500 mg")
