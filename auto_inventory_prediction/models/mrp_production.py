import logging
from datetime import datetime
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class MrpProductionExtension(models.Model):
    _inherit = 'mrp.production'

    creation_information = fields.Html(
        string='Інформація про створення',
        help='Банер з інформацією про те, хто і коли створив цей MO або чи був він створений автоматично'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Extend create to auto-fill creation information"""
        records = super(MrpProductionExtension, self).create(vals_list)

        for record in records:
            try:
                record._set_creation_information()
            except Exception as e:
                _logger.error(f"Помилка при заповненні інформації про створення MO {record.name}: {str(e)}")

        return records

    def _set_creation_information(self):
        """Fill creation information for Manufacturing Order"""
        self.ensure_one()

        # Check if auto-created via auto_inventory_prediction
        is_auto_created = (
                self.env.context.get('smart_inventory_auto_creation') or
                (self.orderpoint_id and self.orderpoint_id.trigger == 'auto')
        )

        if is_auto_created:
            # Get specific reason for this orderpoint
            orderpoint_reasons = self.env.context.get('orderpoint_reasons', {})
            if self.orderpoint_id and self.orderpoint_id.id in orderpoint_reasons:
                reason = orderpoint_reasons[self.orderpoint_id.id]
            else:
                # Fallback reason
                product_name = self.product_id.name if self.product_id else "продукту"
                reason = f"Передбачена відсутність товару {product_name} найближчим часом"
            creation_html = self._generate_auto_creation_banner(reason)
        else:
            # Manually created by user
            user = self.env.user
            creation_date = datetime.now()
            creation_html = self._generate_manual_creation_banner(user, creation_date)

        self.creation_information = creation_html

    def _generate_auto_creation_banner(self, reason):
        """Generate HTML banner for auto-created MO"""
        html = f"""
        <div style="
            background: linear-gradient(135deg, #e3f2fd 0%, #ffffff 100%);
            border: 2px solid #2196f3;
            border-radius: 8px;
            padding: 10px 14px;
            margin: 6px 0;
            box-shadow: 0 2px 6px rgba(33, 150, 243, 0.2);
        ">
            <div style="display: flex; align-items: flex-start;">
                <div style="
                    background-color: #2196f3;
                    color: white;
                    border-radius: 50%;
                    width: 22px;
                    height: 22px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-right: 10px;
                    font-size: 11px;
                    margin-top: 1px;
                ">🤖</div>
                <div style="flex: 1;">
                    <div style="
                        font-size: 13px;
                        font-weight: bold;
                        color: #1976d2;
                        margin-bottom: 5px;
                    ">
                        АВТОМАТИЧНО СТВОРЕНО
                    </div>
                    <div style="
                        font-size: 12px;
                        color: #424242;
                        line-height: 1.4;
                    ">
                        <div><strong>Причина:</strong></div>
                        <div>{reason}</div>
                    </div>
                </div>
            </div>
        </div>
        """
        return html

    def _generate_manual_creation_banner(self, user, creation_date):
        """Generate HTML banner for manually created MO"""
        formatted_date = creation_date.strftime("%d.%m.%Y о %H:%M")

        html = f"""
        <div style="
            background: linear-gradient(135deg, #f3e5f5 0%, #ffffff 100%);
            border: 2px solid #9c27b0;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            box-shadow: 0 2px 8px rgba(156, 39, 176, 0.2);
        ">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <div style="
                    background-color: #9c27b0;
                    color: white;
                    border-radius: 50%;
                    width: 24px;
                    height: 24px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-right: 8px;
                    font-size: 12px;
                    font-weight: bold;
                ">👤</div>
                <div style="
                    font-size: 14px;
                    font-weight: bold;
                    color: #7b1fa2;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                ">
                    СТВОРЕНО ВРУЧНУ
                </div>
            </div>
            <div style="
                font-size: 13px;
                color: #424242;
                line-height: 1.4;
                margin-left: 32px;
            ">
                <strong>Користувач:</strong> {user.name}
            </div>
        </div>
        """
        return html
