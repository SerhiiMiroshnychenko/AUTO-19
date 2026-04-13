from odoo import models, api
from odoo.fields import Domain
from collections import defaultdict
from datetime import datetime, time


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    def _get_replenishment_breakdown(self):
        breakdown = {
            orderpoint.id: {
                "standard_forecast": 0.0,
                "purchase_in_progress": 0.0,
                "mo_draft_in_progress": 0.0,
                "mo_confirmed_in_progress": 0.0,
                "kit_in_progress": 0.0,
                "enterprise_in_progress": 0.0,
                "total_in_progress": 0.0,
                "replenishment_forecast": 0.0,
            }
            for orderpoint in self
        }
        if not self:
            return breakdown

        grouped_orderpoints = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint in self:
            grouped_orderpoints[orderpoint.company_id] |= orderpoint

        for company, company_orderpoints in grouped_orderpoints.items():
            self._fill_standard_forecast_breakdown(company_orderpoints.with_company(company), breakdown)
            self._fill_purchase_breakdown(company_orderpoints.with_company(company), breakdown)
            self._fill_mrp_breakdown(company_orderpoints.with_company(company), breakdown)
            self._fill_enterprise_breakdown(company_orderpoints.with_company(company), breakdown)

        for orderpoint in self:
            values = breakdown[orderpoint.id]
            values["total_in_progress"] = (
                values["purchase_in_progress"]
                + values["mo_draft_in_progress"]
                + values["mo_confirmed_in_progress"]
                + values["kit_in_progress"]
                + values["enterprise_in_progress"]
            )
            values["replenishment_forecast"] = values["standard_forecast"] + values["total_in_progress"]

        return breakdown

    def _fill_standard_forecast_breakdown(self, orderpoints, breakdown):
        orderpoints_contexts = defaultdict(lambda: self.env["stock.warehouse.orderpoint"])
        for orderpoint in orderpoints:
            if not orderpoint.product_id or not orderpoint.location_id:
                continue
            product_context = orderpoint._get_product_context()
            orderpoints_contexts[frozenset(product_context.items())] |= orderpoint
        for context_items, orderpoints_by_context in orderpoints_contexts.items():
            product_context = dict(context_items)
            products_qty = {
                product_values["id"]: product_values
                for product_values in orderpoints_by_context.product_id.with_context(product_context).read(["virtual_available"])
            }
            for orderpoint in orderpoints_by_context:
                breakdown[orderpoint.id]["standard_forecast"] = products_qty.get(orderpoint.product_id.id, {}).get("virtual_available", 0.0)

    def _fill_purchase_breakdown(self, orderpoints, breakdown):
        if "purchase.order.line" not in self.env:
            return
        products = orderpoints.product_id
        location_ids = orderpoints.location_id.ids
        domains = []
        rfq_domain = Domain("state", "in", ("draft", "sent", "to approve")) & Domain("product_id", "in", products.ids)
        if location_ids:
            domains.append(Domain([
                "|",
                    "&",
                    ("orderpoint_id", "=", False),
                    "|",
                        "&",
                            ("location_final_id", "=", False),
                            ("order_id.picking_type_id.default_location_dest_id", "in", location_ids),
                        "&",
                            ("move_ids", "=", False),
                            ("location_final_id", "child_of", location_ids),
                "&",
                    ("move_dest_ids", "=", False),
                    ("orderpoint_id.location_id", "in", location_ids),
            ]))
        if orderpoints.warehouse_id.ids:
            domains.append(Domain([
                "|",
                    "&",
                        ("orderpoint_id", "=", False),
                        ("order_id.picking_type_id.warehouse_id", "in", orderpoints.warehouse_id.ids),
                    "&",
                        ("move_dest_ids", "=", False),
                        ("orderpoint_id.warehouse_id", "in", orderpoints.warehouse_id.ids),
            ]))
        domain = rfq_domain & Domain.OR(domains or [Domain.TRUE])
        groups = self.env["purchase.order.line"].sudo()._read_group(
            domain,
            ["order_id", "product_id", "product_uom_id", "orderpoint_id", "location_final_id"],
            ["product_qty:sum"],
        )
        orderpoint_by_product_location = {
            (orderpoint.product_id.id, orderpoint.location_id.id): orderpoint
            for orderpoint in orderpoints
        }
        for order, product, uom, linked_orderpoint, location_final, product_qty_sum in groups:
            if linked_orderpoint and linked_orderpoint.id in breakdown:
                target_orderpoint = linked_orderpoint
            else:
                if location_final:
                    location = location_final
                else:
                    location = order.picking_type_id.default_location_dest_id
                target_orderpoint = orderpoint_by_product_location.get((product.id, location.id))
            if not target_orderpoint:
                continue
            product_qty = uom._compute_quantity(product_qty_sum, target_orderpoint.product_uom, round=False)
            breakdown[target_orderpoint.id]["purchase_in_progress"] += product_qty

    def _fill_mrp_breakdown(self, orderpoints, breakdown):
        if "mrp.production" not in self.env or "mrp.bom" not in self.env:
            return
        bom_kits = self.env["mrp.bom"]._bom_find(orderpoints.product_id, bom_type="phantom")
        bom_kit_orderpoints = {
            orderpoint: bom_kits[orderpoint.product_id]
            for orderpoint in orderpoints
            if orderpoint.product_id in bom_kits
        }
        for orderpoint, bom in bom_kit_orderpoints.items():
            dummy, bom_sub_lines = bom.explode(orderpoint.product_id, 1)
            ratios_qty_available = []
            ratios_total = []
            for bom_line, bom_line_data in bom_sub_lines:
                component = bom_line.product_id
                if not component.is_storable or bom_line.product_uom_id.is_zero(bom_line_data["qty"]):
                    continue
                uom_qty_per_kit = bom_line_data["qty"] / bom_line_data["original_qty"]
                qty_per_kit = bom_line.product_uom_id._compute_quantity(uom_qty_per_kit, component.uom_id, raise_if_failure=False)
                if not qty_per_kit:
                    continue
                qty_by_product_location = component._get_quantity_in_progress(orderpoint.location_id.ids)[0]
                qty_in_progress = qty_by_product_location.get((component.id, orderpoint.location_id.id), 0.0)
                qty_available = component.qty_available / qty_per_kit
                ratios_qty_available.append(qty_available)
                ratios_total.append(qty_available + (qty_in_progress / qty_per_kit))
            product_qty = min(ratios_total or [0.0]) - min(ratios_qty_available or [0.0])
            breakdown[orderpoint.id]["kit_in_progress"] += orderpoint.product_id.uom_id._compute_quantity(product_qty, orderpoint.product_uom, round=False)

        orderpoints_without_kit = orderpoints - self.env["stock.warehouse.orderpoint"].concat(*bom_kit_orderpoints.keys())
        if not orderpoints_without_kit:
            return
        bom_manufacture_map = self.env["mrp.bom"]._bom_find(orderpoints_without_kit.product_id, bom_type="normal")
        bom_manufacture = self.env["mrp.bom"].concat(*bom_manufacture_map.values())
        if not bom_manufacture:
            return

        productions_group = self.env["mrp.production"]._read_group(
            [
                ("bom_id", "in", bom_manufacture.ids),
                ("state", "=", "draft"),
                ("orderpoint_id", "in", orderpoints_without_kit.ids),
                ("id", "not in", self.env.context.get("ignore_mo_ids", [])),
            ],
            ["orderpoint_id", "product_uom_id"],
            ["product_qty:sum"],
        )
        for linked_orderpoint, uom, product_qty_sum in productions_group:
            breakdown[linked_orderpoint.id]["mo_draft_in_progress"] += uom._compute_quantity(
                product_qty_sum, linked_orderpoint.product_uom, round=False
            )

        in_progress_productions = self.env["mrp.production"].search([
            ("bom_id", "in", bom_manufacture.ids),
            ("state", "=", "confirmed"),
            ("orderpoint_id", "in", orderpoints_without_kit.ids),
            ("id", "not in", self.env.context.get("ignore_mo_ids", [])),
        ])
        for production in in_progress_productions:
            linked_orderpoint = production.orderpoint_id
            lead_horizon_date = datetime.combine(linked_orderpoint.lead_horizon_date, time.max)
            if production.date_start <= lead_horizon_date < production.date_finished:
                breakdown[linked_orderpoint.id]["mo_confirmed_in_progress"] += production.product_uom_id._compute_quantity(
                    production.product_qty, linked_orderpoint.product_uom, round=False
                )

    def _fill_enterprise_breakdown(self, orderpoints, breakdown):
        company_model = self.env["res.company"]
        product_model = self.env["product.product"]
        if "rental_loc_id" not in company_model._fields or "rent_ok" not in product_model._fields:
            return
        rental_loc_ids = self.env.companies.mapped("rental_loc_id").ids
        if not rental_loc_ids:
            return
        for orderpoint in orderpoints:
            if not orderpoint.product_id.rent_ok:
                continue
            domain = [
                ("product_id", "=", orderpoint.product_id.id),
                ("state", "in", ["confirmed", "assigned", "waiting", "partially_available"]),
                ("date", "<=", orderpoint.lead_horizon_date),
                "|",
                    ("location_id", "in", rental_loc_ids),
                    "|",
                        ("location_dest_id", "in", rental_loc_ids),
                        ("location_final_id", "in", rental_loc_ids),
                "|",
                    ("location_id.warehouse_id", "=", orderpoint.warehouse_id.id),
                    ("location_dest_id.warehouse_id", "=", orderpoint.warehouse_id.id),
            ]
            rental_moves = self.env["stock.move"].search(domain, order="date, id")
            outs_qty = 0.0
            current_qty = 0.0
            max_missing_qty = 0.0
            for move in rental_moves:
                if move.location_id.id in rental_loc_ids:
                    current_qty += move.product_qty
                else:
                    outs_qty += move.product_qty
                    current_qty -= move.product_qty
                    if current_qty < max_missing_qty:
                        max_missing_qty = current_qty
            breakdown[orderpoint.id]["enterprise_in_progress"] += outs_qty + max_missing_qty

    def _procure_orderpoint_confirm(self, use_new_cursor=False, company_id=None, raise_user_error=True):
        """Override to pass auto-creation context for UI banners.
        
        We don't override _compute_qty here anymore because it causes 
        SerializationFailure in Odoo 19. Instead, the logic is implemented 
        in product.py by enhancing virtual_available.
        """
        context = dict(self.env.context)
        context['smart_inventory_auto_creation'] = True

        if not use_new_cursor:
            orderpoint_reasons = {}
            for orderpoint in self:
                if orderpoint.product_id and orderpoint.qty_forecast < orderpoint.product_min_qty:
                    target_date = orderpoint.lead_horizon_date.strftime("%d.%m.%Y") if orderpoint.lead_horizon_date else "найближчим часом"
                    orderpoint_reasons[orderpoint.id] = f"Передбачена відсутність товару {orderpoint.product_id.name} на дату {target_date}"
            context['orderpoint_reasons'] = orderpoint_reasons

        return super(StockWarehouseOrderpoint, self.with_context(context))._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor, 
            company_id=company_id, 
            raise_user_error=raise_user_error
        )
