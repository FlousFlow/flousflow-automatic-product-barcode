import datetime

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class _FakeMoveLine(dict):
    def __getattr__(self, name):
        return self[name]


class TestSmartLotBarcode(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Product = cls.env['product.product']
        cls.Lot = cls.env['stock.lot']
        cls.Config = cls.env['smart.lot.barcode.config']
        cls.config = cls.Config.search([('company_id', '=', cls.company.id)], limit=1)
        if cls.config:
            cls.config.write({'enabled': True, 'auto_generate': True, 'prefix': 'FFL-', 'sequence_digits': 6})
        else:
            cls.config = cls.Config.create({
                'company_id': cls.company.id,
                'prefix': 'FFL-',
                'sequence_digits': 6,
            })

    def _product(self, **vals):
        vals.setdefault('name', 'Tracked Product')
        vals.setdefault('barcode', 'TEST-PRODUCT-%s' % (self.Product.search_count([]) + 1))
        vals.setdefault('tracking', 'lot')
        vals.setdefault('is_storable', True)
        return self.Product.create(vals)

    def test_manufacturer_barcode_is_preserved(self):
        product = self._product(barcode='6221234567895')
        lot = self.Lot.create({'name': 'BATCH-A', 'product_id': product.id, 'company_id': self.company.id})
        self.assertTrue(lot.smart_barcode)
        self.assertEqual(product.barcode, '6221234567895')
        self.assertEqual(self.Lot.resolve_smart_barcode(lot.smart_barcode)['product_id'], product.id)

    def test_smart_barcode_is_derived_from_product_barcode_and_unique_per_lot(self):
        product = self._product(barcode='PROD-42')
        first = self.Lot.create({
            'name': 'BATCH-1', 'product_id': product.id, 'company_id': self.company.id,
        })
        second = self.Lot.create({
            'name': 'BATCH-2', 'product_id': product.id, 'company_id': self.company.id,
        })

        self.assertTrue(first.smart_barcode.startswith('FFL-PROD-42-'))
        self.assertTrue(second.smart_barcode.startswith('FFL-PROD-42-'))
        self.assertNotEqual(first.smart_barcode, second.smart_barcode)
        self.assertEqual(first.smart_barcode_symbology, 'Code128')

    def test_missing_product_barcode_blocks_smart_barcode_generation(self):
        product = self._product(barcode=False)
        lot = self.Lot.create({
            'name': 'BATCH-NO-PRODUCT-BARCODE',
            'product_id': product.id,
            'company_id': self.company.id,
        })
        self.assertFalse(lot.smart_barcode)

        product.barcode = 'PROD-43'
        lot._ensure_smart_barcodes()
        self.assertTrue(lot.smart_barcode.startswith('FFL-PROD-43-'))

    def test_pos_user_can_resolve_lot_without_stock_group(self):
        lot = self.Lot.create({
            'name': 'BATCH-POS',
            'product_id': self._product().id,
            'company_id': self.company.id,
        })
        pos_user = self.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'POS cashier',
            'login': 'smart_lot_pos_cashier',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        self.assertFalse(pos_user.has_group('stock.group_stock_user'))

        result = self.Lot.with_user(pos_user).with_company(
            self.company
        ).pos_resolve_smart_barcode(lot.smart_barcode, self.company.id)

        self.assertEqual(result['id'], lot.id)
        self.assertEqual(result['name'], lot.name)
        self.assertEqual(result['product_id'], lot.product_id.id)

    def test_sales_product_search_resolves_smart_lot_barcode(self):
        product = self._product(name='Searchable Tracked Product')
        lot = self.Lot.create({
            'name': 'BATCH-SALE-SEARCH',
            'product_id': product.id,
            'company_id': self.company.id,
        })

        result = self.Product.name_search(
            name=lot.smart_barcode,
            domain=[('sale_ok', '=', True)],
            operator='ilike',
        )

        self.assertEqual(result, [(product.id, product.display_name)])

        template_result = self.env['product.template'].name_search(
            name=lot.smart_barcode,
            domain=[('sale_ok', '=', True)],
            operator='ilike',
        )
        self.assertEqual(
            template_result,
            [(product.product_tmpl_id.id, product.product_tmpl_id.display_name)],
        )

        lot_name_result = self.env['product.template'].name_search(
            name=lot.name,
            domain=[('sale_ok', '=', True)],
            operator='=',
        )
        self.assertEqual(
            lot_name_result,
            [(product.product_tmpl_id.id, product.product_tmpl_id.display_name)],
        )

        excluded_result = self.Product.name_search(
            name=lot.smart_barcode,
            domain=[('id', '=', False)],
            operator='ilike',
        )
        self.assertFalse(excluded_result)

        excluded_template_result = self.env['product.template'].name_search(
            name=lot.smart_barcode,
            domain=[('id', '=', False)],
            operator='ilike',
        )
        self.assertFalse(excluded_template_result)

        other_product = self._product(name='Another Product With Same Lot Name')
        self.Lot.create({
            'name': lot.name,
            'product_id': other_product.id,
            'company_id': self.company.id,
        })
        self.assertFalse(self.env['product.template'].name_search(
            name=lot.name,
            domain=[('sale_ok', '=', True)],
            operator='=',
        ))

    def test_non_pos_user_cannot_resolve_lot(self):
        lot = self.Lot.create({
            'name': 'BATCH-NON-POS',
            'product_id': self._product().id,
            'company_id': self.company.id,
        })
        user = self.env['res.users'].with_context(
            no_reset_password=True,
        ).create({
            'name': 'Internal user',
            'login': 'smart_lot_internal_user',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })

        with self.assertRaises(AccessError):
            self.Lot.with_user(user).with_company(
                self.company
            ).pos_resolve_smart_barcode(lot.smart_barcode, self.company.id)

    def test_serial_wizard_requires_one_unit_per_serial(self):
        product = self._product(tracking='serial')
        wizard = self.env['smart.lot.create.wizard']
        line = type('WizardLine', (), {'quantity': 2.0})()

        with self.assertRaises(ValidationError):
            wizard._validate_lot_lines(product, [line], ['SERIAL-1'])

        line.quantity = 1.0
        wizard._validate_lot_lines(product, [line], ['SERIAL-1'])

    def test_partial_move_line_keeps_pick_and_package_context(self):
        wizard = self.env['smart.lot.create.wizard']
        move_line = _FakeMoveLine(
            _fields={'owner_id', 'package_id', 'result_package_id', 'picked'},
            move_id=type('Record', (), {'id': 1})(),
            picking_id=type('Record', (), {'id': 2})(),
            company_id=type('Record', (), {'id': 3})(),
            product_id=type('Record', (), {'id': 4})(),
            uom_id=type('Record', (), {'id': 5})(),
            location_id=type('Record', (), {'id': 6})(),
            location_dest_id=type('Record', (), {'id': 7})(),
            owner_id=type('Record', (), {'id': 8})(),
            package_id=type('Record', (), {'id': 9})(),
            result_package_id=type('Record', (), {'id': 10})(),
            picked=True,
        )

        values = wizard._partial_move_line_values(move_line, 3.0)

        self.assertEqual(values['quantity'], 3.0)
        self.assertEqual(values['uom_id'], 5)
        self.assertNotIn('product_uom_id', values)
        self.assertEqual(values['owner_id'], 8)
        self.assertEqual(values['package_id'], 9)
        self.assertEqual(values['result_package_id'], 10)
        self.assertTrue(values['picked'])

    def test_receipt_lot_split_and_redistribution_keep_quantities_and_expiry_dates(self):
        product = self._product(barcode='PRODUCT-SPLIT-TEST')
        template = product.product_tmpl_id
        if 'use_expiration_date' in template._fields:
            template.write({'use_expiration_date': True, 'expiration_time': 365})

        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company.id)], limit=1)
        picking_type = warehouse.in_type_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
        })
        move = self.env['stock.move'].create({
            'description_picking_manual': product.display_name,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'product_uom_qty': 10,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
        })
        self.env['stock.move.line'].create({
            'picking_id': picking.id,
            'move_id': move.id,
            'company_id': self.company.id,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'quantity': 10,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })

        wizard = self.env['smart.lot.create.wizard'].create({
            'picking_id': picking.id,
            'mode': 'create',
        })
        self.env['smart.lot.create.wizard.line'].create([
            {
                'wizard_id': wizard.id,
                'product_id': product.id,
                'lot_name': 'SUPPLIER-5M',
                'quantity': 4,
                'expiration_date': fields.Date.to_date('2027-04-01'),
            },
            {
                'wizard_id': wizard.id,
                'product_id': product.id,
                'lot_name': 'SUPPLIER-11M',
                'quantity': 6,
                'expiration_date': fields.Date.to_date('2027-10-01'),
            },
        ])
        wizard.action_create_and_print()

        self.assertEqual(
            sorted((line.lot_id.name, line.quantity) for line in picking.move_line_ids),
            [('SUPPLIER-11M', 6.0), ('SUPPLIER-5M', 4.0)],
        )
        if 'expiration_date' in self.Lot._fields:
            expirations = {
                lot.name: fields.Date.to_date(lot.expiration_date)
                for lot in picking.move_line_ids.mapped('lot_id')
            }
            self.assertEqual(expirations['SUPPLIER-5M'], fields.Date.to_date('2027-04-01'))
            self.assertEqual(expirations['SUPPLIER-11M'], fields.Date.to_date('2027-10-01'))

        redistribute = self.env['smart.lot.create.wizard'].create({
            'picking_id': picking.id,
            'mode': 'redistribute',
        })
        self.env['smart.lot.create.wizard.line'].create([
            {
                'wizard_id': redistribute.id,
                'product_id': product.id,
                'lot_name': 'REDISTRIBUTED-3',
                'quantity': 3,
                'expiration_date': fields.Date.to_date('2027-05-01'),
            },
            {
                'wizard_id': redistribute.id,
                'product_id': product.id,
                'lot_name': 'REDISTRIBUTED-7',
                'quantity': 7,
                'expiration_date': fields.Date.to_date('2027-11-01'),
            },
        ])
        redistribute.action_create_and_print()

        redistributed_quantities = {}
        for line in picking.move_line_ids:
            redistributed_quantities[line.lot_id.name] = (
                redistributed_quantities.get(line.lot_id.name, 0.0) + line.quantity
            )
        self.assertEqual(
            redistributed_quantities,
            {'REDISTRIBUTED-3': 3.0, 'REDISTRIBUTED-7': 7.0},
        )
        if 'expiration_date' in self.Lot._fields:
            expirations = {
                lot.name: fields.Date.to_date(lot.expiration_date)
                for lot in picking.move_line_ids.mapped('lot_id')
            }
            self.assertEqual(expirations['REDISTRIBUTED-3'], fields.Date.to_date('2027-05-01'))
            self.assertEqual(expirations['REDISTRIBUTED-7'], fields.Date.to_date('2027-11-01'))

    def test_create_wizard_prefills_remaining_demand_and_product_expiration(self):
        product = self._product(barcode='PRODUCT-DEFAULT-TEST')
        template = product.product_tmpl_id
        if 'use_expiration_date' in template._fields:
            template.write({'use_expiration_date': True, 'expiration_time': 365})

        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company.id)], limit=1)
        picking_type = warehouse.in_type_id
        scheduled_date = fields.Datetime.to_datetime('2027-01-01 12:00:00')
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
            'scheduled_date': scheduled_date,
        })
        move = self.env['stock.move'].create({
            'description_picking_manual': product.display_name,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'product_uom_qty': 10,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
        })
        self.env['stock.move.line'].create({
            'picking_id': picking.id,
            'move_id': move.id,
            'company_id': self.company.id,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'quantity': 0,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })

        defaults = self.env['smart.lot.create.wizard'].with_context(
            default_picking_id=picking.id,
        ).default_get(['picking_id', 'line_ids'])

        self.assertEqual(defaults['picking_id'], picking.id)
        self.assertEqual(len(defaults['line_ids']), 1)
        line_values = defaults['line_ids'][0][2]
        self.assertEqual(line_values['product_id'], product.id)
        self.assertEqual(line_values['quantity'], 10)
        if 'use_expiration_date' in template._fields:
            self.assertEqual(
                line_values['expiration_date'],
                fields.Date.to_date(picking.scheduled_date) + datetime.timedelta(days=365),
            )

    def test_create_wizard_assigns_quantity_when_receipt_line_is_zero(self):
        product = self._product(barcode='PRODUCT-ZERO-LINE-TEST')
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company.id)], limit=1)
        picking_type = warehouse.in_type_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': picking_type.default_location_dest_id.id,
        })
        move = self.env['stock.move'].create({
            'description_picking_manual': product.display_name,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'product_uom_qty': 10,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'picking_id': picking.id,
        })
        self.env['stock.move.line'].create({
            'picking_id': picking.id,
            'move_id': move.id,
            'company_id': self.company.id,
            'product_id': product.id,
            'uom_id': product.uom_id.id,
            'quantity': 0,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })
        wizard = self.env['smart.lot.create.wizard'].create({
            'picking_id': picking.id,
        })
        self.env['smart.lot.create.wizard.line'].create({
            'wizard_id': wizard.id,
            'product_id': product.id,
            'lot_name': 'SUPPLIER-PARTIAL',
            'quantity': 4,
        })

        wizard.action_create_and_print()

        self.assertEqual(move.quantity, 4)
        self.assertEqual(len(picking.move_line_ids), 1)
        self.assertEqual(picking.move_line_ids.lot_id.name, 'SUPPLIER-PARTIAL')
        self.assertEqual(picking.move_line_ids.quantity, 4)

    def test_repeated_generation_is_idempotent(self):
        lot = self.Lot.create({'name': 'BATCH-B', 'product_id': self._product().id, 'company_id': self.company.id})
        value = lot.smart_barcode
        lot._ensure_smart_barcodes()
        self.assertEqual(lot.smart_barcode, value)

    def test_existing_lot_backfill_does_not_change_stock(self):
        self.config.write({'auto_generate': False})
        lot = self.Lot.create({'name': 'BATCH-C', 'product_id': self._product().id, 'company_id': self.company.id})
        self.assertFalse(lot.smart_barcode)
        result = self.env['smart.lot.backfill.wizard'].create({
            'company_id': self.company.id,
        }).action_generate()
        self.assertIn('1 Smart Lot barcode(s) generated.', result['params']['message'])
        self.assertTrue(lot.smart_barcode)

    def test_disabled_smart_lot_feature_does_not_assign(self):
        self.config.write({'enabled': False})
        lot = self.Lot.create({
            'name': 'BATCH-D',
            'product_id': self._product().id,
            'company_id': self.company.id,
        })
        self.assertFalse(lot.smart_barcode)
        self.config.write({'enabled': True})
        enabled_lot = self.Lot.create({
            'name': 'BATCH-E',
            'product_id': self._product().id,
            'company_id': self.company.id,
        })
        self.assertTrue(enabled_lot.smart_barcode)

    def test_untracked_product_is_not_assigned(self):
        # Odoo 20 represents an untracked storable product with a false
        # tracking value; the legacy ``'none'`` selection was removed.
        product = self.Product.create({'name': 'Untracked', 'is_storable': True, 'tracking': False})
        lot = self.Lot.create({'name': 'NOT-ELIGIBLE', 'product_id': product.id, 'company_id': self.company.id})
        self.assertFalse(lot.smart_barcode)
