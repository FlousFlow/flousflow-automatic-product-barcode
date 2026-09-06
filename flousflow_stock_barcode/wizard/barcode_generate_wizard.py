from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AutoBarcodeGenerateWizard(models.TransientModel):
    _name = 'auto.barcode.generate.wizard'
    _description = 'Generate Product Barcodes'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    include_archived = fields.Boolean(string='Include Archived Products')
    existing_barcode_policy = fields.Selection([
        ('keep', 'Keep Existing Barcodes'),
    ], string='Existing Barcode Policy', default='keep', required=True)
    missing_count = fields.Integer(
        string='Products Without Barcode', readonly=True,
        compute='_compute_missing_count')

    @api.constrains('company_id')
    def _check_company_id(self):
        for wizard in self:
            if wizard.company_id not in wizard.env.companies:
                raise ValidationError(_(
                    'You can only generate barcodes for a company you have '
                    'access to.'))

    @api.depends('company_id', 'include_archived')
    def _compute_missing_count(self):
        for wizard in self:
            domain = [
                ('barcode', '=', False),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', wizard.company_id.id),
            ]
            wizard.missing_count = self.env['product.product'].with_context(
                active_test=not wizard.include_archived).search_count(domain)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        config = self.env['auto.barcode.config'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        if 'include_archived' in fields_list:
            res['include_archived'] = config.include_archived if config else False
        return res

    def action_generate(self):
        self.ensure_one()
        config = self.env['auto.barcode.config'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not config:
            raise UserError(_(
                'No barcode configuration exists for this company. '
                'Configure it in Settings first.'))
        domain = [
            ('barcode', '=', False),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ]
        products = self.env['product.product'].with_context(
            active_test=not self.include_archived).search(domain)
        count = config._generate_for_products(products)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generate Product Barcodes'),
                'message': _('%(count)s barcode(s) were generated.', count=count),
                'type': 'success' if count else 'info',
                'sticky': False,
            },
        }
