"""
MPESA Integration Views for Flask-AppBuilder

This module provides Flask-AppBuilder views for managing MPESA accounts,
configurations, and transactions through the admin interface.
"""

import logging
from flask import flash, redirect, url_for, request
from flask_appbuilder import ModelView, action, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access
from flask_babel import lazy_gettext, gettext
from wtforms import StringField, TextAreaField, SelectField, BooleanField, DecimalField
from wtforms.validators import DataRequired, ValidationError, Length, Regexp
from wtforms.widgets import TextArea

from .mpesa_models import (
    MPESAAccount, MPESATransaction, MPESAConfiguration, MPESACallback,
    MPESATransactionType, MPESATransactionStatus
)
from .mpesa_service import get_mpesa_service

log = logging.getLogger(__name__)


class MPESAAccountModelView(ModelView):
    """
    ModelView for MPESA Account management.
    """
    
    datamodel = SQLAInterface(MPESAAccount)
    
    # List view configuration
    list_columns = [
        'id', 'user', 'phone_number', 'account_name', 
        'is_verified', 'is_active', 'wallet', 'created_on'
    ]
    
    show_columns = [
        'id', 'user', 'wallet', 'phone_number', 'account_name',
        'paybill_number', 'account_number', 'is_verified', 'verification_date',
        'is_active', 'created_on', 'changed_on', 'created_by', 'changed_by'
    ]
    
    add_columns = [
        'user', 'wallet', 'phone_number', 'account_name',
        'paybill_number', 'account_number', 'is_active'
    ]
    
    edit_columns = [
        'user', 'wallet', 'phone_number', 'account_name',
        'paybill_number', 'account_number', 'is_active', 'is_verified'
    ]
    
    # Search and filtering
    search_columns = ['phone_number', 'account_name', 'user.username']
    
    base_filters = [['user', lambda: current_user, 'eq']] if hasattr(lambda: None, 'current_user') else []
    
    # Display configuration
    base_order = ('created_on', 'desc')
    page_size = 25
    
    # Labels and descriptions
    label_columns = {
        'user': 'User',
        'wallet': 'Linked Wallet',
        'phone_number': 'Phone Number',
        'account_name': 'Account Name',
        'paybill_number': 'PayBill Number',
        'account_number': 'Account Number',
        'is_verified': 'Verified',
        'verification_date': 'Verification Date',
        'is_active': 'Active',
        'created_on': 'Created On',
        'changed_on': 'Last Modified'
    }
    
    description_columns = {
        'phone_number': 'Kenyan phone number in international format (254XXXXXXXXX)',
        'paybill_number': 'PayBill number for business accounts (optional)',
        'account_number': 'Account number for PayBill transactions (optional)',
        'is_verified': 'Whether the account has been verified via SMS',
        'is_active': 'Whether the account is active for transactions'
    }
    
    @action("verify", "Verify Account", "Verify selected MPESA accounts", "fa-check")
    def verify_accounts(self, items):
        """Verify selected MPESA accounts."""
        if not items:
            flash(gettext('No accounts selected'), 'warning')
            return redirect(url_for('MPESAAccountModelView.list'))
        
        verified_count = 0
        for account in items:
            if not account.is_verified:
                # In a real implementation, this would send SMS verification
                # For now, we'll just mark as verified
                account.is_verified = True
                account.verification_date = datetime.now(tz=timezone.utc)
                verified_count += 1
        
        if verified_count > 0:
            self.datamodel.session.commit()
            flash(gettext(f'{verified_count} accounts verified successfully'), 'success')
        else:
            flash(gettext('No unverified accounts selected'), 'info')
        
        return redirect(url_for('MPESAAccountModelView.list'))
    
    @action("deactivate", "Deactivate", "Deactivate selected MPESA accounts", "fa-times")
    def deactivate_accounts(self, items):
        """Deactivate selected MPESA accounts."""
        if not items:
            flash(gettext('No accounts selected'), 'warning')
            return redirect(url_for('MPESAAccountModelView.list'))
        
        for account in items:
            account.is_active = False
        
        self.datamodel.session.commit()
        flash(gettext(f'{len(items)} accounts deactivated'), 'success')
        
        return redirect(url_for('MPESAAccountModelView.list'))


class MPESATransactionModelView(ModelView):
    """
    ModelView for MPESA Transaction management.
    """
    
    datamodel = SQLAInterface(MPESATransaction)
    
    # List view configuration
    list_columns = [
        'id', 'mpesa_account', 'transaction_type', 'amount', 'phone_number',
        'status', 'mpesa_receipt_number', 'transaction_date', 'created_on'
    ]
    
    show_columns = [
        'id', 'mpesa_account', 'wallet_transaction', 'checkout_request_id',
        'merchant_request_id', 'mpesa_receipt_number', 'transaction_id',
        'transaction_type', 'amount', 'phone_number', 'account_reference',
        'transaction_desc', 'status', 'transaction_date', 'response_code',
        'response_description', 'callback_received', 'callback_processed',
        'created_on', 'changed_on'
    ]
    
    # No add/edit for transactions (they're created by the system)
    add_columns = []
    edit_columns = ['status', 'response_description']  # Limited editing
    
    # Search and filtering
    search_columns = [
        'phone_number', 'mpesa_receipt_number', 'checkout_request_id',
        'account_reference', 'transaction_desc'
    ]
    
    # Display configuration
    base_order = ('created_on', 'desc')
    page_size = 25
    
    # Labels and descriptions
    label_columns = {
        'mpesa_account': 'MPESA Account',
        'wallet_transaction': 'Wallet Transaction',
        'checkout_request_id': 'Checkout Request ID',
        'merchant_request_id': 'Merchant Request ID',
        'mpesa_receipt_number': 'MPESA Receipt',
        'transaction_id': 'Transaction ID',
        'transaction_type': 'Type',
        'phone_number': 'Phone Number',
        'account_reference': 'Reference',
        'transaction_desc': 'Description',
        'response_code': 'Response Code',
        'response_description': 'Response Message',
        'callback_received': 'Callback Received',
        'callback_processed': 'Callback Processed',
        'transaction_date': 'Transaction Date',
        'created_on': 'Created On'
    }
    
    @action("query_status", "Query Status", "Query MPESA status for selected transactions", "fa-search")
    def query_transaction_status(self, items):
        """Query MPESA status for selected transactions."""
        if not items:
            flash(gettext('No transactions selected'), 'warning')
            return redirect(url_for('MPESATransactionModelView.list'))
        
        mpesa_service = get_mpesa_service()
        updated_count = 0
        
        for transaction in items:
            if transaction.checkout_request_id and transaction.status == MPESATransactionStatus.PENDING.value:
                try:
                    success, message, response_data = mpesa_service.query_stk_status(
                        transaction.checkout_request_id
                    )
                    if success and response_data:
                        # Update transaction based on response
                        result_code = response_data.get('ResultCode')
                        if result_code == '0':
                            transaction.status = MPESATransactionStatus.COMPLETED.value
                        elif result_code in ['1032', '1037']:
                            transaction.status = MPESATransactionStatus.CANCELLED.value
                        elif result_code:
                            transaction.status = MPESATransactionStatus.FAILED.value
                            transaction.response_code = str(result_code)
                            transaction.response_description = response_data.get('ResultDesc', 'Failed')
                        
                        updated_count += 1
                
                except Exception as e:
                    log.error(f"Error querying transaction status: {e}")
                    continue
        
        if updated_count > 0:
            self.datamodel.session.commit()
            flash(gettext(f'{updated_count} transactions updated'), 'success')
        else:
            flash(gettext('No transactions were updated'), 'info')
        
        return redirect(url_for('MPESATransactionModelView.list'))


class MPESAConfigurationModelView(ModelView):
    """
    ModelView for MPESA Configuration management.
    """
    
    datamodel = SQLAInterface(MPESAConfiguration)
    
    # List view configuration
    list_columns = [
        'id', 'name', 'environment', 'business_shortcode',
        'lipa_na_mpesa_shortcode', 'is_active', 'is_default'
    ]
    
    show_columns = [
        'id', 'name', 'environment', 'description', 'base_url', 'auth_url',
        'business_shortcode', 'lipa_na_mpesa_shortcode', 'consumer_key',
        'confirmation_url', 'validation_url', 'callback_url', 'result_url',
        'timeout_url', 'is_active', 'is_default', 'created_on', 'changed_on'
    ]
    
    add_columns = [
        'name', 'environment', 'description', 'base_url', 'auth_url',
        'business_shortcode', 'lipa_na_mpesa_shortcode', 'passkey',
        'consumer_key', 'consumer_secret', 'confirmation_url', 'validation_url',
        'callback_url', 'result_url', 'timeout_url', 'is_active', 'is_default'
    ]
    
    edit_columns = [
        'name', 'environment', 'description', 'base_url', 'auth_url',
        'business_shortcode', 'lipa_na_mpesa_shortcode', 'passkey',
        'consumer_key', 'consumer_secret', 'confirmation_url', 'validation_url',
        'callback_url', 'result_url', 'timeout_url', 'is_active', 'is_default'
    ]
    
    # Search and filtering
    search_columns = ['name', 'environment', 'business_shortcode']
    
    # Display configuration
    base_order = ('created_on', 'desc')
    page_size = 25
    
    # Labels and descriptions
    label_columns = {
        'name': 'Configuration Name',
        'environment': 'Environment',
        'base_url': 'Base API URL',
        'auth_url': 'Authentication URL',
        'business_shortcode': 'Business Shortcode',
        'lipa_na_mpesa_shortcode': 'Lipa na M-Pesa Shortcode',
        'passkey': 'Lipa na M-Pesa Passkey',
        'consumer_key': 'Consumer Key',
        'consumer_secret': 'Consumer Secret',
        'confirmation_url': 'Confirmation URL',
        'validation_url': 'Validation URL',
        'callback_url': 'Callback URL',
        'result_url': 'Result URL',
        'timeout_url': 'Timeout URL',
        'is_active': 'Active',
        'is_default': 'Default Configuration'
    }
    
    description_columns = {
        'environment': 'Environment: "sandbox" for testing, "production" for live transactions',
        'base_url': 'MPESA API base URL (e.g., https://sandbox.safaricom.co.ke)',
        'business_shortcode': 'Your business shortcode for B2C and other transactions',
        'lipa_na_mpesa_shortcode': 'Shortcode for Lipa na M-Pesa (STK Push) transactions',
        'passkey': 'Lipa na M-Pesa passkey provided by Safaricom',
        'consumer_key': 'OAuth consumer key from Safaricom developer portal',
        'consumer_secret': 'OAuth consumer secret from Safaricom developer portal',
        'callback_url': 'URL for receiving STK Push callbacks',
        'is_default': 'Whether this is the default configuration to use'
    }
    
    # Form customizations
    add_form_extra_fields = {
        'environment': SelectField(
            'Environment',
            choices=[('sandbox', 'Sandbox'), ('production', 'Production')],
            validators=[DataRequired()]
        )
    }
    
    edit_form_extra_fields = {
        'environment': SelectField(
            'Environment',
            choices=[('sandbox', 'Sandbox'), ('production', 'Production')],
            validators=[DataRequired()]
        )
    }
    
    @action("test_config", "Test Configuration", "Test selected MPESA configurations", "fa-flask")
    def test_configurations(self, items):
        """Test selected MPESA configurations."""
        if not items:
            flash(gettext('No configurations selected'), 'warning')
            return redirect(url_for('MPESAConfigurationModelView.list'))
        
        results = []
        for config in items:
            try:
                # Test by trying to get access token
                mpesa_service = get_mpesa_service(config)
                token = mpesa_service._get_access_token()
                if token:
                    results.append(f"✓ {config.name}: Connection successful")
                else:
                    results.append(f"✗ {config.name}: Failed to get access token")
            except Exception as e:
                results.append(f"✗ {config.name}: {str(e)}")
        
        flash('\n'.join(results), 'info')
        return redirect(url_for('MPESAConfigurationModelView.list'))
    
    @action("set_default", "Set as Default", "Set selected configuration as default", "fa-star")
    def set_default_configuration(self, items):
        """Set selected configuration as default."""
        if not items or len(items) != 1:
            flash(gettext('Please select exactly one configuration'), 'warning')
            return redirect(url_for('MPESAConfigurationModelView.list'))
        
        # Clear all default flags
        self.datamodel.session.query(MPESAConfiguration).update({'is_default': False})
        
        # Set selected as default
        config = items[0]
        config.is_default = True
        config.is_active = True
        
        self.datamodel.session.commit()
        flash(gettext(f'Configuration "{config.name}" set as default'), 'success')
        
        return redirect(url_for('MPESAConfigurationModelView.list'))


class MPESACallbackModelView(ModelView):
    """
    ModelView for MPESA Callback logs (read-only).
    """
    
    datamodel = SQLAInterface(MPESACallback)
    
    # List view configuration
    list_columns = [
        'id', 'checkout_request_id', 'is_processed', 'processing_attempts',
        'last_processing_attempt', 'created_on'
    ]
    
    show_columns = [
        'id', 'checkout_request_id', 'merchant_request_id', 'callback_url',
        'callback_data', 'headers_data', 'is_processed', 'processing_error',
        'processing_attempts', 'last_processing_attempt', 'created_on'
    ]
    
    # Read-only (callbacks are created by the system)
    add_columns = []
    edit_columns = []
    
    # Search and filtering
    search_columns = ['checkout_request_id', 'merchant_request_id']
    
    # Display configuration
    base_order = ('created_on', 'desc')
    page_size = 25
    can_create = False
    can_edit = False
    can_delete = True  # Allow cleanup of old callbacks
    
    # Labels
    label_columns = {
        'checkout_request_id': 'Checkout Request ID',
        'merchant_request_id': 'Merchant Request ID',
        'callback_url': 'Callback URL',
        'callback_data': 'Callback Data',
        'headers_data': 'Headers Data',
        'is_processed': 'Processed',
        'processing_error': 'Processing Error',
        'processing_attempts': 'Processing Attempts',
        'last_processing_attempt': 'Last Processing Attempt',
        'created_on': 'Received On'
    }
    
    @action("reprocess", "Reprocess", "Reprocess selected callbacks", "fa-refresh")
    def reprocess_callbacks(self, items):
        """Reprocess selected failed callbacks."""
        if not items:
            flash(gettext('No callbacks selected'), 'warning')
            return redirect(url_for('MPESACallbackModelView.list'))
        
        mpesa_service = get_mpesa_service()
        processed_count = 0
        
        for callback in items:
            if not callback.is_processed or callback.processing_error:
                try:
                    callback_data = callback.get_callback_data_dict()
                    success, message = mpesa_service.process_stk_callback(callback_data)
                    
                    if success:
                        callback.is_processed = True
                        callback.processing_error = None
                        processed_count += 1
                    else:
                        callback.processing_error = message
                        callback.processing_attempts += 1
                        callback.last_processing_attempt = datetime.now(tz=timezone.utc)
                
                except Exception as e:
                    callback.processing_error = str(e)
                    callback.processing_attempts += 1
                    callback.last_processing_attempt = datetime.now(tz=timezone.utc)
        
        self.datamodel.session.commit()
        
        if processed_count > 0:
            flash(gettext(f'{processed_count} callbacks reprocessed successfully'), 'success')
        else:
            flash(gettext('No callbacks were successfully reprocessed'), 'warning')
        
        return redirect(url_for('MPESACallbackModelView.list')