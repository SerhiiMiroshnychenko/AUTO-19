{
    "name": "Auto Inventory Demand Trace",
    "version": "19.0.1.0.0",
    "category": "Inventory",
    "summary": "Autonomous ML inventory prediction with demand tracing",
    "sequence": 1,
    "description": """
        Full standalone replacement for ML-based inventory prediction.
        Includes order success prediction, enhanced stock forecast,
        auto replenishment, and demand-wave tracing with explicit coverage.
    """,
    "author": "Local Team",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "stock",
        "sale",
        "sale_stock",
        "contacts",
        "mrp",
        "purchase",
    ],
    "external_dependencies": {
        "python": ["pandas", "scikit-learn", "xgboost"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/inventory_prediction_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_view.xml",
        "views/product_views.xml",
        "views/mrp_production_views.xml",
        "views/purchase_order_views.xml",
        "views/menus.xml",
        "views/ml_demand_views.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "auto_inventory_demand_trace/static/src/stock_forecasted/*.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
