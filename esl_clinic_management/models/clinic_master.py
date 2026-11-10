from odoo import fields, models


class ClinicWeekday(models.Model):
    _name = 'clinic.weekday'
    _description = 'Weekday'
    _order = 'code'

    name = fields.Char(required=True, translate=True)
    code = fields.Integer(required=True, help="0 = Monday ... 6 = Sunday")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Each weekday can only exist once.')


class ClinicDisease(models.Model):
    _name = 'clinic.disease'
    _description = 'Disease / Condition'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()

    _name_uniq = models.Constraint('UNIQUE(name)', 'This condition already exists.')


class ClinicSpecialization(models.Model):
    _name = 'clinic.specialization'
    _description = 'Medical Specialization'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)


class ClinicDepartment(models.Model):
    _name = 'clinic.department'
    _description = 'Clinic Department'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char()
    head_doctor_id = fields.Many2one('clinic.doctor', string="Head of Department")
    doctor_ids = fields.One2many('clinic.doctor', 'department_id', string="Doctors")
    doctor_count = fields.Integer(compute='_compute_doctor_count')
    color = fields.Integer()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _compute_doctor_count(self):
        for department in self:
            department.doctor_count = len(department.doctor_ids)


class ClinicMedicineCategory(models.Model):
    _name = 'clinic.medicine.category'
    _description = 'Medicine Category'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
