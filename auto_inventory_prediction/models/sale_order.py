import logging
from datetime import datetime
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SaleOrderExtension(models.Model):
    _inherit = 'sale.order'

    is_success_provided = fields.Boolean(
        string='Успішність передбачена?',
        default=False,
        help='Показує, чи було проведено передбачення успішності замовлення'
    )
    success_prediction = fields.Float(
        string='Ймовірність успішності',
        digits=(5, 2),
        help='Ймовірність успішності замовлення (у відсотках)'
    )
    last_prediction_date = fields.Datetime(
        string='Дата останнього передбачення',
        help='Дата та час останнього передбачення успішності замовлення'
    )
    prediction_log = fields.Text(
        string='Лог передбачень',
        help='Історія передбачень успішності цього замовлення'
    )
    features_importance = fields.Html(
        string='Важливість ознак',
        help='Таблиця з важливістю ознак для цього замовлення'
    )
    success_prediction_display = fields.Html(
        string='Прогноз успішності',
        help='Візуальне відображення ймовірності успішності замовлення',
        compute='_compute_success_prediction_display',
        store=True
    )

    @api.depends('state', 'success_prediction')
    def _compute_success_prediction_display(self):
        """Compute success prediction display based on state and probability"""
        for record in self:
            record.success_prediction_display = record._generate_success_prediction_display(record.success_prediction)

    @api.model_create_multi
    def create(self, vals_list):
        """Extend create to auto-predict order success"""
        records = super(SaleOrderExtension, self).create(vals_list)

        for record in records:
            try:
                record._predict_order_success()
            except Exception as e:
                _logger.error(f"Помилка при спробі передбачення успішності замовлення {record.name}: {str(e)}")

        return records

    def write(self, vals):
        """Extend write to track important field changes"""
        result = super(SaleOrderExtension, self).write(vals)

        # Fields whose change triggers re-prediction
        trigger_fields = [
            'partner_id', 'amount_total', 'user_id', 'state'
        ]

        if any(field in vals for field in trigger_fields):
            for record in self:
                try:
                    record._predict_order_success()
                except Exception as e:
                    _logger.error(
                        f"Помилка при спробі передбачення успішності замовлення {record.name} після змін: {str(e)}")

        return result

    def _predict_order_success(self):
        """Get order success prediction from ML model using SQL query"""
        self.ensure_one()

        # Recursion guard
        if self.env.context.get('skip_prediction'):
            return None

        # Get active (production) model
        prediction_model = self.env['inventory.prediction.model'].search([('is_production', '=', True)], limit=1)

        if not prediction_model:
            _logger.warning("Не знайдено активної моделі прогнозування для використання")
            return False

        try:
            prefix_number = 1

            # SQL query analogous to order_data_collector but filtered for current order
            query = """
                WITH order_data AS (
                    SELECT 
                        so.id as order_id,
                        so.name as order_name,
                        so.create_date as create_date,
                        so.partner_id,
                        so.state,
                        so.amount_total as order_amount,
                        CASE WHEN so.state = 'sale' THEN 1 ELSE 0 END as is_successful,
                        (
                            SELECT COUNT(DISTINCT m.id)
                            FROM mail_message m 
                            WHERE m.res_id = so.id AND m.model = 'sale.order'
                        ) as order_messages,
                        (
                            SELECT COUNT(DISTINCT CASE 
                                WHEN EXISTS (
                                    SELECT 1 FROM mail_tracking_value mtv 
                                    WHERE mtv.mail_message_id = m.id
                                ) THEN m.id 
                            END)
                            FROM mail_message m
                            WHERE m.res_id = so.id AND m.model = 'sale.order'
                        ) as order_changes,
                        (
                            SELECT COALESCE(
                                CAST(COUNT(CASE WHEN s2.state = 'sale' THEN 1 END) AS DECIMAL(10,2)) /
                                NULLIF(COUNT(*), 0),
                                0
                            )
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_success_rate,
                        (
                            SELECT COUNT(*)
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_total_orders,
                        (
                            SELECT 
                                EXTRACT(DAY FROM (so.create_date - MIN(s2.create_date)))::INTEGER
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_order_age_days,
                        (
                            SELECT COALESCE(AVG(s2.amount_total), 0)
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_avg_amount,
                        (
                            SELECT COALESCE(AVG(s2.amount_total), 0)
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                            AND s2.state = 'sale'
                        ) as partner_success_avg_amount,
                        (
                            SELECT COALESCE(AVG(s2.amount_total), 0)
                            FROM sale_order s2
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                            AND s2.state != 'sale'
                        ) as partner_fail_avg_amount,
                        (
                            SELECT COUNT(DISTINCT m.id)
                            FROM sale_order s2
                            LEFT JOIN mail_message m ON m.res_id = s2.id AND m.model = 'sale.order'
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_total_messages,
                        (
                            SELECT COALESCE(AVG(message_count), 0)
                            FROM (
                                SELECT s2.id, COUNT(DISTINCT m.id) as message_count
                                FROM sale_order s2
                                LEFT JOIN mail_message m ON m.res_id = s2.id AND m.model = 'sale.order'
                                WHERE s2.partner_id = so.partner_id
                                AND s2.create_date < so.create_date
                                AND s2.state = 'sale'
                                GROUP BY s2.id
                            ) as t
                        ) as partner_success_avg_messages,
                        (
                            SELECT COALESCE(AVG(message_count), 0)
                            FROM (
                                SELECT s2.id, COUNT(DISTINCT m.id) as message_count
                                FROM sale_order s2
                                LEFT JOIN mail_message m ON m.res_id = s2.id AND m.model = 'sale.order'
                                WHERE s2.partner_id = so.partner_id
                                AND s2.create_date < so.create_date
                                AND s2.state != 'sale'
                                GROUP BY s2.id
                            ) as t
                        ) as partner_fail_avg_messages,
                        (
                            SELECT COALESCE(
                                CAST(COUNT(DISTINCT CASE 
                                    WHEN EXISTS (
                                        SELECT 1 FROM mail_tracking_value mtv 
                                        WHERE mtv.mail_message_id = m2.id
                                    ) THEN m2.id 
                                END) AS DECIMAL(10,2)) /
                                NULLIF(COUNT(DISTINCT s2.id), 0),
                                0
                            )
                            FROM sale_order s2
                            LEFT JOIN mail_message m2 ON m2.res_id = s2.id AND m2.model = 'sale.order'
                            WHERE s2.partner_id = so.partner_id
                            AND s2.create_date < so.create_date
                        ) as partner_avg_changes,
                        (
                            SELECT COALESCE(AVG(change_count), 0)
                            FROM (
                                SELECT s2.id,
                                COUNT(DISTINCT CASE 
                                    WHEN EXISTS (
                                        SELECT 1 FROM mail_tracking_value mtv 
                                        WHERE mtv.mail_message_id = m2.id
                                    ) THEN m2.id 
                                END) as change_count
                                FROM sale_order s2
                                LEFT JOIN mail_message m2 ON m2.res_id = s2.id AND m2.model = 'sale.order'
                                WHERE s2.partner_id = so.partner_id
                                AND s2.create_date < so.create_date
                                AND s2.state = 'sale'
                                GROUP BY s2.id
                            ) as t
                        ) as partner_success_avg_changes,
                        (
                            SELECT COALESCE(AVG(change_count), 0)
                            FROM (
                                SELECT s2.id,
                                COUNT(DISTINCT CASE 
                                    WHEN EXISTS (
                                        SELECT 1 FROM mail_tracking_value mtv 
                                        WHERE mtv.mail_message_id = m2.id
                                    ) THEN m2.id 
                                END) as change_count
                                FROM sale_order s2
                                LEFT JOIN mail_message m2 ON m2.res_id = s2.id AND m2.model = 'sale.order'
                                WHERE s2.partner_id = so.partner_id
                                AND s2.create_date < so.create_date
                                AND s2.state != 'sale'
                                GROUP BY s2.id
                            ) as t
                        ) as partner_fail_avg_changes
                    FROM sale_order so
                    WHERE so.id = %s
                )
                SELECT
                    %s * 1000000 + order_id as order_id_with_prefix,
                    order_name,
                    is_successful,
                    create_date,
                    %s * 1000000 + partner_id as partner_id_with_prefix,
                    order_amount,
                    order_messages,
                    order_changes,
                    COALESCE(partner_success_rate * 100, 0) as partner_success_rate,
                    COALESCE(partner_total_orders, 0) as partner_total_orders,
                    COALESCE(partner_order_age_days, 0) as partner_order_age_days,
                    COALESCE(partner_avg_amount, 0) as partner_avg_amount,
                    COALESCE(partner_success_avg_amount, 0) as partner_success_avg_amount,
                    COALESCE(partner_fail_avg_amount, 0) as partner_fail_avg_amount,
                    COALESCE(partner_total_messages, 0) as partner_total_messages,
                    COALESCE(partner_success_avg_messages, 0) as partner_success_avg_messages,
                    COALESCE(partner_fail_avg_messages, 0) as partner_fail_avg_messages,
                    COALESCE(partner_avg_changes, 0) as partner_avg_changes,
                    COALESCE(partner_success_avg_changes, 0) as partner_success_avg_changes,
                    COALESCE(partner_fail_avg_changes, 0) as partner_fail_avg_changes
                FROM order_data
            """

            # Execute query for current order
            self.env.cr.execute(query, (self.id, prefix_number, prefix_number))
            result = self.env.cr.fetchone()

            if not result:
                _logger.warning(f"Не вдалося отримати дані для замовлення {self.id}")
                return False

            # Prepare data for prediction
            column_names = [
                'order_id', 'order_name', 'is_successful', 'create_date', 'partner_id',
                'order_amount', 'order_messages', 'order_changes',
                'partner_success_rate', 'partner_total_orders', 'partner_order_age_days',
                'partner_avg_amount', 'partner_success_avg_amount', 'partner_fail_avg_amount',
                'partner_total_messages', 'partner_success_avg_messages', 'partner_fail_avg_messages',
                'partner_avg_changes', 'partner_success_avg_changes', 'partner_fail_avg_changes'
            ]

            order_data = dict(zip(column_names, result))
            print(f"{order_data = }")
            client = self.partner_id
            print(f"{client = }")
            client.update({
                'local_partner_success_rate': order_data['partner_success_rate'],
                'local_partner_total_orders': order_data['partner_total_orders'],
                'local_partner_order_age_days': order_data['partner_order_age_days'],
                'local_partner_avg_amount': order_data['partner_avg_amount'],
                'local_partner_success_avg_amount': order_data['partner_success_avg_amount'],
                'local_partner_fail_avg_amount': order_data['partner_fail_avg_amount'],
                'local_partner_total_messages': order_data['partner_total_messages'],
                'local_partner_success_avg_messages': order_data['partner_success_avg_messages'],
                'local_partner_fail_avg_messages': order_data['partner_fail_avg_messages'],
                'local_partner_avg_changes': order_data['partner_avg_changes'],
                'local_partner_success_avg_changes': order_data['partner_success_avg_changes'],
                'local_partner_fail_avg_changes': order_data['partner_fail_avg_changes']
            })

            # Get prediction from model
            prediction_result = prediction_model.predict_order_success(order_data)
            print(f"{prediction_result = }")

            if prediction_result and 'success_probability' in prediction_result:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                prediction_log = self.prediction_log or ""
                probability_percent = round(prediction_result.get('success_probability', 0) * 100, 2)
                new_log_entry = f"{now}: Передбачення успішності: {probability_percent}%\n"
                updated_log = new_log_entry + prediction_log

                # Generate HTML table with feature importance
                features_html = self._generate_features_importance_html(
                    prediction_result.get('feature_importance', [])
                )

                # Update record fields
                self.write({
                    'is_success_provided': True,
                    'success_prediction': probability_percent,
                    'last_prediction_date': fields.Datetime.now(),
                    'prediction_log': updated_log,
                    'features_importance': features_html
                })

                # Post chatter message
                message = f"<b>Передбачення успішності замовлення:</b><br/>"
                message += f"Ймовірність успішного завершення: <b>{probability_percent}%</b><br/>"

                if 'top_features' in prediction_result and prediction_result['top_features']:
                    message += f"Ознаки, що мали найбільший вплив: {', '.join(prediction_result.get('top_features', []))}"

                self.with_context(skip_prediction=True).message_post(
                    body=message,
                    subtype_id=self.env.ref('mail.mt_note').id,
                    message_type='comment',
                    body_is_html=True
                )

                return True

            return False

        except Exception as e:
            _logger.error(f"Помилка при передбаченні успішності замовлення {self.id}: {str(e)}")
            return False

    @staticmethod
    def _generate_features_importance_html(feature_importance_list):
        """Generate HTML table with feature importance"""
        if not feature_importance_list:
            return "<p>Дані про важливість ознак недоступні</p>"

        # Feature name translations
        feature_translations = {
            'order_amount': 'Сума замовлення',
            'partner_avg_amount': 'Середня сума замовлень клієнта',
            'partner_success_avg_amount': 'Середня сума успішних замовлень',
            'partner_fail_avg_amount': 'Середня сума неуспішних замовлень',
            'partner_success_rate': 'Рейтинг успішності клієнта',
            'partner_total_orders': 'Загальна кількість замовлень клієнта',
            'partner_order_age_days': 'Термін співпраці з клієнтом (днів)',
            'partner_total_messages': 'Загальна кількість повідомлень клієнта',
            'partner_success_avg_messages': 'Середня кількість повідомлень в успішних замовленнях',
            'partner_fail_avg_messages': 'Середня кількість повідомлень в неуспішних замовленнях',
            'partner_avg_changes': 'Середня кількість змін в замовленнях клієнта',
            'partner_success_avg_changes': 'Середня кількість змін в успішних замовленнях',
            'partner_fail_avg_changes': 'Середня кількість змін в неуспішних замовленнях',
            'order_messages': 'Кількість повідомлень в замовленні',
            'order_changes': 'Кількість змін в замовленні',
            'amount_success_fail_diff': 'Різниця між середніми сумами (успішні - неуспішні)',
            'messages_success_fail_diff': 'Різниця повідомлень (успішні - неуспішні)',
            'changes_success_fail_diff': 'Різниця змін (успішні - неуспішні)',
            'order_amount_to_avg_ratio': 'Відношення суми замовлення до середньої суми клієнта'
        }

        html = """
        <div style="margin: 10px 0;">
            <h4 style="color: #875A7B; margin-bottom: 10px;">Важливість ознак для прогнозування</h4>
            <table class="table table-striped" style="width: 100%; border-collapse: collapse;">
                <thead style="background-color: #f8f9fa;">
                    <tr>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left;">Рейтинг</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left;">Ознака</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: right;">Важливість</th>
                        <th style="padding: 8px; border: 1px solid #dee2e6; text-align: center;">Важливість (%)</th>
                    </tr>
                </thead>
                <tbody>
        """

        # Sort features by importance
        if feature_importance_list and isinstance(feature_importance_list[0], tuple):
            sorted_features = sorted(feature_importance_list, key=lambda x: x[1], reverse=True)
        else:
            sorted_features = [(feature, 0.0) for feature in feature_importance_list]

        max_importance = max([importance for _, importance in sorted_features]) if sorted_features else 1.0

        for rank, (feature_name, importance) in enumerate(sorted_features, 1):
            translated_name = feature_translations.get(feature_name, feature_name)
            importance_percent = (importance / max_importance * 100) if max_importance > 0 else 0

            if importance_percent >= 80:
                color_class = "text-success"
                bg_color = "#d4edda"
            elif importance_percent >= 50:
                color_class = "text-warning"
                bg_color = "#fff3cd"
            else:
                color_class = "text-muted"
                bg_color = "#f8f9fa"

            bar_color = '#28a745' if importance_percent >= 80 else '#ffc107' if importance_percent >= 50 else '#6c757d'

            html += f"""
                    <tr style="background-color: {bg_color};">
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: center; font-weight: bold;">{rank}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6;">{translated_name}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: right;" class="{color_class}">{importance:.4f}</td>
                        <td style="padding: 8px; border: 1px solid #dee2e6; text-align: center;" class="{color_class}">
                            <div style="display: flex; align-items: center;">
                                <span style="margin-right: 5px;">{importance_percent:.1f}%</span>
                                <div style="background-color: #e9ecef; height: 10px; width: 60px; border-radius: 5px; overflow: hidden;">
                                    <div style="background-color: {bar_color}; height: 100%; width: {importance_percent}%; transition: width 0.3s ease;"></div>
                                </div>
                            </div>
                        </td>
                    </tr>
            """

        html += """
                </tbody>
            </table>
            <p style="margin-top: 10px; font-size: 0.9em; color: #6c757d;">
                <i>Важливість показує, наскільки кожна ознака впливає на прогнозування успішності замовлення.</i>
            </p>
        </div>
        """

        return html

    def _generate_success_prediction_display(self, success_probability):
        """Generate rich HTML display of success probability or order status"""
        if self.state == 'sale':
            return self._generate_status_display("ЗАМОВЛЕННЯ ПОГОДЖЕНО", "#28a745", "#d4edda", "#c3e6cb", "✓")
        elif self.state == 'cancel':
            return self._generate_status_display("ЗАМОВЛЕННЯ ВІДХИЛЕНО", "#dc3545", "#f8d7da", "#f5c6cb", "✗")

        if success_probability is None or success_probability == 0:
            return ""

        if success_probability >= 75:
            color = "#28a745"
            bg_color = "#d4edda"
            border_color = "#c3e6cb"
            status_text = "ВИСОКА"
            icon = "✓"
        elif success_probability >= 50:
            color = "#ffc107"
            bg_color = "#fff3cd"
            border_color = "#ffeaa7"
            status_text = "СЕРЕДНЯ"
            icon = "⚠"
        elif success_probability >= 30:
            color = "#fd7e14"
            bg_color = "#ffeaa7"
            border_color = "#fdcb6e"
            status_text = "НИЗЬКА"
            icon = "⚡"
        else:
            color = "#dc3545"
            bg_color = "#f8d7da"
            border_color = "#f5c6cb"
            status_text = "ДУЖЕ НИЗЬКА"
            icon = "✗"

        html = f"""
        <div style="
            background: linear-gradient(135deg, {bg_color} 0%, #ffffff 100%);
            border: 2px solid {border_color};
            border-radius: 12px;
            padding: 12px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            margin: 0;
            width: 12vw;
            max-width: 200px;
            max-height: 220px;
            min-width: 100px;
            min-height: 110px;
            position: relative;
            overflow: hidden;
        ">
            <div style="
                font-size: 10px;
                font-weight: bold;
                color: #495057;
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 1px;
            ">
                {icon} ПРОГНОЗ УСПІШНОСТІ
            </div>
            <div style="
                font-size: 36px;
                font-weight: bold;
                color: {color};
                margin: 8px 0;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
            ">
                {success_probability:.1f}%
            </div>
            <div style="
                font-size: 12px;
                font-weight: bold;
                color: {color};
                background-color: rgba(255,255,255,0.8);
                padding: 4px 8px;
                border-radius: 20px;
                display: inline-block;
                margin-bottom: 10px;
                border: 1px solid {color};
            ">
                {status_text} ВІРОГІДНІСТЬ
            </div>
            <div style="
                background-color: #e9ecef;
                height: 8px;
                border-radius: 4px;
                overflow: hidden;
                margin: 8px 0;
                box-shadow: inset 0 1px 2px rgba(0,0,0,0.1);
            ">
                <div style="
                    background: linear-gradient(90deg, {color} 0%, {color}aa 100%);
                    height: 100%;
                    width: {success_probability}%;
                    transition: width 0.5s ease-in-out;
                    border-radius: 4px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
                "></div>
            </div>
            <div style="
                display: flex;
                justify-content: space-between;
                font-size: 10px;
                color: #6c757d;
                margin-top: 4px;
            ">
                <span>0%</span>
                <span>25%</span>
                <span>50%</span>
                <span>75%</span>
                <span>100%</span>
            </div>
            <div style="
                position: absolute;
                top: -20px;
                right: -20px;
                width: 60px;
                height: 60px;
                background: radial-gradient(circle, {color}22 0%, transparent 70%);
                border-radius: 50%;
            "></div>
        </div>
        """

        return html

    @staticmethod
    def _generate_status_display(status_text, color, bg_color, border_color, icon):
        """Generate HTML display for order status"""
        html = f"""
        <div style="
            background: linear-gradient(135deg, {bg_color} 0%, #ffffff 100%);
            border: 2px solid {border_color};
            border-radius: 12px;
            padding: 12px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            margin: 0;
            width: 12vw;
            max-width: 200px;
            max-height: 210px;
            min-width: 100px;
            min-height: 110px;
            position: relative;
            overflow: hidden;
        ">
            <div style="
                font-size: 14px;
                font-weight: bold;
                color: #495057;
                margin-bottom: 8px;
                text-transform: uppercase;
                letter-spacing: 1px;
            ">
                {icon} СТАТУС ЗАМОВЛЕННЯ
            </div>
            <div style="
                font-size: 20px;
                font-weight: bold;
                color: {color};
                margin: 15px 0;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
            ">
                {status_text}
            </div>
            <div style="
                position: absolute;
                top: -20px;
                right: -20px;
                width: 60px;
                height: 60px;
                background: radial-gradient(circle, {color}22 0%, transparent 70%);
                border-radius: 50%;
            "></div>
        </div>
        """
        return html


# Track mail messages that may affect prediction
class MailMessageExtension(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        """Track new messages for sale orders to re-predict"""
        records = super(MailMessageExtension, self).create(vals_list)

        if self.env.context.get('skip_prediction'):
            return records

        # Collect messages related to sale.order
        order_messages = records.filtered(lambda m: m.model == 'sale.order' and m.res_id)

        # Group messages by order
        order_dict = {}
        for message in order_messages:
            if message.res_id not in order_dict:
                order_dict[message.res_id] = []
            order_dict[message.res_id].append(message)

        # Re-calculate prediction for each order with new messages
        for order_id, messages in order_dict.items():
            order = self.env['sale.order'].browse(order_id)
            if order.exists():
                try:
                    order._predict_order_success()
                    print('+++ ЗМІНИ ВІДБУЛИСЯ +++')
                except Exception as e:
                    _logger.error(f"Помилка при оновленні прогнозу після додавання повідомлення: {str(e)}")

        return records
