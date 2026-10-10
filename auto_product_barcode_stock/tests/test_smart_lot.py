from odoo.exceptions import UserError
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
        vals.setdefault('tracking', 'lot')
        vals.setdefault('is_storable', True)
        return self.Product.create(vals)

    def test_manufacturer_barcode_is_preserved(self):
        product = self._product(barcode='6221234567895')
        lot = self.Lot.create({'name': 'BATCH-A', 'product_id': product.id, 'company_id': self.company.id})
        self.assertTrue(lot.smart_barcode)
        self.assertEqual(product.barcode, '6221234567895')
        self.assertEqual(self.Lot.resolve_smart_barcode(lot.smart_barcode)['product_id'], product.id)

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

    def test_untracked_product_is_not_assigned(self):
        product = self.Product.create({'name': 'Untracked', 'is_storable': True, 'tracking': 'none'})
        lot = self.Lot.create({'name': 'NOT-ELIGIBLE', 'product_id': product.id, 'company_id': self.company.id})
        self.assertFalse(lot.smart_barcode)
