from odoo import models


class StockForecasted(models.AbstractModel):
    _inherit = "stock.forecasted_product_product"

    def _get_report_data(self, product_template_ids=False, product_ids=False):
        """Get stock forecasting report data with ML-enhanced quantities"""
        data = super()._get_report_data(product_template_ids, product_ids)
        products = (
            self.env["product.template"]
            .browse(product_template_ids)
            .product_variant_ids
            if product_template_ids
            else self.env["product.product"].browse(product_ids)
        )

        # Use ML predictions instead of primitive CRM system
        results = products._get_products_qty_in_unconfirmed_quotations()
        data["draft_sale_qty"] = sum([r["qty"] for r in results.values()])
        data["draft_sale_orders"] = [
            o for r in results.values() for o in r["orders"].values()
        ]

        return data

    def _get_report_header(self, product_template_ids, product_ids, wh_location_ids):
        """Report header with extended metrics"""
        res = super()._get_report_header(
            product_template_ids, product_ids, wh_location_ids
        )
        products = (
            self.env["product.template"]
            .browse(product_template_ids)
            .product_variant_ids
            if product_template_ids
            else self.env["product.product"].browse(product_ids)
        )

        # Add new fields from our product.py extension
        res["unconfirmed_outgoing_qty"] = sum(
            products.mapped("unconfirmed_outgoing_qty")
        )

        res["incoming_onhand_qty"] = sum(products.mapped("incoming_onhand_qty"))
        res["incoming_inbound_qty"] = sum(products.mapped("incoming_inbound_qty"))
        res["incoming_missing_qty"] = sum(products.mapped("incoming_missing_qty"))
        res["virtual_available_real"] = sum(products.mapped("virtual_available_real"))
        res["virtual_onhand_qty"] = sum(products.mapped("virtual_onhand_qty"))

        return res
