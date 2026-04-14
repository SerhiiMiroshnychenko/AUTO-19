from odoo import models


class ProductDemandTrace(models.Model):
    _inherit = "product.product"

    def _get_products_qty_in_unconfirmed_quotations(self, to_date=False, from_date=False):
        """Replace heuristic ML decomposition with demand-wave aggregation."""
        warehouse_id = self.env.context.get("warehouse")
        wave_model = self.env["ml.demand.wave"]
        return wave_model.aggregate_for_products(
            self.ids,
            warehouse_id=warehouse_id,
            from_date=from_date,
            to_date=to_date,
        )
