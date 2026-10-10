from odoo import _, fields, models
from odoo.exceptions import UserError


class SmartLotBackfillWizard(models.TransientModel):
    _name = 'smart.lot.backfill.wizard'
    _description = 'Generate Missing Smart Lot Barcodes'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    product_ids = fields.Many2many('product.product', string='Variants')
    include_archived = fields.Boolean()
    missing_count = fields.Integer(compute='_compute_missing_count')

    def _domain(self):
        domain = [('smart_barcode', '=', False), ('product_id.tracking', '!=', 'none'),
                  '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)]
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        return domain

    def _compute_missing_count(self):
        for wizard in self:
            wizard.missing_count = self.env['stock.lot'].with_context(
                active_test=not wizard.include_archived).search_count(wizard._domain())

    def action_generate(self):
        self.ensure_one()
        config = self.env['smart.lot.barcode.config'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not config or not config.enabled:
            raise UserError(_('Enable Smart Lot Barcodes for this company first.'))
        lots = self.env['stock.lot'].with_context(active_test=not self.include_archived).search(self._domain())
        lots._ensure_smart_barcodes()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Smart Lot Barcodes'),
                       'message': _('%s missing barcode(s) generated.', len(lots)),
                       'type': 'success' if lots else 'info', 'sticky': False},
        }


class SmartLotPrintWizard(models.TransientModel):
    _name = 'smart.lot.print.wizard'
    _description = 'Print Smart Lot Barcodes'

    lot_ids = fields.Many2many('stock.lot', required=True)
    label_quantity = fields.Integer(default=1, required=True)
    label_format = fields.Selection([
        ('thermal_50x30', 'Thermal 50 x 30 mm'),
        ('thermal_40x25', 'Thermal 40 x 25 mm'),
        ('a4', 'A4 sheet'),
    ], default='thermal_50x30', required=True)

    def action_print(self):
        self.ensure_one()
        if self.label_quantity < 1 or self.label_quantity > 1000:
            raise UserError(_('Label quantity must be between 1 and 1000.'))
        self.lot_ids._ensure_smart_barcodes()
        return self.env.ref('auto_product_barcode_stock.action_smart_lot_label').report_action(
            self.lot_ids, data={'label_quantity': self.label_quantity, 'label_format': self.label_format})
