from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _update_orderpoints(self):
        """Override to prevent AssertionError when qty_to_order_computed is store=False.
        
        Odoo 19's add_to_compute requires fields to be stored. By skipping the 
        call for non-stored fields, we avoid the error while keeping 
        orderpoints calculation dynamic and lock-free.
        """
        print(
            f"[AIP DEBUG][stock.move._update_orderpoints] start move_ids={self.ids} count={len(self)} "
            f"context_keys={sorted(self.env.context.keys())}"
        )
        if self.env.context.get('from_orderpoint') or self.env.context.get('smart_inventory_auto_creation'):
            print(
                f"[AIP DEBUG][stock.move._update_orderpoints] skip_procurement_context move_ids={self.ids} "
                f"from_orderpoint={self.env.context.get('from_orderpoint')} "
                f"smart_inventory_auto_creation={self.env.context.get('smart_inventory_auto_creation')}"
            )
            return
        orderpoint_field = self.env['stock.warehouse.orderpoint']._fields.get('qty_to_order_computed')
        if orderpoint_field and not orderpoint_field.store:
            # Skip the standard recomputation logic because it assumes the field is stored
            print(
                f"[AIP DEBUG][stock.move._update_orderpoints] skip_non_stored move_ids={self.ids} "
                f"field_store={orderpoint_field.store}"
            )
            return
        
        print(f"[AIP DEBUG][stock.move._update_orderpoints] before_super move_ids={self.ids}")
        return super()._update_orderpoints()
