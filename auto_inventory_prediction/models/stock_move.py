from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _update_orderpoints(self):
        """Override to prevent AssertionError when qty_to_order_computed is store=False.
        
        Odoo 19's add_to_compute requires fields to be stored. By skipping the 
        call for non-stored fields, we avoid the error while keeping 
        orderpoints calculation dynamic and lock-free.
        """
        orderpoint_field = self.env['stock.warehouse.orderpoint']._fields.get('qty_to_order_computed')
        if orderpoint_field and not orderpoint_field.store:
            # Skip the standard recomputation logic because it assumes the field is stored
            return
        
        return super()._update_orderpoints()
