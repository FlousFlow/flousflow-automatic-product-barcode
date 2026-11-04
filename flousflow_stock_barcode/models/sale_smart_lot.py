from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    preferred_lot_id = fields.Many2one(
        'stock.lot',
        string='Delivery Lot',
        check_company=True,
        copy=False,
        domain="[('product_id', '=', product_id)]",
        help='Lot selected by scanning on the sales order; delivery reserves this Lot first.',
    )

    @api.constrains('preferred_lot_id', 'product_id', 'company_id')
    def _check_preferred_lot(self):
        for line in self:
            lot = line.preferred_lot_id
            if not lot:
                continue
            if line.product_id and lot.product_id != line.product_id:
                raise ValidationError(_(
                    'The selected Delivery Lot belongs to a different product.'
                ))
            if lot.product_id.tracking not in ('lot', 'serial'):
                raise ValidationError(_(
                    'A Delivery Lot can only be selected for a Lot/Serial tracked product.'
                ))
            if lot.company_id and line.company_id and lot.company_id != line.company_id:
                raise ValidationError(_(
                    'The selected Delivery Lot belongs to another company.'
                ))


class StockMove(models.Model):
    _inherit = 'stock.move'

    preferred_lot_id = fields.Many2one(
        related='sale_line_id.preferred_lot_id',
        string='Preferred Delivery Lot',
        store=True,
        readonly=True,
    )

    def _action_assign(self, force_qty=False):
        result = super()._action_assign(force_qty=force_qty)
        for move in self.filtered(
            lambda item: (
                item.preferred_lot_id
                and not item.picked
                and item.state not in ('done', 'cancel')
                and item.preferred_lot_id.product_id == item.product_id
            )
        ):
            # Replace core FIFO reservations with the exact scanned Lot. If
            # stock is short, leave the remainder unreserved for a backorder.
            move._do_unreserve()
            quants = self.env['stock.quant']._gather(
                move.product_id,
                move.location_id,
                lot_id=move.preferred_lot_id,
            ).filtered(lambda quant: quant.lot_id == move.preferred_lot_id)
            available = sum(max(quant.available_quantity, 0.0) for quant in quants)
            if available:
                move.lot_ids = move.preferred_lot_id
        return result
