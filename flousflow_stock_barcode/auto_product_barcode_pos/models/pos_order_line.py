from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    smart_lot_barcode = fields.Char(copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            lot_name = vals.get('pack_lot_ids') and vals['pack_lot_ids'][0]
            if isinstance(lot_name, dict):
                vals.setdefault('smart_lot_barcode', lot_name.get('smart_lot_barcode'))
        return super().create(vals_list)
