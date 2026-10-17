{
    'name': 'Flous Flow Smart Lot Barcode - POS',
    'version': '20.0.1.0.0',
    'summary': 'Resolve Smart Lot Barcodes in Odoo Community POS',
    'category': 'Point of Sale',
    'author': 'Flous Flow',
    'license': 'LGPL-3',
    'depends': ['auto_product_barcode_stock', 'point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'auto_product_barcode_pos/static/src/app/product_screen_smart_lot.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
