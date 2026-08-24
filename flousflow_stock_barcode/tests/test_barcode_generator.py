from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.flousflow_stock_barcode.models.barcode_config import (
    _ean13_checksum,
)


class TestAutoProductBarcode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Config = cls.env['auto.barcode.config']
        cls.Product = cls.env['product.product']
        cls.Wizard = cls.env['auto.barcode.generate.wizard']

    def setUp(self):
        super().setUp()
        # A fresh config (and thus a fresh ir.sequence) per test makes exact
        # barcode values deterministic, because ir.sequence uses PostgreSQL
        # sequences (nextval) which are not rolled back between tests.
        self.config = self.Config.create({
            'company_id': self.company.id,
            'enabled': True,
            'barcode_format': 'prefix',
            'prefix': '20',
            'sequence_digits': 10,
            'starting_number': 1,
        })

    def _create_product(self, **values):
        values.setdefault('name', 'Test Product')
        return self.Product.create(values)

    def test_01_simple_product_gets_barcode(self):
        product = self._create_product()
        self.assertTrue(product.barcode)
        self.assertEqual(product.barcode, '200000000001')

    def test_02_variants_get_unique_barcodes(self):
        attribute = self.env['product.attribute'].create({'name': 'Color'})
        values = self.env['product.attribute.value'].create([
            {'name': 'Red', 'attribute_id': attribute.id},
            {'name': 'Blue', 'attribute_id': attribute.id},
        ])
        template = self.env['product.template'].create({
            'name': 'T-Shirt',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, values.ids)],
            })],
        })
        variants = template.product_variant_ids
        self.assertEqual(len(variants), 2)
        barcodes = variants.mapped('barcode')
        self.assertTrue(all(barcodes))
        self.assertEqual(len(set(barcodes)), 2)

    def test_03_new_variant_after_template_creation(self):
        attribute = self.env['product.attribute'].create({'name': 'Size'})
        values = self.env['product.attribute.value'].create([
            {'name': 'S', 'attribute_id': attribute.id},
            {'name': 'M', 'attribute_id': attribute.id},
        ])
        template = self.env['product.template'].create({'name': 'Shirt'})
        template.write({
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, values.ids)],
            })],
        })
        variants = template.product_variant_ids
        self.assertEqual(len(variants), 2)
        self.assertTrue(all(variants.mapped('barcode')))

    def test_04_explicit_barcode_preserved(self):
        product = self.Product.create({'name': 'Manual', 'barcode': 'MANUAL123'})
        self.assertEqual(product.barcode, 'MANUAL123')

    def test_05_disabled_no_auto_barcode(self):
        self.config.write({'enabled': False})
        product = self._create_product(name='No Barcode')
        self.assertFalse(product.barcode)

    def test_06_reenable_resumes(self):
        self.config.write({'enabled': False})
        self._create_product(name='First')
        self.config.write({'enabled': True})
        product = self._create_product(name='Second')
        self.assertTrue(product.barcode)

    def test_07_wizard_only_fills_missing(self):
        self.config.write({'enabled': False})
        a = self._create_product(name='A')
        b = self._create_product(name='B')
        c = self.Product.create({'name': 'C', 'barcode': 'KEEP123'})
        self.config.write({'enabled': True})
        wizard = self.Wizard.create({
            'company_id': self.company.id, 'include_archived': False})
        self.assertEqual(wizard.missing_count, 2)
        wizard.action_generate()
        self.assertTrue(a.barcode)
        self.assertTrue(b.barcode)
        self.assertEqual(c.barcode, 'KEEP123')

    def test_08_wizard_preserves_existing(self):
        self.config.write({'enabled': False})
        existing = self.Product.create({'name': 'Existing', 'barcode': 'EXIST001'})
        self.config.write({'enabled': True})
        wizard = self.Wizard.create({
            'company_id': self.company.id, 'include_archived': False})
        wizard.action_generate()
        self.assertEqual(existing.barcode, 'EXIST001')

    def test_09_archived_excluded_by_default(self):
        self.config.write({'enabled': False})
        product = self._create_product(name='Archived')
        product.write({'active': False})
        self.config.write({'enabled': True})
        wizard = self.Wizard.create({
            'company_id': self.company.id, 'include_archived': False})
        self.assertEqual(wizard.missing_count, 0)
        wizard.action_generate()
        self.assertFalse(product.barcode)

    def test_10_archived_included(self):
        self.config.write({'enabled': False})
        product = self._create_product(name='Archived')
        product.write({'active': False})
        self.config.write({'enabled': True})
        wizard = self.Wizard.create({
            'company_id': self.company.id, 'include_archived': True})
        self.assertEqual(wizard.missing_count, 1)
        wizard.action_generate()
        self.assertTrue(product.barcode)

    def test_11_multi_company_independent(self):
        company_b = self.env['res.company'].create({'name': 'Company B'})
        self.Config.create({
            'company_id': company_b.id,
            'enabled': True,
            'barcode_format': 'prefix',
            'prefix': '30',
            'sequence_digits': 10,
            'starting_number': 1,
        })
        product_b = self.env['product.product'].with_company(company_b).create({
            'name': 'Product B',
            'company_id': company_b.id,
        })
        self.assertEqual(product_b.barcode, '300000000001')
        product_a = self._create_product(name='Product A')
        self.assertEqual(product_a.barcode, '200000000001')

    def test_12_collision_skips_used_value(self):
        self._create_product(name='A')  # 200000000001
        self.Product.create({'name': 'B', 'barcode': '200000000002'})
        product_c = self._create_product(name='C')
        self.assertEqual(product_c.barcode, '200000000003')

    def test_13_ean13_generation(self):
        self.config.write({
            'barcode_format': 'ean13',
            'prefix': '20',
            'sequence_digits': 10,
            'starting_number': 1,
        })
        product = self._create_product(name='EAN')
        code = product.barcode
        self.assertEqual(len(code), 13)
        self.assertEqual(code[12], _ean13_checksum(code[:12]))

    def test_13b_ean13_checksum_reference(self):
        self.assertEqual(_ean13_checksum('590123412345'), '7')

    def test_14_invalid_ean_config(self):
        with self.assertRaises(ValidationError):
            self.config.write({
                'barcode_format': 'ean13',
                'prefix': '20',
                'sequence_digits': 9,
            })

    def test_14b_ean_prefix_must_be_digits(self):
        with self.assertRaises(ValidationError):
            self.config.write({
                'barcode_format': 'ean13',
                'prefix': 'AB',
                'sequence_digits': 10,
            })

    def test_15_contextual_action_selected_only(self):
        self.config.write({'enabled': False})
        a = self._create_product(name='A')
        b = self._create_product(name='B')
        c = self._create_product(name='C')
        self.config.write({'enabled': True})
        (a | b).generate_missing_barcodes()
        self.assertTrue(a.barcode)
        self.assertTrue(b.barcode)
        self.assertFalse(c.barcode)

    def test_16_many_products_unique(self):
        products = self.env['product.product']
        for index in range(50):
            products |= self._create_product(name='Product %s' % index)
        barcodes = products.mapped('barcode')
        self.assertEqual(len(barcodes), 50)
        self.assertEqual(len(set(barcodes)), 50)

    def test_17_config_unlink_keeps_barcodes(self):
        product = self._create_product(name='Keep')
        barcode = product.barcode
        self.config.unlink()
        self.assertTrue(product.barcode)
        self.assertEqual(product.barcode, barcode)

    def test_18_duplicate_template_gets_new_barcode(self):
        template = self.env['product.template'].create({'name': 'Original'})
        original = template.product_variant_id
        self.assertEqual(original.barcode, '200000000001')
        copied_template = template.copy()
        copied = copied_template.product_variant_id
        self.assertTrue(copied.barcode)
        self.assertNotEqual(copied.barcode, original.barcode)
