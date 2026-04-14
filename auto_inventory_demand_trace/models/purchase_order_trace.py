from odoo import api, fields, models


class PurchaseOrderDemandTrace(models.Model):
    _inherit = "purchase.order"

    ml_demand_wave_id = fields.Many2one("ml.demand.wave", index=True, copy=False)
    ml_demand_uid = fields.Char(index=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        uid_from_context = self.env.context.get("ml_demand_uid")
        wave_id_from_context = self.env.context.get("ml_demand_wave_id")
        for vals in vals_list:
            if uid_from_context and not vals.get("ml_demand_uid"):
                vals["ml_demand_uid"] = uid_from_context
            if wave_id_from_context and not vals.get("ml_demand_wave_id"):
                vals["ml_demand_wave_id"] = wave_id_from_context
        records = super().create(vals_list)
        records._recompute_linked_wave_coverages()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._recompute_linked_wave_coverages()
        return res

    def _recompute_linked_wave_coverages(self):
        waves = self.env["ml.demand.wave"]
        for order in self:
            if order.ml_demand_wave_id:
                waves |= order.ml_demand_wave_id
            elif order.ml_demand_uid:
                waves |= self.env["ml.demand.wave"].search(
                    [("demand_uid", "=", order.ml_demand_uid)], limit=1
                )
        if waves:
            waves.recompute_coverages()


class PurchaseOrderLineDemandTrace(models.Model):
    _inherit = "purchase.order.line"

    ml_demand_wave_id = fields.Many2one("ml.demand.wave", index=True, copy=False)
    ml_demand_uid = fields.Char(index=True, copy=False)
    ml_demand_line_id = fields.Many2one("ml.demand.line", index=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        uid_from_context = self.env.context.get("ml_demand_uid")
        wave_id_from_context = self.env.context.get("ml_demand_wave_id")
        line_id_from_context = self.env.context.get("ml_demand_line_id")
        for vals in vals_list:
            if uid_from_context and not vals.get("ml_demand_uid"):
                vals["ml_demand_uid"] = uid_from_context
            if wave_id_from_context and not vals.get("ml_demand_wave_id"):
                vals["ml_demand_wave_id"] = wave_id_from_context
            if line_id_from_context and not vals.get("ml_demand_line_id"):
                vals["ml_demand_line_id"] = line_id_from_context
        records = super().create(vals_list)
        records._propagate_from_order()
        records._recompute_linked_wave_coverages()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_ml_trace_propagation"):
            return res
        self._propagate_from_order()
        self._recompute_linked_wave_coverages()
        return res

    def _propagate_from_order(self):
        for line in self:
            updates = {}
            if not line.ml_demand_uid and line.order_id.ml_demand_uid:
                updates["ml_demand_uid"] = line.order_id.ml_demand_uid
            if not line.ml_demand_wave_id and line.order_id.ml_demand_wave_id:
                updates["ml_demand_wave_id"] = line.order_id.ml_demand_wave_id.id
            if updates:
                line.with_context(skip_ml_trace_propagation=True).write(updates)

    def _recompute_linked_wave_coverages(self):
        waves = self.env["ml.demand.wave"]
        for line in self:
            if line.ml_demand_wave_id:
                waves |= line.ml_demand_wave_id
            elif line.ml_demand_uid:
                waves |= self.env["ml.demand.wave"].search(
                    [("demand_uid", "=", line.ml_demand_uid)], limit=1
                )
        if waves:
            waves.recompute_coverages()
