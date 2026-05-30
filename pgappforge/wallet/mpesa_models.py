"""
MPESA Integration Models

This module defines database models for MPESA (mobile money) integration
including account linking, transaction processing, and callback handling.
"""

import json
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from enum import Enum

from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Numeric, 
    ForeignKey, Index, CheckConstraint, UniqueConstraint
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property

log = logging.getLogger(__name__)


class MPESATransactionType(Enum):
    """MPESA transaction types."""
    B2C = "b2c"  # Business to Customer
    C2B = "c2b"  # Customer to Business
    B2B = "b2b"  # Business to Business
    LIPA_NA_MPESA = "lipa_na_mpesa"  # Lipa na M-Pesa Online Payment
    ACCOUNT_BALANCE = "account_balance"  # Account Balance
    TRANSACTION_STATUS = "transaction_status"  # Transaction Status Query


class MPESATransactionStatus(Enum):
    """MPESA transaction status values."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MPESAAccount(AuditMixin, Model):
    """
    MPESA account linking for users.
    
    Stores MPESA phone numbers and account details linked to user wallets.
    """
    
    __tablename__ = 'ab_mpesa_accounts'
    __table_args__ = (
        Index('ix_mpesa_accounts_user', 'user_id'),
        Index('ix_mpesa_accounts_phone', 'phone_number'),
        UniqueConstraint('user_id', 'phone_number', name='uq_user_mpesa_phone')
    )
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    wallet_id = Column(Integer, ForeignKey('ab_user_wallets.id'), nullable=True)
    
    # MPESA account details
    phone_number = Column(String(15), nullable=False, index=True)
    account_name = Column(String(100), nullable=True)
    paybill_number = Column(String(20), nullable=True)  # For business accounts
    account_number = Column(String(50), nullable=True)  # Account number for paybill
    
    # Verification and status
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_date = Column(DateTime, nullable=True)
    verification_code = Column(String(10), nullable=True)  # SMS verification code
    is_active = Column(Boolean, default=True, nullable=False)
    
    # MPESA API configuration
    consumer_key = Column(String(100), nullable=True)  # For business integrations
    consumer_secret = Column(String(100), nullable=True)
    passkey = Column(String(100), nullable=True)  # Lipa na M-Pesa passkey
    shortcode = Column(String(10), nullable=True)  # Business shortcode
    
    # Metadata
    metadata = Column(Text, nullable=True)  # JSON metadata
    
    # Relationships
    user = relationship("User", back_populates="mpesa_accounts")
    wallet = relationship("UserWallet", back_populates="mpesa_accounts")
    transactions = relationship("MPESATransaction", back_populates="mpesa_account")
    
    @validates('phone_number')
    def validate_phone_number(self, key, phone_number):
        """Validate phone number format."""
        if not phone_number:
            raise ValueError("Phone number is required")
        
        # Remove any spaces, dashes, or parentheses
        clean_number = ''.join(filter(str.isdigit, phone_number))
        
        # Kenyan phone numbers should be 12 digits (254XXXXXXXXX)
        if len(clean_number) == 9 and clean_number.startswith('7'):
            # Convert to international format
            clean_number = '254' + clean_number
        elif len(clean_number) == 10 and clean_number.startswith('07'):
            # Convert to international format
            clean_number = '254' + clean_number[1:]
        elif not (len(clean_number) == 12 and clean_number.startswith('254')):
            raise ValueError("Invalid phone number format. Use format: 254XXXXXXXXX")
        
        return clean_number
    
    def get_metadata_dict(self) -> Dict[str, Any]:
        """Get metadata as dictionary."""
        try:
            return json.loads(self.metadata) if self.metadata else {}
        except json.JSONDecodeError:
            return {}
    
    def set_metadata(self, metadata_dict: Dict[str, Any]):
        """Set metadata from dictionary."""
        self.metadata = json.dumps(metadata_dict)
    
    def verify_account(self, verification_code: str = None) -> bool:
        """Mark account as verified."""
        if verification_code and self.verification_code == verification_code:
            self.is_verified = True
            self.verification_date = datetime.now(tz=timezone.utc)
            self.verification_code = None  # Clear after use
            return True
        return False
    
    def is_business_account(self) -> bool:
        """Check if this is a business account."""
        return bool(self.paybill_number or self.shortcode)
    
    def __repr__(self):
        return f"<MPESAAccount(id={self.id}, phone='{self.phone_number}', verified={self.is_verified})>"


class MPESATransaction(AuditMixin, Model):
    """
    MPESA transaction records.
    
    Stores all MPESA transaction details including callbacks and status updates.
    """
    
    __tablename__ = 'ab_mpesa_transactions'
    __table_args__ = (
        Index('ix_mpesa_transactions_account', 'mpesa_account_id'),
        Index('ix_mpesa_transactions_status', 'status'),
        Index('ix_mpesa_transactions_type', 'transaction_type'),
        Index('ix_mpesa_transactions_reference', 'mpesa_receipt_number'),
        Index('ix_mpesa_transactions_checkout', 'checkout_request_id'),
        Index('ix_mpesa_transactions_date', 'transaction_date'),
    )
    
    id = Column(Integer, primary_key=True)
    mpesa_account_id = Column(Integer, ForeignKey('ab_mpesa_accounts.id'), nullable=False)
    wallet_transaction_id = Column(Integer, ForeignKey('ab_wallet_transactions.id'), nullable=True)
    
    # MPESA transaction identifiers
    checkout_request_id = Column(String(100), nullable=True, unique=True)
    merchant_request_id = Column(String(100), nullable=True)
    mpesa_receipt_number = Column(String(100), nullable=True, unique=True)
    transaction_id = Column(String(100), nullable=True)  # MPESA internal ID
    
    # Transaction details
    transaction_type = Column(String(20), nullable=False)  # From MPESATransactionType enum
    amount = Column(Numeric(precision=15, scale=2), nullable=False)
    phone_number = Column(String(15), nullable=False)
    account_reference = Column(String(50), nullable=True)
    transaction_desc = Column(String(200), nullable=True)
    
    # Status and timing
    status = Column(String(20), default=MPESATransactionStatus.PENDING.value, nullable=False)
    transaction_date = Column(DateTime, nullable=True)  # MPESA transaction time
    response_code = Column(String(10), nullable=True)  # MPESA response code
    response_description = Column(Text, nullable=True)  # MPESA response message
    
    # Callback data
    callback_received = Column(Boolean, default=False, nullable=False)
    callback_data = Column(Text, nullable=True)  # Full callback JSON
    callback_processed = Column(Boolean, default=False, nullable=False)
    callback_processing_error = Column(Text, nullable=True)
    
    # Balance information (for balance queries)
    account_balance = Column(Numeric(precision=15, scale=2), nullable=True)
    available_balance = Column(Numeric(precision=15, scale=2), nullable=True)
    
    # Relationships
    mpesa_account = relationship("MPESAAccount", back_populates="transactions")
    wallet_transaction = relationship("WalletTransaction", back_populates="mpesa_transaction")
    
    @validates('transaction_type')
    def validate_transaction_type(self, key, transaction_type):
        """Validate transaction type."""
        valid_types = [t.value for t in MPESATransactionType]
        if transaction_type not in valid_types:
            raise ValueError(f"Invalid transaction type. Must be one of: {', '.join(valid_types)}")
        return transaction_type
    
    @validates('status')
    def validate_status(self, key, status):
        """Validate transaction status."""
        valid_statuses = [s.value for s in MPESATransactionStatus]
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        return status
    
    @validates('amount')
    def validate_amount(self, key, amount):
        """Validate transaction amount."""
        if amount is not None and amount <= 0:
            raise ValueError("Amount must be positive")
        return amount
    
    def get_callback_data_dict(self) -> Dict[str, Any]:
        """Get callback data as dictionary."""
        try:
            return json.loads(self.callback_data) if self.callback_data else {}
        except json.JSONDecodeError:
            return {}
    
    def set_callback_data(self, callback_dict: Dict[str, Any]):
        """Set callback data from dictionary."""
        self.callback_data = json.dumps(callback_dict)
        self.callback_received = True
    
    def mark_completed(self, mpesa_receipt: str, response_data: Dict[str, Any] = None):
        """Mark transaction as completed with MPESA receipt."""
        self.status = MPESATransactionStatus.COMPLETED.value
        self.mpesa_receipt_number = mpesa_receipt
        self.transaction_date = datetime.now(tz=timezone.utc)
        
        if response_data:
            self.set_callback_data(response_data)
            # Extract additional details from response
            if 'TransactionDate' in response_data:
                try:
                    # MPESA date format: 20231201143022
                    date_str = str(response_data['TransactionDate'])
                    if len(date_str) == 14:
                        self.transaction_date = datetime.strptime(date_str, '%Y%m%d%H%M%S')
                except (ValueError, TypeError):
                    pass
    
    def mark_failed(self, error_message: str, error_code: str = None):
        """Mark transaction as failed with error details."""
        self.status = MPESATransactionStatus.FAILED.value
        self.response_description = error_message
        self.response_code = error_code or "FAILED"
    
    def is_completed(self) -> bool:
        """Check if transaction is completed."""
        return self.status == MPESATransactionStatus.COMPLETED.value
    
    def is_pending(self) -> bool:
        """Check if transaction is pending."""
        return self.status == MPESATransactionStatus.PENDING.value
    
    def __repr__(self):
        return f"<MPESATransaction(id={self.id}, type='{self.transaction_type}', amount={self.amount}, status='{self.status}')>"


class MPESACallback(AuditMixin, Model):
    """
    MPESA callback logs.
    
    Stores raw callback data from MPESA for debugging and audit purposes.
    """
    
    __tablename__ = 'ab_mpesa_callbacks'
    __table_args__ = (
        Index('ix_mpesa_callbacks_checkout', 'checkout_request_id'),
        Index('ix_mpesa_callbacks_processed', 'is_processed'),
    )
    
    id = Column(Integer, primary_key=True)
    
    # Callback identifiers
    checkout_request_id = Column(String(100), nullable=True, index=True)
    merchant_request_id = Column(String(100), nullable=True)
    
    # Callback data
    callback_url = Column(String(500), nullable=True)
    callback_data = Column(Text, nullable=False)  # Full JSON payload
    headers_data = Column(Text, nullable=True)  # HTTP headers
    
    # Processing status
    is_processed = Column(Boolean, default=False, nullable=False)
    processing_error = Column(Text, nullable=True)
    processing_attempts = Column(Integer, default=0, nullable=False)
    last_processing_attempt = Column(DateTime, nullable=True)
    
    def get_callback_data_dict(self) -> Dict[str, Any]:
        """Get callback data as dictionary."""
        try:
            return json.loads(self.callback_data) if self.callback_data else {}
        except json.JSONDecodeError:
            return {}
    
    def get_headers_dict(self) -> Dict[str, Any]:
        """Get headers as dictionary."""
        try:
            return json.loads(self.headers_data) if self.headers_data else {}
        except json.JSONDecodeError:
            return {}
    
    def mark_processed(self, error_message: str = None):
        """Mark callback as processed."""
        self.is_processed = True
        self.processing_attempts += 1
        self.last_processing_attempt = datetime.now(tz=timezone.utc)
        if error_message:
            self.processing_error = error_message
    
    def __repr__(self):
        return f"<MPESACallback(id={self.id}, processed={self.is_processed}, attempts={self.processing_attempts})>"


class MPESAConfiguration(AuditMixin, Model):
    """
    MPESA API configuration settings.
    
    Stores environment-specific MPESA API configurations.
    """
    
    __tablename__ = 'ab_mpesa_configurations'
    __table_args__ = (
        Index('ix_mpesa_configurations_env', 'environment'),
        Index('ix_mpesa_configurations_active', 'is_active'),
        UniqueConstraint('environment', 'name', name='uq_mpesa_config_env_name')
    )
    
    id = Column(Integer, primary_key=True)
    
    # Configuration details
    name = Column(String(100), nullable=False)
    environment = Column(String(20), nullable=False)  # 'sandbox' or 'production'
    description = Column(Text, nullable=True)
    
    # API endpoints
    base_url = Column(String(200), nullable=False)
    auth_url = Column(String(200), nullable=False)
    
    # Business details
    business_shortcode = Column(String(10), nullable=True)
    lipa_na_mpesa_shortcode = Column(String(10), nullable=True)
    passkey = Column(String(100), nullable=True)
    
    # API credentials (encrypted)
    consumer_key = Column(String(100), nullable=False)
    consumer_secret = Column(String(100), nullable=False)
    
    # Callback URLs
    confirmation_url = Column(String(500), nullable=True)
    validation_url = Column(String(500), nullable=True)
    callback_url = Column(String(500), nullable=True)
    result_url = Column(String(500), nullable=True)
    timeout_url = Column(String(500), nullable=True)
    
    # Configuration status
    is_active = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    
    @validates('environment')
    def validate_environment(self, key, environment):
        """Validate environment."""
        if environment not in ['sandbox', 'production']:
            raise ValueError("Environment must be 'sandbox' or 'production'")
        return environment
    
    def get_access_token_url(self) -> str:
        """Get OAuth access token URL."""
        return f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
    
    def get_stk_push_url(self) -> str:
        """Get STK Push URL."""
        return f"{self.base_url}/mpesa/stkpush/v1/processrequest"
    
    def get_stk_query_url(self) -> str:
        """Get STK Query URL."""
        return f"{self.base_url}/mpesa/stkpushquery/v1/query"
    
    def get_b2c_url(self) -> str:
        """Get B2C URL."""
        return f"{self.base_url}/mpesa/b2c/v1/paymentrequest"
    
    def get_c2b_register_url(self) -> str:
        """Get C2B register URL."""
        return f"{self.base_url}/mpesa/c2b/v1/registerurl"
    
    def get_account_balance_url(self) -> str:
        """Get account balance URL."""
        return f"{self.base_url}/mpesa/accountbalance/v1/query"
    
    def __repr__(self):
        return f"<MPESAConfiguration(id={self.id}, name='{self.name}', env='{self.environment}', active={self.is_active})>"