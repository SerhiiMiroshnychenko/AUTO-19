from odoo import models, api


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

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
