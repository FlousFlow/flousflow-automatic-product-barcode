from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


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


class SmartLotCreateWizard(models.TransientModel):
    _name = 'smart.lot.create.wizard'
    _description = 'Create Lots for an Incoming Transfer'

    picking_id = fields.Many2one('stock.picking', required=True, readonly=True)
    line_ids = fields.One2many('smart.lot.create.wizard.line', 'wizard_id', string='Lots')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        picking_id = values.get('picking_id') or self.env.context.get('default_picking_id') or self.env.context.get('active_id')
        picking = self.env['stock.picking'].browse(picking_id).exists()
        if not picking:
            return values
        values['picking_id'] = picking.id
        commands = []
        products = picking.move_line_ids.filtered(
            lambda line: line.product_id.tracking != 'none' and not line.lot_id and not line.lot_name
        ).mapped('product_id')
        for product in products.sorted('display_name'):
            quantity = sum(
                line.quantity for line in picking.move_line_ids
                if line.product_id == product and not line.lot_id and not line.lot_name
            )
            if not float_is_zero(quantity, precision_rounding=product.uom_id.rounding):
                commands.append(Command.create({
                    'product_id': product.id,
                    'quantity': quantity,
                }))
        values['line_ids'] = commands
        return values

    def _unassigned_move_lines(self, product):
        self.ensure_one()
        return self.picking_id.move_line_ids.filtered(
            lambda line: line.product_id == product and not line.lot_id and not line.lot_name
        )

    def action_create_and_print(self):
        self.ensure_one()
        picking = self.picking_id
        if picking.state in ('done', 'cancel'):
            raise UserError(_('Lots cannot be created on a completed or cancelled transfer.'))
        if not self.line_ids:
            raise UserError(_('Add at least one manufacturer Lot/Batch before continuing.'))
        config = self.env['smart.lot.barcode.config'].search(
            [('company_id', '=', picking.company_id.id)], limit=1)
        if not config:
            self.env['smart.lot.barcode.config'].create({
                'company_id': picking.company_id.id,
                'enabled': True,
                'auto_generate': True,
                'prefix': 'FFL-',
                'sequence_digits': 12,
            })

        tracked_products = picking.move_line_ids.filtered(
            lambda line: line.product_id.tracking != 'none'
        ).mapped('product_id')
        if any(line.product_id not in tracked_products for line in self.line_ids):
            raise ValidationError(_('Every selected product must be a tracked product on this transfer.'))

        lots = self.env['stock.lot']
        for product in self.line_ids.mapped('product_id'):
            wizard_lines = self.line_ids.filtered(lambda line: line.product_id == product)
            if any(float_is_zero(line.quantity, precision_rounding=product.uom_id.rounding) or line.quantity < 0 for line in wizard_lines):
                raise ValidationError(_('Lot quantities must be greater than zero.'))
            names = [(line.lot_name or '').strip() for line in wizard_lines]
            if any(not name for name in names):
                raise ValidationError(_('Enter the actual manufacturer Lot/Batch for every row.'))
            if len(names) != len(set(names)):
                raise ValidationError(_('The same Lot/Batch cannot be repeated for one product.'))

            move_lines = self._unassigned_move_lines(product)
            available = sum(move_line.quantity for move_line in move_lines)
            requested = sum(wizard_lines.mapped('quantity'))
            if float_compare(requested, available, precision_rounding=product.uom_id.rounding) != 0:
                raise ValidationError(_(
                    'The total quantity for %(product)s must be %(available)s; you entered %(requested)s.',
                    product=product.display_name, available=available, requested=requested,
                ))

            segments = [
                {'line': move_line, 'remaining': move_line.quantity}
                for move_line in move_lines
            ]
            cursor = 0
            for wizard_line in wizard_lines:
                lot_name = wizard_line.lot_name.strip()
                lot = self.env['stock.lot'].search([
                    ('name', '=', lot_name), ('product_id', '=', product.id),
                    '|', ('company_id', '=', picking.company_id.id), ('company_id', '=', False),
                ], limit=1)
                if not lot:
                    lot_vals = {
                        'name': lot_name,
                        'product_id': product.id,
                        'company_id': picking.company_id.id,
                    }
                    if 'expiration_date' in self.env['stock.lot']._fields and wizard_line.expiration_date:
                        lot_vals['expiration_date'] = wizard_line.expiration_date
                    lot = self.env['stock.lot'].create(lot_vals)
                elif wizard_line.expiration_date and 'expiration_date' in lot._fields:
                    if lot.expiration_date and lot.expiration_date != wizard_line.expiration_date:
                        raise ValidationError(_(
                            'Lot %(lot)s already has a different expiration date.', lot=lot_name,
                        ))
                    if not lot.expiration_date:
                        lot.expiration_date = wizard_line.expiration_date

                quantity_left = wizard_line.quantity
                while not float_is_zero(quantity_left, precision_rounding=product.uom_id.rounding):
                    if cursor >= len(segments):
                        raise ValidationError(_('There is not enough unassigned quantity for %s.') % product.display_name)
                    segment = segments[cursor]
                    move_line = segment['line']
                    available_on_line = segment['remaining']
                    assigned = min(quantity_left, available_on_line)
                    move_line.write({'lot_id': lot.id, 'quantity': assigned})
                    quantity_left -= assigned
                    if float_is_zero(available_on_line - assigned, precision_rounding=product.uom_id.rounding):
                        cursor += 1
                    else:
                        remaining_vals = {
                            'move_id': move_line.move_id.id,
                            'picking_id': picking.id,
                            'company_id': picking.company_id.id,
                            'product_id': product.id,
                            'product_uom_id': move_line.product_uom_id.id,
                            'location_id': move_line.location_id.id,
                            'location_dest_id': move_line.location_dest_id.id,
                            'quantity': available_on_line - assigned,
                        }
                        for field_name in ('owner_id', 'package_id', 'result_package_id'):
                            if field_name in move_line._fields and move_line[field_name]:
                                remaining_vals[field_name] = move_line[field_name].id
                        remaining_line = self.env['stock.move.line'].create(remaining_vals)
                        segments.insert(cursor + 1, {
                            'line': remaining_line,
                            'remaining': available_on_line - assigned,
                        })
                        cursor += 1
                lots |= lot

        lots._ensure_smart_barcodes()
        return self.env.ref('auto_product_barcode_stock.action_smart_lot_label').report_action(lots)


class SmartLotCreateWizardLine(models.TransientModel):
    _name = 'smart.lot.create.wizard.line'
    _description = 'Lot Creation Wizard Line'
    _order = 'id'

    wizard_id = fields.Many2one('smart.lot.create.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    # Kept nullable so the wizard can open with prefilled quantity rows before
    # the operator enters the supplier's actual batch number.
    lot_name = fields.Char(string='Manufacturer Lot/Batch')
    quantity = fields.Float(required=True, digits='Product Unit')
    expiration_date = fields.Date(string='Expiration Date')
