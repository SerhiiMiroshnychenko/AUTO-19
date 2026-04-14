from odoo import api, fields, models


class StockMoveDemandTrace(models.Model):
    _inherit = "stock.move"

    ml_demand_wave_id = fields.Many2one("ml.demand.wave", index=True, copy=False)
    ml_demand_uid = fields.Char(index=True, copy=False)
    ml_demand_line_id = fields.Many2one("ml.demand.line", index=True, copy=False)
    ml_coverage_qty = fields.Float(default=0.0, copy=False)

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
        records._propagate_ml_trace_from_related_docs()
        records._recompute_linked_wave_coverages()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_ml_trace_propagation"):
            return res
        self._propagate_ml_trace_from_related_docs()
        self._recompute_linked_wave_coverages()
        return res

    def _propagate_ml_trace_from_related_docs(self):
        for move in self:
            if move.ml_demand_uid:
                continue

            linked_uid = False
            linked_wave_id = False
            if move.raw_material_production_id and move.raw_material_production_id.ml_demand_uid:
                linked_uid = move.raw_material_production_id.ml_demand_uid
                linked_wave_id = move.raw_material_production_id.ml_demand_wave_id.id
            elif move.production_id and move.production_id.ml_demand_uid:
                linked_uid = move.production_id.ml_demand_uid
                linked_wave_id = move.production_id.ml_demand_wave_id.id
            elif move.purchase_line_id and move.purchase_line_id.ml_demand_uid:
                linked_uid = move.purchase_line_id.ml_demand_uid
                linked_wave_id = move.purchase_line_id.ml_demand_wave_id.id

            if linked_uid:
                move.with_context(skip_ml_trace_propagation=True).write(
                    {
                        "ml_demand_uid": linked_uid,
                        "ml_demand_wave_id": linked_wave_id or False,
                    }
                )

    def _recompute_linked_wave_coverages(self):
        waves = self.env["ml.demand.wave"]
        for move in self:
            if move.ml_demand_wave_id:
                waves |= move.ml_demand_wave_id
            elif move.ml_demand_uid:
                waves |= self.env["ml.demand.wave"].search(
                    [("demand_uid", "=", move.ml_demand_uid)], limit=1
                )
        if waves:
            waves.recompute_coverages()
