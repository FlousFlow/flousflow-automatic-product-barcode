{
    'name': 'Flous Flow Automatic Product & Lot Barcode',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Barcode',
    'summary': 'Generate product and Smart Lot barcodes for Inventory and POS.',
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

Inventory and POS Smart Lot barcode support is included in this single Apps
module. Installing it enables product barcode generation, tracked-lot barcode
generation, receipt redistribution, printing, and POS scanning.
""",
    'author': 'Flous Flow',
    'website': 'https://flousflow.com',
    'license': 'LGPL-3',
    'depends': ['product', 'stock', 'point_of_sale'],
    'data': [
        'security/ir.access.csv',
        'auto_product_barcode_stock/security/ir.access.csv',
        'views/res_config_settings_views.xml',
        'views/barcode_config_views.xml',
        'wizard/barcode_generate_wizard_views.xml',
        'data/server_actions.xml',
        'auto_product_barcode_stock/data/smart_lot_sequence.xml',
        'auto_product_barcode_stock/views/smart_lot_views.xml',
        'auto_product_barcode_stock/views/stock_picking_views.xml',
        'auto_product_barcode_stock/views/product_views.xml',
        'auto_product_barcode_stock/views/res_config_settings_views.xml',
        'auto_product_barcode_stock/wizard/smart_lot_wizard_views.xml',
        'auto_product_barcode_stock/report/smart_lot_label_report.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'auto_product_barcode_pos/static/src/app/product_screen_smart_lot.js',
        ],
    },
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
