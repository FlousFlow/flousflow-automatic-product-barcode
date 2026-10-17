{
    'name': 'Flous Flow Stock Barcode',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Barcode',
    'summary': 'Automatically generate unique barcodes for products and variants.',
    'description': """
Flous Flow Stock Barcode
=========================

Automatically assign a unique barcode to every new product variant when its
``barcode`` field is empty. Administrators can also generate barcodes
retroactively for existing products and variants.

Key features
------------
- Automatic barcode generation on product variant creation.
- Retroactive generation for existing products (wizard + contextual action).
- Configurable format: Sequential Numeric, Prefix + Sequential Numeric, or
  EAN-13 with a valid checksum.
- Multi-company support with independent, concurrency-safe ``ir.sequence``
  per company.
- Collision protection: generated values are checked before assignment.
- Existing barcodes are always preserved.
- Archived products handling.

Configuration
-------------
Open *Settings -> Automatic Product Barcodes*, enable the feature and choose
the barcode format, prefix, sequence length and starting number. Use the
*Generate Missing Barcodes* button to fill barcodes on existing products.

Generated EAN-13 numbers are internal identifiers unless the company owns an
appropriate GS1 prefix.

Optional inventory/POS integrations are shipped in the same repository as
``auto_product_barcode_stock`` and ``auto_product_barcode_pos``. They are not
dependencies of this product-only addon, so existing installations do not
silently install Inventory or Point of Sale.
""",
    'author': 'Flous Flow',
    'website': 'https://flousflow.com',
    'license': 'LGPL-3',
    'depends': ['product'],
    'data': [
        'security/ir.access.csv',
        'views/res_config_settings_views.xml',
        'views/barcode_config_views.xml',
        'wizard/barcode_generate_wizard_views.xml',
        'data/server_actions.xml',
    ],
    'images': [
        'static/description/thumbnail.png',
        'static/description/banner.png',
        'static/description/cover.png',
        'static/description/icon.png',
        'static/description/screenshot1.png',
        'static/description/screenshot2.png',
        'static/description/screenshot3.png',
        'static/description/screenshot4.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
