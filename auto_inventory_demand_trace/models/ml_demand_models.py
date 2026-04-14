from math import ceil
from uuid import uuid4
from datetime import datetime, time
from collections import defaultdict

from dateutil import relativedelta

from odoo import api, fields, models
from odoo.tools.float_utils import float_round


PENDING_STATES = ("waiting", "confirmed", "assigned", "partially_available")


class MlDemandWave(models.Model):
    _name = "ml.demand.wave"
    _description = "ML Demand Wave"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    demand_uid = fields.Char(required=True, index=True, copy=False)
    warehouse_id = fields.Many2one("stock.warehouse", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    horizon_date_from = fields.Datetime()
    horizon_date_to = fields.Datetime(required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    note = fields.Text()
    line_ids = fields.One2many("ml.demand.line", "wave_id")
    coverage_ids = fields.One2many("ml.demand.coverage", "wave_id")

    _sql_constraints = [
        ("ml_demand_wave_uid_uniq", "unique(demand_uid)", "Demand UID must be unique."),
    ]

    @api.model
    def _normalize_to_date(self, to_date=False):
        if not to_date:
            to_date = fields.Datetime.now() + relativedelta.relativedelta(days=90)
        if isinstance(to_date, str):
            to_date = fields.Datetime.from_string(to_date)
        return datetime.combine(to_date.date(), time.max)

    @api.model
    def _normalize_from_date(self, from_date=False):
        if not from_date:
            return False
        if isinstance(from_date, str):
            from_date = fields.Datetime.from_string(from_date)
        return datetime.combine(from_date.date(), time.min)

    @api.model
    def get_or_build_active_wave(self, warehouse_id=False, from_date=False, to_date=False):
        warehouse = self.env["stock.warehouse"].browse(warehouse_id) if warehouse_id else self.env["stock.warehouse"].search([], limit=1)
        if not warehouse:
            return self.env["ml.demand.wave"]

        norm_to_date = self._normalize_to_date(to_date)
        norm_from_date = self._normalize_from_date(from_date)
        domain = [
            ("state", "=", "active"),
            ("warehouse_id", "=", warehouse.id),
            ("company_id", "=", self.env.company.id),
            ("horizon_date_to", "=", norm_to_date),
        ]
        if norm_from_date:
            domain.append(("horizon_date_from", "=", norm_from_date))
        else:
            domain.append(("horizon_date_from", "=", False))

        wave = self.search(domain, limit=1)
        if wave:
            wave.recompute_coverages()
            return wave
        return self.build_wave_from_quotations(
            warehouse_id=warehouse.id,
            from_date=norm_from_date,
            to_date=norm_to_date,
        )

    @api.model
    def build_wave_from_quotations(self, warehouse_id=False, from_date=False, to_date=False):
        warehouse = self.env["stock.warehouse"].browse(warehouse_id) if warehouse_id else self.env["stock.warehouse"].search([], limit=1)
        if not warehouse:
            return self.env["ml.demand.wave"]

        norm_to_date = self._normalize_to_date(to_date)
        norm_from_date = self._normalize_from_date(from_date)
        uid = str(uuid4())
        wave = self.create(
            {
                "name": f"ML Wave {fields.Datetime.now()}",
                "demand_uid": uid,
                "warehouse_id": warehouse.id,
                "company_id": self.env.company.id,
                "horizon_date_from": norm_from_date or False,
                "horizon_date_to": norm_to_date,
                "state": "draft",
            }
        )

        quotation_domain = [
            ("state", "not in", ["sale", "cancel"]),
            ("is_success_provided", "=", True),
            ("company_id", "=", self.env.company.id),
            ("warehouse_id", "=", warehouse.id),
        ]
        if norm_to_date:
            quotation_domain.append(("date_order", "<=", norm_to_date))
        if norm_from_date:
            quotation_domain.append(("date_order", ">=", norm_from_date))

        quotations = self.env["sale.order"].search(quotation_domain)
        lines = self.env["sale.order.line"].search([("order_id", "in", quotations.ids)])
        bom_cache = {}

        delta = relativedelta.relativedelta(norm_to_date, fields.Datetime.now())
        timeframe_months = min(12, delta.years * 12 + delta.months)

        vals_list = []
        for line in lines:
            if not line.product_id or line.product_id.type == "service":
                continue

            calc = self._compute_ml_line_qty(line, timeframe_months)
            if not calc["modified_qty"] or calc["final_qty"] <= 0:
                continue

            vals_list.append(
                wave._prepare_line_vals(
                    line=line,
                    target_product=line.product_id,
                    demand_type="direct",
                    raw_qty=calc["final_qty"],
                    source_calc=calc,
                )
            )

            component_demands = wave._explode_bom_component_demand(
                line.product_id, calc["final_qty"], bom_cache=bom_cache
            )
            for component_id, raw_component_qty in component_demands.items():
                component = self.env["product.product"].browse(component_id)
                component_qty = ceil(
                    float_round(
                        raw_component_qty,
                        precision_rounding=component.uom_id.rounding,
                    )
                )
                if component_qty <= 0:
                    continue
                vals_list.append(
                    wave._prepare_line_vals(
                        line=line,
                        target_product=component,
                        demand_type="indirect",
                        raw_qty=component_qty,
                        source_calc=calc,
                    )
                )

        if vals_list:
            self.env["ml.demand.line"].create(vals_list)

        wave.recompute_coverages()
        wave.state = "active"
        return wave

    @api.model
    def _compute_ml_line_qty(self, line, timeframe_months):
        rounding = line.product_id.uom_id.rounding
        line_qty = line.product_uom_qty
        success_probability = line.order_id.success_prediction / 100.0
        modified_qty = ceil(
            float_round(line_qty * success_probability, precision_rounding=rounding)
        )
        final_qty = ceil(float_round(modified_qty, precision_rounding=rounding))
        no_delivery_batches = getattr(line.order_id, "no_delivery_batches", 1) or 1
        if modified_qty and no_delivery_batches > 1:
            final_qty = ceil(
                float_round(
                    timeframe_months * (modified_qty / no_delivery_batches),
                    precision_rounding=rounding,
                )
            )
        return {
            "line_qty": line_qty,
            "success_probability": success_probability,
            "modified_qty": modified_qty,
            "final_qty": final_qty,
            "no_delivery_batches": no_delivery_batches,
        }

    def _prepare_line_vals(self, line, target_product, demand_type, raw_qty, source_calc):
        self.ensure_one()
        return {
            "wave_id": self.id,
            "demand_uid": self.demand_uid,
            "source_sale_order_id": line.order_id.id,
            "source_sale_order_line_id": line.id,
            "source_product_id": line.product_id.id,
            "target_product_id": target_product.id,
            "demand_type": demand_type,
            "raw_qty": raw_qty,
            "covered_qty": 0.0,
            "effective_qty": raw_qty,
            "uom_id": target_product.uom_id.id,
            "ml_probability": source_calc["success_probability"],
            "source_original_qty": source_calc["line_qty"],
            "source_modified_qty": source_calc["modified_qty"],
            "source_final_qty": source_calc["final_qty"],
            "source_no_delivery_batches": source_calc["no_delivery_batches"],
            "is_active": raw_qty > 0,
        }

    def _get_product_bom_for_ml(self, product, bom_cache=None):
        bom_cache = bom_cache or {}
        if product.id in bom_cache:
            return bom_cache[product.id]

        bom_model = self.env["mrp.bom"]
        bom = False
        normal_bom = bom_model._bom_find(product, bom_type="normal")
        if isinstance(normal_bom, dict):
            bom = normal_bom.get(product) or normal_bom.get(product.id)
        else:
            bom = normal_bom

        if not bom:
            phantom_bom = bom_model._bom_find(product, bom_type="phantom")
            if isinstance(phantom_bom, dict):
                bom = phantom_bom.get(product) or phantom_bom.get(product.id)
            else:
                bom = phantom_bom

        bom_cache[product.id] = bom or False
        return bom_cache[product.id]

    def _explode_bom_component_demand(self, product, qty, bom_cache=None, traversal_path=None):
        if not product or qty <= 0:
            return {}
        traversal_path = traversal_path or set()
        if product.id in traversal_path:
            return {}

        bom = self._get_product_bom_for_ml(product, bom_cache=bom_cache)
        if not bom or not bom.bom_line_ids or not bom.product_qty:
            return {}

        qty_in_bom_uom = product.uom_id._compute_quantity(
            qty, bom.product_uom_id, raise_if_failure=False
        )
        if qty_in_bom_uom <= 0:
            return {}

        factor = qty_in_bom_uom / bom.product_qty
        aggregated_demands = defaultdict(float)

        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if not component or component.type == "service":
                continue

            component_qty_in_line_uom = bom_line.product_qty * factor
            component_qty = bom_line.product_uom_id._compute_quantity(
                component_qty_in_line_uom,
                component.uom_id,
                raise_if_failure=False,
            )
            if component_qty <= 0:
                continue

            next_path = set(traversal_path)
            next_path.add(product.id)
            nested_demands = self._explode_bom_component_demand(
                component,
                component_qty,
                bom_cache=bom_cache,
                traversal_path=next_path,
            )
            if nested_demands:
                for nested_component_id, nested_qty in nested_demands.items():
                    aggregated_demands[nested_component_id] += nested_qty
            else:
                aggregated_demands[component.id] += component_qty

        return dict(aggregated_demands)

    def recompute_coverages(self):
        for wave in self:
            wave.coverage_ids.unlink()
            wave._recompute_indirect_coverages()
        return True

    def _recompute_indirect_coverages(self):
        self.ensure_one()
        line_model = self.env["ml.demand.line"]
        move_model = self.env["stock.move"]
        indirect_lines = line_model.search(
            [
                ("wave_id", "=", self.id),
                ("demand_type", "=", "indirect"),
            ],
            order="target_product_id, id",
        )
        if not indirect_lines:
            direct_lines = line_model.search(
                [("wave_id", "=", self.id), ("demand_type", "=", "direct")]
            )
            for line in direct_lines:
                line.covered_qty = 0.0
                line.effective_qty = line.raw_qty
                line.is_active = line.effective_qty > 0
            return

        lines_by_product = defaultdict(lambda: self.env["ml.demand.line"])
        for line in indirect_lines:
            lines_by_product[line.target_product_id.id] |= line

        for product_id, product_lines in lines_by_product.items():
            domain = [
                ("ml_demand_uid", "=", self.demand_uid),
                ("product_id", "=", product_id),
                ("raw_material_production_id", "!=", False),
                ("state", "in", PENDING_STATES),
            ]
            moves = move_model.search(domain, order="date,id")
            move_remaining = {move.id: move.product_qty for move in moves}

            for line in product_lines.sorted("id"):
                required = max(0.0, line.raw_qty)
                remaining = required
                allocated = 0.0
                for move in moves:
                    available = move_remaining[move.id]
                    if available <= 0 or remaining <= 0:
                        continue
                    alloc = min(available, remaining)
                    move_remaining[move.id] -= alloc
                    remaining -= alloc
                    allocated += alloc
                    self.env["ml.demand.coverage"].create(
                        {
                            "wave_id": self.id,
                            "demand_line_id": line.id,
                            "covered_model": "stock.move",
                            "covered_res_id": move.id,
                            "covered_qty": alloc,
                            "coverage_state": "in_progress",
                        }
                    )

                line.covered_qty = allocated
                line.effective_qty = max(0.0, required - allocated)
                line.is_active = line.effective_qty > 0

        direct_lines = line_model.search(
            [("wave_id", "=", self.id), ("demand_type", "=", "direct")]
        )
        for line in direct_lines:
            line.covered_qty = 0.0
            line.effective_qty = max(0.0, line.raw_qty)
            line.is_active = line.effective_qty > 0

    @api.model
    def aggregate_for_products(self, product_ids, warehouse_id=False, from_date=False, to_date=False):
        wave = self.get_or_build_active_wave(
            warehouse_id=warehouse_id, from_date=from_date, to_date=to_date
        )
        res = {
            pid: {"orders": {}, "qty": 0.0, "direct_qty": 0.0, "indirect_qty": 0.0}
            for pid in product_ids
        }
        if not wave:
            return res

        lines = self.env["ml.demand.line"].search(
            [
                ("wave_id", "=", wave.id),
                ("target_product_id", "in", list(product_ids)),
                ("is_active", "=", True),
            ]
        )
        for line in lines:
            item = res[line.target_product_id.id]
            qty = line.effective_qty
            item["qty"] += qty
            if line.demand_type == "direct":
                item["direct_qty"] += qty
            else:
                item["indirect_qty"] += qty

            order = line.source_sale_order_id
            order_info = item["orders"].setdefault(
                order,
                {
                    "id": order.id,
                    "name": order.name,
                    "final_value": 0.0,
                    "direct_value": 0.0,
                    "indirect_value": 0.0,
                    "no_delivery_batches": line.source_no_delivery_batches or 1,
                    "modified_value": line.source_modified_qty,
                    "original_value": line.source_original_qty,
                    "ml_probability": line.ml_probability,
                },
            )
            order_info["final_value"] += qty
            if line.demand_type == "direct":
                order_info["direct_value"] += qty
            else:
                order_info["indirect_value"] += qty
        return res


class MlDemandLine(models.Model):
    _name = "ml.demand.line"
    _description = "ML Demand Line"
    _order = "id"

    wave_id = fields.Many2one("ml.demand.wave", required=True, ondelete="cascade", index=True)
    demand_uid = fields.Char(required=True, index=True)

    source_sale_order_id = fields.Many2one("sale.order", index=True)
    source_sale_order_line_id = fields.Many2one("sale.order.line", index=True)
    source_product_id = fields.Many2one("product.product", required=True, index=True)
    target_product_id = fields.Many2one("product.product", required=True, index=True)

    demand_type = fields.Selection(
        [("direct", "Direct"), ("indirect", "Indirect")], required=True, index=True
    )
    raw_qty = fields.Float(required=True, default=0.0)
    covered_qty = fields.Float(required=True, default=0.0)
    effective_qty = fields.Float(required=True, default=0.0)
    uom_id = fields.Many2one("uom.uom", required=True)
    ml_probability = fields.Float()
    is_active = fields.Boolean(default=True, index=True)

    source_original_qty = fields.Float(default=0.0)
    source_modified_qty = fields.Float(default=0.0)
    source_final_qty = fields.Float(default=0.0)
    source_no_delivery_batches = fields.Float(default=1.0)

    coverage_ids = fields.One2many("ml.demand.coverage", "demand_line_id")

    _sql_constraints = [
        ("ml_demand_line_non_negative_raw", "CHECK(raw_qty >= 0)", "raw_qty must be >= 0."),
        (
            "ml_demand_line_non_negative_covered",
            "CHECK(covered_qty >= 0)",
            "covered_qty must be >= 0.",
        ),
        (
            "ml_demand_line_non_negative_effective",
            "CHECK(effective_qty >= 0)",
            "effective_qty must be >= 0.",
        ),
    ]


class MlDemandCoverage(models.Model):
    _name = "ml.demand.coverage"
    _description = "ML Demand Coverage Allocation"
    _order = "id"

    wave_id = fields.Many2one("ml.demand.wave", required=True, ondelete="cascade", index=True)
    demand_line_id = fields.Many2one(
        "ml.demand.line", required=True, ondelete="cascade", index=True
    )
    covered_model = fields.Selection(
        [("mrp.production", "Manufacturing Order"), ("stock.move", "Stock Move"), ("purchase.order.line", "Purchase Line")],
        required=True,
    )
    covered_res_id = fields.Integer(required=True, index=True)
    covered_qty = fields.Float(required=True, default=0.0)
    coverage_state = fields.Selection(
        [("planned", "Planned"), ("in_progress", "In Progress"), ("done", "Done"), ("cancelled", "Cancelled")],
        default="in_progress",
        required=True,
    )

    _sql_constraints = [
        (
            "ml_demand_coverage_unique_doc",
            "unique(demand_line_id, covered_model, covered_res_id)",
            "Coverage entry must be unique per demand line and document.",
        ),
        (
            "ml_demand_coverage_non_negative",
            "CHECK(covered_qty >= 0)",
            "covered_qty must be >= 0.",
        ),
    ]
