{
    'name': 'Auto Inventory Prediction',
    'version': '19.0.1.0.0',
    'category': 'Inventory',
    'summary': 'ML-based order success prediction and enhanced stock forecasting',
    'sequence': 1,
    'description': """
        Auto Inventory
        =========================
        Binary classification of sale orders using XGBoost.
        Enhanced stock forecasted report with virtual_available_real.
        Automatic PO/MO creation based on reordering rules.
    """,
    'author': 'Serhii Miroshnychenko',
    'website': 'https://github.com/SerhiiMiroshnychenko',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'stock',
        'sale',
        'sale_stock',
        'contacts',
        'mrp',
        'purchase',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_prediction_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_view.xml',
        'views/product_views.xml',
        'views/mrp_production_views.xml',
        'views/purchase_order_views.xml',
        'views/menus.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'auto_inventory_prediction/static/src/stock_forecasted/*.xml',
        ],
    },
    'external_dependencies': {
        'python': ['pandas', 'scikit-learn', 'xgboost'],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
