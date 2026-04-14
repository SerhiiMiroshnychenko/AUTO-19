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
            "unconfirmed_outgoing_direct_qty": 0.0,
            "unconfirmed_outgoing_indirect_qty": 0.0,
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

    def _build_formula_explanations(self, data):
        rows = [
            {
                "term": "On Hand",
                "source": "Default Odoo: product.qty_available",
                "meaning": "Поточний фізичний залишок на складі в межах активного контексту локації/складу.",
                "value": data.get("qty_available", 0.0),
            },
            {
                "term": "Scheduled Incoming",
                "source": "Default Odoo: product.incoming_qty",
                "meaning": "Усі заплановані вхідні переміщення, які стандартний forecast Odoo враховує як incoming.",
                "value": data.get("incoming_qty", 0.0),
            },
            {
                "term": "Outgoing",
                "source": "Default Odoo: product.outgoing_qty",
                "meaning": "Усі заплановані вихідні переміщення, які стандартний forecast Odoo враховує як outgoing.",
                "value": data.get("outgoing_qty", 0.0),
            },
            {
                "term": "Standard Forecast",
                "source": "Default Odoo: product.virtual_available",
                "meaning": "Стандартний прогноз Odoo: On Hand + Scheduled Incoming - Outgoing.",
                "value": data.get("standard_forecast_scheduled", 0.0),
            },
            {
                "term": "Non-MO Incoming",
                "source": "Custom module: _breakdown_incoming_quantities()",
                "meaning": "Частина incoming, що не походить із finished moves виробничих замовлень.",
                "value": data.get("incoming_non_mo_qty", 0.0),
            },
            {
                "term": "Scheduled MO Incoming",
                "source": "Default Odoo moves + custom aggregation of MO finished moves",
                "meaning": "Запланований вихід готової продукції за finished moves виробничих замовлень, незалежно від забезпеченості компонентами.",
                "value": data.get("incoming_mo_scheduled_qty", 0.0),
            },
            {
                "term": "Total Scheduled Incoming",
                "source": "Default Odoo + custom decomposition",
                "meaning": "Підсумок Scheduled Incoming як сума Non-MO Incoming та Scheduled MO Incoming.",
                "value": data.get("incoming_qty", 0.0),
            },
            {
                "term": "MO Feasible from On-Hand Components",
                "source": "Custom module: BOM feasibility breakdown",
                "meaning": "Частина MO incoming, яку можна виробити лише з поточних доступних компонентів (free_qty).",
                "value": data.get("incoming_onhand_qty", 0.0),
            },
            {
                "term": "MO Feasible from Inbound Components",
                "source": "Custom module: BOM feasibility breakdown",
                "meaning": "Додаткова частина MO incoming, яку можна виробити з очікуваних вхідних компонентів (incoming_qty компонентів).",
                "value": data.get("incoming_component_inbound_qty", 0.0),
            },
            {
                "term": "Total Feasible MO Incoming",
                "source": "Custom module: BOM feasibility breakdown",
                "meaning": "Сума feasible MO incoming з on-hand та inbound component capacity.",
                "value": data.get("feasibility_qty", 0.0),
            },
            {
                "term": "Unsupported MO Incoming",
                "source": "Custom module: BOM feasibility breakdown",
                "meaning": "Частина scheduled MO incoming, яка не підкріплена доступністю компонентів.",
                "value": data.get("incoming_mo_unfeasible_qty", 0.0),
            },
            {
                "term": "Missing Components",
                "source": "Custom module: BOM feasibility breakdown",
                "meaning": "Обсяг виробничого випуску, для якого зараз бракує компонентів.",
                "value": data.get("incoming_missing_qty", 0.0),
            },
            {
                "term": "Reliable Incoming",
                "source": "Custom module: Non-MO Incoming + feasible MO incoming",
                "meaning": "Надійне incoming для forecast: Non-MO Incoming + Total Feasible MO Incoming.",
                "value": data.get("incoming_reliable_qty", 0.0),
            },
            {
                "term": "Reliable Standard Forecast",
                "source": "Custom module: reliable stock forecast",
                "meaning": "Надійний прогноз: On Hand + Reliable Incoming - Outgoing.",
                "value": data.get("standard_forecast_reliable", 0.0),
            },
            {
                "term": "Scheduled-Reliable Gap",
                "source": "Custom module: comparison metric",
                "meaning": "Різниця між стандартним scheduled forecast Odoo та reliable forecast після перевірки feasibility.",
                "value": data.get("standard_forecast_gap", 0.0),
            },
            {
                "term": "Outgoing (Unconfirmed, ML)",
                "source": "Custom module: _get_products_qty_in_unconfirmed_quotations()",
                "meaning": "Прогнозований ML-обсяг відвантажень із непідтверджених комерційних пропозицій.",
                "value": data.get("unconfirmed_outgoing_qty", 0.0),
            },
            {
                "term": "Outgoing (Unconfirmed, ML Direct)",
                "source": "Custom module: direct match by sale.order.line.product_id",
                "meaning": "Прямий ML-попит: товар явно присутній у рядках непідтверджених комерційних пропозицій.",
                "value": data.get("unconfirmed_outgoing_direct_qty", 0.0),
            },
            {
                "term": "Outgoing (Unconfirmed, ML Indirect BOM)",
                "source": "Custom module: BOM explosion of quoted finished products",
                "meaning": "Похідний ML-попит на компоненти, отриманий із BoM-розкладу прогнозованого попиту на готові вироби.",
                "value": data.get("unconfirmed_outgoing_indirect_qty", 0.0),
            },
            {
                "term": "Reliable ML Forecast",
                "source": "Custom module: reliable forecast with ML adjustment",
                "meaning": "Фінальний надійний ML forecast: Reliable Standard Forecast - Outgoing (Unconfirmed, ML).",
                "value": data.get("virtual_available_ml_reliable", 0.0),
            },
            {
                "term": "Scheduled ML Forecast",
                "source": "Custom module: virtual_available_ml",
                "meaning": "ML forecast на базі стандартного scheduled Odoo forecast без feasibility correction.",
                "value": data.get("virtual_available_ml", 0.0),
            },
            {
                "term": "ML Forecast Gap",
                "source": "Custom module: comparison metric",
                "meaning": "Різниця між scheduled ML forecast та reliable ML forecast.",
                "value": data.get("ml_forecast_gap", 0.0),
            },
            {
                "term": "Odoo Replenishment Base Forecast",
                "source": "Custom report label over orderpoint standard_forecast",
                "meaning": "Базовий forecast для orderpoint replenishment logic перед додаванням quantity in progress.",
                "value": data.get("standard_forecast", 0.0),
            },
            {
                "term": "PO In Progress",
                "source": "Default Odoo purchase_stock logic mirrored in custom breakdown",
                "meaning": "Закупівлі в процесі, які входять у quantity in progress для replenishment.",
                "value": data.get("purchase_in_progress", 0.0),
            },
            {
                "term": "Draft MO In Progress",
                "source": "Custom replenishment breakdown",
                "meaning": "Виробничі замовлення у draft, які модуль додає до replenishment breakdown.",
                "value": data.get("mo_draft_in_progress", 0.0),
            },
            {
                "term": "Confirmed MO In Progress",
                "source": "Default Odoo mrp logic mirrored in custom breakdown",
                "meaning": "Підтверджені MO в межах replenishment horizon, які входять у quantity in progress.",
                "value": data.get("mo_confirmed_in_progress", 0.0),
            },
            {
                "term": "Kit In Progress",
                "source": "Default Odoo mrp phantom BOM logic mirrored in custom breakdown",
                "meaning": "Потенційне поповнення від kit/phantom BOM логіки, яке враховується в replenishment.",
                "value": data.get("kit_in_progress", 0.0),
            },
            {
                "term": "Enterprise In Progress",
                "source": "Odoo Enterprise-specific logic if available",
                "meaning": "Enterprise-специфічні коригування quantity in progress, якщо вони присутні у встановлених модулях.",
                "value": data.get("enterprise_in_progress", 0.0),
            },
            {
                "term": "Replenishment Forecast",
                "source": "Default Odoo replenishment concept mirrored in custom report",
                "meaning": "Прогноз для replenishment: Odoo Replenishment Base Forecast + total in progress.",
                "value": data.get("replenishment_forecast", 0.0),
            },
        ]
        return rows

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
        data["formula_explanations"] = self._build_formula_explanations(data)

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
        res["formula_explanations"] = self._build_formula_explanations(res)

        return res
