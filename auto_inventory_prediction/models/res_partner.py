import io
import base64
import pandas as pd
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class Partner(models.Model):
    _inherit = "res.partner"

    extended_id = fields.Integer('Extended ID')
    extended_partner_success_rate = fields.Float('Success Rate')
    extended_partner_total_orders = fields.Integer('Total Orders')
    extended_partner_order_age_days = fields.Float('Order Age Days')
    extended_partner_avg_amount = fields.Float('Avg Amount')
    extended_partner_success_avg_amount = fields.Float('Success Avg Amount')
    extended_partner_fail_avg_amount = fields.Float('Fail Avg Amount')
    extended_partner_total_messages = fields.Integer('Total Messages')
    extended_partner_success_avg_messages = fields.Float('Success Avg Messages')
    extended_partner_fail_avg_messages = fields.Float('Fail Avg Messages')
    extended_partner_avg_changes = fields.Float('Avg Changes')
    extended_partner_success_avg_changes = fields.Float('Success Avg Changes')
    extended_partner_fail_avg_changes = fields.Float('Fail Avg Changes')

    local_partner_success_rate = fields.Float('Success Rate')
    local_partner_total_orders = fields.Integer('Total Orders')
    local_partner_order_age_days = fields.Float('Order Age Days')
    local_partner_avg_amount = fields.Float('Avg Amount')
    local_partner_success_avg_amount = fields.Float('Success Avg Amount')
    local_partner_fail_avg_amount = fields.Float('Fail Avg Amount')
    local_partner_total_messages = fields.Integer('Total Messages')
    local_partner_success_avg_messages = fields.Float('Success Avg Messages')
    local_partner_fail_avg_messages = fields.Float('Fail Avg Messages')
    local_partner_avg_changes = fields.Float('Avg Changes')
    local_partner_success_avg_changes = fields.Float('Success Avg Changes')
    local_partner_fail_avg_changes = fields.Float('Fail Avg Changes')

    total_partner_success_rate = fields.Float('Success Rate')
    total_partner_total_orders = fields.Integer('Total Orders', compute='_compute_total_information', store=True)
    total_partner_order_age_days = fields.Float('Order Age Days')
    total_partner_avg_amount = fields.Float('Avg Amount')
    total_partner_success_avg_amount = fields.Float('Success Avg Amount')
    total_partner_fail_avg_amount = fields.Float('Fail Avg Amount')
    total_partner_total_messages = fields.Integer('Total Messages')
    total_partner_success_avg_messages = fields.Float('Success Avg Messages')
    total_partner_fail_avg_messages = fields.Float('Fail Avg Messages')
    total_partner_avg_changes = fields.Float('Avg Changes')
    total_partner_success_avg_changes = fields.Float('Success Avg Changes')
    total_partner_fail_avg_changes = fields.Float('Fail Avg Changes')

    def action_sync_extended_from_legacy(self):
        """Synchronize extended_* fields from legacy CSV using extended_id."""
        for partner in self:
            if not partner.extended_id:
                raise ValidationError(_("Set 'Extended ID' first before syncing from legacy data."))

            prediction_model = self.env["inventory.prediction.model"].search([
                ('is_production', '=', True)
            ], limit=1)
            if not prediction_model or not prediction_model.csv_file:
                raise ValidationError(_("No production Inventory Prediction Model with CSV file found."))

            try:
                csv_content = base64.b64decode(prediction_model.csv_file)
                csv_data = pd.read_csv(io.BytesIO(csv_content))
            except Exception as e:
                raise ValidationError(_("Failed to read legacy CSV data: %s") % str(e))

            legacy_id = partner.extended_id
            partner_records = csv_data[csv_data['partner_id'] == legacy_id]
            if partner_records.empty:
                raise ValidationError(_("No legacy records found in CSV for Extended ID %s") % legacy_id)

            if 'create_date' in partner_records.columns:
                try:
                    partner_records = partner_records.copy()
                    partner_records['create_date'] = pd.to_datetime(
                        partner_records['create_date'], errors='coerce'
                    )
                    partner_records = partner_records.sort_values('create_date', ascending=True)
                except Exception:
                    pass

            latest_record = partner_records.iloc[-1]

            mapping = {
                'partner_success_rate': 'extended_partner_success_rate',
                'partner_total_orders': 'extended_partner_total_orders',
                'partner_order_age_days': 'extended_partner_order_age_days',
                'partner_avg_amount': 'extended_partner_avg_amount',
                'partner_success_avg_amount': 'extended_partner_success_avg_amount',
                'partner_fail_avg_amount': 'extended_partner_fail_avg_amount',
                'partner_total_messages': 'extended_partner_total_messages',
                'partner_success_avg_messages': 'extended_partner_success_avg_messages',
                'partner_fail_avg_messages': 'extended_partner_fail_avg_messages',
                'partner_avg_changes': 'extended_partner_avg_changes',
                'partner_success_avg_changes': 'extended_partner_success_avg_changes',
                'partner_fail_avg_changes': 'extended_partner_fail_avg_changes',
            }

            values = {}
            for csv_field, partner_field in mapping.items():
                if csv_field in latest_record:
                    values[partner_field] = latest_record[csv_field]

            if 'partner_id' in latest_record:
                try:
                    values['extended_id'] = int(latest_record['partner_id'])
                except Exception:
                    pass

            if values:
                partner.write(values)

    def partner_info_extend(self):
        """Mass-update partners from production model CSV."""
        prediction_model = self.env["inventory.prediction.model"].search([('is_production', '=', True)], limit=1)
        print(f"{prediction_model = }")
        if prediction_model.state != 'trained' or not prediction_model.xgboost_model_binary or not prediction_model.scaler_binary:
            print("Модель не натренована. Спочатку виконайте навчання моделі.")
            raise ValidationError("Модель не натренована. Спочатку виконайте навчання моделі.")

        csv_content = base64.b64decode(prediction_model.csv_file)
        csv_data = pd.read_csv(io.BytesIO(csv_content))
        print("CSV файл успішно завантажено")

        partners_to_update = self.search([('extended_id', '=', False)])
        partners_to_update = self.search([])
        print(f"{partners_to_update = }")

        for partner in partners_to_update:
            print(f"{partner = }")
            partner_id_to_find = partner.id
            print(f"{type(partner_id_to_find) = }")
            print(f"Шукаємо дані для partner_id: {partner_id_to_find}")
            latest_record = None

            partner_records = csv_data[csv_data['partner_id'] == partner_id_to_find]

            if not partner_records.empty:
                if 'create_date' in partner_records.columns:
                    partner_records = partner_records.sort_values('create_date', ascending=False)

                latest_record = partner_records.iloc[0]
                print(f"Знайдено останній запис для partner_id {partner_id_to_find}:")

            if partner_records.empty:
                print(f"У CSV файлі немає даних для partner_id {partner_id_to_find}")

                mask = csv_data['partner_id'].apply(
                    lambda x: isinstance(x, (int, float)) and x % 100 == partner_id_to_find % 100)
                matching_records = csv_data[mask]

                if not matching_records.empty:
                    print(
                        f"Знайдено {len(matching_records)} записів з ID, що закінчується на {partner_id_to_find % 100}:")

                    if 'create_date' in matching_records.columns and not pd.api.types.is_datetime64_any_dtype(
                            matching_records['create_date']):
                        matching_records.loc[:, 'create_date'] = pd.to_datetime(matching_records['create_date'],
                                                                                errors='coerce')

                    if 'create_date' in matching_records.columns:
                        sorted_records = matching_records.sort_values('create_date', ascending=False)
                        print("Відсортовані за датою (найновіші перші):")
                        print(sorted_records[['partner_id', 'create_date']].head())

                        latest_record = sorted_records.iloc[0]
                        print(f"\nНайновіший запис для partner_id що закінчується на {partner_id_to_find % 100}:")
                        print(f"ID: {latest_record['partner_id']}, Дата: {latest_record['create_date']}")
                    else:
                        print("Колонки create_date немає в даних, неможливо сортувати за датою")
                        print(matching_records[['partner_id']].head())
                else:
                    print(f"Записів з ID, що закінчується на {partner_id_to_find % 100}, не знайдено")

                if latest_record is not None:
                    partner_fields = [
                        'partner_success_rate', 'partner_total_orders', 'partner_order_age_days',
                        'partner_avg_amount', 'partner_success_avg_amount', 'partner_fail_avg_amount',
                        'partner_total_messages', 'partner_success_avg_messages', 'partner_fail_avg_messages',
                        'partner_avg_changes', 'partner_success_avg_changes', 'partner_fail_avg_changes'
                    ]
                    for field in partner_fields:
                        if field in latest_record:
                            print(f"{field}: {latest_record[field]}")
                    partner.update({
                        "extended_id": latest_record['partner_id'],
                        "extended_partner_success_rate": latest_record['partner_success_rate'],
                        "extended_partner_total_orders": latest_record['partner_total_orders'],
                        "extended_partner_order_age_days": latest_record['partner_order_age_days'],
                        "extended_partner_avg_amount": latest_record['partner_avg_amount'],
                        "extended_partner_success_avg_amount": latest_record['partner_success_avg_amount'],
                        "extended_partner_fail_avg_amount": latest_record['partner_fail_avg_amount'],
                        "extended_partner_total_messages": latest_record['partner_total_messages'],
                        "extended_partner_success_avg_messages": latest_record['partner_success_avg_messages'],
                        "extended_partner_fail_avg_messages": latest_record['partner_fail_avg_messages'],
                        "extended_partner_avg_changes": latest_record['partner_avg_changes'],
                        "extended_partner_success_avg_changes": latest_record['partner_success_avg_changes'],
                        "extended_partner_fail_avg_changes": latest_record['partner_fail_avg_changes']
                    })
                    print(f'Клієнту {partner.name} призначено Extended ID {latest_record["partner_id"]}')

    @api.depends('local_partner_total_orders', 'extended_partner_total_orders')
    def _compute_total_information(self):
        for partner in self:
            total_partner_total_orders = partner.local_partner_total_orders + partner.extended_partner_total_orders
            total_partner_order_age_days = partner.local_partner_order_age_days + partner.extended_partner_order_age_days
            total_partner_total_messages = partner.local_partner_total_messages + partner.extended_partner_total_messages

            local_total_amount = partner.local_partner_avg_amount * partner.local_partner_total_orders
            extended_total_amount = partner.extended_partner_avg_amount * partner.extended_partner_total_orders
            total_amount = local_total_amount + extended_total_amount
            total_partner_avg_amount = (total_amount / total_partner_total_orders) if total_partner_total_orders > 0 else 0

            local_success_orders = partner.local_partner_total_orders * partner.local_partner_success_rate / 100
            extended_success_orders = partner.extended_partner_total_orders * partner.extended_partner_success_rate / 100
            total_success_orders = local_success_orders + extended_success_orders

            local_fail_orders = partner.local_partner_total_orders - local_success_orders
            extended_fail_orders = partner.extended_partner_total_orders - extended_success_orders
            total_fail_orders = local_fail_orders + extended_fail_orders

            local_success_amount = partner.local_partner_success_avg_amount * local_success_orders
            local_fail_amount = local_total_amount - local_success_amount

            extended_success_amount = partner.extended_partner_success_avg_amount * extended_success_orders
            extended_fail_amount = partner.extended_partner_fail_avg_amount * extended_fail_orders

            total_success_amount = local_success_amount + extended_success_amount
            total_fail_amount = local_fail_amount + extended_fail_amount

            total_partner_success_avg_amount = total_success_amount / total_success_orders if total_success_orders > 0 else 0
            total_partner_fail_avg_amount = total_fail_amount / total_fail_orders if total_fail_orders > 0 else 0

            local_sum_success_messages = partner.local_partner_success_avg_messages * local_success_orders
            extended_sum_success_messages = partner.extended_partner_success_avg_messages * extended_success_orders
            local_sum_fail_messages = partner.local_partner_fail_avg_messages * local_fail_orders
            extended_sum_fail_messages = partner.extended_partner_fail_avg_messages * extended_fail_orders

            total_sum_success_messages = local_sum_success_messages + extended_sum_success_messages
            total_sum_fail_messages = local_sum_fail_messages + extended_sum_fail_messages

            total_partner_success_avg_messages = total_sum_success_messages / total_success_orders if total_success_orders > 0 else 0
            total_partner_fail_avg_messages = total_sum_fail_messages / total_fail_orders if total_fail_orders > 0 else 0

            local_partner_sum_changes = partner.local_partner_avg_changes * partner.local_partner_total_orders
            extended_partner_sum_changes = partner.extended_partner_avg_changes * partner.extended_partner_total_orders

            total_partner_sum_changes = local_partner_sum_changes + extended_partner_sum_changes

            total_partner_avg_changes = total_partner_sum_changes / total_partner_total_orders if total_partner_total_orders > 0 else 0

            local_sum_success_changes = partner.local_partner_success_avg_changes * local_success_orders
            local_sum_fail_changes = partner.local_partner_fail_avg_changes * local_fail_orders

            extended_sum_success_changes = partner.extended_partner_success_avg_changes * extended_success_orders
            extended_sum_fail_changes = partner.extended_partner_fail_avg_changes * extended_fail_orders

            total_partner_success_changes = local_sum_success_changes + extended_sum_success_changes
            total_partner_fail_changes = local_sum_fail_changes + extended_sum_fail_changes

            total_partner_success_avg_changes = total_partner_success_changes / total_success_orders if total_success_orders > 0 else 0
            total_partner_fail_avg_changes = total_partner_fail_changes / total_fail_orders if total_fail_orders > 0 else 0

            total_partner_success_rate = 100 * total_success_orders / total_partner_total_orders if total_partner_total_orders > 0 else 0

            partner.update({
                "total_partner_success_rate": total_partner_success_rate,
                "total_partner_total_orders": total_partner_total_orders,
                "total_partner_order_age_days": total_partner_order_age_days,
                "total_partner_avg_amount": total_partner_avg_amount,
                "total_partner_success_avg_amount": total_partner_success_avg_amount,
                "total_partner_fail_avg_amount": total_partner_fail_avg_amount,
                "total_partner_total_messages": total_partner_total_messages,
                "total_partner_success_avg_messages": total_partner_success_avg_messages,
                "total_partner_fail_avg_messages": total_partner_fail_avg_messages,
                "total_partner_avg_changes": total_partner_avg_changes,
                "total_partner_success_avg_changes": total_partner_success_avg_changes,
                "total_partner_fail_avg_changes": total_partner_fail_avg_changes
            })
