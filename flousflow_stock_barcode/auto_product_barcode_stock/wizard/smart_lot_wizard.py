import re
import datetime

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SmartLotBackfillWizard(models.TransientModel):
    _name = 'smart.lot.backfill.wizard'
    _description = 'Generate Missing Smart Lot Barcodes'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    product_ids = fields.Many2many('product.product', string='Variants')
    include_archived = fields.Boolean()
    missing_count = fields.Integer(compute='_compute_missing_count')

    def _domain(self):
        domain = [('smart_barcode', '=', False), ('product_id.tracking', 'in', ['lot', 'serial']),
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
        generated = lots._ensure_smart_barcodes()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Smart Lot Barcodes'),
                       'message': _('%s Smart Lot barcode(s) generated.', len(generated)),
                       'type': 'success' if generated else 'info', 'sticky': False},
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
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(
            self.lot_ids, data={'label_quantity': self.label_quantity, 'label_format': self.label_format})


class SmartLotCreateWizard(models.TransientModel):
    _name = 'smart.lot.create.wizard'
    _description = 'Create Lots for an Incoming Transfer'

    picking_id = fields.Many2one('stock.picking', required=True, readonly=True)
    mode = fields.Selection([
        ('create', 'Create Lots'),
        ('redistribute', 'Redistribute Lots'),
    ], default='create', required=True, readonly=True)
    allowed_product_ids = fields.Many2many(
        'product.product', compute='_compute_allowed_product_ids')
    line_ids = fields.One2many('smart.lot.create.wizard.line', 'wizard_id', string='Lots')

    @api.depends('picking_id')
    def _compute_allowed_product_ids(self):
        for wizard in self:
            wizard.allowed_product_ids = wizard.picking_id.move_ids.mapped('product_id').filtered(
                lambda product: product.tracking in ('lot', 'serial')
            ) if wizard.picking_id else self.env['product.product']

    def _default_expiration_date(self, product, picking=None):
        picking = picking or self.picking_id
        if not picking:
            return False
        if not {'use_expiration_date', 'expiration_time'} <= product._fields.keys():
            return False
        if not product.use_expiration_date:
            return False
        receipt_date = fields.Datetime.to_datetime(picking.scheduled_date) or fields.Datetime.now()
        return fields.Date.to_date(
            receipt_date + datetime.timedelta(days=product.expiration_time)
        )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        picking_id = values.get('picking_id') or self.env.context.get('default_picking_id') or self.env.context.get('active_id')
        picking = self.env['stock.picking'].browse(picking_id).exists()
        if not picking:
            return values
        values['picking_id'] = picking.id
        commands = []
        mode = values.get('mode') or self.env.context.get('default_mode') or 'create'
        if mode == 'redistribute':
            source_lines = picking.move_line_ids.filtered(
                lambda line: line.product_id.tracking in ('lot', 'serial') and line.lot_id
            )
            for source_line in source_lines:
                values_line = {
                    'product_id': source_line.product_id.id,
                    'quantity': source_line.quantity,
                    'lot_name': source_line.lot_id.name,
                }
                if source_line.lot_id.expiration_date:
                    values_line.update({
                        'expiration_date': fields.Date.to_date(source_line.lot_id.expiration_date),
                    })
                commands.append(Command.create(values_line))
        else:
            moves = picking.move_ids.filtered(
                lambda move: move.product_id.tracking in ('lot', 'serial')
            )
            products = moves.mapped('product_id')
            for product in products.sorted('display_name'):
                product_moves = moves.filtered(lambda move: move.product_id == product)
                unassigned_lines = product_moves.move_line_ids.filtered(
                    lambda line: not line.lot_id and not line.lot_name
                )
                quantity = sum(
                    line.uom_id._compute_quantity(line.quantity, product.uom_id, round=False)
                    for line in unassigned_lines
                )
                if product.uom_id.is_zero(quantity):
                    quantity = sum(
                        max(
                            move.uom_id._compute_quantity(move.product_uom_qty, product.uom_id, round=False)
                            - move.uom_id._compute_quantity(move.quantity, product.uom_id, round=False),
                            0.0,
                        )
                        for move in product_moves
                    )
                if product.uom_id.is_zero(quantity):
                    continue

                values_line = {'product_id': product.id, 'quantity': quantity}
                expiry_dates = set()
                if 'expiration_date' in self.env['stock.move.line']._fields:
                    expiry_dates = {
                        fields.Date.to_date(line.expiration_date)
                        for line in unassigned_lines if line.expiration_date
                    }
                if len(expiry_dates) == 1:
                    default_expiration = expiry_dates.pop()
                else:
                    default_expiration = self._default_expiration_date(product, picking) if not expiry_dates else False
                if default_expiration:
                    values_line['expiration_date'] = default_expiration

                row_quantities = [quantity]
                if product.tracking == 'serial':
                    whole_quantity = round(quantity)
                    if product.uom_id.compare(quantity, whole_quantity) == 0:
                        row_quantities = [1.0] * int(whole_quantity)
                for row_quantity in row_quantities:
                    row_values = dict(values_line, quantity=row_quantity)
                    commands.append(Command.create(row_values))
        values['line_ids'] = commands
        return values

    def _unassigned_move_lines(self, product):
        self.ensure_one()
        return self.picking_id.move_line_ids.filtered(
            lambda line: line.product_id == product and not line.lot_id and not line.lot_name
        )

    def _next_internal_lot_name(self, product, reserved_names=None):
        self.ensure_one()
        reserved_names = set(reserved_names or ())
        source = product.barcode or product.default_code or 'P%s' % product.id
        source = re.sub(r'[^A-Za-z0-9]+', '-', source).strip('-') or 'P%s' % product.id
        prefix = 'FFL-%s-' % source
        Lot = self.env['stock.lot']
        for number in range(1, 1000000):
            candidate = '%s%06d' % (prefix, number)
            if candidate not in reserved_names and not Lot.search_count([
                ('name', '=', candidate), ('product_id', '=', product.id),
                '|', ('company_id', '=', self.picking_id.company_id.id), ('company_id', '=', False),
            ]):
                return candidate
        raise UserError(_('Could not generate an internal Lot name for %s.') % product.display_name)

    def _validate_lot_lines(self, product, wizard_lines, names):
        if any(
            product.uom_id.is_zero(line.quantity)
            or line.quantity < 0
            for line in wizard_lines
        ):
            raise ValidationError(_('Lot quantities must be greater than zero.'))
        if product.tracking == 'serial' and any(
            product.uom_id.compare(line.quantity, 1.0) != 0
            for line in wizard_lines
        ):
            raise ValidationError(_(
                'Serial-tracked products require exactly one unit per serial number.'
            ))
        if len(names) != len(set(names)):
            raise ValidationError(_('The same Lot/Batch cannot be repeated for one product.'))

    def _partial_move_line_values(self, move_line, quantity):
        values = {
            'move_id': move_line.move_id.id,
            'picking_id': move_line.picking_id.id,
            'company_id': move_line.company_id.id,
            'product_id': move_line.product_id.id,
            'uom_id': move_line.uom_id.id,
            'location_id': move_line.location_id.id,
            'location_dest_id': move_line.location_dest_id.id,
            'quantity': quantity,
        }
        for field_name in ('owner_id', 'package_id', 'result_package_id'):
            if field_name in move_line._fields and move_line[field_name]:
                values[field_name] = move_line[field_name].id
        if 'picked' in move_line._fields:
            values['picked'] = move_line.picked
        return values

    def action_create_and_print(self):
        self.ensure_one()
        if self.mode == 'redistribute':
            return self._action_redistribute()
        picking = self.picking_id
        if picking.picking_type_code != 'incoming':
            raise UserError(_('Lots can only be created from incoming receipts.'))
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
            lambda line: line.product_id.tracking in ('lot', 'serial')
        ).mapped('product_id')
        if any(line.product_id not in tracked_products for line in self.line_ids):
            raise ValidationError(_('Every selected product must be a tracked product on this transfer.'))

        lots = self.env['stock.lot']
        for product in self.line_ids.mapped('product_id'):
            wizard_lines = self.line_ids.filtered(lambda line: line.product_id == product)
            names = []
            for line in wizard_lines:
                name = (line.lot_name or '').strip() or self._next_internal_lot_name(product, names)
                names.append(name)
            self._validate_lot_lines(product, wizard_lines, names)

            move_lines = self._unassigned_move_lines(product)
            requested = sum(wizard_lines.mapped('quantity'))
            available = sum(
                move_line.uom_id._compute_quantity(move_line.quantity, product.uom_id, round=False)
                for move_line in move_lines
            )
            if product.uom_id.is_zero(available):
                # Draft receipts can have demand lines with zero done quantity. Let
                # the lot allocation set the received quantity entered in the wizard.
                quantity_left = requested
                for move in picking.move_ids.filtered(lambda candidate: candidate.product_id == product):
                    assigned_quantity = sum(
                        line.uom_id._compute_quantity(line.quantity, product.uom_id, round=False)
                        for line in move.move_line_ids
                        if line.lot_id or line.lot_name
                    )
                    demand = move.uom_id._compute_quantity(move.product_uom_qty, product.uom_id, round=False)
                    capacity = max(demand - assigned_quantity, 0.0)
                    allocated = min(quantity_left, capacity)
                    if product.uom_id.is_zero(allocated):
                        continue
                    move.quantity = move.quantity + product.uom_id._compute_quantity(
                        allocated, move.uom_id, round=False,
                    )
                    quantity_left -= allocated
                    if product.uom_id.is_zero(quantity_left):
                        break
                if not product.uom_id.is_zero(quantity_left):
                    raise ValidationError(_(
                        'The lot quantities exceed the remaining demand for %(product)s.',
                        product=product.display_name,
                    ))
                move_lines = self._unassigned_move_lines(product)
                empty_lines = move_lines.filtered(
                    lambda line: product.uom_id.is_zero(
                        line.uom_id._compute_quantity(line.quantity, product.uom_id, round=False)
                    )
                )
                empty_lines.unlink()
                move_lines -= empty_lines
                available = sum(
                    move_line.uom_id._compute_quantity(move_line.quantity, product.uom_id, round=False)
                    for move_line in move_lines
                )
            if product.uom_id.compare(requested, available) != 0:
                raise ValidationError(_(
                    'The total quantity for %(product)s must be %(available)s; you entered %(requested)s.',
                    product=product.display_name, available=available, requested=requested,
                ))

            segments = [
                {
                    'line': move_line,
                    'remaining': move_line.uom_id._compute_quantity(
                        move_line.quantity, product.uom_id, round=False,
                    ),
                }
                for move_line in move_lines
            ]
            cursor = 0
            for wizard_line, lot_name in zip(wizard_lines, names):
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
                    if 'expiration_date' in self.env['stock.lot']._fields:
                        expiration_date = wizard_line.expiration_date or self._default_expiration_date(product)
                        if expiration_date:
                            lot_vals['expiration_date'] = expiration_date
                    lot = self.env['stock.lot'].create(lot_vals)
                elif wizard_line.expiration_date and 'expiration_date' in lot._fields:
                    if lot.expiration_date and fields.Date.to_date(lot.expiration_date) != fields.Date.to_date(wizard_line.expiration_date):
                        raise ValidationError(_(
                            'Lot %(lot)s already has a different expiration date.', lot=lot_name,
                        ))
                    if not lot.expiration_date:
                        lot.expiration_date = wizard_line.expiration_date

                quantity_left = wizard_line.quantity
                while not product.uom_id.is_zero(quantity_left):
                    if cursor >= len(segments):
                        raise ValidationError(_('There is not enough unassigned quantity for %s.') % product.display_name)
                    segment = segments[cursor]
                    move_line = segment['line']
                    available_on_line = segment['remaining']
                    assigned = min(quantity_left, available_on_line)
                    assigned_in_line_uom = product.uom_id._compute_quantity(
                        assigned, move_line.uom_id, round=False,
                    )
                    move_line.write({'lot_id': lot.id, 'quantity': assigned_in_line_uom})
                    quantity_left -= move_line.uom_id._compute_quantity(
                        assigned_in_line_uom, product.uom_id, round=False,
                    )
                    remaining_on_line = available_on_line - assigned
                    if product.uom_id.is_zero(remaining_on_line):
                        cursor += 1
                    else:
                        remaining_vals = self._partial_move_line_values(
                            move_line,
                            product.uom_id._compute_quantity(
                                remaining_on_line, move_line.uom_id, round=False,
                            ),
                        )
                        remaining_line = self.env['stock.move.line'].create(remaining_vals)
                        segments.insert(cursor + 1, {
                            'line': remaining_line,
                            'remaining': remaining_on_line,
                        })
                        cursor += 1
                lots |= lot

            empty_lines = picking.move_line_ids.filtered(
                lambda line: (
                    line.product_id == product
                    and not line.lot_id
                    and not line.lot_name
                    and product.uom_id.is_zero(
                        line.uom_id._compute_quantity(line.quantity, product.uom_id, round=False)
                    )
                )
            )
            empty_lines.unlink()

        lots._ensure_smart_barcodes()
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(lots)

    def _action_redistribute(self):
        self.ensure_one()
        picking = self.picking_id
        if picking.picking_type_code != 'incoming':
            raise UserError(_('Lots can only be redistributed on incoming receipts.'))
        if picking.state in ('done', 'cancel'):
            raise UserError(_('Lots cannot be redistributed on a completed or cancelled transfer.'))
        if not self.line_ids:
            raise UserError(_('There are no assigned Lots to redistribute on this transfer.'))

        tracked_products = picking.move_ids.mapped('product_id').filtered(
            lambda product: product.tracking in ('lot', 'serial')
        )
        if any(line.product_id not in tracked_products for line in self.line_ids):
            raise ValidationError(_('Every selected product must be a tracked product on this transfer.'))

        lots = self.env['stock.lot']
        for product in self.line_ids.mapped('product_id'):
            wizard_lines = self.line_ids.filtered(lambda line: line.product_id == product)
            names = []
            for line in wizard_lines:
                names.append((line.lot_name or '').strip() or self._next_internal_lot_name(product, names))
            self._validate_lot_lines(product, wizard_lines, names)

            move_lines = picking.move_line_ids.filtered(lambda line: line.product_id == product)
            available = sum(move_line.quantity for move_line in move_lines)
            requested = sum(wizard_lines.mapped('quantity'))
            if product.uom_id.compare(requested, available) != 0:
                raise ValidationError(_(
                    'The total quantity for %(product)s must be %(available)s; you entered %(requested)s.',
                    product=product.display_name, available=available, requested=requested,
                ))

            for move_line in move_lines:
                move_line.write({'lot_id': False, 'lot_name': False})
            segments = [
                {'line': move_line, 'remaining': move_line.quantity}
                for move_line in move_lines
            ]
            cursor = 0
            for wizard_line, lot_name in zip(wizard_lines, names):
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
                    if lot.expiration_date and fields.Date.to_date(lot.expiration_date) != fields.Date.to_date(wizard_line.expiration_date):
                        raise ValidationError(_(
                            'Lot %(lot)s already has a different expiration date.', lot=lot_name,
                        ))
                    if not lot.expiration_date:
                        lot.expiration_date = wizard_line.expiration_date

                quantity_left = wizard_line.quantity
                while not product.uom_id.is_zero(quantity_left):
                    if cursor >= len(segments):
                        raise ValidationError(_('There is not enough quantity for %s.') % product.display_name)
                    segment = segments[cursor]
                    move_line = segment['line']
                    available_on_line = segment['remaining']
                    assigned = min(quantity_left, available_on_line)
                    move_line.write({'lot_id': lot.id, 'quantity': assigned})
                    quantity_left -= assigned
                    if product.uom_id.is_zero(available_on_line - assigned):
                        cursor += 1
                    else:
                        remaining_vals = self._partial_move_line_values(
                            move_line, available_on_line - assigned,
                        )
                        remaining_line = self.env['stock.move.line'].create(remaining_vals)
                        segments.insert(cursor + 1, {
                            'line': remaining_line,
                            'remaining': available_on_line - assigned,
                        })
                        cursor += 1
                lots |= lot

        lots._ensure_smart_barcodes()
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(lots)


class SmartLotCreateWizardLine(models.TransientModel):
    _name = 'smart.lot.create.wizard.line'
    _description = 'Lot Creation Wizard Line'
    _order = 'id'

    wizard_id = fields.Many2one('smart.lot.create.wizard', required=True, ondelete='cascade')
    allowed_product_ids = fields.Many2many(
        related='wizard_id.allowed_product_ids', readonly=True)
    product_id = fields.Many2one('product.product', required=True)
    # Kept nullable so the wizard can open with prefilled quantity rows before
    # the operator enters the supplier's actual batch number.
    lot_name = fields.Char(
        string='Manufacturer Lot/Batch (optional)',
        help='Leave blank to generate an internal Lot name from the product barcode or code.',
    )
    quantity = fields.Float(required=True, digits='Product Unit')
    expiration_date = fields.Date(string='Expiration Date')
