from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .barcode_config import format_barcode


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    barcode_generation_enabled = fields.Boolean(
        string='Enable Automatic Barcode Generation')
    barcode_format = fields.Selection([
        ('sequential', 'Sequential Numeric'),
        ('prefix', 'Prefix + Sequential Numeric'),
        ('ean13', 'EAN-13'),
    ], string='Barcode Format')
    barcode_prefix = fields.Char(string='Prefix')
    barcode_sequence_digits = fields.Integer(string='Sequence Digits', default=10)
    barcode_starting_number = fields.Integer(string='Starting Number', default=1)
    barcode_include_archived = fields.Boolean(
        string='Include Archived Products')
    barcode_existing_policy = fields.Selection([
        ('keep', 'Keep Existing Barcodes'),
    ], string='Existing Barcode Policy', readonly=True)
    barcode_preview = fields.Char(
        string='Barcode Preview', compute='_compute_barcode_preview')

    @api.depends('barcode_format', 'barcode_prefix',
                 'barcode_sequence_digits', 'barcode_starting_number')
    def _compute_barcode_preview(self):
        for record in self:
            if not record.barcode_sequence_digits \
                    or record.barcode_sequence_digits < 1:
                record.barcode_preview = ''
                continue
            number_str = str(record.barcode_starting_number or 0).zfill(
                record.barcode_sequence_digits)
            try:
                record.barcode_preview = format_barcode(
                    record.barcode_format, record.barcode_prefix, number_str)
            except ValidationError:
                record.barcode_preview = _('Invalid EAN-13 configuration')

    def get_values(self):
        res = super().get_values()
        config = self.env['auto.barcode.config'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        res.update(
            barcode_generation_enabled=config.enabled if config else False,
            barcode_format=config.barcode_format if config else 'sequential',
            barcode_prefix=config.prefix if config else '',
            barcode_sequence_digits=config.sequence_digits if config else 10,
            barcode_starting_number=config.starting_number if config else 1,
            barcode_include_archived=config.include_archived if config else False,
            barcode_existing_policy=(
                config.existing_barcode_policy if config else 'keep'),
        )
        return res

    def set_values(self):
        super().set_values()
        company = self.env.company
        config = self.env['auto.barcode.config'].search(
            [('company_id', '=', company.id)], limit=1)
        vals = {
            'enabled': self.barcode_generation_enabled,
            'barcode_format': self.barcode_format,
            'prefix': self.barcode_prefix or '',
            'sequence_digits': self.barcode_sequence_digits,
            'starting_number': self.barcode_starting_number,
            'include_archived': self.barcode_include_archived,
        }
        if config:
            config.write(vals)
        else:
            vals['company_id'] = company.id
            self.env['auto.barcode.config'].create(vals)

    def action_generate_missing_barcodes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Product Barcodes'),
            'res_model': 'auto.barcode.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_id': self.env.company.id},
        }
