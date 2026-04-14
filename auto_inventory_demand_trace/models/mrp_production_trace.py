from odoo import api, fields, models


class MrpProductionDemandTrace(models.Model):
    _inherit = "mrp.production"

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
        for record in self:
            if record.ml_demand_wave_id:
                waves |= record.ml_demand_wave_id
            elif record.ml_demand_uid:
                waves |= self.env["ml.demand.wave"].search(
                    [("demand_uid", "=", record.ml_demand_uid)], limit=1
                )
        if waves:
            waves.recompute_coverages()
