from math import ceil
from collections import defaultdict
from dateutil import relativedelta
from datetime import datetime, time
from html import escape

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
    unconfirmed_outgoing_direct_qty = fields.Float(
        "Unconfirmed Outgoing (Direct)", compute="_compute_quantities", compute_sudo=False
    )
    unconfirmed_outgoing_indirect_qty = fields.Float(
        "Unconfirmed Outgoing (Indirect)", compute="_compute_quantities", compute_sudo=False
    )

    virtual_available_ml = fields.Float(
        "Virtual Available ML", compute="_compute_quantities", compute_sudo=False
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
    forecast_validation_html = fields.Html(
        "Forecast Formula Validation",
        readonly=True,
        sanitize=False,
        help="Detailed validation report for selected variant forecast formula.",
    )
    forecast_validation_last_run = fields.Datetime(
        "Forecast Validation Last Run",
        readonly=True,
    )

    def action_validate_forecast_formula(self):
        self.ensure_one()
        self.sudo().write({
            "forecast_validation_html": self._build_forecast_validation_html(),
            "forecast_validation_last_run": fields.Datetime.now(),
        })
        return True

    def _get_forecast_formula_snapshot(self, to_date=False):
        self.ensure_one()
        product = self.sudo()
        to_date = to_date or (fields.Datetime.today() + relativedelta.relativedelta(days=90))
        breakdown = product._get_detailed_forecast_breakdown(to_date=to_date).get(product.id, {})
        standard_virtual = breakdown.get("virtual_available", 0.0)
        standard_incoming = breakdown.get("incoming_qty", 0.0)
        reliable_incoming = breakdown.get("incoming_reliable_qty", standard_incoming)
        ml_outgoing = breakdown.get("unconfirmed_outgoing_qty", 0.0)
        expected_virtual_real = standard_virtual - (standard_incoming - reliable_incoming) - ml_outgoing
        actual_virtual_real = product.with_context(to_date=to_date).virtual_available_real
        formula_delta = actual_virtual_real - expected_virtual_real
        return {
            "to_date": to_date,
            "breakdown": breakdown,
            "standard_virtual": standard_virtual,
            "standard_incoming": standard_incoming,
            "reliable_incoming": reliable_incoming,
            "ml_outgoing": ml_outgoing,
            "expected_virtual_real": expected_virtual_real,
            "actual_virtual_real": actual_virtual_real,
            "formula_delta": formula_delta,
            "formula_ok": abs(formula_delta) < 1e-6,
        }

    def _build_forecast_validation_html(self):
        self.ensure_one()
        product = self.sudo()
        snapshot = product._get_forecast_formula_snapshot()
        to_date = snapshot["to_date"]
        breakdown = snapshot["breakdown"]
        unconfirmed_result = product._get_products_qty_in_unconfirmed_quotations(to_date=to_date).get(product.id, {})
        standard_virtual = snapshot["standard_virtual"]
        standard_incoming = snapshot["standard_incoming"]
        reliable_incoming = snapshot["reliable_incoming"]
        ml_outgoing = snapshot["ml_outgoing"]
        expected_virtual_real = snapshot["expected_virtual_real"]
        actual_virtual_real = snapshot["actual_virtual_real"]
        formula_delta = snapshot["formula_delta"]
        formula_ok = snapshot["formula_ok"]

        outgoing_links = self._build_unconfirmed_outgoing_links(unconfirmed_result)
        incoming_links = self._build_incoming_source_links(product, to_date=to_date)
        confirmed_outgoing_links = self._build_confirmed_outgoing_source_links(product, to_date=to_date)
        dedup_links = self._build_pending_mo_raw_links(product, to_date=to_date)

        status_color = "#198754" if formula_ok else "#dc3545"
        status_text = "PASS" if formula_ok else "FAIL"

        incoming_gap = standard_incoming - reliable_incoming
        step_1 = standard_virtual - incoming_gap
        step_2 = step_1 - ml_outgoing
        non_mo_incoming = breakdown.get("incoming_non_mo_qty", 0.0)
        mo_scheduled = breakdown.get("incoming_mo_scheduled_qty", 0.0)
        mo_feasible = breakdown.get("incoming_mo_feasible_qty", 0.0)
        mo_unfeasible = breakdown.get("incoming_mo_unfeasible_qty", 0.0)
        outgoing_qty = breakdown.get("outgoing_qty", 0.0)
        qty_available = breakdown.get("qty_available", 0.0)
        virtual_ml = breakdown.get("virtual_available_ml", 0.0)
        reliable_standard = breakdown.get("standard_forecast_reliable", 0.0)

        html = [
            "<div class='o_forecast_validation_report'>",
            f"<h3>Перевірка формули прогнозу: {escape(product.display_name)}</h3>",
            f"<p><strong>Дата перевірки:</strong> {fields.Datetime.now()}</p>",
            f"<p><strong>Статус:</strong> <span style='color:{status_color};'><strong>{status_text}</strong></span></p>",
            "<hr/>",
            "<h4>1) Формула virtual_available_real</h4>",
            "<p><code>virtual_available_real = virtual_available - (incoming_qty - incoming_reliable_qty) - unconfirmed_outgoing_qty</code></p>",
            "<h5>1.1 Розклад параметрів формули</h5>",
            "<table class='table table-sm table-bordered'>"
            "<thead><tr><th>Параметр</th><th>Значення</th></tr></thead>"
            "<tbody>",
            f"<tr><td>virtual_available</td><td>{standard_virtual:.2f}</td></tr>",
            f"<tr><td>incoming_qty</td><td>{standard_incoming:.2f}</td></tr>",
            f"<tr><td>incoming_reliable_qty</td><td>{reliable_incoming:.2f}</td></tr>",
            f"<tr><td>unconfirmed_outgoing_qty</td><td>{ml_outgoing:.2f}</td></tr>",
            f"<tr><td><strong>Очікуване virtual_available_real</strong></td><td><strong>{expected_virtual_real:.2f}</strong></td></tr>",
            f"<tr><td><strong>Фактичне virtual_available_real</strong></td><td><strong>{actual_virtual_real:.2f}</strong></td></tr>",
            f"<tr><td><strong>Різниця (fact - expected)</strong></td><td><strong>{formula_delta:.6f}</strong></td></tr>",
            "</tbody></table>",
            "<h5>1.2 Покрокова арифметика</h5>",
            "<table class='table table-sm table-bordered'>"
            "<thead><tr><th>Крок</th><th>Вираз</th><th>Результат</th></tr></thead>"
            "<tbody>",
            f"<tr><td>Крок 1</td><td>incoming_gap = incoming_qty - incoming_reliable_qty = {standard_incoming:.2f} - {reliable_incoming:.2f}</td><td>{incoming_gap:.2f}</td></tr>",
            f"<tr><td>Крок 2</td><td>base_after_reliability = virtual_available - incoming_gap = {standard_virtual:.2f} - {incoming_gap:.2f}</td><td>{step_1:.2f}</td></tr>",
            f"<tr><td>Крок 3</td><td>expected_virtual_available_real = base_after_reliability - unconfirmed_outgoing_qty = {step_1:.2f} - {ml_outgoing:.2f}</td><td>{step_2:.2f}</td></tr>",
            "</tbody></table>",
            "<hr/>",
            "<h4>2) Розклад вхідних/вихідних складових</h4>",
            "<table class='table table-sm table-bordered'>"
            "<thead><tr><th>Складова</th><th>Значення</th></tr></thead>"
            "<tbody>",
            f"<tr><td>qty_available</td><td>{breakdown.get('qty_available', 0.0):.2f}</td></tr>",
            f"<tr><td>outgoing_qty</td><td>{breakdown.get('outgoing_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>unconfirmed_outgoing_direct_qty</td><td>{breakdown.get('unconfirmed_outgoing_direct_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>unconfirmed_outgoing_indirect_qty</td><td>{breakdown.get('unconfirmed_outgoing_indirect_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>incoming_non_mo_qty</td><td>{breakdown.get('incoming_non_mo_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>incoming_mo_feasible_qty</td><td>{breakdown.get('incoming_mo_feasible_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>incoming_mo_unfeasible_qty</td><td>{breakdown.get('incoming_mo_unfeasible_qty', 0.0):.2f}</td></tr>",
            f"<tr><td>incoming_missing_qty</td><td>{breakdown.get('incoming_missing_qty', 0.0):.2f}</td></tr>",
            "</tbody></table>",
            "<hr/>",
            "<h4>3) Документи-джерела</h4>",
            "<h5>3.1 ML Outgoing з комерційних пропозицій (SO)</h5>",
            outgoing_links,
            "<h5>3.2 Вхідні документи (Stock Moves / MO)</h5>",
            incoming_links,
            "<h5>3.3 Підтверджені вихідні документи (для outgoing_qty)</h5>",
            confirmed_outgoing_links,
            "<h5>3.4 Pending raw MO для dedup indirect demand</h5>",
            dedup_links,
            "<hr/>",
            "<h4>4) Трасування ключових метрик</h4>",
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>Метрика</th><th>Як обчислюється</th><th>Звідки беруться дані</th></tr></thead>",
            "<tbody>",
            "<tr>"
            f"<td>virtual_available = {standard_virtual:.2f}</td>"
            f"<td>qty_available + incoming_qty - outgoing_qty = {qty_available:.2f} + {standard_incoming:.2f} - {outgoing_qty:.2f}</td>"
            "<td>Базовий stock forecast Odoo; документи див. 3.2 (incoming) і 3.3 (outgoing).</td>"
            "</tr>",
            "<tr>"
            f"<td>incoming_qty = {standard_incoming:.2f}</td>"
            "<td>Сума запланованих вхідних moves у горизонті</td>"
            "<td>Документально: таблиця 3.2 (Stock Moves / MO).</td>"
            "</tr>",
            "<tr>"
            f"<td>incoming_reliable_qty = {reliable_incoming:.2f}</td>"
            f"<td>incoming_non_mo_qty + incoming_mo_feasible_qty = {non_mo_incoming:.2f} + {mo_feasible:.2f}</td>"
            "<td>Похідне від надійності MO-компонентів; базові документи див. 3.2 (incoming moves + MO).</td>"
            "</tr>",
            "<tr>"
            f"<td>unconfirmed_outgoing_qty = {ml_outgoing:.2f}</td>"
            f"<td>unconfirmed_outgoing_direct_qty + unconfirmed_outgoing_indirect_qty (після dedup)</td>"
            "<td>Документально: 3.1 (SO джерела ML) + 3.4 (raw MO для dedup, якщо є).</td>"
            "</tr>",
            "</tbody></table>",
            "<hr/>",
            "<h4>5) Словник метрик</h4>",
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>Метрика</th><th>Значення</th><th>Пояснення</th></tr></thead>",
            "<tbody>",
            f"<tr><td>qty_available</td><td>{qty_available:.2f}</td><td>Поточний on-hand (з урахуванням контексту локації/складу).</td></tr>",
            f"<tr><td>incoming_qty</td><td>{standard_incoming:.2f}</td><td>Усі заплановані вхідні move у горизонті.</td></tr>",
            f"<tr><td>outgoing_qty</td><td>{outgoing_qty:.2f}</td><td>Усі підтверджені вихідні move у горизонті.</td></tr>",
            f"<tr><td>virtual_available</td><td>{standard_virtual:.2f}</td><td>Базовий прогноз Odoo: qty_available + incoming_qty - outgoing_qty.</td></tr>",
            f"<tr><td>incoming_non_mo_qty</td><td>{non_mo_incoming:.2f}</td><td>Вхідні, не пов'язані з MO.</td></tr>",
            f"<tr><td>incoming_mo_scheduled_qty</td><td>{mo_scheduled:.2f}</td><td>Усі заплановані надходження з MO.</td></tr>",
            f"<tr><td>incoming_mo_feasible_qty</td><td>{mo_feasible:.2f}</td><td>Частина MO, забезпечена компонентами (on-hand/inbound).</td></tr>",
            f"<tr><td>incoming_mo_unfeasible_qty</td><td>{mo_unfeasible:.2f}</td><td>Частина MO без достатніх компонентів.</td></tr>",
            f"<tr><td>incoming_reliable_qty</td><td>{reliable_incoming:.2f}</td><td>Надійні надходження: non-MO + feasible MO.</td></tr>",
            f"<tr><td>unconfirmed_outgoing_direct_qty</td><td>{breakdown.get('unconfirmed_outgoing_direct_qty', 0.0):.2f}</td><td>ML-попит напряму з SO по цьому продукту.</td></tr>",
            f"<tr><td>unconfirmed_outgoing_indirect_qty</td><td>{breakdown.get('unconfirmed_outgoing_indirect_qty', 0.0):.2f}</td><td>ML-попит через BOM (компонентний).</td></tr>",
            f"<tr><td>unconfirmed_outgoing_qty</td><td>{ml_outgoing:.2f}</td><td>Загальний ML outgoing (direct + indirect після dedup).</td></tr>",
            f"<tr><td>virtual_available_ml</td><td>{virtual_ml:.2f}</td><td>virtual_available - unconfirmed_outgoing_qty.</td></tr>",
            f"<tr><td>virtual_available_real</td><td>{actual_virtual_real:.2f}</td><td>Фінальний прогноз: корекція на надійність incoming + ML outgoing.</td></tr>",
            "</tbody></table>",
            "</div>",
        ]
        return "".join(html)

    def _build_unconfirmed_outgoing_links(self, unconfirmed_result):
        orders = list(unconfirmed_result.get("orders", {}).values())
        if not orders:
            return "<p><em>Немає джерел SO для unconfirmed outgoing.</em></p>"
        rows = [
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>SO</th><th>Final</th><th>Direct</th><th>Indirect</th><th>Probability %</th></tr></thead>",
            "<tbody>",
        ]
        for order in sorted(orders, key=lambda x: x.get("id", 0)):
            order_id = order.get("id")
            order_name = escape(order.get("name", f"SO {order_id}"))
            rows.append(
                "<tr>"
                f"<td><a href='/web#id={order_id}&model=sale.order&view_type=form'>{order_name}</a></td>"
                f"<td>{order.get('final_value', 0.0):.2f}</td>"
                f"<td>{order.get('direct_value', 0.0):.2f}</td>"
                f"<td>{order.get('indirect_value', 0.0):.2f}</td>"
                f"<td>{order.get('ml_probability', 0.0) * 100.0:.2f}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
        return "".join(rows)

    def _build_incoming_source_links(self, product, to_date=False):
        _, domain_move_in_loc, _ = product._get_domain_locations()
        domain = [
            ("product_id", "=", product.id),
            ("state", "in", ("waiting", "confirmed", "assigned", "partially_available")),
        ] + domain_move_in_loc
        if to_date:
            domain.append(("date", "<=", to_date))
        moves = product.env["stock.move"].sudo().search(domain, order="date asc, id asc")
        if not moves:
            return "<p><em>Немає вхідних move-документів у горизонті.</em></p>"
        rows = [
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>Stock Move</th><th>Qty</th><th>State</th><th>MO</th></tr></thead>",
            "<tbody>",
        ]
        for move in moves:
            move_name = escape(move.reference or move.picking_id.name or move.name or f"MOVE {move.id}")
            move_link = f"/web#id={move.id}&model=stock.move&view_type=form"
            mo_cell = "-"
            if move.production_id:
                mo_cell = (
                    f"<a href='/web#id={move.production_id.id}&model=mrp.production&view_type=form'>"
                    f"{escape(move.production_id.name)}</a>"
                )
            rows.append(
                "<tr>"
                f"<td><a href='{move_link}'>{move_name}</a></td>"
                f"<td>{move.product_qty:.2f}</td>"
                f"<td>{escape(move.state)}</td>"
                f"<td>{mo_cell}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
        return "".join(rows)

    def _build_confirmed_outgoing_source_links(self, product, to_date=False):
        _, _, domain_move_out_loc = product._get_domain_locations()
        domain = [
            ("product_id", "=", product.id),
            ("state", "in", ("waiting", "confirmed", "assigned", "partially_available")),
        ] + domain_move_out_loc
        if to_date:
            domain.append(("date", "<=", to_date))
        moves = product.env["stock.move"].sudo().search(domain, order="date asc, id asc")
        if not moves:
            return "<p><em>Немає вихідних move-документів у горизонті.</em></p>"
        rows = [
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>Stock Move</th><th>Qty</th><th>State</th><th>Джерело</th></tr></thead>",
            "<tbody>",
        ]
        for move in moves:
            move_name = escape(move.reference or move.picking_id.name or move.name or f"MOVE {move.id}")
            move_link = f"/web#id={move.id}&model=stock.move&view_type=form"
            origin_label = "-"
            if move.sale_line_id and move.sale_line_id.order_id:
                so = move.sale_line_id.order_id
                origin_label = (
                    f"<a href='/web#id={so.id}&model=sale.order&view_type=form'>{escape(so.name)}</a>"
                )
            elif move.raw_material_production_id:
                mo = move.raw_material_production_id
                origin_label = (
                    f"<a href='/web#id={mo.id}&model=mrp.production&view_type=form'>{escape(mo.name)}</a>"
                )
            rows.append(
                "<tr>"
                f"<td><a href='{move_link}'>{move_name}</a></td>"
                f"<td>{move.product_qty:.2f}</td>"
                f"<td>{escape(move.state)}</td>"
                f"<td>{origin_label}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
        return "".join(rows)

    def _build_pending_mo_raw_links(self, product, to_date=False):
        _, _, domain_move_out_loc = product._get_domain_locations()
        domain = [
            ("product_id", "=", product.id),
            ("raw_material_production_id", "!=", False),
            ("state", "in", ("waiting", "confirmed", "assigned", "partially_available")),
        ] + domain_move_out_loc
        if to_date:
            domain.append(("date", "<=", to_date))
        raw_moves = product.env["stock.move"].sudo().search(domain, order="date asc, id asc")
        if not raw_moves:
            return "<p><em>Немає pending raw moves для dedup.</em></p>"
        rows = [
            "<table class='table table-sm table-bordered'>",
            "<thead><tr><th>Raw Move</th><th>Qty</th><th>State</th><th>MO</th></tr></thead>",
            "<tbody>",
        ]
        for move in raw_moves:
            move_link = f"/web#id={move.id}&model=stock.move&view_type=form"
            mo = move.raw_material_production_id
            mo_cell = (
                f"<a href='/web#id={mo.id}&model=mrp.production&view_type=form'>{escape(mo.name)}</a>"
                if mo else "-"
            )
            rows.append(
                "<tr>"
                f"<td><a href='{move_link}'>{escape(move.reference or move.name or f'RAW MOVE {move.id}')}</a></td>"
                f"<td>{move.product_qty:.2f}</td>"
                f"<td>{escape(move.state)}</td>"
                f"<td>{mo_cell}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
        return "".join(rows)

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
        services.unconfirmed_outgoing_direct_qty = 0.0
        services.unconfirmed_outgoing_indirect_qty = 0.0
        services.virtual_available_ml = 0.0
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
        component_products = self._get_bom_component_products()
        component_quantities = self._get_base_component_quantities_dict(
            component_products,
            lot_id,
            owner_id,
            package_id,
            from_date,
            to_date,
        )

        incoming_breakdown_results = self._breakdown_incoming_quantities(
            incoming_qties_dict,
            component_quantities,
            owner_id,
            to_date,
            from_date,
        )
        for product in self:
            p_res = res[product.id]
            unconfirmed = unconfirmed_results.get(product.id, {})
            unconfirmed_qty = unconfirmed.get("qty", 0)
            p_res["unconfirmed_outgoing_qty"] = unconfirmed_qty
            p_res["unconfirmed_outgoing_direct_qty"] = unconfirmed.get("direct_qty", 0)
            p_res["unconfirmed_outgoing_indirect_qty"] = unconfirmed.get("indirect_qty", 0)
            
            incoming = incoming_breakdown_results.get(product.id, {})
            p_res["incoming_onhand_qty"] = incoming.get("incoming_onhand_qty", 0)
            p_res["incoming_inbound_qty"] = incoming.get("incoming_inbound_qty", 0)
            p_res["incoming_missing_qty"] = incoming.get("incoming_missing_qty", 0)
            
            # Smart Inventory Enhancement for virtual_available_real:
            # 1. Start with standard Odoo forecast
            # 2. Subtract ML-predicted outgoing from unconfirmed orders
            # 3. Adjust for unreliable incoming (MOs without components)
            
            standard_virtual_available = p_res["virtual_available"]
            standard_incoming_qty = p_res["incoming_qty"]
            reliable_incoming_qty = incoming.get("incoming_reliable_qty", standard_incoming_qty)
            
            # Formula: (Standard Forecast - (Total Incoming - Reliable Incoming)) - ML Outgoing
            real_forecast = standard_virtual_available - (standard_incoming_qty - reliable_incoming_qty) - unconfirmed_qty
            
            p_res["virtual_available_ml"] = standard_virtual_available - unconfirmed_qty
            p_res["virtual_available_real"] = real_forecast
            p_res["virtual_onhand_qty"] = (
                    p_res["qty_available"] + p_res["incoming_onhand_qty"]
            )

        return res

    def _get_bom_component_products(self):
        bom_lines = self.env["mrp.bom.line"].search([
            ("bom_id.product_id", "in", self.ids),
        ])
        return bom_lines.product_id

    def _get_base_component_quantities_dict(
            self, component_products, lot_id, owner_id, package_id, from_date=False, to_date=False
    ):
        if not component_products:
            return {}
        return super(Product, component_products)._compute_quantities_dict(
            lot_id, owner_id, package_id, from_date, to_date
        )

    def _get_detailed_forecast_breakdown(
            self, lot_id=None, owner_id=None, package_id=None, from_date=False, to_date=False
    ):
        products = self.sudo()
        if not products:
            return {}
        base_quantities = super(Product, products)._compute_quantities_dict(
            lot_id, owner_id, package_id, from_date, to_date
        )
        unconfirmed_results = products._get_products_qty_in_unconfirmed_quotations(
            to_date, from_date
        )
        incoming_qties_dict = {
            product.id: base_quantities[product.id]["incoming_qty"]
            for product in products
        }
        component_products = products._get_bom_component_products()
        component_quantities = products._get_base_component_quantities_dict(
            component_products,
            lot_id,
            owner_id,
            package_id,
            from_date,
            to_date,
        )
        incoming_breakdown_results = products._breakdown_incoming_quantities(
            incoming_qties_dict,
            component_quantities,
            owner_id,
            to_date,
            from_date,
        )

        detailed = {}
        for product in products:
            base = base_quantities[product.id]
            unconfirmed = unconfirmed_results.get(product.id, {})
            incoming = incoming_breakdown_results.get(product.id, {})
            standard_forecast = base["virtual_available"]
            ml_forecast = standard_forecast - unconfirmed.get("qty", 0)
            reliable_standard_forecast = (
                base["qty_available"]
                + incoming.get("incoming_reliable_qty", 0.0)
                - base["outgoing_qty"]
            )
            reliable_ml_forecast = reliable_standard_forecast - unconfirmed.get("qty", 0)
            detailed[product.id] = {
                "qty_available": base["qty_available"],
                "incoming_qty": base["incoming_qty"],
                "outgoing_qty": base["outgoing_qty"],
                "virtual_available": standard_forecast,
                "unconfirmed_outgoing_qty": unconfirmed.get("qty", 0.0),
                "unconfirmed_outgoing_direct_qty": unconfirmed.get("direct_qty", 0.0),
                "unconfirmed_outgoing_indirect_qty": unconfirmed.get("indirect_qty", 0.0),
                "virtual_available_ml": ml_forecast,
                "incoming_onhand_qty": incoming.get("incoming_onhand_qty", 0.0),
                "incoming_inbound_qty": incoming.get("incoming_inbound_qty", 0.0),
                "incoming_component_inbound_qty": incoming.get("incoming_component_inbound_qty", 0.0),
                "incoming_missing_qty": incoming.get("incoming_missing_qty", 0.0),
                "incoming_non_mo_qty": incoming.get("incoming_non_mo_qty", 0.0),
                "incoming_mo_scheduled_qty": incoming.get("incoming_mo_scheduled_qty", 0.0),
                "incoming_mo_feasible_qty": incoming.get("incoming_mo_feasible_qty", 0.0),
                "incoming_mo_unfeasible_qty": incoming.get("incoming_mo_unfeasible_qty", 0.0),
                "incoming_reliable_qty": incoming.get("incoming_reliable_qty", 0.0),
                "standard_forecast_reliable": reliable_standard_forecast,
                "virtual_available_ml_reliable": reliable_ml_forecast,
            }
        return detailed

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
            ("is_success_provided", "=", True),
        ]
        if to_date:
            quotation_domain.append(("date_order", "<=", to_date))
        if from_date:
            quotation_domain.append(("date_order", ">=", from_date))
        if warehouse_id:
            quotation_domain.append(("warehouse_id", "=", warehouse_id))

        quotations = sudo_self.env["sale.order"].search(quotation_domain)
        target_products = {product.id: product for product in sudo_self}
        results = {}
        lines = sudo_self.env["sale.order.line"].search(
            [("order_id", "in", quotations.ids)]
        )
        bom_cache = {}

        # Get number of months until to_date
        delta = relativedelta.relativedelta(to_date, fields.Datetime.today())
        timeframe_months = delta.years * 12 + delta.months
        if timeframe_months > 12:
            timeframe_months = 12

        for line in lines:
            if not line.product_id or line.product_id.type == "service":
                continue

            line_product = line.product_id
            line_rounding = line_product.uom_id.rounding
            line_qty = line.product_uom_qty

            # Use ML prediction instead of primitive CRM rules
            success_probability = line.order_id.success_prediction / 100.0
            modified_qty = ceil(
                float_round(line_qty * success_probability, precision_rounding=line_rounding)
            )
            final_qty = ceil(float_round(modified_qty, precision_rounding=line_rounding))
            no_delivery_batches = getattr(line.order_id, "no_delivery_batches", 1) or 1

            if not modified_qty:
                continue

            if no_delivery_batches > 1:
                final_qty = ceil(
                    float_round(
                        timeframe_months * (modified_qty / no_delivery_batches),
                        precision_rounding=line_rounding,
                    )
                )

            if line_product.id in target_products:
                result = results.setdefault(
                    line_product.id,
                    {"orders": {}, "qty": 0.0, "direct_qty": 0.0, "indirect_qty": 0.0},
                )
                result["qty"] += final_qty
                result["direct_qty"] += final_qty
                if line.order_id not in result["orders"]:
                    result["orders"][line.order_id] = {
                        "id": line.order_id.id,
                        "name": line.order_id.name,
                        "final_value": final_qty,
                        "direct_value": final_qty,
                        "indirect_value": 0.0,
                        "no_delivery_batches": no_delivery_batches,
                        "modified_value": modified_qty,
                        "original_value": line_qty,
                        "ml_probability": success_probability,
                    }
                else:
                    result["orders"][line.order_id]["final_value"] += final_qty
                    result["orders"][line.order_id]["direct_value"] += final_qty
                    result["orders"][line.order_id]["modified_value"] += modified_qty
                    result["orders"][line.order_id]["original_value"] += line_qty

            component_demands = sudo_self._explode_bom_component_demand(
                line_product, final_qty, bom_cache=bom_cache
            )
            for component_id, raw_component_qty in component_demands.items():
                if component_id not in target_products:
                    continue
                component = target_products[component_id]
                component_qty = ceil(
                    float_round(
                        raw_component_qty,
                        precision_rounding=component.uom_id.rounding,
                    )
                )
                if component_qty <= 0:
                    continue

                result = results.setdefault(
                    component_id,
                    {"orders": {}, "qty": 0.0, "direct_qty": 0.0, "indirect_qty": 0.0},
                )
                result["qty"] += component_qty
                result["indirect_qty"] += component_qty
                if line.order_id not in result["orders"]:
                    result["orders"][line.order_id] = {
                        "id": line.order_id.id,
                        "name": line.order_id.name,
                        "final_value": component_qty,
                        "direct_value": 0.0,
                        "indirect_value": component_qty,
                        "no_delivery_batches": no_delivery_batches,
                        "modified_value": modified_qty,
                        "original_value": line_qty,
                        "ml_probability": success_probability,
                    }
                else:
                    result["orders"][line.order_id]["final_value"] += component_qty
                    result["orders"][line.order_id]["indirect_value"] += component_qty

        pending_mo_raw_by_product = sudo_self._get_pending_mo_raw_consumption_qty(
            target_products.keys(), from_date=from_date, to_date=to_date
        )
        sudo_self._apply_indirect_demand_dedup(results, pending_mo_raw_by_product)
        return results

    def _get_pending_mo_raw_consumption_qty(self, product_ids, from_date=False, to_date=False):
        sudo_self = self.sudo()
        product_ids = [pid for pid in product_ids if pid]
        if not product_ids:
            return {}

        _, __, domain_move_out_loc = sudo_self._get_domain_locations()
        domain = [
            ("product_id", "in", product_ids),
            ("raw_material_production_id", "!=", False),
            ("state", "in", ("waiting", "confirmed", "assigned", "partially_available")),
        ] + domain_move_out_loc

        if from_date:
            domain.append(("date", ">=", from_date))
        if to_date:
            domain.append(("date", "<=", to_date))

        moves = sudo_self.env["stock.move"].with_context(active_test=False).search(domain)
        consumption = defaultdict(float)
        for move in moves:
            consumption[move.product_id.id] += move.product_qty
        return dict(consumption)

    def _apply_indirect_demand_dedup(self, results, pending_mo_raw_by_product):
        for product_id, values in results.items():
            indirect_qty = values.get("indirect_qty", 0.0)
            if indirect_qty <= 0:
                continue

            covered_qty = min(indirect_qty, pending_mo_raw_by_product.get(product_id, 0.0))
            if covered_qty <= 0:
                continue

            values["indirect_qty"] = max(0.0, indirect_qty - covered_qty)
            values["qty"] = values.get("direct_qty", 0.0) + values["indirect_qty"]

            order_values = list(values.get("orders", {}).values())
            total_order_indirect = sum(
                max(0.0, order_data.get("indirect_value", 0.0))
                for order_data in order_values
            )
            if total_order_indirect <= 0:
                continue

            remaining_to_reduce = covered_qty
            for order_data in order_values:
                current_indirect = max(0.0, order_data.get("indirect_value", 0.0))
                if current_indirect <= 0:
                    continue

                proportional_reduce = covered_qty * (current_indirect / total_order_indirect)
                reduce_qty = min(current_indirect, proportional_reduce)
                new_indirect = current_indirect - reduce_qty
                order_data["indirect_value"] = new_indirect
                order_data["final_value"] = max(
                    0.0, order_data.get("direct_value", 0.0) + new_indirect
                )
                remaining_to_reduce -= reduce_qty

            if remaining_to_reduce > 1e-6:
                sorted_orders = sorted(
                    order_values,
                    key=lambda row: row.get("indirect_value", 0.0),
                    reverse=True,
                )
                for order_data in sorted_orders:
                    if remaining_to_reduce <= 1e-6:
                        break
                    current_indirect = max(0.0, order_data.get("indirect_value", 0.0))
                    if current_indirect <= 0:
                        continue
                    reduce_qty = min(current_indirect, remaining_to_reduce)
                    new_indirect = current_indirect - reduce_qty
                    order_data["indirect_value"] = new_indirect
                    order_data["final_value"] = max(
                        0.0, order_data.get("direct_value", 0.0) + new_indirect
                    )
                    remaining_to_reduce -= reduce_qty

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

    def _explode_bom_component_demand(
            self, product, qty, bom_cache=None, traversal_path=None
    ):
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

    def _breakdown_incoming_quantities(
            self, incoming_qties, component_quantities, owner_id, to_date, from_date
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
                    "incoming_component_inbound_qty": 0,
                    "incoming_missing_qty": 0,
                    "incoming_non_mo_qty": 0,
                    "incoming_mo_scheduled_qty": 0,
                    "incoming_mo_feasible_qty": 0,
                    "incoming_mo_unfeasible_qty": 0,
                    "incoming_reliable_qty": 0,
                },
            )

            if incoming_qty == 0:
                continue

            product_moves = moves.filtered(lambda move: move.product_id == product)
            product_mos = product_moves.production_id
            result["incoming_mo_scheduled_qty"] = sum(
                product_mos.move_finished_ids.filtered(lambda move: move.product_id == product).mapped("product_qty")
            )
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
                    lambda line: line.product_id.is_storable
                              and not line.product_id.skip_when_computing_component_quantities
                )

                if not valid_bom_lines:
                    result["incoming_missing_qty"] += qty
                    continue

                # To avoid double counting for confirmed MOs (where components are already reserved),
                # we need to know how much of each component is reserved for THESE specific MOs.
                reserved_by_component = defaultdict(float)
                for mo in product_mos.filtered(lambda m: m.bom_id == bom):
                    for move in mo.move_raw_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                        # forecast_availability may be negative when components are missing,
                        # but feasibility capacity must not use negative reservation.
                        reserved_qty = getattr(move, "reserved_availability", 0.0) or 0.0
                        if not reserved_qty:
                            reserved_qty = getattr(move, "quantity", 0.0) or 0.0
                        reserved_by_component[move.product_id.id] += max(0.0, reserved_qty)

                onhand = min(
                    float_round(
                        (component_quantities.get(l.product_id.id, {}).get("free_qty", 0.0) + reserved_by_component.get(l.product_id.id, 0.0)) / l.product_qty,
                        precision_rounding=product.uom_id.rounding,
                    )
                    for l in valid_bom_lines
                )
                onhand = max(0.0, min(qty, onhand))

                inbound = min(
                    float_round(
                        component_quantities.get(l.product_id.id, {}).get("incoming_qty", 0.0) / l.product_qty,
                        precision_rounding=product.uom_id.rounding,
                    )
                    for l in valid_bom_lines
                )
                inbound = max(0.0, min(qty - onhand, inbound))
                missing = max(0.0, qty - onhand - inbound)

                result["incoming_onhand_qty"] += onhand
                result["incoming_inbound_qty"] += inbound
                result["incoming_component_inbound_qty"] += inbound
                result["incoming_missing_qty"] += missing
                result["incoming_mo_feasible_qty"] += onhand + inbound
                result["incoming_mo_unfeasible_qty"] += missing

            # Non MO moves
            if incoming_qty > 0:
                non_mo_qty = sum(
                    move.product_qty
                    for move in (product_moves - product_mos.move_finished_ids)
                )
                result["incoming_inbound_qty"] += non_mo_qty
                result["incoming_non_mo_qty"] += non_mo_qty

            result["incoming_reliable_qty"] = (
                result["incoming_non_mo_qty"] + result["incoming_mo_feasible_qty"]
            )

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
    unconfirmed_outgoing_direct_qty = fields.Float(
        "Unconfirmed Outgoing (Direct)", compute="_compute_quantities", compute_sudo=False
    )
    unconfirmed_outgoing_indirect_qty = fields.Float(
        "Unconfirmed Outgoing (Indirect)", compute="_compute_quantities", compute_sudo=False
    )

    virtual_available_ml = fields.Float(
        "Virtual Available ML", compute="_compute_quantities", compute_sudo=False
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
    forecast_validation_html = fields.Html(
        compute="_compute_forecast_validation_fields",
        readonly=True,
        sanitize=False,
        help="Validation report from the main product variant.",
    )
    forecast_validation_last_run = fields.Datetime(
        compute="_compute_forecast_validation_fields",
        readonly=True,
    )

    skip_when_computing_component_quantities = fields.Boolean(
        compute="_compute_skip_when_computing_component_quantities"
    )

    def _compute_skip_when_computing_component_quantities(self):
        for template in self:
            template.skip_when_computing_component_quantities = False

    def _compute_forecast_validation_fields(self):
        for template in self:
            variants = template.product_variant_ids.sudo()
            if not variants:
                template.forecast_validation_html = "<p><strong>Немає варіантів продукту.</strong></p>"
                template.forecast_validation_last_run = False
                continue
            if len(variants) == 1:
                variant = variants[0]
                template.forecast_validation_html = variant.forecast_validation_html or (
                    "<p><em>Для цього продукту доступний детальний звіт одного варіанта. "
                    "Натисніть кнопку перевірки.</em></p>"
                )
                template.forecast_validation_last_run = variant.forecast_validation_last_run
                continue

            rows = [
                "<div class='o_forecast_validation_report'>",
                f"<h3>Зведена перевірка по варіантах: {escape(template.display_name)}</h3>",
                "<p>Для повного розбору натисніть на конкретний варіант у таблиці.</p>",
                "<table class='table table-sm table-bordered'>",
                "<thead><tr>"
                "<th>Варіант</th><th>Статус</th><th>Expected</th><th>Actual</th><th>Delta</th><th>Last Run</th>"
                "</tr></thead><tbody>",
            ]

            latest_run = False
            for variant in variants:
                snapshot = variant._get_forecast_formula_snapshot()
                status = "PASS" if snapshot["formula_ok"] else "FAIL"
                status_color = "#198754" if snapshot["formula_ok"] else "#dc3545"
                last_run = variant.forecast_validation_last_run
                if last_run and (not latest_run or last_run > latest_run):
                    latest_run = last_run
                variant_link = f"/web#id={variant.id}&model=product.product&view_type=form"
                rows.append(
                    "<tr>"
                    f"<td><a href='{variant_link}'>{escape(variant.display_name)}</a></td>"
                    f"<td><span style='color:{status_color};'><strong>{status}</strong></span></td>"
                    f"<td>{snapshot['expected_virtual_real']:.2f}</td>"
                    f"<td>{snapshot['actual_virtual_real']:.2f}</td>"
                    f"<td>{snapshot['formula_delta']:.6f}</td>"
                    f"<td>{last_run or '-'}</td>"
                    "</tr>"
                )

            rows.append("</tbody></table></div>")
            template.forecast_validation_html = "".join(rows)
            template.forecast_validation_last_run = latest_run

    def action_validate_forecast_formula(self):
        self.ensure_one()
        variants = self.product_variant_ids.sudo()
        if not variants:
            return True
        for variant in variants:
            variant.action_validate_forecast_formula()
        return True

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
            template.unconfirmed_outgoing_direct_qty = t_res["unconfirmed_outgoing_direct_qty"]
            template.unconfirmed_outgoing_indirect_qty = t_res["unconfirmed_outgoing_indirect_qty"]
            template.virtual_available_ml = t_res["virtual_available_ml"]
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
                    "unconfirmed_outgoing_direct_qty",
                    "unconfirmed_outgoing_indirect_qty",
                    "virtual_available_ml",
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
            unconfirmed_outgoing_direct_qty = 0
            unconfirmed_outgoing_indirect_qty = 0
            virtual_available_ml = 0
            incoming_onhand_qty = 0
            incoming_inbound_qty = 0
            incoming_missing_qty = 0
            virtual_onhand_qty = 0
            virtual_available_real = 0
            for p in template.product_variant_ids._origin:
                unconfirmed_outgoing_qty += variants_available[p.id]["unconfirmed_outgoing_qty"]
                unconfirmed_outgoing_direct_qty += variants_available[p.id]["unconfirmed_outgoing_direct_qty"]
                unconfirmed_outgoing_indirect_qty += variants_available[p.id]["unconfirmed_outgoing_indirect_qty"]
                virtual_available_ml += variants_available[p.id]["virtual_available_ml"]
                incoming_onhand_qty += variants_available[p.id]["incoming_onhand_qty"]
                incoming_inbound_qty += variants_available[p.id]["incoming_inbound_qty"]
                incoming_missing_qty += variants_available[p.id]["incoming_missing_qty"]
                virtual_onhand_qty += variants_available[p.id]["virtual_onhand_qty"]
                virtual_available_real += variants_available[p.id]["virtual_available_real"]
            t_res = res[template.id]
            t_res["unconfirmed_outgoing_qty"] = unconfirmed_outgoing_qty
            t_res["unconfirmed_outgoing_direct_qty"] = unconfirmed_outgoing_direct_qty
            t_res["unconfirmed_outgoing_indirect_qty"] = unconfirmed_outgoing_indirect_qty
            t_res["virtual_available_ml"] = virtual_available_ml
            t_res["incoming_onhand_qty"] = incoming_onhand_qty
            t_res["incoming_inbound_qty"] = incoming_inbound_qty
            t_res["incoming_missing_qty"] = incoming_missing_qty
            t_res["virtual_onhand_qty"] = virtual_onhand_qty
            t_res["virtual_available_real"] = virtual_available_real
        return res
