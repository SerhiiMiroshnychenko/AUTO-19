from math import ceil
from dateutil import relativedelta
from datetime import datetime, time

from odoo import models, fields, api
from odoo.tools.float_utils import float_round


class Product(models.Model):
    _inherit = "product.product"

    # Legacy DB mapping field (related to template)
    old_name = fields.Char(
        'Назва в старій базі',
        related='product_tmpl_id.old_name',
        store=True,
        readonly=False,
        help='Назва продукту в старій базі даних для точного мапінгу з CSV файлами історичних даних'
    )

    unconfirmed_outgoing_qty = fields.Float(
        "Unconfirmed Outgoing", compute="_compute_quantities", compute_sudo=False
    )

    incoming_onhand_qty = fields.Float(
        "Incoming On-Hand", compute="_compute_quantities", compute_sudo=False
    )
    incoming_inbound_qty = fields.Float(
        "Incoming Inbound", compute="_compute_quantities", compute_sudo=False
    )
    incoming_missing_qty = fields.Float(
        "Incoming Missing", compute="_compute_quantities", compute_sudo=False
    )
    virtual_onhand_qty = fields.Float(
        "Virtual On-Hand", compute="_compute_quantities", compute_sudo=False
    )

    virtual_available_real = fields.Float(
        "Virtual Available Real", compute="_compute_quantities", compute_sudo=False
    )

    @api.depends(
        "stock_move_ids.product_qty", "stock_move_ids.state", "stock_move_ids.quantity"
    )
    @api.depends_context(
        "lot_id",
        "owner_id",
        "package_id",
        "from_date",
        "to_date",
        "location",
        "warehouse",
    )
    def _compute_quantities(self):
        products = (
            self.with_context(prefetch_fields=False)
            .filtered(lambda p: p.type != "service")
            .with_context(prefetch_fields=True)
        )
        res = products._compute_quantities_dict(
            self.env.context.get("lot_id"),
            self.env.context.get("owner_id"),
            self.env.context.get("package_id"),
            self.env.context.get("from_date"),
            self.env.context.get("to_date"),
        )
        for product in products:
            product.update(res[product.id])
        # Services need to be set with 0.0 for all quantities
        services = self - products
        services.qty_available = 0.0
        services.incoming_qty = 0.0
        services.outgoing_qty = 0.0
        services.virtual_available = 0.0
        services.free_qty = 0.0
        services.unconfirmed_outgoing_qty = 0.0
        services.incoming_onhand_qty = 0.0
        services.incoming_inbound_qty = 0.0
        services.incoming_missing_qty = 0.0
        services.virtual_available_real = 0.0
        services.virtual_onhand_qty = 0.0

    def _compute_quantities_dict(
            self, lot_id, owner_id, package_id, from_date=False, to_date=False
    ):
        # Limit to_date to 3 months from now
        three_months_from_now = datetime.combine(
            datetime.now() + relativedelta.relativedelta(days=90),
            time.max,
        )
        to_date = (
            min(to_date, three_months_from_now) if to_date else three_months_from_now
        )
        res = super()._compute_quantities_dict(
            lot_id, owner_id, package_id, from_date, to_date
        )
        unconfirmed_results = self._get_products_qty_in_unconfirmed_quotations(
            to_date, from_date
        )
        incoming_qties_dict = {product.id: res[product.id]["incoming_qty"] for product in self}

        incoming_breakdown_results = self._breakdown_incoming_quantities(
            incoming_qties_dict,
            owner_id,
            to_date,
            from_date,
        )
        for product in self:
            p_res = res[product.id]
            unconfirmed = unconfirmed_results.get(product.id, {})
            p_res["unconfirmed_outgoing_qty"] = unconfirmed.get("qty", 0)
            p_res["virtual_available"] = (
                    p_res["virtual_available"] - p_res["unconfirmed_outgoing_qty"]
            )

            incoming = incoming_breakdown_results.get(product.id, {})
            p_res["incoming_onhand_qty"] = incoming.get("incoming_onhand_qty", 0)
            p_res["incoming_inbound_qty"] = incoming.get("incoming_inbound_qty", 0)
            p_res["incoming_missing_qty"] = incoming.get("incoming_missing_qty", 0)
            p_res["virtual_onhand_qty"] = (
                    p_res["qty_available"] + p_res["incoming_onhand_qty"]
            )
            p_res["virtual_available_real"] = (
                    p_res["virtual_available"] - p_res["incoming_missing_qty"]
            )

        return res

    def _get_products_qty_in_unconfirmed_quotations(
            self, to_date=False, from_date=False
    ):
        """Compute quantities in unconfirmed quotations using ML predictions"""
        sudo_self = self.sudo()

        warehouse_id = sudo_self.env.context.get("warehouse")

        if not to_date:
            to_date = fields.Datetime.today() + relativedelta.relativedelta(months=3)

        # Search for unconfirmed orders with success predictions
        quotation_domain = [
            ("state", "not in", ["sale", "cancel"]),
            ("order_line.product_id", "in", sudo_self.ids),
            ("is_success_provided", "=", True),
        ]
        if to_date:
            quotation_domain.append(("date_order", "<=", to_date))
        if from_date:
            quotation_domain.append(("date_order", ">=", from_date))
        if warehouse_id:
            quotation_domain.append(("warehouse_id", "=", warehouse_id))

        quotations = sudo_self.env["sale.order"].search(quotation_domain)
        results = {}
        lines = sudo_self.env["sale.order.line"].search(
            [("order_id", "in", quotations.ids)]
        )

        # Get number of months until to_date
        delta = relativedelta.relativedelta(to_date, fields.Datetime.today())
        timeframe_months = delta.years * 12 + delta.months
        if timeframe_months > 12:
            timeframe_months = 12

        for line in lines:
            if line.product_id.id in sudo_self.ids:
                result = results.setdefault(
                    line.product_id.id, {"orders": {}, "qty": 0}
                )
                rounding = line.product_id.uom_id.rounding
                line_qty = line.product_uom_qty

                # Use ML prediction instead of primitive CRM rules
                success_probability = line.order_id.success_prediction / 100.0

                modified_qty = ceil(
                    float_round(
                        line_qty * success_probability, precision_rounding=rounding
                    )
                )
                final_qty = ceil(float_round(modified_qty, precision_rounding=rounding))
                no_delivery_batches = getattr(line.order_id, 'no_delivery_batches', 1) or 1

                if modified_qty:
                    if no_delivery_batches > 1:
                        final_qty = ceil(
                            float_round(
                                timeframe_months * (modified_qty / no_delivery_batches),
                                precision_rounding=rounding,
                            )
                        )
                    result["qty"] += final_qty
                    if line.order_id not in result["orders"]:
                        result["orders"][line.order_id] = {
                            "id": line.order_id.id,
                            "name": line.order_id.name,
                            "final_value": final_qty,
                            "no_delivery_batches": no_delivery_batches,
                            "modified_value": modified_qty,
                            "original_value": line_qty,
                            "ml_probability": success_probability,
                        }
                    else:
                        result["orders"][line.order_id]["final_value"] += final_qty
                        result["orders"][line.order_id]["modified_value"] += modified_qty
                        result["orders"][line.order_id]["original_value"] += line_qty

        return results

    def _breakdown_incoming_quantities(
            self, incoming_qties, owner_id, to_date, from_date
    ):
        """Breakdown incoming quantities into onhand/inbound/missing (BOM-aware)"""
        sudo_self = self.sudo()
        _, domain_move_in_loc, __ = sudo_self._get_domain_locations()
        domain_move_in = [("product_id", "in", sudo_self.ids)] + domain_move_in_loc

        if owner_id is not None:
            domain_move_in += [("restrict_partner_id", "=", owner_id)]
        if from_date:
            domain_move_in += [("date", ">=", from_date)]
        if to_date:
            domain_move_in += [("date", "<=", to_date)]

        domain_move_in_todo = [
            (
                "state",
                "in",
                ("waiting", "confirmed", "assigned", "partially_available"),
            ),
        ] + domain_move_in
        moves = (
            sudo_self.env["stock.move"]
            .with_context(active_test=False)
            .search(domain_move_in_todo)
        )
        results = {}
        for product in sudo_self.with_context(prefetch_fields=False):
            incoming_qty = incoming_qties.get(product.id, 0)

            result = results.setdefault(
                product.id,
                {
                    "incoming_onhand_qty": 0,
                    "incoming_qty": incoming_qty,
                    "incoming_inbound_qty": 0,
                    "incoming_missing_qty": 0,
                },
            )

            if incoming_qty == 0:
                continue

            product_moves = moves.filtered(lambda move: move.product_id == product)
            product_mos = product_moves.production_id
            qty_by_bom = {}
            for mo in product_mos:
                if mo.bom_id not in qty_by_bom:
                    qty_by_bom[mo.bom_id] = mo.product_qty
                else:
                    qty_by_bom[mo.bom_id] += mo.product_qty

            for bom, qty in qty_by_bom.items():
                if not bom:
                    result["incoming_missing_qty"] += qty
                    continue
                elif not bom.bom_line_ids:
                    result["incoming_missing_qty"] += qty
                    continue

                valid_bom_lines = bom.bom_line_ids.filtered(
                    lambda l: l.product_id.type == "consu"
                              and not l.product_id.skip_when_computing_component_quantities
                )

                if not valid_bom_lines:
                    result["incoming_missing_qty"] += qty
                    continue

                onhand = min(
                    float_round(
                        (l.product_id.free_qty + l.product_id.incoming_onhand_qty)
                        / l.product_qty,
                        precision_rounding=product.uom_id.rounding,
                    )
                    for l in valid_bom_lines
                )
                onhand = min(qty, onhand)

                inbound = min(
                    float_round(
                        l.product_id.incoming_inbound_qty / l.product_qty,
                        precision_rounding=product.uom_id.rounding,
                    )
                    for l in valid_bom_lines
                )
                inbound = min(qty - onhand, inbound)
                missing = qty - onhand - inbound

                result["incoming_onhand_qty"] += onhand
                result["incoming_inbound_qty"] += inbound
                result["incoming_missing_qty"] += missing

            # Non MO moves
            if incoming_qty > 0:
                non_mo_qty = sum(
                    move.product_qty
                    for move in (product_moves - product_mos.move_finished_ids)
                )
                result["incoming_inbound_qty"] += non_mo_qty

        return results


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Legacy DB mapping field
    old_name = fields.Char(
        'Назва в старій базі',
        help='Назва продукту в старій базі даних для точного мапінгу з CSV файлами історичних даних'
    )

    unconfirmed_outgoing_qty = fields.Float(
        "Unconfirmed Outgoing", compute="_compute_quantities", compute_sudo=False
    )

    incoming_onhand_qty = fields.Float(
        "Incoming On-Hand", compute="_compute_quantities", compute_sudo=False
    )
    incoming_inbound_qty = fields.Float(
        "Incoming Inbound", compute="_compute_quantities", compute_sudo=False
    )
    incoming_missing_qty = fields.Float(
        "Incoming Missing", compute="_compute_quantities", compute_sudo=False
    )
    virtual_onhand_qty = fields.Float(
        "Virtual On-Hand", compute="_compute_quantities", compute_sudo=False
    )

    virtual_available_real = fields.Float(
        "Virtual Available Real", compute="_compute_quantities", compute_sudo=False
    )

    skip_when_computing_component_quantities = fields.Boolean(
        compute="_compute_skip_when_computing_component_quantities"
    )

    def _compute_skip_when_computing_component_quantities(self):
        for template in self:
            template.skip_when_computing_component_quantities = False

    @api.depends(
        "product_variant_ids.qty_available",
        "product_variant_ids.virtual_available",
        "product_variant_ids.incoming_qty",
        "product_variant_ids.outgoing_qty",
    )
    def _compute_quantities(self):
        super()._compute_quantities()
        res = self._compute_quantities_dict()
        for template in self:
            t_res = res[template.id]
            template.unconfirmed_outgoing_qty = t_res["unconfirmed_outgoing_qty"]
            template.incoming_onhand_qty = t_res["incoming_onhand_qty"]
            template.incoming_inbound_qty = t_res["incoming_inbound_qty"]
            template.incoming_missing_qty = t_res["incoming_missing_qty"]
            template.virtual_onhand_qty = t_res["virtual_onhand_qty"]
            template.virtual_available_real = t_res["virtual_available_real"]

    def _compute_quantities_dict(self):
        res = super()._compute_quantities_dict()
        variants_available = {
            p["id"]: p
            for p in self.product_variant_ids._origin.read(
                [
                    "unconfirmed_outgoing_qty",
                    "incoming_onhand_qty",
                    "incoming_inbound_qty",
                    "incoming_missing_qty",
                    "virtual_onhand_qty",
                    "virtual_available_real",
                ]
            )
        }
        for template in self:
            unconfirmed_outgoing_qty = 0
            incoming_onhand_qty = 0
            incoming_inbound_qty = 0
            incoming_missing_qty = 0
            virtual_onhand_qty = 0
            virtual_available_real = 0
            for p in template.product_variant_ids._origin:
                unconfirmed_outgoing_qty += variants_available[p.id]["unconfirmed_outgoing_qty"]
                incoming_onhand_qty += variants_available[p.id]["incoming_onhand_qty"]
                incoming_inbound_qty += variants_available[p.id]["incoming_inbound_qty"]
                incoming_missing_qty += variants_available[p.id]["incoming_missing_qty"]
                virtual_onhand_qty += variants_available[p.id]["virtual_onhand_qty"]
                virtual_available_real += variants_available[p.id]["virtual_available_real"]
            t_res = res[template.id]
            t_res["unconfirmed_outgoing_qty"] = unconfirmed_outgoing_qty
            t_res["incoming_onhand_qty"] = incoming_onhand_qty
            t_res["incoming_inbound_qty"] = incoming_inbound_qty
            t_res["incoming_missing_qty"] = incoming_missing_qty
            t_res["virtual_onhand_qty"] = virtual_onhand_qty
            t_res["virtual_available_real"] = virtual_available_real
        return res
