from odoo import api, fields, models

ROLE_GROUPS = {
    'receptionist': 'clinic_management.group_clinic_receptionist',
    'nurse': 'clinic_management.group_clinic_nurse',
    'lab_technician': 'clinic_management.group_clinic_lab',
    'pharmacist': 'clinic_management.group_clinic_pharmacist',
    'admin': 'clinic_management.group_clinic_manager',
}


class ClinicStaff(models.Model):
    _name = 'clinic.staff'
    _description = 'Clinic Staff Member'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    role = fields.Selection([
        ('receptionist', 'Receptionist'),
        ('nurse', 'Nurse'),
        ('lab_technician', 'Laboratory Technician'),
        ('pharmacist', 'Pharmacist'),
        ('admin', 'Administrative Staff'),
    ], required=True, default='receptionist', tracking=True)
    user_id = fields.Many2one('res.users', string="Related User",
                              help="The user automatically receives the access rights of the selected role.")
    department_id = fields.Many2one('clinic.department')
    phone = fields.Char()
    email = fields.Char()
    joining_date = fields.Date(default=fields.Date.context_today)
    shift = fields.Selection([('morning', 'Morning'), ('evening', 'Evening'), ('night', 'Night')])
    color = fields.Integer()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        staff = super().create(vals_list)
        staff._grant_role_access()
        return staff

    def write(self, vals):
        res = super().write(vals)
        if 'user_id' in vals or 'role' in vals:
            self._grant_role_access()
        return res

    def _grant_role_access(self):
        for member in self.filtered('user_id'):
            group = self.env.ref(ROLE_GROUPS[member.role])
            if group not in member.user_id.all_group_ids:
                member.user_id.sudo().write({'group_ids': [(4, group.id)]})
