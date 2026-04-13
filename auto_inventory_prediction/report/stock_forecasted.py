from odoo import models


class StockForecasted(models.AbstractModel):
    _inherit = "stock.forecasted_product_product"

    def _get_products_for_report(self, product_template_ids=False, product_ids=False):
        return (
            self.env["product.template"]
            .browse(product_template_ids)
            .product_variant_ids
            if product_template_ids
            else self.env["product.product"].browse(product_ids)
        )

    def _get_orderpoints_for_report(self, products):
        warehouse = self._get_warehouse()
        return self.env["stock.warehouse.orderpoint"].search([
            ("product_id", "in", products.ids),
            ("company_id", "=", self.env.company.id),
            ("location_id", "child_of", warehouse.view_location_id.id),
        ])

    def _aggregate_replenishment_breakdown(self, orderpoints):
        aggregated = {
            "standard_forecast": 0.0,
            "purchase_in_progress": 0.0,
            "mo_draft_in_progress": 0.0,
            "mo_confirmed_in_progress": 0.0,
            "kit_in_progress": 0.0,
            "enterprise_in_progress": 0.0,
            "total_in_progress": 0.0,
            "replenishment_forecast": 0.0,
        }
        breakdown = orderpoints._get_replenishment_breakdown()
        for values in breakdown.values():
            for key in aggregated:
                aggregated[key] += values.get(key, 0.0)
        return aggregated

    def _aggregate_product_breakdown(self, products):
        aggregated = {
            "qty_available": 0.0,
            "incoming_qty": 0.0,
            "outgoing_qty": 0.0,
            "virtual_available": 0.0,
            "unconfirmed_outgoing_qty": 0.0,
            "virtual_available_ml": 0.0,
            "incoming_onhand_qty": 0.0,
            "incoming_inbound_qty": 0.0,
            "incoming_component_inbound_qty": 0.0,
            "incoming_missing_qty": 0.0,
            "incoming_non_mo_qty": 0.0,
            "incoming_mo_scheduled_qty": 0.0,
            "incoming_mo_feasible_qty": 0.0,
            "incoming_mo_unfeasible_qty": 0.0,
            "incoming_reliable_qty": 0.0,
            "standard_forecast_reliable": 0.0,
            "virtual_available_ml_reliable": 0.0,
        }
        detailed = products._get_detailed_forecast_breakdown(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date"),
            self.env.context.get("to_date"),
        )
        for values in detailed.values():
            for key in aggregated:
                aggregated[key] += values.get(key, 0.0)
        aggregated["standard_forecast_scheduled"] = aggregated["virtual_available"]
        aggregated["standard_forecast_gap"] = (
            aggregated["standard_forecast_scheduled"] - aggregated["standard_forecast_reliable"]
        )
        aggregated["ml_forecast_gap"] = (
            aggregated["virtual_available_ml"] - aggregated["virtual_available_ml_reliable"]
        )
        aggregated["feasibility_qty"] = (
            aggregated["incoming_onhand_qty"] + aggregated["incoming_component_inbound_qty"]
        )
        return aggregated

    def _get_report_data(self, product_template_ids=False, product_ids=False):
        """Get stock forecasting report data with ML-enhanced quantities"""
        data = super()._get_report_data(product_template_ids, product_ids)
        products = self._get_products_for_report(product_template_ids, product_ids)
        orderpoints = self._get_orderpoints_for_report(products)
        product_breakdown = self._aggregate_product_breakdown(products)
        replenishment_breakdown = self._aggregate_replenishment_breakdown(orderpoints)

        results = products._get_products_qty_in_unconfirmed_quotations()
        data["draft_sale_qty"] = sum([r["qty"] for r in results.values()])
        data["draft_sale_orders"] = [
            o for r in results.values() for o in r["orders"].values()
        ]
        data.update(product_breakdown)
        data.update(replenishment_breakdown)

        return data

    def _get_report_header(self, product_template_ids, product_ids, wh_location_ids):
        """Report header with extended metrics"""
        res = super()._get_report_header(
            product_template_ids, product_ids, wh_location_ids
        )
        products = self._get_products_for_report(product_template_ids, product_ids)
        orderpoints = self._get_orderpoints_for_report(products)
        product_breakdown = self._aggregate_product_breakdown(products)
        replenishment_breakdown = self._aggregate_replenishment_breakdown(orderpoints)
        res.update(product_breakdown)
        res["virtual_available_real"] = sum(products.mapped("virtual_available_real"))
        res["virtual_onhand_qty"] = sum(products.mapped("virtual_onhand_qty"))
        res.update(replenishment_breakdown)

        return res
