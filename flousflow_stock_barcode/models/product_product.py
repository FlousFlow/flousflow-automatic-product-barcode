from odoo import _, api, models
from odoo.fields import Domain
from odoo.exceptions import UserError


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Resolve an exact Smart Lot barcode to its saleable product."""
        if name and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            lots = self.env['stock.lot'].sudo().search([
                ('smart_barcode', '=', name),
                '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids),
            ], limit=1)
            if lots:
                products = self.search(
                    Domain(domain or Domain.TRUE)
                    & Domain('id', '=', lots.product_id.id)
                    & Domain('sale_ok', '=', True),
                    limit=limit,
                )
                if products:
                    return [(product.id, product.display_name) for product in products.sudo()]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        products._auto_assign_barcode()
        return products

    def _auto_assign_barcode(self):
        """Assign a barcode to newly created variants that have none.

        Runs only when automatic generation is enabled for the variant's
        company. Existing barcodes (explicitly provided or imported) are left
        untouched.
        """
        products = self.filtered(lambda product: not product.barcode)
        if not products:
            return
        company_ids = {
            product.company_id.id or self.env.company.id
            for product in products
        }
        configs = self.env['auto.barcode.config'].search([
            ('company_id', 'in', list(company_ids)),
            ('enabled', '=', True),
        ])
        config_by_company = {
            config.company_id.id: config for config in configs
        }
        for product in products:
            company_id = product.company_id.id or self.env.company.id
            config = config_by_company.get(company_id)
            if not config:
                continue
            product.barcode = config._generate_unique_barcode(config.company_id)

    def generate_missing_barcodes(self):
        """Contextual action: fill barcodes for the selected variants.

        Only selected variants with an empty barcode are processed; existing
        barcodes are never modified.
        """
        products = self.filtered(lambda product: not product.barcode)
        if not products:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Generate Missing Barcodes'),
                    'message': _('No selected product is missing a barcode.'),
                    'type': 'info',
                },
            }
        companies = {}
        for product in products:
            company = product.company_id or self.env.company
            companies.setdefault(company.id, company)

        total = 0
        for company_id, company in companies.items():
            company_products = products.filtered(
                lambda product: (
                    product.company_id or self.env.company).id == company_id)
            config = self.env['auto.barcode.config'].search(
                [('company_id', '=', company_id)], limit=1)
            if not config:
                raise UserError(_(
                    'No barcode configuration found for %(company)s. '
                    'Configure it in Settings first.', company=company.name))
            total += config._generate_for_products(company_products)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generate Missing Barcodes'),
                'message': _('%(count)s barcode(s) were generated.', count=total),
                'type': 'success' if total else 'info',
            },
        }


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Resolve a Smart Lot barcode in the Sales product-template picker."""
        if name and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            lot = self.env['stock.lot'].sudo().search([
                ('smart_barcode', '=', name),
                '|', ('company_id', '=', False),
                ('company_id', 'in', self.env.companies.ids),
            ], limit=1)
            if lot:
                templates = self.search(
                    Domain(domain or Domain.TRUE)
                    & Domain('id', '=', lot.product_id.product_tmpl_id.id)
                    & Domain('sale_ok', '=', True),
                    limit=limit,
                )
                if templates:
                    return [
                        (template.id, template.display_name)
                        for template in templates
                    ]
        return super().name_search(
            name=name, domain=domain, operator=operator, limit=limit,
        )
