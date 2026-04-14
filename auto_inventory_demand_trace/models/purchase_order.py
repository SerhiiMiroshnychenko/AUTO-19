import logging
from datetime import datetime
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class PurchaseOrderExtension(models.Model):
    _inherit = 'purchase.order'

    creation_information = fields.Html(
        string='Інформація про створення',
        help='Банер з інформацією про те, хто і коли створив цей PO або чи був він створений автоматично'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Extend create to auto-fill creation information"""
        print(
            f"[AIP DEBUG][purchase.order.create] start vals_count={len(vals_list)} "
            f"context_keys={sorted(self.env.context.keys())}"
        )
        for vals_index, vals in enumerate(vals_list):
            print(
                f"[AIP DEBUG][purchase.order.create] vals[{vals_index}] "
                f"partner_id={vals.get('partner_id')} origin={vals.get('origin')} "
                f"date_order={vals.get('date_order')} picking_type_id={vals.get('picking_type_id')} "
                f"company_id={vals.get('company_id')}"
            )
        records = super(PurchaseOrderExtension, self).create(vals_list)
        print(
            f"[AIP DEBUG][purchase.order.create] created_ids={records.ids} "
            f"names={records.mapped('name')}"
        )

        for record in records:
            try:
                print(
                    f"[AIP DEBUG][purchase.order.create] record id={record.id} name={record.name} "
                    f"origin={record.origin} partner_id={record.partner_id.id if record.partner_id else False} "
                    f"order_line_count={len(record.order_line)}"
                )
                record._set_creation_information()
            except Exception as e:
                _logger.error(f"Помилка при заповненні інформації про створення PO {record.name}: {str(e)}")

        return records

    def _set_creation_information(self):
        """Fill creation information for Purchase Order"""
        self.ensure_one()

        # Check if auto-created via auto_inventory_prediction
        is_auto_created = (
                self.env.context.get('smart_inventory_auto_creation') or
                any(line.move_ids.filtered(lambda m: m.orderpoint_id and m.orderpoint_id.trigger == 'auto') for line in
                    self.order_line)
        )

        if is_auto_created:
            # Get specific reason for this PO
            orderpoint_reasons = self.env.context.get('orderpoint_reasons', {})
            reason = None

            # Find orderpoint via stock.move
            for line in self.order_line:
                for move in line.move_ids:
                    if move.orderpoint_id and move.orderpoint_id.id in orderpoint_reasons:
                        reason = orderpoint_reasons[move.orderpoint_id.id]
                        break
                if reason:
                    break

            # Fallback reason if specific not found
            if not reason:
                first_product = self.order_line[0].product_id.name if self.order_line else "продукту"
                reason = f"Передбачена відсутність товару {first_product} найближчим часом"

            creation_html = self._generate_auto_creation_banner(reason)
        else:
            # Manually created by user
            user = self.env.user
            creation_date = datetime.now()
            creation_html = self._generate_manual_creation_banner(user, creation_date)

        self.creation_information = creation_html

    @staticmethod
    def _generate_auto_creation_banner(reason):
        """Generate HTML banner for auto-created PO"""
        html = f"""
        <div style="
            background: linear-gradient(135deg, #e8f5e8 0%, #ffffff 100%);
            border: 2px solid #4caf50;
            border-radius: 8px;
            padding: 10px 14px;
            margin: 6px 0;
            box-shadow: 0 2px 6px rgba(76, 175, 80, 0.2);
        ">
            <div style="display: flex; align-items: flex-start;">
                <div style="
                    background-color: #4caf50;
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
                        color: #388e3c;
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

    @staticmethod
    def _generate_manual_creation_banner(user, creation_date):
        """Generate HTML banner for manually created PO"""
        formatted_date = creation_date.strftime("%d.%m.%Y о %H:%M")

        html = f"""
        <div style="
            background: linear-gradient(135deg, #fff3e0 0%, #ffffff 100%);
            border: 2px solid #ff9800;
            border-radius: 8px;
            padding: 12px;
            margin: 8px 0;
            box-shadow: 0 2px 8px rgba(255, 152, 0, 0.2);
            max-width: 260px;
            float: right;
            clear: both;
        ">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <div style="
                    background-color: #ff9800;
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
                    color: #f57c00;
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
