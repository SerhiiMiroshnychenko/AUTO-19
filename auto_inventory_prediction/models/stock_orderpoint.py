from odoo import models, fields, api
from collections import defaultdict
from odoo.tools import frozendict, float_compare, float_is_zero


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    def _compute_qty(self):
        """Override to use virtual_available_real instead of virtual_available.

        This ensures that unconfirmed outgoing quantities (weighted by ML
        prediction probability) and missing component quantities are taken
        into account when computing the forecasted quantity, which in turn
        drives automatic PO/MO creation via the standard Odoo replenishment
        scheduler.
        """
        orderpoints_contexts = defaultdict(lambda: self.env['stock.warehouse.orderpoint'])
        for orderpoint in self:
            if not orderpoint.product_id or not orderpoint.location_id:
                orderpoint.qty_on_hand = False
                orderpoint.qty_forecast = False
                continue
            orderpoint_context = orderpoint._get_product_context()
            product_context = frozendict({**orderpoint_context})
            orderpoints_contexts[product_context] |= orderpoint

        for orderpoint_context, orderpoints_by_context in orderpoints_contexts.items():
            # Try virtual_available_real first, fall back to virtual_available
            try:
                products_qty = {
                    p['id']: p for p in orderpoints_by_context.product_id.with_context(orderpoint_context).read(
                        ['qty_available', 'virtual_available_real'])
                }
            except Exception:
                products_qty = {
                    p['id']: p for p in orderpoints_by_context.product_id.with_context(orderpoint_context).read(
                        ['qty_available', 'virtual_available'])
                }

            products_qty_in_progress = orderpoints_by_context._quantity_in_progress()

            for orderpoint in orderpoints_by_context:
                product_data = products_qty[orderpoint.product_id.id]
                qty_in_progress = products_qty_in_progress[orderpoint.id]

                orderpoint.qty_on_hand = product_data['qty_available']

                if 'virtual_available_real' in product_data:
                    # virtual_available_real already accounts for all incomings,
                    # so do NOT add qty_in_progress to avoid double-counting
                    orderpoint.qty_forecast = product_data['virtual_available_real']
                else:
                    orderpoint.qty_forecast = product_data['virtual_available'] + qty_in_progress

    def _get_qty_to_order(self, force_visibility_days=False, qty_in_progress_by_orderpoint={}):
        """Override to use virtual_available_real for order quantity calculation.

        When qty_forecast < product_min_qty, the scheduler will create
        PO or MO depending on the product's supply route (Buy / Manufacture).
        """
        self.ensure_one()
        if not self.product_id or not self.location_id:
            return False

        visibility_days = self.visibility_days
        if force_visibility_days is not False:
            visibility_days = force_visibility_days

        qty_to_order = 0.0
        rounding = self.product_uom.rounding

        # Check main condition: forecast below minimum
        if float_compare(self.qty_forecast, self.product_min_qty, precision_rounding=rounding) < 0:
            product_context = self._get_product_context(visibility_days=visibility_days)
            qty_in_progress = qty_in_progress_by_orderpoint.get(self.id) or self._quantity_in_progress()[self.id]

            # Use virtual_available_real instead of virtual_available
            try:
                qty_forecast_with_visibility = \
                    self.product_id.with_context(product_context).read(['virtual_available_real'])[0][
                        'virtual_available_real']
                # Do NOT add qty_in_progress (avoids double-counting)
            except Exception:
                # Fallback to standard logic
                qty_forecast_with_visibility = \
                    self.product_id.with_context(product_context).read(['virtual_available'])[0][
                        'virtual_available'] + qty_in_progress

            qty_to_order = max(self.product_min_qty, self.product_max_qty) - qty_forecast_with_visibility

            # Handle qty_multiple
            remainder = (self.qty_multiple > 0.0 and qty_to_order % self.qty_multiple) or 0.0
            if (float_compare(remainder, 0.0, precision_rounding=rounding) > 0
                    and float_compare(self.qty_multiple - remainder, 0.0, precision_rounding=rounding) > 0):
                if float_is_zero(self.product_max_qty, precision_rounding=rounding):
                    qty_to_order += self.qty_multiple - remainder
                else:
                    qty_to_order -= remainder

        return qty_to_order

    def _procure_orderpoint_confirm(self, use_new_cursor=False, company_id=None, raise_user_error=True):
        """Override to pass auto-creation context with reason details.

        This context is consumed by mrp.production and purchase.order
        extensions to display creation information banners.
        """
        # Build per-orderpoint reasons
        orderpoint_reasons = {}
        for orderpoint in self:
            if orderpoint.product_id and orderpoint.qty_forecast < orderpoint.product_min_qty:
                target_date = orderpoint.lead_days_date.strftime(
                    "%d.%m.%Y") if orderpoint.lead_days_date else "найближчим часом"
                reason = f"Передбачена відсутність товару {orderpoint.product_id.name} на дату {target_date}"
                orderpoint_reasons[orderpoint.id] = reason

        # Add context to mark automatic creation
        context_with_auto_creation = dict(self.env.context)
        context_with_auto_creation.update({
            'smart_inventory_auto_creation': True,
            'orderpoint_reasons': orderpoint_reasons
        })

        return super(StockWarehouseOrderpoint,
                     self.with_context(context_with_auto_creation))._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor,
            company_id=company_id,
            raise_user_error=raise_user_error
        )
