from odoo.tests.common import TransactionCase


class TestSmartLotBarcode(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Product = cls.env['product.product']
        cls.Lot = cls.env['stock.lot']
        cls.Config = cls.env['smart.lot.barcode.config']
        cls.config = cls.Config.create({'company_id': cls.company.id, 'prefix': 'FFL-', 'sequence_digits': 6})

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

    def test_repeated_generation_is_idempotent(self):
        lot = self.Lot.create({'name': 'BATCH-B', 'product_id': self._product().id, 'company_id': self.company.id})
        value = lot.smart_barcode
        lot._ensure_smart_barcodes()
        self.assertEqual(lot.smart_barcode, value)

    def test_existing_lot_backfill_does_not_change_stock(self):
        self.config.write({'auto_generate': False})
        lot = self.Lot.create({'name': 'BATCH-C', 'product_id': self._product().id, 'company_id': self.company.id})
        self.assertFalse(lot.smart_barcode)
        self.config.write({'auto_generate': True})
        lot._ensure_smart_barcodes()
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
