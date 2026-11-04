from odoo import _, api, models
from odoo.fields import Domain
from odoo.exceptions import UserError


def _lots_for_scan(env, scanned_code):
    """Find accessible Lots by exact code, then by a long unique suffix."""
    if not scanned_code:
        return env['stock.lot']
    company_domain = (
        Domain('company_id', '=', False)
        | Domain('company_id', 'in', env.companies.ids)
    )
    code_domain = (
        Domain('smart_barcode', '=', scanned_code)
        | Domain('name', '=', scanned_code)
    )
    Lot = env['stock.lot'].sudo()
    lots = Lot.search(code_domain & company_domain, limit=101)
    if not lots and len(scanned_code) >= 12:
        # Some scanners/labels omit a configured leading prefix. A long exact
        # suffix is accepted only when it still identifies one product.
        escaped_code = (
            scanned_code.replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_')
        )
        suffix_domain = (
            Domain('smart_barcode', '=like', f'%{escaped_code}')
            | Domain('name', '=like', f'%{escaped_code}')
        )
        lots = Lot.search(suffix_domain & company_domain, limit=101)
    if len(lots) > 100:
        return env['stock.lot']
    return lots


def _products_for_lot_scan(env, scanned_code):
    """Resolve Lots to one unambiguous product for standard search widgets."""
    lots = _lots_for_scan(env, scanned_code)
    products = lots.product_id
    # Lot names may be reused for different products. Do not guess which one
    # the operator meant; multiple matching Lots for one product are safe.
    return products if len(products) == 1 else env['product.product']


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Resolve an exact Lot name or Smart Lot barcode to its product."""
        if name and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            products_from_lot = _products_for_lot_scan(self.env, name)
            if products_from_lot:
                products = self.search(
                    Domain(domain or Domain.TRUE)
                    & Domain('id', '=', products_from_lot.id)
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
    def resolve_sale_lot_scan(self, scanned_code):
        """Return the saleable product and exact Lot selected by a scan."""
        lots = _lots_for_scan(self.env, scanned_code)
        if len(lots) != 1:
            return False
        lot = lots[0]
        product = lot.product_id
        if not product.sale_ok or product.tracking not in ('lot', 'serial'):
            return False
        template = self.search([
            ('id', '=', product.product_tmpl_id.id),
            ('sale_ok', '=', True),
        ], limit=1)
        if not template:
            return False
        return {
            'id': template.id,
            'display_name': template.display_name,
            'lot_id': lot.id,
        }

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Resolve a Lot name or Smart Lot barcode in the Sales picker."""
        if name and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            products_from_lot = _products_for_lot_scan(self.env, name)
            if products_from_lot:
                templates = self.search(
                    Domain(domain or Domain.TRUE)
                    & Domain('id', '=', products_from_lot.product_tmpl_id.id)
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
