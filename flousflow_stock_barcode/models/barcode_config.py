from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _ean13_checksum(base12):
    """Return the EAN-13 check digit for a 12-digit base string."""
    total = sum(
        int(digit) * (1 if position % 2 == 0 else 3)
        for position, digit in enumerate(base12)
    )
    return str((10 - (total % 10)) % 10)


def format_barcode(code_format, prefix, number_str):
    """Build a final barcode from a format, a prefix and a padded number.

    ``number_str`` must already be zero-padded to the configured sequence
    length. For EAN-13 the prefix and the number must total 12 digits; the
    check digit is appended, producing a 13-digit barcode.
    """
    prefix = prefix or ''
    if code_format == 'ean13':
        base = prefix + number_str
        if len(base) != 12:
            raise ValidationError(_(
                "The selected configuration produces more than 13 EAN digits. "
                "For EAN-13, the prefix length plus the sequence length must "
                "equal 12 digits."))
        return base + _ean13_checksum(base)
    if code_format == 'prefix':
        return prefix + number_str
    return number_str


class AutoBarcodeConfig(models.Model):
    _name = 'auto.barcode.config'
    _description = 'Automatic Product Barcode Configuration'
    _order = 'company_id, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    enabled = fields.Boolean(
        string='Enable Automatic Barcode Generation', default=False)
    barcode_format = fields.Selection([
        ('sequential', 'Sequential Numeric'),
        ('prefix', 'Prefix + Sequential Numeric'),
        ('ean13', 'EAN-13'),
    ], string='Barcode Format', default='sequential', required=True)
    prefix = fields.Char(
        string='Prefix',
        help='Optional prefix prepended to the generated number.')
    sequence_digits = fields.Integer(
        string='Sequence Digits', default=10, required=True)
    starting_number = fields.Integer(
        string='Starting Number', default=1, required=True)
    include_archived = fields.Boolean(
        string='Include Archived Products', default=False)
    existing_barcode_policy = fields.Selection([
        ('keep', 'Keep Existing Barcodes'),
    ], string='Existing Barcode Policy', default='keep', required=True,
        help='Existing product barcodes are never overwritten.')
    sequence_id = fields.Many2one(
        'ir.sequence', string='Barcode Sequence', readonly=True, copy=False)
    preview = fields.Char(
        string='Barcode Preview', compute='_compute_preview')

    _company_uniq = models.Constraint(
        'unique (company_id)',
        'Only one barcode configuration can exist per company.',
    )

    @api.depends('barcode_format', 'prefix', 'sequence_digits', 'starting_number')
    def _compute_preview(self):
        for config in self:
            config.preview = config._build_preview()

    @api.constrains('sequence_digits')
    def _check_sequence_digits(self):
        for config in self:
            if config.sequence_digits < 1:
                raise ValidationError(_(
                    'The sequence length must be at least 1 digit.'))

    @api.constrains('starting_number')
    def _check_starting_number(self):
        for config in self:
            if config.starting_number < 0:
                raise ValidationError(_(
                    'The starting number cannot be negative.'))

    @api.constrains('barcode_format', 'prefix', 'sequence_digits', 'starting_number')
    def _check_configuration(self):
        for config in self:
            if config.barcode_format != 'ean13':
                continue
            if not (config.prefix or '').isdigit():
                raise ValidationError(_(
                    'The barcode prefix must contain digits only for EAN-13.'))
            if len(config.prefix or '') + config.sequence_digits != 12:
                raise ValidationError(_(
                    'The selected configuration produces more than 13 EAN digits. '
                    'For EAN-13, the prefix length plus the sequence length '
                    'must equal 12 digits.'))
            if config.starting_number >= 10 ** config.sequence_digits:
                raise ValidationError(_(
                    'The starting number does not fit in the configured '
                    'sequence length.'))

    def _build_preview(self):
        self.ensure_one()
        if not self.sequence_digits or self.sequence_digits < 1:
            return ''
        number_str = str(self.starting_number or 0).zfill(self.sequence_digits)
        try:
            return format_barcode(self.barcode_format, self.prefix, number_str)
        except ValidationError:
            return _('Invalid EAN-13 configuration')

    @api.model_create_multi
    def create(self, vals_list):
        configs = super().create(vals_list)
        Sequence = self.env['ir.sequence']
        for config in configs:
            if not config.sequence_id:
                config.sequence_id = Sequence.create({
                    'name': _('Product barcode sequence - %s',
                              config.company_id.name),
                    'code': 'flousflow.stock.barcode.%s' % config.company_id.id,
                    'company_id': config.company_id.id,
                    'padding': config.sequence_digits,
                    'number_next': config.starting_number,
                    'number_next_actual': config.starting_number,
                    'use_date_range': False,
                }).id
        return configs

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ('sequence_digits', 'starting_number')):
            for config in self:
                if config.sequence_id:
                    config.sequence_id.write({
                        'padding': config.sequence_digits,
                        'number_next': config.starting_number,
                        'number_next_actual': config.starting_number,
                    })
        return res

    def _format_barcode(self, number_str):
        self.ensure_one()
        return format_barcode(self.barcode_format, self.prefix, number_str)

    def _generate_unique_barcode(self, company):
        """Return a company-unique barcode using the linked ``ir.sequence``.

        The sequence guarantees concurrency-safe numbers. A bounded retry loop
        skips values that already exist in the database (e.g. manually entered
        barcodes) so existing barcodes are never overwritten or duplicated.
        """
        self.ensure_one()
        Product = self.env['product.product']
        for _attempt in range(100):
            number_str = self.sequence_id.next_by_id()
            code = self._format_barcode(number_str)
            exists = Product.with_context(active_test=False).search_count(
                [('barcode', '=', code), '|',
                 ('company_id', '=', False), ('company_id', '=', company.id)],
                limit=1)
            if not exists:
                return code
        raise UserError(_(
            'A barcode could not be generated after multiple attempts because '
            'generated values are already in use.'))

    def _generate_for_products(self, products):
        """Fill empty barcodes on ``products`` (they must belong to this company)."""
        self.ensure_one()
        products = products.filtered(
            lambda product: not product.barcode
            and (not product.company_id
                 or product.company_id == self.company_id))
        count = 0
        for product in products:
            product.barcode = self._generate_unique_barcode(self.company_id)
            count += 1
        return count
