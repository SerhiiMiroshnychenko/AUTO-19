from odoo import models


class StockWarehouseOrderpointDemandTrace(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    def _procure_orderpoint_confirm(self, use_new_cursor=False, company_id=None, raise_user_error=True):
        warehouse_id = self[:1].warehouse_id.id if self else False
        wave = self.env["ml.demand.wave"].get_or_build_active_wave(warehouse_id=warehouse_id)
        ctx = dict(self.env.context)
        if wave:
            ctx["ml_demand_uid"] = wave.demand_uid
            ctx["ml_demand_wave_id"] = wave.id
        return super(
            StockWarehouseOrderpointDemandTrace,
            self.with_context(ctx),
        )._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor,
            company_id=company_id,
            raise_user_error=raise_user_error,
        )
