"""
Wallet Views for PgAppForge

This module provides PgAppForge views for the wallet system,
including wallet management, transactions, budgets, and analytics.
"""

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, render_template
from pgappforge import BaseView, ModelView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.actions import action
from pgappforge.security.decorators import protect
from pgappforge.widgets import ListWidget, ShowWidget, FormWidget
from pgappforge.forms import DynamicForm
from wtforms import Form, StringField, DecimalField, SelectField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Length

from .models import (
    UserWallet, WalletTransaction, TransactionCategory, WalletBudget,
    PaymentMethod, RecurringTransaction, WalletAudit,
    TransactionType, TransactionStatus, BudgetPeriod, PaymentMethodType
)
from .services import (
    WalletService, TransactionService, BudgetService, CurrencyService,
    AnalyticsService, TransactionRequest, TransferRequest, ValidationError
)

log = logging.getLogger(__name__)


class WalletDashboardView(BaseView):
    """
    Main wallet dashboard view showing overview of all wallets,
    recent transactions, and key metrics.
    """
    
    route_base = '/wallet'
    
    @expose('/')
    @protect()
    def index(self):
        """Wallet dashboard main page."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            # Get wallet summary
            wallet_summary = AnalyticsService.get_wallet_summary(user_id)
            
            # Get recent transactions (last 10)
            recent_transactions = []
            wallets = WalletService.get_user_wallets(user_id)
            
            for wallet in wallets[:3]:  # Show transactions from first 3 wallets
                history = TransactionService.get_transaction_history(
                    wallet.id, user_id, limit=5
                )
                recent_transactions.extend(history['transactions'])
            
            # Sort by date and take most recent
            recent_transactions.sort(key=lambda x: x.transaction_date, reverse=True)
            recent_transactions = recent_transactions[:10]
            
            # Get budget alerts
            budget_alerts = []
            for wallet in wallets:
                analytics = BudgetService.get_budget_analytics(wallet.id, user_id)
                for budget_analytics in analytics:
                    if budget_analytics.alert_level >= 2:  # High alert
                        budget_alerts.append({
                            'wallet_name': wallet.wallet_name,
                            'budget_name': budget_analytics.budget_name,
                            'spent_percentage': budget_analytics.spent_percentage,
                            'alert_level': budget_analytics.alert_level,
                            'remaining_amount': budget_analytics.remaining_amount
                        })
            
            return self.render_template(
                'wallet/dashboard.html',
                wallet_summary=wallet_summary,
                recent_transactions=recent_transactions,
                budget_alerts=budget_alerts,
                wallets=wallets
            )
            
        except Exception as e:
            log.error(f"Error loading wallet dashboard: {e}")
            flash(f"Error loading dashboard: {str(e)}", "danger")
            return self.render_template('wallet/error.html')
    
    @expose('/api/summary')
    @protect()
    def api_summary(self):
        """API endpoint for wallet summary data."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            currency = request.args.get('currency', 'USD')
            
            summary = AnalyticsService.get_wallet_summary(user_id, currency)
            return jsonify(summary)
            
        except Exception as e:
            log.error(f"Error getting wallet summary: {e}")
            return jsonify({'error': str(e)}), 500
    
    @expose('/quick-transaction', methods=['POST'])
    @protect()
    def quick_transaction(self):
        """Process a quick transaction from dashboard."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            # Get form data
            wallet_id = request.form.get('wallet_id', type=int)
            amount = Decimal(request.form.get('amount', '0'))
            transaction_type = request.form.get('transaction_type')
            description = request.form.get('description')
            
            if not all([wallet_id, amount, transaction_type]):
                flash("Missing required fields", "danger")
                return redirect(url_for('WalletDashboardView.index'))
            
            # Process transaction
            transaction_request = TransactionRequest(
                amount=amount,
                transaction_type=TransactionType(transaction_type),
                description=description
            )
            
            transaction = TransactionService.process_transaction(
                wallet_id, transaction_request, user_id
            )
            
            flash(f"Transaction processed successfully: {transaction_type} of {amount}", "success")
            
        except Exception as e:
            log.error(f"Error processing quick transaction: {e}")
            flash(f"Error processing transaction: {str(e)}", "danger")
        
        return redirect(url_for('WalletDashboardView.index'))


class WalletModelView(ModelView):
    """
    Model view for managing user wallets.
    
    Provides CRUD operations for wallets with enhanced
    functionality and security.
    """
    
    datamodel = SQLAInterface(UserWallet)
    
    # List view configuration
    list_columns = [
        'wallet_name', 'currency_code', 'balance', 'is_primary', 
        'is_active', 'last_transaction_date'
    ]
    
    search_columns = ['wallet_name', 'description', 'currency_code']
    
    show_columns = [
        'wallet_name', 'currency_code', 'balance', 'available_balance',
        'pending_balance', 'description', 'wallet_type', 'is_primary',
        'is_active', 'daily_limit', 'monthly_limit', 'allow_negative_balance',
        'created_on', 'changed_on', 'last_transaction_date'
    ]
    
    edit_columns = [
        'wallet_name', 'description', 'daily_limit', 'monthly_limit',
        'allow_negative_balance', 'require_approval', 'approval_limit',
        'icon', 'color', 'is_active'
    ]
    
    add_columns = [
        'wallet_name', 'currency_code', 'description', 'wallet_type',
        'daily_limit', 'monthly_limit', 'allow_negative_balance',
        'icon', 'color'
    ]
    
    # Security - users can only see their own wallets
    base_filters = [['user_id', lambda: self.appbuilder.sm.current_user.id, '==']]
    
    def pre_add(self, item):
        """Set user_id before adding wallet."""
        item.user_id = self.appbuilder.sm.current_user.id
    
    def pre_update(self, item):
        """Ensure user can only update their own wallets."""
        if item.user_id != self.appbuilder.sm.current_user.id:
            raise ValidationError("Access denied")
    
    @action("set_primary", "Set as Primary", "Set this wallet as primary?", "fa-star")
    def set_primary(self, items):
        """Action to set a wallet as primary."""
        if len(items) != 1:
            flash("Please select exactly one wallet", "danger")
            return redirect(self.get_redirect())
        
        try:
            wallet = items[0]
            user_id = self.appbuilder.sm.current_user.id
            
            # Unset other primary wallets
            UserWallet.query.filter_by(
                user_id=user_id,
                is_primary=True
            ).update({'is_primary': False})
            
            # Set this wallet as primary
            wallet.is_primary = True
            self.datamodel.edit(wallet)
            
            flash(f"Wallet '{wallet.wallet_name}' set as primary", "success")
            
        except Exception as e:
            flash(f"Error setting primary wallet: {str(e)}", "danger")
        
        return redirect(self.get_redirect())
    
    @action("lock_wallet", "Lock Wallet", "Lock this wallet?", "fa-lock")
    def lock_wallet(self, items):
        """Action to lock wallets."""
        try:
            for wallet in items:
                wallet.is_locked = True
                wallet.locked_until = None  # Permanent lock
                self.datamodel.edit(wallet)
            
            flash(f"Locked {len(items)} wallet(s)", "success")
            
        except Exception as e:
            flash(f"Error locking wallets: {str(e)}", "danger")
        
        return redirect(self.get_redirect())


class TransactionView(ModelView):
    """
    Model view for wallet transactions.
    
    Provides comprehensive transaction management with
    filtering, search, and batch operations.
    """
    
    datamodel = SQLAInterface(WalletTransaction)
    
    # List view configuration
    list_columns = [
        'transaction_date', 'wallet.wallet_name', 'amount', 'transaction_type',
        'status', 'description', 'category.name', 'payment_method.name'
    ]
    
    search_columns = [
        'description', 'reference_number', 'external_id', 'location'
    ]
    
    show_columns = [
        'transaction_date', 'wallet.wallet_name', 'amount', 'transaction_type',
        'status', 'description', 'reference_number', 'external_id',
        'category.name', 'payment_method.name', 'location', 'receipt_url',
        'metadata_json', 'created_on', 'changed_on'
    ]
    
    edit_columns = [
        'description', 'category', 'tags', 'location', 'receipt_url'
    ]
    
    # Security - users can only see their own transactions
    base_filters = [['user_id', lambda: self.appbuilder.sm.current_user.id, '==']]
    
    # Default ordering
    base_order = ('transaction_date', 'desc')
    
    def pre_update(self, item):
        """Ensure user can only update their own transactions."""
        if item.user_id != self.appbuilder.sm.current_user.id:
            raise ValidationError("Access denied")
    
    @action("void_transaction", "Void Transaction", 
            "Void selected transactions?", "fa-ban")
    def void_transaction(self, items):
        """Action to void transactions."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            voided_count = 0
            
            for transaction in items:
                if transaction.status == TransactionStatus.COMPLETED.value:
                    TransactionService.void_transaction(
                        transaction.id, user_id, "Voided by user"
                    )
                    voided_count += 1
            
            flash(f"Voided {voided_count} transaction(s)", "success")
            
        except Exception as e:
            flash(f"Error voiding transactions: {str(e)}", "danger")
        
        return redirect(self.get_redirect())


class TransactionFormView(BaseView):
    """
    Custom view for creating transactions with enhanced form.
    """
    
    route_base = '/wallet/transaction'
    
    @expose('/add', methods=['GET', 'POST'])
    @protect()
    def add(self):
        """Add new transaction form."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            if request.method == 'POST':
                # Process form submission
                wallet_id = request.form.get('wallet_id', type=int)
                amount = Decimal(request.form.get('amount', '0'))
                transaction_type = request.form.get('transaction_type')
                description = request.form.get('description')
                category_id = request.form.get('category_id', type=int) or None
                payment_method_id = request.form.get('payment_method_id', type=int) or None
                
                # Process transaction
                transaction_request = TransactionRequest(
                    amount=amount,
                    transaction_type=TransactionType(transaction_type),
                    description=description,
                    category_id=category_id,
                    payment_method_id=payment_method_id
                )
                
                transaction = TransactionService.process_transaction(
                    wallet_id, transaction_request, user_id
                )
                
                flash("Transaction added successfully", "success")
                return redirect(url_for('TransactionView.list'))
            
            # GET request - show form
            wallets = WalletService.get_user_wallets(user_id)
            categories = TransactionCategory.query.filter_by(
                user_id=user_id, is_active=True
            ).all()
            payment_methods = PaymentMethod.query.filter_by(
                user_id=user_id, is_active=True
            ).all()
            
            return self.render_template(
                'wallet/add_transaction.html',
                wallets=wallets,
                categories=categories,
                payment_methods=payment_methods,
                transaction_types=[(t.value, t.value.title()) for t in TransactionType]
            )
            
        except Exception as e:
            log.error(f"Error in transaction form: {e}")
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('WalletDashboardView.index'))
    
    @expose('/transfer', methods=['GET', 'POST'])
    @protect()
    def transfer(self):
        """Transfer funds between wallets."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            if request.method == 'POST':
                # Process transfer
                source_wallet_id = request.form.get('source_wallet_id', type=int)
                target_wallet_id = request.form.get('target_wallet_id', type=int)
                amount = Decimal(request.form.get('amount', '0'))
                description = request.form.get('description')
                
                transfer_request = TransferRequest(
                    source_wallet_id=source_wallet_id,
                    target_wallet_id=target_wallet_id,
                    amount=amount,
                    description=description
                )
                
                outgoing, incoming = TransactionService.transfer_funds(
                    transfer_request, user_id
                )
                
                flash(f"Transfer of {amount} completed successfully", "success")
                return redirect(url_for('WalletDashboardView.index'))
            
            # GET request - show form
            wallets = WalletService.get_user_wallets(user_id)
            
            return self.render_template(
                'wallet/transfer.html',
                wallets=wallets
            )
            
        except Exception as e:
            log.error(f"Error in transfer form: {e}")
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('WalletDashboardView.index'))


class BudgetView(ModelView):
    """
    Model view for budget management.
    
    Provides budget creation, monitoring, and analytics
    with alert management.
    """
    
    datamodel = SQLAInterface(WalletBudget)
    
    # List view configuration
    list_columns = [
        'name', 'wallet.wallet_name', 'budget_amount', 'spent_amount',
        'remaining_amount', 'period_type', 'period_start', 'period_end',
        'is_active'
    ]
    
    search_columns = ['name', 'description']
    
    show_columns = [
        'name', 'description', 'wallet.wallet_name', 'category.name',
        'budget_amount', 'spent_amount', 'remaining_amount', 'period_type',
        'period_start', 'period_end', 'is_active', 'auto_rollover',
        'alert_threshold_1', 'alert_threshold_2', 'alert_threshold_3',
        'created_on', 'last_updated'
    ]
    
    edit_columns = [
        'name', 'description', 'budget_amount', 'alert_threshold_1',
        'alert_threshold_2', 'alert_threshold_3', 'is_active', 'auto_rollover'
    ]
    
    add_columns = [
        'wallet', 'category', 'name', 'description', 'budget_amount',
        'period_type', 'auto_rollover', 'alert_threshold_1', 
        'alert_threshold_2', 'alert_threshold_3'
    ]
    
    def pre_add(self, item):
        """Set period dates when adding budget."""
        try:
            # Calculate period dates based on period_type
            BudgetService.create_budget(
                wallet_id=item.wallet_id,
                user_id=self.appbuilder.sm.current_user.id,
                name=item.name,
                budget_amount=item.budget_amount,
                period_type=BudgetPeriod(item.period_type),
                category_id=item.category_id,
                description=item.description,
                auto_rollover=item.auto_rollover
            )
            # Prevent normal add since we handled it in service
            return False
            
        except Exception as e:
            flash(f"Error creating budget: {str(e)}", "danger")
            return False
    
    @action("update_spent", "Update Spent Amount", 
            "Update spent amounts for selected budgets?", "fa-refresh")
    def update_spent(self, items):
        """Action to update spent amounts for budgets."""
        try:
            for budget in items:
                budget.update_spent_amount()
            
            flash(f"Updated {len(items)} budget(s)", "success")
            
        except Exception as e:
            flash(f"Error updating budgets: {str(e)}", "danger")
        
        return redirect(self.get_redirect())


class PaymentMethodView(ModelView):
    """
    Model view for payment method management.
    
    Provides secure payment method management with
    encryption and usage tracking.
    """
    
    datamodel = SQLAInterface(PaymentMethod)
    
    # List view configuration
    list_columns = [
        'name', 'method_type', 'masked_account_number', 'bank_name',
        'is_active', 'is_primary', 'last_used_date'
    ]
    
    search_columns = ['name', 'description', 'bank_name']
    
    show_columns = [
        'name', 'method_type', 'description', 'masked_account_number',
        'bank_name', 'currency_code', 'is_active', 'is_primary',
        'daily_limit', 'monthly_limit', 'per_transaction_limit',
        'total_transactions', 'total_amount', 'last_used_date'
    ]
    
    edit_columns = [
        'name', 'description', 'is_active', 'daily_limit',
        'monthly_limit', 'per_transaction_limit'
    ]
    
    add_columns = [
        'name', 'method_type', 'description', 'account_number',
        'account_holder', 'bank_name', 'currency_code', 'is_primary',
        'daily_limit', 'monthly_limit', 'per_transaction_limit'
    ]
    
    # Security - users can only see their own payment methods
    base_filters = [['user_id', lambda: self.appbuilder.sm.current_user.id, '==']]
    
    def pre_add(self, item):
        """Set user_id before adding payment method."""
        item.user_id = self.appbuilder.sm.current_user.id
    
    def pre_update(self, item):
        """Ensure user can only update their own payment methods."""
        if item.user_id != self.appbuilder.sm.current_user.id:
            raise ValidationError("Access denied")


class WalletAnalyticsView(BaseView):
    """
    Analytics view for wallet insights and reporting.
    
    Provides comprehensive financial analytics, charts,
    and trend analysis.
    """
    
    route_base = '/wallet/analytics'
    
    @expose('/')
    @protect()
    def index(self):
        """Main analytics dashboard."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            # Get spending analytics
            spending_analytics = AnalyticsService.get_spending_analytics(
                user_id, days=30, group_by='category'
            )
            
            # Get trend analysis
            balance_trends = AnalyticsService.get_trend_analysis(
                user_id, metric='balance', periods=12
            )
            
            income_trends = AnalyticsService.get_trend_analysis(
                user_id, metric='income', periods=12
            )
            
            expense_trends = AnalyticsService.get_trend_analysis(
                user_id, metric='expenses', periods=12
            )
            
            return self.render_template(
                'wallet/analytics.html',
                spending_analytics=spending_analytics,
                balance_trends=balance_trends,
                income_trends=income_trends,
                expense_trends=expense_trends
            )
            
        except Exception as e:
            log.error(f"Error loading analytics: {e}")
            flash(f"Error loading analytics: {str(e)}", "danger")
            return self.render_template('wallet/error.html')
    
    @expose('/api/spending')
    @protect()
    def api_spending(self):
        """API endpoint for spending analytics."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            wallet_id = request.args.get('wallet_id', type=int)
            days = request.args.get('days', 30, type=int)
            group_by = request.args.get('group_by', 'category')
            
            analytics = AnalyticsService.get_spending_analytics(
                user_id, wallet_id, days, group_by
            )
            return jsonify(analytics)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @expose('/api/trends')
    @protect()
    def api_trends(self):
        """API endpoint for trend analysis."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            wallet_id = request.args.get('wallet_id', type=int)
            metric = request.args.get('metric', 'balance')
            periods = request.args.get('periods', 12, type=int)
            
            trends = AnalyticsService.get_trend_analysis(
                user_id, wallet_id, metric, periods
            )
            return jsonify(trends)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500


class WalletReportsView(BaseView):
    """
    Reporting view for wallet reports and exports.
    
    Provides report generation, filtering, and export
    capabilities for financial data.
    """
    
    route_base = '/wallet/reports'
    
    @expose('/')
    @protect()
    def index(self):
        """Main reports dashboard."""
        return self.render_template('wallet/reports.html')
    
    @expose('/transaction-export')
    @protect()
    def transaction_export(self):
        """Export transactions to CSV/Excel."""
        try:
            user_id = self.appbuilder.sm.current_user.id
            
            # Get parameters
            wallet_id = request.args.get('wallet_id', type=int)
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            export_format = request.args.get('format', 'csv')
            
            # Parse dates
            if start_date:
                start_date = datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                end_date = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Get transactions
            history = TransactionService.get_transaction_history(
                wallet_id, user_id, limit=10000,
                start_date=start_date, end_date=end_date
            )
            
            transactions = history['transactions']
            
            if export_format == 'csv':
                # Generate CSV response
                import csv
                from io import StringIO
                
                output = StringIO()
                writer = csv.writer(output)
                
                # Header
                writer.writerow([
                    'Date', 'Wallet', 'Amount', 'Type', 'Status',
                    'Description', 'Category', 'Reference'
                ])
                
                # Data rows
                for t in transactions:
                    writer.writerow([
                        t.transaction_date.strftime('%Y-%m-%d %H:%M:%S'),
                        t.wallet.wallet_name,
                        str(t.amount),
                        t.transaction_type,
                        t.status,
                        t.description or '',
                        t.category.name if t.category else '',
                        t.reference_number or ''
                    ])
                
                output.seek(0)
                return output.getvalue(), 200, {
                    'Content-Type': 'text/csv',
                    'Content-Disposition': 'attachment; filename=transactions.csv'
                }
            
            else:  # JSON
                return jsonify({
                    'transactions': [
                        {
                            'date': t.transaction_date.isoformat(),
                            'wallet': t.wallet.wallet_name,
                            'amount': float(t.amount),
                            'type': t.transaction_type,
                            'status': t.status,
                            'description': t.description,
                            'category': t.category.name if t.category else None,
                            'reference': t.reference_number
                        }
                        for t in transactions
                    ]
                })
            
        except Exception as e:
            log.error(f"Error exporting transactions: {e}")
            return jsonify({'error': str(e)}), 500


# Category management view
class CategoryView(ModelView):
    """Model view for transaction categories."""
    
    datamodel = SQLAInterface(TransactionCategory)
    
    list_columns = ['name', 'category_type', 'parent.name', 'is_active', 'transaction_count']
    show_columns = ['name', 'description', 'category_type', 'parent', 'icon', 'color', 'is_active']
    edit_columns = ['name', 'description', 'parent', 'icon', 'color', 'is_active', 'sort_order']
    add_columns = ['name', 'description', 'parent', 'category_type', 'icon', 'color']
    
    # Security - users can only see their own categories and system categories
    base_filters = [['user_id', lambda: [self.appbuilder.sm.current_user.id, None], 'in']]
    
    def pre_add(self, item):
        """Set user_id for custom categories."""
        item.user_id = self.appbuilder.sm.current_user.id


__all__ = [
    'WalletDashboardView',
    'WalletModelView', 
    'TransactionView',
    'TransactionFormView',
    'BudgetView',
    'PaymentMethodView',
    'WalletAnalyticsView',
    'WalletReportsView',
    'CategoryView'
]