from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class SmartLotBarcodeConfig(models.Model):
    _name = 'smart.lot.barcode.config'
    _description = 'Smart Lot Barcode Configuration'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company)
    enabled = fields.Boolean(default=True)
    auto_generate = fields.Boolean(string='Generate for new Lots', default=True)
    prefix = fields.Char(default='FFL-', required=True)
    sequence_digits = fields.Integer(default=12, required=True)
    sequence_id = fields.Many2one('ir.sequence', readonly=True, copy=False)
    _company_uniq = models.Constraint(
        'unique(company_id)', 'Only one Smart Lot Barcode configuration is allowed per company.',
    )

    @api.constrains('prefix', 'sequence_digits')
    def _check_format(self):
        for config in self:
            if not config.prefix or config.sequence_digits < 1:
                raise ValidationError(_('A non-empty prefix and a positive sequence length are required.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for config in records:
            config._ensure_sequence()
        return records

    def _ensure_sequence(self):
        self.ensure_one()
        if not self.sequence_id:
            self.sequence_id = self.env['ir.sequence'].create({
                'name': _('Smart Lot Barcode - %s', self.company_id.name),
                'code': 'auto.smart.lot.barcode.%s' % self.company_id.id,
                'company_id': self.company_id.id,
                'padding': self.sequence_digits,
                'number_next': 1,
                'number_next_actual': 1,
                'use_date_range': False,
            })

    def write(self, vals):
        result = super().write(vals)
        if 'sequence_digits' in vals:
            for config in self.filtered('sequence_id'):
                config.sequence_id.write({'padding': config.sequence_digits})
        return result

    def _next_unique_barcode(self, product):
        self.ensure_one()
        self._ensure_sequence()
        if not product.barcode:
            raise UserError(_(
                'Product %(product)s has no barcode. Generate a product barcode '
                'before generating its Smart Lot Barcode.',
                product=product.display_name,
            ))

        Lot = self.env['stock.lot'].with_context(active_test=False)
        Product = self.env['product.product'].with_context(active_test=False)
        prefix = '%s%s-' % (self.prefix or '', product.barcode)
        max_attempts = (
            Lot.search_count([('smart_barcode', '!=', False)])
            + Product.search_count([('barcode', '!=', False)])
            + 1
        )
        if 'product.packaging' in self.env:
            max_attempts += self.env['product.packaging'].with_context(
                active_test=False
            ).search_count([('barcode', '!=', False)])
        for _attempt in range(max_attempts):
            suffix = self.sequence_id.next_by_id()
            value = '%s%s' % (prefix, suffix)
            if Lot.search_count([('smart_barcode', '=', value)], limit=1):
                continue
            if Product.search_count([('barcode', '=', value)], limit=1):
                continue
            if 'product.packaging' in self.env:
                if self.env['product.packaging'].search_count([('barcode', '=', value)], limit=1):
                    continue
            return value
        raise UserError(_('Could not allocate a unique Smart Lot Barcode.'))


class StockLot(models.Model):
    _inherit = 'stock.lot'

    smart_barcode = fields.Char(string='Smart Lot Barcode', index=True, copy=False, readonly=True)
    smart_barcode_company_id = fields.Many2one(
        'res.company', related='company_id', store=True, index=True, readonly=True)
    smart_barcode_symbology = fields.Char(compute='_compute_smart_barcode_symbology')
    _smart_barcode_uniq = models.Constraint(
        'unique(smart_barcode)', 'Smart Lot Barcodes must be unique.',
    )

    @api.depends('company_id', 'smart_barcode')
    def _compute_smart_barcode_symbology(self):
        for lot in self:
            # A Smart Lot barcode combines the product barcode with a lot
            # sequence, so it is not an EAN-13 value even if the product code is.
            lot.smart_barcode_symbology = 'Code128'

    @api.model_create_multi
    def create(self, vals_list):
        lots = super().create(vals_list)
        lots._ensure_smart_barcodes(automatic=True)
        return lots

    def _ensure_smart_barcodes(self, automatic=False):
        company_ids = (self.mapped('company_id') | self.env.company).ids
        config_domain = [
            ('company_id', 'in', company_ids), ('enabled', '=', True),
        ]
        if automatic:
            config_domain.append(('auto_generate', '=', True))
        configs = self.env['smart.lot.barcode.config'].search(config_domain)
        by_company = {config.company_id.id: config for config in configs}
        # Odoo 20 represents untracked products with a false tracking value;
        # only lot- and serial-tracked products can receive Smart Lot labels.
        for lot in self.filtered(
            lambda r: (
                not r.smart_barcode
                and r.product_id.barcode
                and r.product_id.tracking in ('lot', 'serial')
            )
        ):
            config = by_company.get((lot.company_id or self.env.company).id)
            if config:
                lot.smart_barcode = config._next_unique_barcode(lot.product_id)
        return self.filtered('smart_barcode')

    def action_print_smart_barcode(self):
        self._ensure_smart_barcodes()
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(self)

    @api.model
    def resolve_smart_barcode(self, barcode):
        lot = self.search([('smart_barcode', '=', barcode)], limit=1)
        if not lot or lot.company_id not in (self.env.company | self.env.companies):
            return False
        return {
            'lot_id': lot.id,
            'lot_name': lot.name,
            'smart_barcode': lot.smart_barcode,
            'product_id': lot.product_id.id,
            'product_name': lot.product_id.display_name,
            'company_id': lot.company_id.id,
            'expiration_date': getattr(lot, 'expiration_date', False),
        }

    @api.model
    def pos_resolve_smart_barcode(self, barcode, company_id):
        """Resolve one Smart Lot barcode for an authorized POS company.

        POS cashiers are not necessarily stock users, so expose only the
        minimal lot data needed by POS after checking their group and company.
        """
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only Point of Sale users can resolve Smart Lot barcodes.'))
        if not isinstance(barcode, str) or not barcode:
            return False
        if not isinstance(company_id, int) or isinstance(company_id, bool):
            return False
        company = self.env['res.company'].browse(company_id).exists()
        if len(company) != 1 or company not in self.env.companies:
            return False
        lot = self.sudo().search([
            ('smart_barcode', '=', barcode),
            ('company_id', '=', company.id),
        ], limit=1)
        if not lot:
            return False
        return {
            'id': lot.id,
            'name': lot.name,
            'product_id': lot.product_id.id,
            'product_tmpl_id': lot.product_id.product_tmpl_id.id,
        }


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_open_smart_lot_creator(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Lots and Print Barcodes'),
            'res_model': 'smart.lot.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id, 'active_id': self.id},
        }

    def action_open_smart_lot_redistributor(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Redistribute Lots'),
            'res_model': 'smart.lot.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_mode': 'redistribute',
                'active_id': self.id,
            },
        }

    def action_generate_print_lot_barcodes(self):
        self.ensure_one()
        lots = self.move_line_ids.filtered(
            lambda line: line.product_id.tracking in ('lot', 'serial') and line.lot_id
        ).mapped('lot_id')
        lots._ensure_smart_barcodes()
        if not lots:
            raise UserError(_('No assigned tracked Lots were found. Enter the actual manufacturer batches first.'))
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(lots)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_print_lot_barcodes(self):
        self.ensure_one()
        lots = self.env['stock.lot'].search([('product_id', '=', self.id)])
        lots._ensure_smart_barcodes()
        if not lots:
            raise UserError(_('This variant has no native Lots yet.'))
        return self.env.ref('flousflow_stock_barcode.action_smart_lot_label').report_action(lots)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    smart_lot_enabled = fields.Boolean(string='Enable Smart Lot Barcodes')
    smart_lot_auto_generate = fields.Boolean(string='Generate for new Lots')
    smart_lot_prefix = fields.Char(string='Smart Lot Prefix')
    smart_lot_sequence_digits = fields.Integer(string='Sequence Digits')

    def get_values(self):
        values = super().get_values()
        config = self.env['smart.lot.barcode.config'].search([('company_id', '=', self.env.company.id)], limit=1)
        values.update({
            'smart_lot_enabled': config.enabled if config else True,
            'smart_lot_auto_generate': config.auto_generate if config else True,
            'smart_lot_prefix': config.prefix if config else 'FFL-',
            'smart_lot_sequence_digits': config.sequence_digits if config else 12,
        })
        return values

    def set_values(self):
        super().set_values()
        config = self.env['smart.lot.barcode.config'].search([('company_id', '=', self.env.company.id)], limit=1)
        vals = {
            'enabled': self.smart_lot_enabled,
            'auto_generate': self.smart_lot_auto_generate,
            'prefix': self.smart_lot_prefix or 'FFL-',
            'sequence_digits': self.smart_lot_sequence_digits or 12,
            'company_id': self.env.company.id,
        }
        if config:
            config.write(vals)
        else:
            self.env['smart.lot.barcode.config'].create(vals)
