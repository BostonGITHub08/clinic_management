from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ClinicRoomCategory(models.Model):
    _name = 'clinic.room.category'
    _description = 'Room Category'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    daily_rate = fields.Monetary(string="Default Daily Rate", currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    description = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    room_ids = fields.One2many('clinic.room', 'category_id')


class ClinicRoom(models.Model):
    _name = 'clinic.room'
    _description = 'Room'
    _order = 'name'

    name = fields.Char(string="Room Number", required=True)
    category_id = fields.Many2one('clinic.room.category', required=True)
    department_id = fields.Many2one('clinic.department')
    floor = fields.Char()
    bed_ids = fields.One2many('clinic.bed', 'room_id', string="Beds")
    bed_count = fields.Integer(compute='_compute_bed_stats')
    available_bed_count = fields.Integer(compute='_compute_bed_stats')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)

    _name_company_uniq = models.Constraint('UNIQUE(name, company_id)', 'The room number must be unique per company.')

    @api.depends('bed_ids.state')
    def _compute_bed_stats(self):
        for room in self:
            room.bed_count = len(room.bed_ids)
            room.available_bed_count = len(room.bed_ids.filtered(lambda b: b.state == 'available'))


class ClinicBed(models.Model):
    _name = 'clinic.bed'
    _description = 'Bed'
    _inherit = ['mail.thread']
    _order = 'room_id, name'

    name = fields.Char(string="Bed Number", required=True)
    room_id = fields.Many2one('clinic.room', required=True, ondelete='cascade', index=True)
    category_id = fields.Many2one(related='room_id.category_id', store=True)
    department_id = fields.Many2one(related='room_id.department_id', store=True)
    bed_type = fields.Selection([
        ('general', 'General'),
        ('semi_private', 'Semi-Private'),
        ('private', 'Private'),
        ('icu', 'ICU'),
        ('pediatric', 'Pediatric'),
        ('maternity', 'Maternity'),
    ], default='general', required=True)
    daily_charge = fields.Monetary(compute='_compute_daily_charge', store=True, readonly=False,
                                   currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    under_maintenance = fields.Boolean(tracking=True)
    admission_id = fields.Many2one('clinic.admission', string="Current Admission", readonly=True, copy=False)
    patient_id = fields.Many2one(related='admission_id.patient_id', string="Assigned Patient")
    admission_date = fields.Datetime(related='admission_id.admission_date')
    state = fields.Selection([
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('maintenance', 'Maintenance'),
    ], compute='_compute_state', store=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(related='room_id.company_id', store=True, index=True)

    _name_room_uniq = models.Constraint('UNIQUE(name, room_id)', 'The bed number must be unique within a room.')

    @api.depends('room_id.category_id.daily_rate')
    def _compute_daily_charge(self):
        for bed in self:
            if not bed.daily_charge:
                bed.daily_charge = bed.room_id.category_id.daily_rate

    @api.depends('admission_id', 'under_maintenance')
    def _compute_state(self):
        for bed in self:
            if bed.admission_id:
                bed.state = 'occupied'
            elif bed.under_maintenance:
                bed.state = 'maintenance'
            else:
                bed.state = 'available'

    @api.depends('name', 'room_id.name')
    def _compute_display_name(self):
        for bed in self:
            bed.display_name = f"{bed.room_id.name} / {bed.name}" if bed.room_id else bed.name

    @api.constrains('daily_charge')
    def _check_charge(self):
        if any(bed.daily_charge < 0 for bed in self):
            raise ValidationError(self.env._("The bed charge cannot be negative."))

    @api.constrains('under_maintenance', 'admission_id')
    def _check_maintenance(self):
        for bed in self:
            if bed.under_maintenance and bed.admission_id:
                raise ValidationError(self.env._("Bed %s is occupied and cannot be put under maintenance.", bed.display_name))

    def unlink(self):
        if self.filtered('admission_id'):
            raise UserError(self.env._("Occupied beds cannot be deleted."))
        return super().unlink()

    def action_view_admission(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Admission"),
            'res_model': 'clinic.admission',
            'res_id': self.admission_id.id,
            'view_mode': 'form',
        }

    def action_new_admission(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("New Admission"),
            'res_model': 'clinic.admission',
            'view_mode': 'form',
            'context': {'default_room_id': self.room_id.id, 'default_bed_id': self.id},
        }

    def action_toggle_maintenance(self):
        for bed in self:
            bed.under_maintenance = not bed.under_maintenance
