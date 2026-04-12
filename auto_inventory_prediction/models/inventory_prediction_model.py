import io
import pickle
import base64
import matplotlib
import numpy as np
import pandas as pd
import seaborn as sns
from markupsafe import Markup
import matplotlib.pyplot as plt

from xgboost import XGBClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, roc_auc_score

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

matplotlib.use('Agg')  # Non-interactive backend to avoid Tcl/Tk dependency


class InventoryPredictionModel(models.Model):
    _name = 'inventory.prediction.model'
    _description = 'Order Success Prediction Model (XGBoost)'

    name = fields.Char(string='Назва', required=True)
    is_production = fields.Boolean()
    use_extended_database = fields.Boolean()
    csv_file = fields.Binary(string='Файл з даними (CSV)', required=True)
    csv_filename = fields.Char(string='Назва CSV-файлу')

    # Data split settings
    train_size = fields.Float(string='Розмір навчальної вибірки (%)', default=70.0, required=True)
    test_size = fields.Float(string='Розмір тестової вибірки (%)', compute='_compute_test_size', store=True)

    # Feature selection flags
    use_order_amount = fields.Boolean(string='Сума замовлення', default=True)
    use_partner_avg_amount = fields.Boolean(string='Загальна середня сума замовлень', default=True)
    use_partner_success_avg_amount = fields.Boolean(string='Середню сума успішних замовлень', default=True)
    use_partner_fail_avg_amount = fields.Boolean(string='Середня сума неуспішних замовлень', default=True)
    use_partner_success_avg_messages = fields.Boolean(
        string='Середня кількість повідомлень в успішних замовленнях', default=True,
    )
    use_partner_fail_avg_messages = fields.Boolean(
        string='Середня кількість повідомлень в неуспішних замовленнях', default=True,
    )
    use_partner_success_avg_changes = fields.Boolean(
        string='Середня кількість змін в успішних замовленнях клієнта', default=True,
    )
    use_partner_fail_avg_changes = fields.Boolean(
        string='Середня кількість змін в неуспішних замовленнях клієнта', default=True,
    )

    # Additional partner parameters
    use_partner_success_rate = fields.Boolean(string='Рейтинг успішності клієнта', default=True)
    use_partner_total_orders = fields.Boolean(string='Загальну кількість замовлень клієнта', default=True)
    use_partner_order_age_days = fields.Boolean(string='Термін співпраці з клієнтом', default=True)
    use_partner_total_messages = fields.Boolean(string='Загальну кількість повідомлень клієнта', default=True)
    use_partner_avg_changes = fields.Boolean(string='Середню кількість змін в замовленнях клієнта', default=True)

    use_order_messages = fields.Boolean(string='Кількість повідомлень в замовленні', default=False)
    use_order_changes = fields.Boolean(string='Кількість змін в замовленні', default=False)

    # Serialized model data
    xgboost_model_binary = fields.Binary(string='XGBoost Model Binary')
    test_data_binary = fields.Binary(string='Test Data', attachment=True)
    scaler_binary = fields.Binary(string='Scaler Binary')

    # XGBoost training metrics
    xgb_train_accuracy = fields.Float(string='Train Accuracy', digits=(8, 6))
    xgb_train_precision = fields.Float(string='Train Precision', digits=(8, 6))
    xgb_train_recall = fields.Float(string='Train Recall', digits=(8, 6))
    xgb_train_f1_score = fields.Float(string='Train F1 Score', digits=(8, 6))
    xgb_train_roc_auc = fields.Float(string='Train ROC AUC', digits=(8, 6))
    xgb_train_confusion_matrix_plot = fields.Binary(string='XGB Train Confusion Matrix Plot')
    xgb_train_confusion_matrix_log = fields.Html(string='XGB Train Confusion Matrix Log')
    xgb_feature_importance = fields.Html(string='XGBoost Feature Importance')

    # XGBoost test metrics
    xgb_test_accuracy = fields.Float(string='Test Accuracy', digits=(8, 6))
    xgb_test_precision = fields.Float(string='Test Precision', digits=(8, 6))
    xgb_test_recall = fields.Float(string='Test Recall', digits=(8, 6))
    xgb_test_f1_score = fields.Float(string='Test F1 Score', digits=(8, 6))
    xgb_test_roc_auc = fields.Float(string='Test ROC AUC', digits=(8, 6))
    xgb_test_confusion_matrix_plot = fields.Binary(string='Test Confusion Matrix Plot')
    xgb_test_confusion_matrix_log = fields.Html(string='Test Confusion Matrix Log')

    # Training state
    state = fields.Selection([
        ('draft', 'Новий'),
        ('trained', 'Навчений'),
    ], string='Стан', default='draft', required=True)

    def toggle_is_production(self):
        self.search([]).update({'is_production': False})
        for m in self:
            m.is_production = not m.is_production

    def toggle_use_extended_database(self):
        for m in self:
            m.use_extended_database = not m.use_extended_database

    def predict_order_success(self, order_data):
        """Predict order success probability from a data dictionary.

        Args:
            order_data (dict): Order data obtained via SQL query.

        Returns:
            dict: Prediction results with success probability and top features.
        """
        self.ensure_one()

        if self.state != 'trained' or not self.xgboost_model_binary or not self.scaler_binary:
            print("Модель не натренована. Спочатку виконайте навчання моделі.")
            return {'success': False, 'error': 'Модель не натренована'}

        try:
            # Load model and scaler from binary fields
            model_binary = base64.b64decode(self.xgboost_model_binary)
            scaler_binary = base64.b64decode(self.scaler_binary)

            model = pickle.loads(model_binary)
            scaler = pickle.loads(scaler_binary)

            # Extract features from order_data (remove metadata)
            features_data = order_data.copy()

            print(f"{features_data = }")
            print(f"{features_data['partner_id'] = }")

            # Remove fields not needed for prediction
            metadata_fields = ['order_id', 'order_name', 'is_successful', 'create_date', 'partner_id']
            for field in metadata_fields:
                if field in features_data:
                    del features_data[field]

            # Convert to DataFrame for prediction
            features_df = pd.DataFrame([features_data])

            # Apply feature selection settings
            features_to_use = []

            # Map DataFrame column names to model settings
            field_mapping = {
                'order_amount': self.use_order_amount,
                'partner_avg_amount': self.use_partner_avg_amount,
                'partner_success_avg_amount': self.use_partner_success_avg_amount,
                'partner_fail_avg_amount': self.use_partner_fail_avg_amount,
                'partner_success_rate': self.use_partner_success_rate,
                'partner_total_orders': self.use_partner_total_orders,
                'partner_order_age_days': self.use_partner_order_age_days,
                'partner_total_messages': self.use_partner_total_messages,
                'partner_success_avg_messages': self.use_partner_success_avg_messages,
                'partner_fail_avg_messages': self.use_partner_fail_avg_messages,
                'partner_avg_changes': self.use_partner_avg_changes,
                'partner_success_avg_changes': self.use_partner_success_avg_changes,
                'partner_fail_avg_changes': self.use_partner_fail_avg_changes,
                'order_messages': self.use_order_messages,
                'order_changes': self.use_order_changes
            }

            # Keep only user-selected features
            for feature, use_it in field_mapping.items():
                if use_it and feature in features_df.columns:
                    features_to_use.append(feature)

            # If no features selected, use all
            if not features_to_use:
                features_to_use = list(features_df.columns)

            # Filter by features
            features_filtered = features_df[features_to_use].copy()

            # Create additional features (same as during training)
            features_filtered = self.create_additional_features(features_filtered)

            # Diagnostic output
            print(f"Ознаки після створення додаткових: {list(features_filtered.columns)}")

            # Align columns to match scaler order before standardisation
            print(f"Впорядковуємо ознаки згідно порядку в скалері: {list(scaler.feature_names_in_)}")
            features_filtered = features_filtered[scaler.feature_names_in_]
            print(f"Ознаки після впорядкування: {list(features_filtered.columns)}")

            # Ensure all required features are present
            if hasattr(scaler, 'feature_names_in_'):
                missing_features = [
                    feature for feature in scaler.feature_names_in_
                    if feature not in features_filtered.columns
                ]
                if missing_features:
                    print(f"Відсутні ознаки: {missing_features}")
                    for col in missing_features:
                        features_filtered.loc[:, col] = 0

                features_filtered = features_filtered[scaler.feature_names_in_]
                print(f"{features_filtered = }")

            # Normalise data using loaded scaler
            try:
                scaled_features = scaler.transform(features_filtered)
            except ValueError as e:
                print(f"Помилка при стандартизації даних: {str(e)}")
                print(f"Ознаки, які очікує скалер: {list(scaler.feature_names_in_)}")

                for col in scaler.feature_names_in_:
                    if col not in features_filtered.columns:
                        features_filtered.loc[:, col] = 0

                features_filtered = features_filtered[scaler.feature_names_in_]
                print(f"{features_filtered = }")
                scaled_features = scaler.transform(features_filtered)

            # Make prediction
            prediction_prob = model.predict_proba(scaled_features)[:, 1][0]

            # Determine most influential features
            top_features, all_features = [], []
            if hasattr(model, 'feature_importances_'):
                feature_importance = {
                    features_filtered.columns[i]: model.feature_importances_[i]
                    for i in range(len(features_filtered.columns))
                }

                print(f"{feature_importance = }")
                all_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
                print(f"{all_features = }")
                top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]
                top_features = [f[0] for f in top_features]

            return {
                'success': True,
                'success_probability': float(prediction_prob),
                'top_features': top_features,
                'feature_importance': all_features
            }

        except Exception as e:
            print(f"Помилка при прогнозуванні замовлення: {str(e)}")
            return {'success': False, 'error': str(e)}

    @api.depends('train_size')
    def _compute_test_size(self):
        """Compute test split size"""
        for record in self:
            record.test_size = 100.0 - record.train_size

    def load_csv_data(self):
        """Load data from CSV file"""
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_('Завантажте CSV-файл перед обробкою даних'))

        try:
            csv_data = base64.b64decode(self.csv_file)
            df = pd.read_csv(io.BytesIO(csv_data))

            if df.empty:
                raise ValidationError(_('CSV-файл не містить даних'))

            required_columns = ['order_id', 'is_successful']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValidationError(_(
                    'Відсутні необхідні колонки у вхідних даних: %s'
                ) % ', '.join(missing_columns))

            return df

        except Exception as e:
            raise ValidationError(_('Помилка при обробці CSV-файлу: %s') % str(e))

    def select_features(self, df):
        """Select features based on user settings"""
        print('Вибір ознак для моделі')

        required_columns = ['order_id', 'is_successful']

        # Print flag states
        print(f"{self.use_order_amount = }")
        print(f"{self.use_partner_avg_amount = }")
        print(f"{self.use_partner_success_avg_amount = }")
        print(f"{self.use_partner_fail_avg_amount = }")
        print(f"{self.use_partner_success_avg_messages = }")
        print(f"{self.use_partner_fail_avg_messages = }")
        print(f"{self.use_partner_success_avg_changes = }")
        print(f"{self.use_partner_fail_avg_changes = }")
        print(f"{self.use_order_messages = }")
        print(f"{self.use_order_changes = }")

        # Add only selected columns to required list
        if self.use_order_amount:
            required_columns.append('order_amount')
        if self.use_order_messages:
            required_columns.append('order_messages')
        if self.use_order_changes:
            required_columns.append('order_changes')
        if self.use_partner_avg_amount:
            required_columns.append('partner_avg_amount')
        if self.use_partner_success_avg_amount:
            required_columns.append('partner_success_avg_amount')
        if self.use_partner_fail_avg_amount:
            required_columns.append('partner_fail_avg_amount')
        if self.use_partner_success_avg_messages:
            required_columns.append('partner_success_avg_messages')
        if self.use_partner_fail_avg_messages:
            required_columns.append('partner_fail_avg_messages')
        if self.use_partner_success_avg_changes:
            required_columns.append('partner_success_avg_changes')
        if self.use_partner_fail_avg_changes:
            required_columns.append('partner_fail_avg_changes')

        # Additional partner parameters
        if self.use_partner_success_rate:
            required_columns.append('partner_success_rate')
        if self.use_partner_total_orders:
            required_columns.append('partner_total_orders')
        if self.use_partner_order_age_days:
            required_columns.append('partner_order_age_days')
        if self.use_partner_total_messages:
            required_columns.append('partner_total_messages')
        if self.use_partner_avg_changes:
            required_columns.append('partner_avg_changes')

        # Validate selected columns exist in dataframe
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValidationError(_(
                'Відсутні необхідні колонки у вхідних даних: %s'
            ) % ', '.join(missing_columns))

        print(f"{required_columns = }")
        return df[required_columns]

    def create_additional_features(self, df):
        """Create additional derived features"""
        # Difference between avg amounts of successful and failed orders
        if self.use_partner_success_avg_amount and self.use_partner_fail_avg_amount:
            df['amount_success_fail_diff'] = df['partner_success_avg_amount'] - df['partner_fail_avg_amount']

        # Difference between avg messages of successful and failed orders
        if self.use_partner_success_avg_messages and self.use_partner_fail_avg_messages:
            df['messages_success_fail_diff'] = df['partner_success_avg_messages'] - df['partner_fail_avg_messages']

        # Difference between avg changes of successful and failed orders
        if self.use_partner_success_avg_changes and self.use_partner_fail_avg_changes:
            df['changes_success_fail_diff'] = df['partner_success_avg_changes'] - df['partner_fail_avg_changes']

        # Ratio of order amount to partner avg amount
        if self.use_order_amount and self.use_partner_avg_amount:
            df['order_amount_to_avg_ratio'] = df['order_amount'] / df['partner_avg_amount']

        # Replace infinite values and NaN with 0
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.fillna(0)

        return df

    @staticmethod
    def _train_xgboost_model(X_train, y_train, X_train_scaled, y_train_scaled):
        """Train XGBoost model with optimised hyperparameters"""
        # Class imbalance weight calculation
        class_counts = np.bincount(y_train)
        if len(class_counts) > 1 and class_counts[1] > 0:
            scale_pos_weight = class_counts[0] / class_counts[1]
        else:
            scale_pos_weight = 1.0

        # Split training data into train and validation subsets
        X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
            X_train_scaled, y_train_scaled, test_size=0.2, random_state=42
        )

        # Create XGBoost model with optimal parameters
        model = XGBClassifier(
            n_estimators=500,
            learning_rate=0.01,
            max_depth=4,
            min_child_weight=3,
            gamma=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            objective='binary:logistic',
            eval_metric=['auc', 'error', 'logloss'],
            random_state=42
        )

        # Train model
        model.fit(
            X_train_split,
            y_train_split,
            eval_set=[(X_train_split, y_train_split), (X_val_split, y_val_split)],
            verbose=True
        )

        return model

    @staticmethod
    def plot_confusion_matrix(y_true, y_pred, title='Confusion Matrix'):
        """Create confusion matrix visualisation"""
        cm = confusion_matrix(y_true, y_pred)
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues')
        plt.title(title)
        plt.ylabel('Фактичні значення')
        plt.xlabel('Прогнозовані значення')

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close()

        return base64.b64encode(buf.getvalue())

    def train_model(self):
        """Main model training method"""
        self.ensure_one()
        try:
            # Load data
            df = self.load_csv_data()

            if df.empty:
                raise ValidationError(_('Набір даних порожній. Перевірте вхідний CSV-файл.'))

            if self.use_extended_database:
                ...  # TODO: Combine with current DB data

            # Select features
            df = self.select_features(df)

            # Create additional features
            df = self.create_additional_features(df)

            # Separate target variable
            if 'is_successful' not in df.columns:
                raise ValidationError(_('У вхідних даних відсутня колонка "is_successful"'))

            X = df.drop(['order_id', 'is_successful'], axis=1)
            y = df['is_successful']

            if X.empty or len(y) == 0:
                raise ValidationError(_('Недостатньо даних для навчання моделі'))

            # Split data
            train_proportion = self.train_size / 100.0
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, train_size=train_proportion, random_state=42
            )

            # Scale data
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            # Train XGBoost model
            model = self._train_xgboost_model(X_train, y_train, X_train_scaled, y_train_scaled=y_train)

            # Save model and scaler
            self.xgboost_model_binary = base64.b64encode(pickle.dumps(model))
            self.scaler_binary = base64.b64encode(pickle.dumps(scaler))

            # Save test data
            test_data = {
                'X_test': X_test,
                'y_test': y_test,
                'X_test_scaled': X_test_scaled
            }
            self.test_data_binary = base64.b64encode(pickle.dumps(test_data))

            # Compute and save training metrics
            self._compute_training_metrics(model, X_train_scaled, y_train)

            # Compute and save test metrics
            self._compute_test_metrics(model, X_test_scaled, y_test)

            # Visualise feature importance
            self._plot_feature_importance(model, X)

            # Update model state
            self.state = 'trained'

            # Commit changes
            self.env.cr.commit()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Успіх'),
                    'message': _('Модель успішно навчена!'),
                    'sticky': False,
                }
            }

        except Exception as e:
            raise ValidationError(_('Помилка при навчанні моделі: %s') % str(e))

    def _compute_training_metrics(self, model, X_train_scaled, y_train):
        """Compute metrics on training set"""
        y_train_pred = model.predict(X_train_scaled)
        y_train_pred_proba = model.predict_proba(X_train_scaled)[:, 1]

        self.xgb_train_accuracy = accuracy_score(y_train, y_train_pred)
        self.xgb_train_precision = precision_score(y_train, y_train_pred, zero_division=0)
        self.xgb_train_recall = recall_score(y_train, y_train_pred, zero_division=0)
        self.xgb_train_f1_score = f1_score(y_train, y_train_pred, zero_division=0)

        if len(np.unique(y_train)) > 1:
            self.xgb_train_roc_auc = roc_auc_score(y_train, y_train_pred_proba)
        else:
            self.xgb_train_roc_auc = 0.5

        self.xgb_train_confusion_matrix_plot = self.plot_confusion_matrix(
            y_train, y_train_pred, title='XGBoost Train Confusion Matrix'
        )

        cm = confusion_matrix(y_train, y_train_pred)
        html = self._format_confusion_matrix_html(cm, 'XGBoost Train Confusion Matrix')
        self.xgb_train_confusion_matrix_log = html

    def _compute_test_metrics(self, model, X_test_scaled, y_test):
        """Compute metrics on test set"""
        y_test_pred = model.predict(X_test_scaled)
        y_test_pred_proba = model.predict_proba(X_test_scaled)[:, 1]

        self.xgb_test_accuracy = accuracy_score(y_test, y_test_pred)
        self.xgb_test_precision = precision_score(y_test, y_test_pred, zero_division=0)
        self.xgb_test_recall = recall_score(y_test, y_test_pred, zero_division=0)
        self.xgb_test_f1_score = f1_score(y_test, y_test_pred, zero_division=0)

        if len(np.unique(y_test)) > 1:
            self.xgb_test_roc_auc = roc_auc_score(y_test, y_test_pred_proba)
        else:
            self.xgb_test_roc_auc = 0.5

        self.xgb_test_confusion_matrix_plot = self.plot_confusion_matrix(
            y_test, y_test_pred, title='XGBoost Test Confusion Matrix'
        )

        cm = confusion_matrix(y_test, y_test_pred)
        html = self._format_confusion_matrix_html(cm, 'XGBoost Test Confusion Matrix')
        self.xgb_test_confusion_matrix_log = html

    @staticmethod
    def _format_confusion_matrix_html(cm, title):
        """Format confusion matrix as HTML for display"""
        html = f'<div style="padding: 10px;"><h3>{title}</h3>'
        html += '<table class="table table-bordered"><tr><th></th><th>Прогноз: 0</th><th>Прогноз: 1</th></tr>'

        try:
            html += f'<tr><th>Факт: 0</th><td>{cm[0][0]}</td><td>{cm[0][1]}</td></tr>'
            html += f'<tr><th>Факт: 1</th><td>{cm[1][0]}</td><td>{cm[1][1]}</td></tr>'
        except IndexError:
            html += '<tr><td colspan="3">Недостатньо даних для матриці помилок</td></tr>'

        html += '</table>'

        if cm.shape == (2, 2):
            tn, fp = cm[0][0], cm[0][1]
            fn, tp = cm[1][0], cm[1][1]

            specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
            sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0

            html += f'<p><strong>Точність (Precision):</strong> {tp / (tp + fp) if (tp + fp) > 0 else 0:.4f}</p>'
            html += f'<p><strong>Повнота (Recall/Sensitivity):</strong> {sensitivity:.4f}</p>'
            html += f'<p><strong>Специфічність (Specificity):</strong> {specificity:.4f}</p>'

        html += '</div>'
        return Markup(html)

    def _plot_feature_importance(self, model, X):
        """Visualise feature importance"""
        feature_importance = model.feature_importances_
        sorted_idx = np.argsort(feature_importance)

        features = X.columns.tolist()
        importance = feature_importance

        features_sorted = [features[i] for i in sorted_idx[::-1]]
        importance_sorted = importance[sorted_idx[::-1]]

        max_features = min(20, len(features_sorted))
        features_sorted = features_sorted[:max_features]
        importance_sorted = importance_sorted[:max_features]

        html = '<div style="padding: 10px;"><h3>Важливість ознак XGBoost</h3>'
        html += '<table class="table table-bordered table-striped"><tr><th>Ознака</th><th>Важливість</th></tr>'

        for feature, importance_value in zip(features_sorted, importance_sorted):
            html += f'<tr><td>{feature}</td><td>{importance_value:.6f}</td></tr>'

        html += '</table></div>'

        self.xgb_feature_importance = Markup(html)
