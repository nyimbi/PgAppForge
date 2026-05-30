"""
Wallet System Models

This module defines the database models for the user wallet system,
including wallets, transactions, budgets, and related entities.
"""

import json
import logging
import hashlib
import hmac
import secrets
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union
from enum import Enum

from flask import current_app
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from flask_login import current_user
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Numeric, 
    ForeignKey, Index, CheckConstraint, UniqueConstraint, event
)
from sqlalchemy.orm import relationship, validates
from contextlib import contextmanager
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func

# Use PgAppForge's standard AuditMixin pattern
# This provides created_on, changed_on, created_by_fk, changed_by_fk fields

log = logging.getLogger(__name__)


class TransactionType(Enum):
    """Transaction types for wallet operations."""
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class TransactionStatus(Enum):
    """Transaction status values."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PROCESSING = "processing"


class BudgetPeriod(Enum):
    """Budget period types."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class PaymentMethodType(Enum):
    """Payment method types."""
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    DIGITAL_WALLET = "digital_wallet"
    CRYPTOCURRENCY = "cryptocurrency"
    CHECK = "check"
    OTHER = "other"


class UserWallet(AuditMixin, Model):
    """
    User wallet model for tracking balances and wallet settings.
    
    Each user can have multiple wallets (different currencies, purposes, etc.)
    with comprehensive balance tracking and transaction history.
    """
    
    __tablename__ = 'ab_user_wallets'
    __table_args__ = (
        UniqueConstraint('user_id', 'currency_code', 'wallet_name', 
                        name='uq_user_wallet_currency_name'),
        Index('ix_user_wallets_user_currency', 'user_id', 'currency_code'),
        Index('ix_user_wallets_active', 'is_active'),
        CheckConstraint('balance >= 0 OR allow_negative_balance = true', 
                       name='ck_wallet_balance_non_negative')
    )
    
    # Core wallet fields
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    wallet_name = Column(String(100), nullable=False, default='Default Wallet')
    currency_code = Column(String(3), nullable=False, default='USD')
    balance = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    
    # Wallet configuration
    is_active = Column(Boolean, nullable=False, default=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    allow_negative_balance = Column(Boolean, nullable=False, default=False)
    daily_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    monthly_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    
    # Wallet metadata
    description = Column(Text, nullable=True)
    wallet_type = Column(String(50), nullable=False, default='personal')
    icon = Column(String(50), nullable=True)  # FontAwesome icon class
    color = Column(String(7), nullable=True)  # Hex color code
    
    # Security and privacy
    is_locked = Column(Boolean, nullable=False, default=False)
    locked_until = Column(DateTime, nullable=True)
    require_approval = Column(Boolean, nullable=False, default=False)
    approval_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    
    # Calculated fields
    available_balance = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    pending_balance = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    last_transaction_date = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", backref="wallets", foreign_keys=[user_id])
    user_profile = relationship("UserProfile", back_populates="wallets")
    transactions = relationship("WalletTransaction", back_populates="wallet", 
                              cascade="all, delete-orphan")
    budgets = relationship("WalletBudget", back_populates="wallet",
                          cascade="all, delete-orphan")
    
    # Cache configuration
    __cache_timeout__ = 300  # 5 minutes
    
    @hybrid_property
    def total_income(self):
        """Calculate total income for this wallet."""
        return self.get_transaction_total(TransactionType.INCOME)
    
    @hybrid_property 
    def total_expenses(self):
        """Calculate total expenses for this wallet."""
        return self.get_transaction_total(TransactionType.EXPENSE)
    
    @hybrid_property
    def net_worth(self):
        """Calculate net worth (income - expenses)."""
        return self.total_income - self.total_expenses
    
    def get_transaction_total(self, transaction_type: TransactionType, 
                            start_date: datetime = None, end_date: datetime = None) -> Decimal:
        """Get total transactions by type and date range with optimized query."""
        # Use optimized aggregation query directly
        query = db.session.query(func.sum(WalletTransaction.amount)).filter(
            WalletTransaction.wallet_id == self.id,
            WalletTransaction.transaction_type == transaction_type.value,
            WalletTransaction.status == TransactionStatus.COMPLETED.value
        )
        
        if start_date:
            query = query.filter(WalletTransaction.transaction_date >= start_date)
        if end_date:
            query = query.filter(WalletTransaction.transaction_date <= end_date)
        
        result = query.scalar()
        return result or Decimal('0.00')
    
    def can_transact(self, amount: Decimal, transaction_type: TransactionType) -> tuple[bool, str]:
        """Check if a transaction is allowed."""
        amount = Decimal(str(amount))
        
        # Check if wallet is active
        if not self.is_active:
            return False, "Wallet is inactive"
        
        # Check if wallet is locked
        if self.is_locked:
            if self.locked_until and self.locked_until > datetime.now(tz=timezone.utc):
                return False, f"Wallet is locked until {self.locked_until}"
            elif self.locked_until is None:
                return False, "Wallet is permanently locked"
        
        # Check for expenses
        if transaction_type == TransactionType.EXPENSE:
            # Check negative balance allowance
            if not self.allow_negative_balance and (self.available_balance - amount) < 0:
                return False, "Insufficient funds"
            
            # Check daily limit
            if self.daily_limit:
                today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                today_expenses = self.get_transaction_total(
                    TransactionType.EXPENSE, today_start, datetime.now(tz=timezone.utc)
                )
                if (today_expenses + amount) > self.daily_limit:
                    return False, f"Daily limit of {self.currency_code} {self.daily_limit} exceeded"
            
            # Check monthly limit
            if self.monthly_limit:
                month_start = datetime.now(tz=timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                month_expenses = self.get_transaction_total(
                    TransactionType.EXPENSE, month_start, datetime.now(tz=timezone.utc)
                )
                if (month_expenses + amount) > self.monthly_limit:
                    return False, f"Monthly limit of {self.currency_code} {self.monthly_limit} exceeded"
            
            # Check approval requirement
            if self.require_approval and self.approval_limit and amount > self.approval_limit:
                return False, f"Transactions over {self.currency_code} {self.approval_limit} require approval"
        
        return True, "Transaction allowed"
    
    def add_transaction(self, amount: Decimal, transaction_type: TransactionType,
                       description: str = None, category_id: int = None,
                       payment_method_id: int = None, metadata: dict = None,
                       auto_commit: bool = True, bypass_approval: bool = False) -> 'WalletTransaction':
        """Add a new transaction to the wallet with security validation."""
        from sqlalchemy.orm import sessionmaker
        
        amount = Decimal(str(amount))
        
        # Validate transaction
        can_transact, message = self.can_transact(amount, transaction_type)
        if not can_transact:
            raise ValueError(f"Transaction not allowed: {message}")
        
        # Check if approval is required and not bypassed
        requires_approval = (
            self.require_approval and 
            self.approval_limit and 
            amount > self.approval_limit and 
            not bypass_approval
        )
        
        # Create secure transaction
        transaction = SecureWalletTransaction.create_secure_transaction(
            wallet_id=self.id,
            user_id=self.user.id if hasattr(self, 'user') and self.user else current_user.id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            category_id=category_id,
            payment_method_id=payment_method_id,
            metadata=metadata,
            requires_approval=requires_approval
        )
        
        # If approval required, set status to pending
        if requires_approval:
            transaction.status = TransactionStatus.PENDING.value
            transaction.requires_approval = True
        else:
            transaction.status = TransactionStatus.COMPLETED.value
            # Update wallet balance immediately for non-approval transactions
            self._apply_transaction_to_balance(transaction, transaction_type, amount)
        
        # Update last transaction date
        self.last_transaction_date = datetime.now(tz=timezone.utc)
        
        # Add to session
        from pgappforge import db
        db.session.add(transaction)
        
        # Create approval workflow if required
        if requires_approval:
            self._create_transaction_approval_workflow(transaction)
        
        if auto_commit:
            db.session.commit()
        
        return transaction
    
    @contextmanager
    def _lock_wallet_for_transaction(self):
        """Database-level locking context manager for wallet balance updates.
        
        CRITICAL SECURITY FIX: Prevents race conditions in concurrent transactions
        by using SELECT FOR UPDATE to lock the wallet row during balance modifications.
        """
        # Use PgAppForge's session access pattern
        from flask import g
        db_session = g.appbuilder.get_session if hasattr(g, 'appbuilder') else None
        if not db_session:
            from pgappforge import db
            db_session = db.session
        
        try:
            # Lock this wallet instance for update
            locked_wallet = db_session.query(UserWallet).filter_by(
                id=self.id
            ).with_for_update().first()
            
            if not locked_wallet:
                raise ValueError(f"Wallet {self.id} not found or could not be locked")
            
            yield locked_wallet
        except Exception as e:
            log.error(f"Database locking failed for wallet {self.id}: {e}")
            db_session.rollback()
            raise
    
    def _apply_transaction_to_balance(self, transaction: 'WalletTransaction', 
                                    transaction_type: TransactionType, amount: Decimal):
        """Apply transaction to wallet balance (internal method with locking).
        
        SECURITY FIX: This method now operates within a database lock context
        to prevent race conditions during concurrent balance updates.
        """
        # This method should now only be called within _lock_wallet_for_transaction context
        log.info(f"Applying {transaction_type.value} of {amount} to wallet {self.id}")
        
        if transaction_type == TransactionType.INCOME:
            self.balance += amount
            self.available_balance += amount
        elif transaction_type == TransactionType.EXPENSE:
            self.balance -= amount
            self.available_balance -= amount
        elif transaction_type == TransactionType.REFUND:
            self.balance += amount
            self.available_balance += amount
        elif transaction_type == TransactionType.ADJUSTMENT:
            # Adjustment can be positive or negative
            if amount >= 0:
                self.balance += amount
                self.available_balance += amount
            else:
                self.balance += amount  # amount is already negative
                self.available_balance += amount
        
        log.info(f"Wallet {self.id} balance updated: {self.balance} (available: {self.available_balance})")
    
    def _create_transaction_approval_workflow(self, transaction: 'WalletTransaction'):
        """Create approval workflow for high-value transactions."""
        try:
            from pgappforge.process.models.process_models import ProcessInstance
            from pgappforge.process.approval.chain_manager import ApprovalChainManager
            
            # Create approval workflow instance
            workflow_data = {
                'transaction_id': transaction.id,
                'wallet_id': self.id,
                'amount': float(transaction.amount),
                'currency': self.currency_code,
                'transaction_type': transaction.transaction_type,
                'description': transaction.description,
                'requested_by': transaction.user_id
            }
            
            # Determine approval chain based on amount
            chain_config = self._get_approval_chain_config(transaction.amount)
            
            # Use approval chain manager to create workflow
            chain_manager = ApprovalChainManager()
            approval_workflow = chain_manager.create_approval_workflow(
                target_model='WalletTransaction',
                target_id=transaction.id,
                workflow_type='financial_transaction',
                chain_config=chain_config,
                input_data=workflow_data
            )
            
            # Link transaction to approval workflow
            transaction.approval_workflow_id = approval_workflow.id
            
            log.info(f"Created approval workflow {approval_workflow.id} for transaction {transaction.id}")
            
        except Exception as e:
            log.error(f"Failed to create approval workflow for transaction {transaction.id}: {str(e)}")
            # Don't fail the transaction, but log the error
    
    def _get_approval_chain_config(self, amount: Decimal) -> Dict[str, Any]:
        """Get approval chain configuration based on transaction amount."""
        # Define approval tiers based on amount
        if amount >= Decimal('10000'):
            # High value - requires CFO + CEO approval
            return {
                'chain_type': 'multi_level',
                'levels': [
                    {
                        'name': 'Manager Approval',
                        'approver_roles': ['Manager', 'Team Lead'],
                        'require_all': False
                    },
                    {
                        'name': 'CFO Approval', 
                        'approver_roles': ['CFO', 'Finance Director'],
                        'require_all': False
                    },
                    {
                        'name': 'CEO Approval',
                        'approver_roles': ['CEO', 'President'],
                        'require_all': False
                    }
                ]
            }
        elif amount >= Decimal('1000'):
            # Medium value - requires manager + finance approval
            return {
                'chain_type': 'multi_level',
                'levels': [
                    {
                        'name': 'Manager Approval',
                        'approver_roles': ['Manager', 'Team Lead'],
                        'require_all': False
                    },
                    {
                        'name': 'Finance Approval',
                        'approver_roles': ['Finance Manager', 'CFO'],
                        'require_all': False
                    }
                ]
            }
        else:
            # Standard approval - single manager
            return {
                'chain_type': 'single',
                'levels': [
                    {
                        'name': 'Manager Approval',
                        'approver_roles': ['Manager', 'Team Lead'],
                        'require_all': False
                    }
                ]
            }
    
    def transfer_to(self, target_wallet: 'UserWallet', amount: Decimal,
                   description: str = None, auto_commit: bool = True) -> tuple['WalletTransaction', 'WalletTransaction']:
        """Transfer funds to another wallet with cryptographic security."""
        amount = Decimal(str(amount))
        
        if target_wallet.id == self.id:
            raise ValueError("Cannot transfer to the same wallet")
        
        # Validate source wallet can make the transfer
        can_transact, message = self.can_transact(amount, TransactionType.TRANSFER)
        if not can_transact:
            raise ValueError(f"Transfer not allowed: {message}")
        
        # Create secure transfer pair with cryptographic linking
        transfer_id = secrets.token_urlsafe(32)
        transfer_timestamp = datetime.now(tz=timezone.utc)
        
        # Metadata for transfer linking
        outgoing_metadata = {
            'transfer_type': 'outgoing',
            'target_wallet_id': target_wallet.id,
            'target_wallet_name': target_wallet.wallet_name,
            'transfer_id': transfer_id,
            'transfer_timestamp': transfer_timestamp.isoformat()
        }
        
        incoming_metadata = {
            'transfer_type': 'incoming',
            'source_wallet_id': self.id,
            'source_wallet_name': self.wallet_name,
            'transfer_id': transfer_id,
            'transfer_timestamp': transfer_timestamp.isoformat()
        }
        
        # Create secure outgoing transaction
        outgoing = SecureWalletTransaction.create_secure_transaction(
            wallet_id=self.id,
            user_id=current_user.id if current_user else self.user.id,
            amount=amount,
            transaction_type=TransactionType.TRANSFER,
            description=f"Transfer to {target_wallet.wallet_name}: {description}" if description else f"Transfer to {target_wallet.wallet_name}",
            metadata=outgoing_metadata,
            transaction_date=transfer_timestamp
        )
        
        # Create secure incoming transaction
        incoming = SecureWalletTransaction.create_secure_transaction(
            wallet_id=target_wallet.id,
            user_id=current_user.id if current_user else self.user.id,
            amount=amount,
            transaction_type=TransactionType.TRANSFER,
            description=f"Transfer from {self.wallet_name}: {description}" if description else f"Transfer from {self.wallet_name}",
            metadata=incoming_metadata,
            transaction_date=transfer_timestamp
        )
        
        # Link transactions cryptographically
        outgoing.linked_transaction_id = incoming.id
        incoming.linked_transaction_id = outgoing.id
        
        # Update transfer signatures to include both transaction IDs
        outgoing._update_transfer_signature(incoming.id)
        incoming._update_transfer_signature(outgoing.id)
        
        # Check if either transaction requires approval
        source_requires_approval = (
            self.require_approval and 
            self.approval_limit and 
            amount > self.approval_limit
        )
        
        if source_requires_approval:
            outgoing.status = TransactionStatus.PENDING.value
            incoming.status = TransactionStatus.PENDING.value
            outgoing.requires_approval = True
        else:
            # Apply balance changes immediately
            outgoing.status = TransactionStatus.COMPLETED.value
            incoming.status = TransactionStatus.COMPLETED.value
            
            self.balance -= amount
            self.available_balance -= amount
            self.last_transaction_date = transfer_timestamp
            
            target_wallet.balance += amount
            target_wallet.available_balance += amount
            target_wallet.last_transaction_date = transfer_timestamp
        
        # Add to session
        from pgappforge import db
        db.session.add(outgoing)
        db.session.add(incoming)
        
        # Create approval workflow if required
        if source_requires_approval:
            self._create_transaction_approval_workflow(outgoing)
        
        if auto_commit:
            db.session.commit()
        
        return outgoing, incoming
    
    def get_balance_history(self, days: int = 30) -> List[Dict]:
        """Get balance history for the specified number of days."""
        end_date = datetime.now(tz=timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Get transactions in date range with optimized query
        from sqlalchemy.orm import selectinload
        transactions = db.session.query(WalletTransaction).options(
            selectinload(WalletTransaction.category)
        ).filter(
            WalletTransaction.wallet_id == self.id,
            WalletTransaction.transaction_date >= start_date,
            WalletTransaction.transaction_date <= end_date,
            WalletTransaction.status == TransactionStatus.COMPLETED.value
        ).order_by(WalletTransaction.transaction_date.asc()).all()
        
        # Calculate running balance
        balance_history = []
        current_balance = self.balance
        
        # Start from current balance and work backwards
        for i in range(len(transactions) - 1, -1, -1):
            trans = transactions[i]
            if trans.transaction_type == TransactionType.INCOME.value:
                current_balance -= trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE.value:
                current_balance += trans.amount
        
        # Now work forward to create history
        for trans in transactions:
            if trans.transaction_type == TransactionType.INCOME.value:
                current_balance += trans.amount
            elif trans.transaction_type == TransactionType.EXPENSE.value:
                current_balance -= trans.amount
            
            balance_history.append({
                'date': trans.transaction_date,
                'balance': float(current_balance),
                'transaction_id': trans.id,
                'transaction_type': trans.transaction_type,
                'amount': float(trans.amount)
            })
        
        return balance_history
    
    @validates('currency_code')
    def validate_currency_code(self, key, currency_code):
        """Validate currency code format."""
        if currency_code and len(currency_code) != 3:
            raise ValueError("Currency code must be 3 characters")
        return currency_code.upper() if currency_code else currency_code
    
    # MPESA integration relationships
    mpesa_accounts = relationship("MPESAAccount", back_populates="wallet", cascade="all, delete-orphan")
    
    # Backward compatibility property (lazy loaded fallback)
    def get_mpesa_accounts(self):
        """Get MPESA accounts linked to this wallet (fallback method)"""
        try:
            from .mpesa_models import MPESAAccount
            from pgappforge import db
            return db.session.query(MPESAAccount).filter_by(wallet_id=self.id, is_active=True).all()
        except ImportError:
            return []
    
    def has_mpesa_integration(self):
        """Check if wallet has MPESA integration"""
        return len(self.mpesa_accounts) > 0
    
    def get_active_mpesa_accounts(self):
        """Get active MPESA accounts for this wallet"""
        return [acc for acc in self.mpesa_accounts if acc.is_active and acc.is_verified]
    
    def deposit(self, amount: Decimal, description: str = None, 
               reference: str = None, auto_commit: bool = True) -> 'WalletTransaction':
        """
        Deposit funds into wallet (convenience method for income transactions).
        
        Args:
            amount: Amount to deposit
            description: Transaction description
            reference: Transaction reference (stored in metadata)
            auto_commit: Whether to commit the transaction immediately
            
        Returns:
            WalletTransaction: The created transaction record
        """
        metadata = {'reference': reference} if reference else None
        
        return self.add_transaction(
            amount=amount,
            transaction_type=TransactionType.INCOME,
            description=description or "Deposit",
            metadata=metadata,
            auto_commit=auto_commit
        )
    
    def cashout(self, amount: Decimal, destination: str, description: str = None,
               reference: str = None, auto_commit: bool = True) -> 'WalletTransaction':
        """
        Cash out funds from wallet to external system (creates expense transaction).
        
        Args:
            amount: Amount to cash out
            destination: Destination identifier (e.g., phone number, bank account)
            description: Transaction description
            reference: Transaction reference (stored in metadata)
            auto_commit: Whether to commit the transaction immediately
            
        Returns:
            WalletTransaction: The created transaction record
        """
        metadata = {
            'destination': destination,
            'cashout_type': 'external'
        }
        if reference:
            metadata['reference'] = reference
        
        return self.add_transaction(
            amount=amount,
            transaction_type=TransactionType.EXPENSE,
            description=description or f"Cashout to {destination}",
            metadata=metadata,
            auto_commit=auto_commit
        )
    
    def withdraw(self, amount: Decimal, description: str = None,
                reference: str = None, auto_commit: bool = True) -> 'WalletTransaction':
        """
        Withdraw funds from wallet (creates expense transaction).
        
        Args:
            amount: Amount to withdraw
            description: Transaction description
            reference: Transaction reference (stored in metadata)
            auto_commit: Whether to commit the transaction immediately
            
        Returns:
            WalletTransaction: The created transaction record
        """
        metadata = {
            'withdrawal_type': 'manual',
            'reference': reference
        } if reference else {'withdrawal_type': 'manual'}
        
        return self.add_transaction(
            amount=amount,
            transaction_type=TransactionType.EXPENSE,
            description=description or "Withdrawal",
            metadata=metadata,
            auto_commit=auto_commit
        )
    
    def get_statement(self, start_date: datetime = None, end_date: datetime = None,
                     transaction_type: str = None, limit: int = None,
                     include_balance: bool = True) -> Dict[str, Any]:
        """
        Generate detailed wallet statement with comprehensive transaction history.
        
        Args:
            start_date: Start date for statement (defaults to 30 days ago)
            end_date: End date for statement (defaults to now)
            transaction_type: Filter by transaction type (income, expense, transfer)
            limit: Maximum number of transactions to include
            include_balance: Whether to include running balance calculations
            
        Returns:
            Dict containing statement data with transactions and summary
        """
        from datetime import datetime, timedelta
        from pgappforge import db
        from sqlalchemy import and_
        
        # Set default date range if not provided
        if not end_date:
            end_date = datetime.now(tz=timezone.utc)
        if not start_date:
            start_date = end_date - timedelta(days=30)
        
        # Build optimized query for transactions in date range with eager loading
        from sqlalchemy.orm import selectinload
        query = db.session.query(WalletTransaction).options(
            selectinload(WalletTransaction.category),
            selectinload(WalletTransaction.payment_method),
            selectinload(WalletTransaction.mpesa_transaction)
        ).filter(
            and_(
                WalletTransaction.wallet_id == self.id,
                WalletTransaction.transaction_date >= start_date,
                WalletTransaction.transaction_date <= end_date
            )
        )
        
        # Apply transaction type filter if specified
        if transaction_type:
            query = query.filter(WalletTransaction.transaction_type == transaction_type)
        
        # Order by date (newest first) and apply limit
        query = query.order_by(WalletTransaction.transaction_date.desc())
        if limit:
            query = query.limit(limit)
        
        transactions = query.all()
        
        # Calculate summary statistics
        total_income = Decimal('0')
        total_expense = Decimal('0')
        transaction_count = len(transactions)
        
        # Process transactions for statement
        statement_transactions = []
        running_balance = self.balance if include_balance else None
        
        # If including balance, we need to calculate from oldest to newest
        if include_balance:
            # Reverse order for balance calculation
            transactions_for_balance = list(reversed(transactions))
            
            # Calculate starting balance (current balance minus net changes)
            net_change = Decimal('0')
            for txn in transactions:
                if txn.transaction_type == TransactionType.INCOME.value:
                    net_change += txn.amount
                elif txn.transaction_type == TransactionType.EXPENSE.value:
                    net_change -= txn.amount
            
            starting_balance = self.balance - net_change
            running_balance = starting_balance
        
        # Process each transaction
        for i, txn in enumerate(transactions):
            # Update totals
            if txn.transaction_type == TransactionType.INCOME.value:
                total_income += txn.amount
                if include_balance:
                    running_balance += txn.amount
            elif txn.transaction_type == TransactionType.EXPENSE.value:
                total_expense += txn.amount
                if include_balance:
                    running_balance -= txn.amount
            
            # Parse metadata
            metadata = {}
            if txn.metadata_json:
                try:
                    import json
                    metadata = json.loads(txn.metadata_json)
                except json.JSONDecodeError:
                    metadata = {}
            
            # Determine transaction details
            transaction_details = {
                'id': txn.id,
                'date': txn.transaction_date.isoformat(),
                'type': txn.transaction_type,
                'amount': float(txn.amount),
                'description': txn.description,
                'reference': txn.reference_number,
                'status': txn.status,
                'category': txn.category.name if txn.category else None,
                'payment_method': txn.payment_method.name if txn.payment_method else None,
                'metadata': metadata,
                'is_mpesa': txn.is_mpesa_transaction()
            }
            
            # Add running balance if requested
            if include_balance:
                # For display, show balance after this transaction
                # Since we're displaying newest first, reverse the running balance calculation
                display_balance = running_balance
                if i < len(transactions) - 1:  # Not the oldest transaction
                    next_txn = transactions[i + 1]
                    if next_txn.transaction_type == TransactionType.INCOME.value:
                        display_balance -= next_txn.amount
                    elif next_txn.transaction_type == TransactionType.EXPENSE.value:
                        display_balance += next_txn.amount
                
                transaction_details['balance_after'] = float(display_balance)
            
            statement_transactions.append(transaction_details)
        
        # Build complete statement
        statement = {
            'wallet': {
                'id': self.id,
                'name': self.wallet_name,
                'current_balance': float(self.balance),
                'currency': self.currency_code
            },
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'days': (end_date - start_date).days + 1
            },
            'summary': {
                'transaction_count': transaction_count,
                'total_income': float(total_income),
                'total_expense': float(total_expense),
                'net_change': float(total_income - total_expense),
                'average_transaction': float((total_income + total_expense) / transaction_count) if transaction_count > 0 else 0
            },
            'transactions': statement_transactions,
            'generated_at': datetime.now(tz=timezone.utc).isoformat(),
            'include_balance': include_balance
        }
        
        return statement
    
    def get_monthly_summary(self, year: int = None, month: int = None) -> Dict[str, Any]:
        """
        Get monthly transaction summary for a specific month.
        
        Args:
            year: Year for summary (defaults to current year)
            month: Month for summary (defaults to current month)
            
        Returns:
            Dict containing monthly summary data
        """
        from datetime import datetime
        from calendar import monthrange
        
        if not year:
            year = datetime.now().year
        if not month:
            month = datetime.now().month
        
        # Get first and last day of month
        start_date = datetime(year, month, 1)
        last_day = monthrange(year, month)[1]
        end_date = datetime(year, month, last_day, 23, 59, 59)
        
        # Get statement for the month
        statement = self.get_statement(
            start_date=start_date,
            end_date=end_date,
            include_balance=False
        )
        
        # Add month-specific information
        statement['period']['month_name'] = start_date.strftime('%B')
        statement['period']['year'] = year
        statement['period']['month'] = month
        
        return statement
    
    def __repr__(self):
        return f"<UserWallet(id={self.id}, user_id={self.user_id}, name='{self.wallet_name}', balance={self.balance} {self.currency_code})>"


class WalletTransaction(AuditMixin, Model):
    """
    Transaction model for recording all wallet activities.
    
    Provides comprehensive transaction tracking with categorization,
    metadata, and audit trails.
    """
    
    __tablename__ = 'ab_wallet_transactions'
    __table_args__ = (
        Index('ix_wallet_transactions_wallet_date', 'wallet_id', 'transaction_date'),
        Index('ix_wallet_transactions_type_status', 'transaction_type', 'status'),
        Index('ix_wallet_transactions_category', 'category_id'),
        Index('ix_wallet_transactions_user_date', 'user_id', 'transaction_date'),
        CheckConstraint('amount > 0', name='ck_transaction_amount_positive')
    )
    
    # Core transaction fields
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('ab_user_wallets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Transaction details
    amount = Column(Numeric(precision=15, scale=2), nullable=False)
    transaction_type = Column(String(20), nullable=False)  # income, expense, transfer, refund, adjustment
    status = Column(String(20), nullable=False, default='completed')
    transaction_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Transaction metadata
    description = Column(Text, nullable=True)
    reference_number = Column(String(100), nullable=True)
    external_id = Column(String(100), nullable=True)  # External system reference
    
    # Categorization
    category_id = Column(Integer, ForeignKey('ab_transaction_categories.id'), nullable=True)
    tags = Column(Text, nullable=True)  # JSON array of tags
    
    # Payment details
    payment_method_id = Column(Integer, ForeignKey('ab_payment_methods.id'), nullable=True)
    
    # Additional data
    metadata_json = Column(Text, nullable=True)  # JSON metadata
    receipt_url = Column(String(500), nullable=True)
    location = Column(String(200), nullable=True)
    
    # Processing details
    processed_date = Column(DateTime, nullable=True)
    processor_id = Column(String(100), nullable=True)
    processing_fee = Column(Numeric(precision=15, scale=2), nullable=True, default=0.00)
    
    # Security and approval
    transaction_hash = Column(String(128), nullable=True)  # SHA-512 hash
    digital_signature = Column(Text, nullable=True)  # Cryptographic signature
    requires_approval = Column(Boolean, nullable=False, default=False)
    approval_workflow_id = Column(Integer, nullable=True)  # Link to approval workflow
    approved_by_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    
    # Transfer linking
    linked_transaction_id = Column(Integer, ForeignKey('ab_wallet_transactions.id'), nullable=True)
    
    # Relationships
    wallet = relationship("UserWallet", back_populates="transactions")
    user = relationship("User", foreign_keys=[user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    category = relationship("TransactionCategory", backref="transactions")
    payment_method = relationship("PaymentMethod", backref="transactions")
    linked_transaction = relationship("WalletTransaction", remote_side=[id])
    
    # Search configuration
    __searchable__ = {
        'description': 'A',
        'reference_number': 'B', 
        'tags': 'C'
    }
    
    @hybrid_property
    def metadata(self):
        """Get metadata as dictionary."""
        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @metadata.setter
    def metadata(self, value):
        """Set metadata from dictionary."""
        if value is not None:
            self.metadata_json = json.dumps(value)
        else:
            self.metadata_json = None
    
    @hybrid_property
    def tag_list(self):
        """Get tags as list."""
        if self.tags:
            try:
                return json.loads(self.tags)
            except (json.JSONDecodeError, TypeError):
                return []
        return []
    
    @tag_list.setter
    def tag_list(self, value):
        """Set tags from list."""
        if value is not None:
            self.tags = json.dumps(value)
        else:
            self.tags = None
    
    def add_tag(self, tag: str):
        """Add a tag to the transaction."""
        tags = self.tag_list
        if tag not in tags:
            tags.append(tag)
            self.tag_list = tags
    
    def remove_tag(self, tag: str):
        """Remove a tag from the transaction."""
        tags = self.tag_list
        if tag in tags:
            tags.remove(tag)
            self.tag_list = tags
    
    @validates('transaction_type')
    def validate_transaction_type(self, key, transaction_type):
        """Validate transaction type."""
        valid_types = [t.value for t in TransactionType]
        if transaction_type not in valid_types:
            raise ValueError(f"Invalid transaction type: {transaction_type}")
        return transaction_type
    
    @validates('status')
    def validate_status(self, key, status):
        """Validate transaction status."""
        valid_statuses = [s.value for s in TransactionStatus]
        if status not in valid_statuses:
            raise ValueError(f"Invalid transaction status: {status}")
        return status
    
    # MPESA integration relationship
    mpesa_transaction = relationship("MPESATransaction", back_populates="wallet_transaction", uselist=False)
    
    def is_mpesa_transaction(self):
        """Check if this transaction came from MPESA"""
        return self.mpesa_transaction is not None
    
    def verify_transaction_integrity(self) -> bool:
        """Verify transaction cryptographic integrity."""
        if not self.transaction_hash or not self.digital_signature:
            return False
        
        # Recreate hash from transaction data
        expected_hash = self._calculate_transaction_hash()
        return hmac.compare_digest(self.transaction_hash, expected_hash)
    
    def _calculate_transaction_hash(self) -> str:
        """Calculate SHA-512 hash of transaction data."""
        # Include all critical transaction fields
        data_to_hash = (
            f"{self.wallet_id}|{self.user_id}|{self.amount}|"
            f"{self.transaction_type}|{self.transaction_date.isoformat()}|"
            f"{self.reference_number or ''}|{self.description or ''}"
        )
        
        return hashlib.sha512(data_to_hash.encode('utf-8')).hexdigest()
    
    def _generate_digital_signature(self) -> str:
        """Generate HMAC digital signature for transaction."""
        # Use application secret key for HMAC
        secret_key = current_app.config.get('SECRET_KEY', '').encode('utf-8')
        transaction_hash = self._calculate_transaction_hash()
        
        return hmac.new(
            secret_key,
            transaction_hash.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def approve_transaction(self, approver_id: int, auto_commit: bool = True) -> bool:
        """Approve a pending transaction and apply balance changes.
        
        SECURITY FIX: Added database-level locking to prevent race conditions
        during concurrent transaction approvals and balance updates.
        """
        if self.status != TransactionStatus.PENDING.value:
            raise ValueError(f"Cannot approve transaction with status: {self.status}")
        
        if not self.requires_approval:
            raise ValueError("Transaction does not require approval")
        
        # Verify transaction integrity before approval
        if not self.verify_transaction_integrity():
            raise ValueError("Transaction failed integrity check - cannot approve")
        
        # Use PgAppForge's session access pattern
        from flask import g
        db_session = g.appbuilder.get_session if hasattr(g, 'appbuilder') else None
        if not db_session:
            from pgappforge import db
            db_session = db.session
        
        try:
            # CRITICAL: Use database-level locking for wallet balance updates
            with self.wallet._lock_wallet_for_transaction() as locked_wallet:
                # Double-check transaction status after acquiring lock
                fresh_transaction = db_session.query(WalletTransaction).filter_by(
                    id=self.id
                ).with_for_update().first()
                
                if not fresh_transaction or fresh_transaction.status != TransactionStatus.PENDING.value:
                    raise ValueError(f"Transaction {self.id} no longer pending (concurrent modification)")
                
                # Update approval fields on the locked transaction
                fresh_transaction.approved_by_id = approver_id
                fresh_transaction.approved_at = datetime.now(tz=timezone.utc)
                fresh_transaction.status = TransactionStatus.COMPLETED.value
                
                # Apply balance changes to locked wallet
                transaction_type = TransactionType(fresh_transaction.transaction_type)
                locked_wallet._apply_transaction_to_balance(fresh_transaction, transaction_type, fresh_transaction.amount)
                
                # Handle linked transactions (transfers) with proper locking
                if fresh_transaction.linked_transaction_id:
                    linked_txn = db_session.query(WalletTransaction).filter_by(
                        id=fresh_transaction.linked_transaction_id
                    ).with_for_update().first()
                    
                    if linked_txn and linked_txn.status == TransactionStatus.PENDING.value:
                        # Lock the target wallet for the linked transaction
                        with linked_txn.wallet._lock_wallet_for_transaction() as linked_locked_wallet:
                            linked_txn.approved_by_id = approver_id
                            linked_txn.approved_at = datetime.now(tz=timezone.utc)
                            linked_txn.status = TransactionStatus.COMPLETED.value
                            
                            # Apply balance to target wallet
                            linked_type = TransactionType(linked_txn.transaction_type)
                            linked_locked_wallet._apply_transaction_to_balance(
                                linked_txn, linked_type, linked_txn.amount
                            )
                
                # Log approval in audit trail
                WalletAudit.log_event(
                    wallet_id=fresh_transaction.wallet_id,
                    user_id=approver_id,
                    transaction_id=fresh_transaction.id,
                    event_type='transaction_approved',
                    event_description=f'Transaction {fresh_transaction.id} approved by user {approver_id}',
                    metadata={'approved_amount': float(fresh_transaction.amount)},
                    auto_commit=False
                )
                
                # Update instance attributes to reflect locked instance state
                self.approved_by_id = fresh_transaction.approved_by_id
                self.approved_at = fresh_transaction.approved_at
                self.status = fresh_transaction.status
            
            if auto_commit:
                db_session.commit()
                log.info(f"Transaction {self.id} approved successfully with database locking")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to approve transaction {self.id} with locking: {str(e)}")
            if auto_commit:
                db_session.rollback()
            raise
    
    def reject_transaction(self, approver_id: int, reason: str, auto_commit: bool = True) -> bool:
        """Reject a pending transaction.
        
        SECURITY FIX: Added database-level locking to prevent race conditions
        between concurrent approve/reject operations on the same transaction.
        """
        if self.status != TransactionStatus.PENDING.value:
            raise ValueError(f"Cannot reject transaction with status: {self.status}")
        
        # Use PgAppForge's session access pattern
        from flask import g
        db_session = g.appbuilder.get_session if hasattr(g, 'appbuilder') else None
        if not db_session:
            from pgappforge import db
            db_session = db.session
        
        try:
            # CRITICAL: Use database-level locking to prevent concurrent approve/reject
            fresh_transaction = db_session.query(WalletTransaction).filter_by(
                id=self.id
            ).with_for_update().first()
            
            if not fresh_transaction:
                raise ValueError(f"Transaction {self.id} not found")
            
            # Double-check transaction status after acquiring lock
            if fresh_transaction.status != TransactionStatus.PENDING.value:
                raise ValueError(f"Transaction {self.id} no longer pending (concurrent modification)")
            
            # Update transaction on the locked instance
            fresh_transaction.approved_by_id = approver_id
            fresh_transaction.approved_at = datetime.now(tz=timezone.utc)
            fresh_transaction.status = TransactionStatus.CANCELLED.value
            
            # Add rejection reason to metadata
            current_metadata = fresh_transaction.metadata.copy() if fresh_transaction.metadata else {}
            current_metadata['rejection_reason'] = reason
            current_metadata['rejected_by'] = approver_id
            current_metadata['rejected_at'] = datetime.now(tz=timezone.utc).isoformat()
            fresh_transaction.metadata = current_metadata
            
            # Handle linked transactions (transfers) with proper locking
            if fresh_transaction.linked_transaction_id:
                linked_txn = db_session.query(WalletTransaction).filter_by(
                    id=fresh_transaction.linked_transaction_id
                ).with_for_update().first()
                
                if linked_txn and linked_txn.status == TransactionStatus.PENDING.value:
                    linked_txn.approved_by_id = approver_id
                    linked_txn.approved_at = datetime.now(tz=timezone.utc)
                    linked_txn.status = TransactionStatus.CANCELLED.value
                    
                    # Add rejection reason to linked transaction
                    linked_metadata = linked_txn.metadata.copy() if linked_txn.metadata else {}
                    linked_metadata['rejection_reason'] = reason
                    linked_metadata['rejected_by'] = approver_id
                    linked_metadata['rejected_at'] = datetime.now(tz=timezone.utc).isoformat()
                    linked_txn.metadata = linked_metadata
            
            # Log rejection in audit trail
            WalletAudit.log_event(
                wallet_id=fresh_transaction.wallet_id,
                user_id=approver_id,
                transaction_id=fresh_transaction.id,
                event_type='transaction_rejected',
                event_description=f'Transaction {fresh_transaction.id} rejected by user {approver_id}: {reason}',
                metadata={'rejected_amount': float(fresh_transaction.amount), 'reason': reason},
                auto_commit=False
            )
            
            # Update instance attributes to reflect locked instance state
            self.approved_by_id = fresh_transaction.approved_by_id
            self.approved_at = fresh_transaction.approved_at
            self.status = fresh_transaction.status
            self.metadata = fresh_transaction.metadata
            
            if auto_commit:
                db_session.commit()
                log.info(f"Transaction {self.id} rejected successfully with database locking")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to reject transaction {self.id}: {str(e)}")
            if auto_commit:
                db_session.rollback()
            raise
    
    def __repr__(self):
        return f"<WalletTransaction(id={self.id}, wallet_id={self.wallet_id}, amount={self.amount}, type='{self.transaction_type}')>"


class TransactionCategory(AuditMixin, Model):
    """
    Categories for organizing transactions.
    
    Provides hierarchical categorization with budgeting integration
    and spending analysis capabilities.
    """
    
    __tablename__ = 'ab_transaction_categories'
    __table_args__ = (
        Index('ix_transaction_categories_parent', 'parent_id'),
        Index('ix_transaction_categories_type', 'category_type'),
        UniqueConstraint('name', 'parent_id', 'user_id', name='uq_category_name_parent_user')
    )
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=True)  # NULL for system categories
    
    # Category details
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)  # FontAwesome icon
    color = Column(String(7), nullable=True)  # Hex color
    
    # Hierarchy
    parent_id = Column(Integer, ForeignKey('ab_transaction_categories.id'), nullable=True)
    category_type = Column(String(20), nullable=False, default='expense')  # income, expense, transfer
    
    # Configuration
    is_system = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    
    # Budget integration
    has_budget = Column(Boolean, nullable=False, default=False)
    budget_alert_threshold = Column(Integer, nullable=True)  # Percentage threshold for alerts
    
    # Relationships
    parent = relationship("TransactionCategory", remote_side=[id], backref="children")
    user = relationship("User", foreign_keys=[user_id])
    
    @hybrid_property
    def full_name(self):
        """Get full category path."""
        if self.parent:
            return f"{self.parent.full_name} > {self.name}"
        return self.name
    
    @hybrid_property
    def transaction_count(self):
        """Get count of transactions in this category."""
        return WalletTransaction.query.filter_by(category_id=self.id).count()
    
    def get_spending_total(self, start_date: datetime = None, 
                          end_date: datetime = None, user_id: int = None) -> Decimal:
        """Get total spending in this category."""
        query = WalletTransaction.query.filter(
            WalletTransaction.category_id == self.id,
            WalletTransaction.transaction_type == TransactionType.EXPENSE.value,
            WalletTransaction.status == TransactionStatus.COMPLETED.value
        )
        
        if start_date:
            query = query.filter(WalletTransaction.transaction_date >= start_date)
        if end_date:
            query = query.filter(WalletTransaction.transaction_date <= end_date)
        if user_id:
            query = query.filter(WalletTransaction.user_id == user_id)
        
        result = query.with_entities(func.sum(WalletTransaction.amount)).scalar()
        return result or Decimal('0.00')
    
    def __repr__(self):
        return f"<TransactionCategory(id={self.id}, name='{self.name}', type='{self.category_type}')>"


# Set up event listeners for wallet balance updates
@event.listens_for(WalletTransaction, 'after_insert')
def update_wallet_balance_on_insert(mapper, connection, target):
    """Update wallet balance when transaction is inserted."""
    # This is handled in the add_transaction method to ensure consistency
    pass


@event.listens_for(WalletTransaction, 'after_update') 
def update_wallet_balance_on_update(mapper, connection, target):
    """Update wallet balance when transaction is updated."""
    # Handle status changes that affect balance
    pass


class WalletBudget(AuditMixin, Model):
    """
    Budget tracking for wallet categories and spending limits.
    
    Provides comprehensive budget management with alerts,
    rollover options, and spending analytics.
    """
    
    __tablename__ = 'ab_wallet_budgets'
    __table_args__ = (
        Index('ix_wallet_budgets_wallet_period', 'wallet_id', 'period_type'),
        Index('ix_wallet_budgets_category', 'category_id'),
        UniqueConstraint('wallet_id', 'category_id', 'period_type', 'period_start',
                        name='uq_budget_wallet_category_period')
    )
    
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('ab_user_wallets.id'), nullable=False)
    category_id = Column(Integer, ForeignKey('ab_transaction_categories.id'), nullable=True)
    
    # Budget details
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    budget_amount = Column(Numeric(precision=15, scale=2), nullable=False)
    
    # Period configuration
    period_type = Column(String(20), nullable=False)  # daily, weekly, monthly, quarterly, yearly
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    
    # Budget settings
    is_active = Column(Boolean, nullable=False, default=True)
    auto_rollover = Column(Boolean, nullable=False, default=False)
    rollover_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    
    # Alert settings
    alert_threshold_1 = Column(Integer, nullable=False, default=75)  # 75% warning
    alert_threshold_2 = Column(Integer, nullable=False, default=90)  # 90% critical
    alert_threshold_3 = Column(Integer, nullable=False, default=100) # 100% exceeded
    
    # Tracking
    spent_amount = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    remaining_amount = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    wallet = relationship("UserWallet", back_populates="budgets")
    category = relationship("TransactionCategory")
    
    @hybrid_property
    def spent_percentage(self):
        """Calculate percentage of budget spent."""
        if self.budget_amount > 0:
            return (self.spent_amount / self.budget_amount) * 100
        return 0
    
    @hybrid_property
    def is_over_budget(self):
        """Check if budget is exceeded."""
        return self.spent_amount > self.budget_amount
    
    @hybrid_property
    def alert_level(self):
        """Get current alert level (0-3)."""
        percentage = self.spent_percentage
        if percentage >= self.alert_threshold_3:
            return 3
        elif percentage >= self.alert_threshold_2:
            return 2
        elif percentage >= self.alert_threshold_1:
            return 1
        return 0
    
    def update_spent_amount(self, auto_commit: bool = True):
        """Update spent amount based on actual transactions."""
        # Calculate spent amount for this budget period
        query = WalletTransaction.query.filter(
            WalletTransaction.wallet_id == self.wallet_id,
            WalletTransaction.transaction_type == TransactionType.EXPENSE.value,
            WalletTransaction.status == TransactionStatus.COMPLETED.value,
            WalletTransaction.transaction_date >= self.period_start,
            WalletTransaction.transaction_date <= self.period_end
        )
        
        if self.category_id:
            query = query.filter(WalletTransaction.category_id == self.category_id)
        
        spent = query.with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0.00')
        
        self.spent_amount = spent
        self.remaining_amount = self.budget_amount - spent
        self.last_updated = datetime.now(tz=timezone.utc)
        
        if auto_commit:
            from pgappforge import db
            db.session.commit()
    
    def get_daily_average_spending(self) -> Decimal:
        """Get average daily spending for this budget period."""
        days_in_period = (self.period_end - self.period_start).days + 1
        if days_in_period > 0:
            return self.spent_amount / days_in_period
        return Decimal('0.00')
    
    def get_projected_spending(self) -> Decimal:
        """Project total spending based on current daily average."""
        daily_avg = self.get_daily_average_spending()
        days_in_period = (self.period_end - self.period_start).days + 1
        return daily_avg * days_in_period
    
    def __repr__(self):
        return f"<WalletBudget(id={self.id}, name='{self.name}', amount={self.budget_amount})>"


class PaymentMethod(AuditMixin, Model):
    """
    Payment methods for transactions (cards, bank accounts, etc.).
    
    Provides secure storage of payment method details with encryption
    and comprehensive transaction tracking.
    """
    
    __tablename__ = 'ab_payment_methods'
    __table_args__ = (
        Index('ix_payment_methods_user_type', 'user_id', 'method_type'),
        Index('ix_payment_methods_active', 'is_active'),
    )
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Payment method details
    name = Column(String(100), nullable=False)
    method_type = Column(String(20), nullable=False)  # cash, credit_card, etc.
    description = Column(Text, nullable=True)
    
    # Card/Account details (encrypted)
    account_number = Column(String(200), nullable=True)  # Last 4 digits only
    account_holder = Column(String(100), nullable=True)
    bank_name = Column(String(100), nullable=True)
    
    # Configuration
    is_active = Column(Boolean, nullable=False, default=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    currency_code = Column(String(3), nullable=False, default='USD')
    
    # Limits and restrictions
    daily_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    monthly_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    per_transaction_limit = Column(Numeric(precision=15, scale=2), nullable=True)
    
    # Tracking
    last_used_date = Column(DateTime, nullable=True)
    total_transactions = Column(Integer, nullable=False, default=0)
    total_amount = Column(Numeric(precision=15, scale=2), nullable=False, default=0.00)
    
    # Security
    requires_verification = Column(Boolean, nullable=False, default=False)
    verification_method = Column(String(50), nullable=True)  # sms, email, biometric
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    
    @validates('method_type')
    def validate_method_type(self, key, method_type):
        """Validate payment method type."""
        valid_types = [t.value for t in PaymentMethodType]
        if method_type not in valid_types:
            raise ValueError(f"Invalid payment method type: {method_type}")
        return method_type
    
    @hybrid_property
    def masked_account_number(self):
        """Get masked account number for display."""
        if self.account_number and len(self.account_number) > 4:
            return '*' * (len(self.account_number) - 4) + self.account_number[-4:]
        return self.account_number
    
    def can_transact(self, amount: Decimal) -> tuple[bool, str]:
        """Check if payment method can handle the transaction amount."""
        amount = Decimal(str(amount))
        
        if not self.is_active:
            return False, "Payment method is inactive"
        
        if self.per_transaction_limit and amount > self.per_transaction_limit:
            return False, f"Amount exceeds per-transaction limit of {self.currency_code} {self.per_transaction_limit}"
        
        # Check daily limit
        if self.daily_limit:
            today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_total = WalletTransaction.query.filter(
                WalletTransaction.payment_method_id == self.id,
                WalletTransaction.transaction_date >= today_start,
                WalletTransaction.status == TransactionStatus.COMPLETED.value
            ).with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0.00')
            
            if (today_total + amount) > self.daily_limit:
                return False, f"Daily limit of {self.currency_code} {self.daily_limit} exceeded"
        
        # Check monthly limit
        if self.monthly_limit:
            month_start = datetime.now(tz=timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_total = WalletTransaction.query.filter(
                WalletTransaction.payment_method_id == self.id,
                WalletTransaction.transaction_date >= month_start,
                WalletTransaction.status == TransactionStatus.COMPLETED.value
            ).with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0.00')
            
            if (month_total + amount) > self.monthly_limit:
                return False, f"Monthly limit of {self.currency_code} {self.monthly_limit} exceeded"
        
        return True, "Transaction allowed"
    
    def update_usage_stats(self, amount: Decimal, auto_commit: bool = True):
        """Update usage statistics after a transaction."""
        self.last_used_date = datetime.now(tz=timezone.utc)
        self.total_transactions += 1
        self.total_amount += Decimal(str(amount))
        
        if auto_commit:
            from pgappforge import db
            db.session.commit()
    
    def __repr__(self):
        return f"<PaymentMethod(id={self.id}, name='{self.name}', type='{self.method_type}')>"


class RecurringTransaction(AuditMixin, Model):
    """
    Recurring transaction templates for subscriptions and regular payments.
    
    Provides automated transaction scheduling with comprehensive
    recurrence patterns and exception handling.
    """
    
    __tablename__ = 'ab_recurring_transactions'
    __table_args__ = (
        Index('ix_recurring_transactions_wallet', 'wallet_id'),
        Index('ix_recurring_transactions_next_date', 'next_execution_date'),
        Index('ix_recurring_transactions_active', 'is_active'),
    )
    
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('ab_user_wallets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    
    # Transaction template
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(precision=15, scale=2), nullable=False)
    transaction_type = Column(String(20), nullable=False)
    category_id = Column(Integer, ForeignKey('ab_transaction_categories.id'), nullable=True)
    payment_method_id = Column(Integer, ForeignKey('ab_payment_methods.id'), nullable=True)
    
    # Recurrence configuration
    recurrence_pattern = Column(String(20), nullable=False)  # daily, weekly, monthly, yearly
    recurrence_interval = Column(Integer, nullable=False, default=1)  # every N periods
    
    # Schedule
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)  # NULL for indefinite
    next_execution_date = Column(DateTime, nullable=False)
    last_execution_date = Column(DateTime, nullable=True)
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    execution_count = Column(Integer, nullable=False, default=0)
    max_executions = Column(Integer, nullable=True)  # NULL for unlimited
    
    # Processing
    auto_execute = Column(Boolean, nullable=False, default=True)
    requires_approval = Column(Boolean, nullable=False, default=False)
    
    # Failure handling
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    last_error = Column(Text, nullable=True)
    
    # Relationships
    wallet = relationship("UserWallet")
    user = relationship("User", foreign_keys=[user_id])
    category = relationship("TransactionCategory")
    payment_method = relationship("PaymentMethod")
    
    def calculate_next_execution_date(self):
        """Calculate the next execution date based on recurrence pattern."""
        current_date = self.last_execution_date or self.start_date
        
        if self.recurrence_pattern == 'daily':
            next_date = current_date + timedelta(days=self.recurrence_interval)
        elif self.recurrence_pattern == 'weekly':
            next_date = current_date + timedelta(weeks=self.recurrence_interval)
        elif self.recurrence_pattern == 'monthly':
            # Handle month boundaries properly
            month = current_date.month
            year = current_date.year
            
            month += self.recurrence_interval
            while month > 12:
                month -= 12
                year += 1
            
            try:
                next_date = current_date.replace(year=year, month=month)
            except ValueError:
                # Handle cases like Jan 31 -> Feb 31 (invalid)
                next_date = current_date.replace(year=year, month=month, day=28)
                
        elif self.recurrence_pattern == 'yearly':
            next_date = current_date.replace(year=current_date.year + self.recurrence_interval)
        else:
            raise ValueError(f"Invalid recurrence pattern: {self.recurrence_pattern}")
        
        return next_date
    
    def is_ready_for_execution(self) -> bool:
        """Check if recurring transaction is ready for execution."""
        if not self.is_active:
            return False
        
        if self.next_execution_date > datetime.now(tz=timezone.utc):
            return False
        
        if self.end_date and datetime.now(tz=timezone.utc) > self.end_date:
            return False
        
        if self.max_executions and self.execution_count >= self.max_executions:
            return False
        
        return True
    
    def execute_transaction(self, auto_commit: bool = True) -> 'WalletTransaction':
        """Execute the recurring transaction."""
        if not self.is_ready_for_execution():
            raise ValueError("Recurring transaction is not ready for execution")
        
        try:
            # Create transaction
            transaction = self.wallet.add_transaction(
                amount=self.amount,
                transaction_type=TransactionType(self.transaction_type),
                description=f"{self.name}: {self.description}" if self.description else self.name,
                category_id=self.category_id,
                payment_method_id=self.payment_method_id,
                metadata={
                    'recurring_transaction_id': self.id,
                    'execution_count': self.execution_count + 1
                },
                auto_commit=False
            )
            
            # Update recurring transaction
            self.last_execution_date = datetime.now(tz=timezone.utc)
            self.execution_count += 1
            self.next_execution_date = self.calculate_next_execution_date()
            self.retry_count = 0
            self.last_error = None
            
            # Check if we've reached max executions
            if self.max_executions and self.execution_count >= self.max_executions:
                self.is_active = False
            
            if auto_commit:
                from pgappforge import db
                db.session.commit()
            
            return transaction
            
        except Exception as e:
            self.retry_count += 1
            self.last_error = str(e)
            
            if self.retry_count >= self.max_retries:
                self.is_active = False
                log.error(f"Recurring transaction {self.id} disabled after {self.max_retries} failed attempts: {e}")
            
            if auto_commit:
                from pgappforge import db
                db.session.commit()
            
            raise
    
    def __repr__(self):
        return f"<RecurringTransaction(id={self.id}, name='{self.name}', amount={self.amount})>"


class WalletAudit(AuditMixin, Model):
    """
    Audit trail for wallet operations and security events.
    
    Provides comprehensive audit logging for compliance and security monitoring.
    """
    
    __tablename__ = 'ab_wallet_audits'
    __table_args__ = (
        Index('ix_wallet_audits_wallet_date', 'wallet_id', 'audit_date'),
        Index('ix_wallet_audits_event_type', 'event_type'),
        Index('ix_wallet_audits_user', 'user_id'),
    )
    
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('ab_user_wallets.id'), nullable=True)
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    transaction_id = Column(Integer, ForeignKey('ab_wallet_transactions.id'), nullable=True)
    
    # Audit details
    event_type = Column(String(50), nullable=False)  # transaction, balance_update, settings_change, etc.
    event_description = Column(Text, nullable=False)
    audit_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Context
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(String(500), nullable=True)
    session_id = Column(String(100), nullable=True)
    
    # Data
    old_values = Column(Text, nullable=True)  # JSON
    new_values = Column(Text, nullable=True)  # JSON
    metadata_json = Column(Text, nullable=True)  # Additional audit data
    
    # Security
    risk_score = Column(Integer, nullable=False, default=0)  # 0-100 risk score
    is_suspicious = Column(Boolean, nullable=False, default=False)
    
    # Relationships
    wallet = relationship("UserWallet")
    user = relationship("User", foreign_keys=[user_id])
    transaction = relationship("WalletTransaction")
    
    @hybrid_property
    def old_data(self):
        """Get old values as dictionary."""
        if self.old_values:
            try:
                return json.loads(self.old_values)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @old_data.setter
    def old_data(self, value):
        """Set old values from dictionary."""
        if value is not None:
            self.old_values = json.dumps(value, default=str)
        else:
            self.old_values = None
    
    @hybrid_property
    def new_data(self):
        """Get new values as dictionary."""
        if self.new_values:
            try:
                return json.loads(self.new_values)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @new_data.setter
    def new_data(self, value):
        """Set new values from dictionary."""
        if value is not None:
            self.new_values = json.dumps(value, default=str)
        else:
            self.new_values = None
    
    @hybrid_property
    def metadata(self):
        """Get metadata as dictionary."""
        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
    
    @metadata.setter
    def metadata(self, value):
        """Set metadata from dictionary."""
        if value is not None:
            self.metadata_json = json.dumps(value, default=str)
        else:
            self.metadata_json = None
    
    @classmethod
    def log_event(cls, wallet_id: int, user_id: int, event_type: str, 
                  event_description: str, transaction_id: int = None,
                  old_values: dict = None, new_values: dict = None,
                  metadata: dict = None, risk_score: int = 0,
                  auto_commit: bool = True) -> 'WalletAudit':
        """Log an audit event."""
        from flask import request
        
        audit = cls(
            wallet_id=wallet_id,
            user_id=user_id,
            transaction_id=transaction_id,
            event_type=event_type,
            event_description=event_description,
            risk_score=risk_score,
            is_suspicious=risk_score > 70
        )
        
        # Set data
        if old_values:
            audit.old_data = old_values
        if new_values:
            audit.new_data = new_values
        if metadata:
            audit.metadata = metadata
        
        # Capture request context if available
        try:
            if request:
                audit.ip_address = request.remote_addr
                audit.user_agent = request.headers.get('User-Agent')
                audit.session_id = request.session.get('session_id')
        except RuntimeError:
            # Outside request context
            pass
        
        from pgappforge import db
        db.session.add(audit)
        
        if auto_commit:
            db.session.commit()
        
        return audit
    
    def __repr__(self):
        return f"<WalletAudit(id={self.id}, event='{self.event_type}', user_id={self.user_id})>"


class SecureWalletTransaction:
    """Factory class for creating secure wallet transactions with cryptographic integrity."""
    
    @staticmethod
    def create_secure_transaction(
        wallet_id: int, user_id: int, amount: Decimal, 
        transaction_type: TransactionType, description: str = None,
        category_id: int = None, payment_method_id: int = None,
        metadata: dict = None, requires_approval: bool = False,
        transaction_date: datetime = None
    ) -> WalletTransaction:
        """Create a cryptographically secure transaction."""
        
        # Generate reference number
        reference_number = f"TXN-{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}-{secrets.token_urlsafe(8)}"
        
        # Create transaction object
        transaction = WalletTransaction(
            wallet_id=wallet_id,
            user_id=user_id,
            amount=amount,
            transaction_type=transaction_type.value,
            description=description,
            category_id=category_id,
            payment_method_id=payment_method_id,
            metadata_json=json.dumps(metadata) if metadata else None,
            reference_number=reference_number,
            transaction_date=transaction_date or datetime.now(tz=timezone.utc),
            requires_approval=requires_approval
        )
        
        # Generate cryptographic hash and signature
        transaction.transaction_hash = transaction._calculate_transaction_hash()
        transaction.digital_signature = transaction._generate_digital_signature()
        
        return transaction
    
    @staticmethod
    def verify_transaction_chain(transactions: List[WalletTransaction]) -> bool:
        """Verify integrity of a chain of transactions."""
        for transaction in transactions:
            if not transaction.verify_transaction_integrity():
                log.warning(f"Transaction {transaction.id} failed integrity check")
                return False
        return True


# Additional wallet transaction security methods
class WalletTransactionSecurityMixin:
    """Mixin to add security methods to WalletTransaction."""
    
    def _update_transfer_signature(self, linked_transaction_id: int):
        """Update signature to include linked transaction for transfers."""
        if self.transaction_type == TransactionType.TRANSFER.value:
            # Include linked transaction in signature
            enhanced_data = f"{self._calculate_transaction_hash()}|{linked_transaction_id}"
            secret_key = current_app.config.get('SECRET_KEY', '').encode('utf-8')
            
            self.digital_signature = hmac.new(
                secret_key,
                enhanced_data.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()


# Apply security mixin to WalletTransaction
WalletTransaction.__bases__ = WalletTransaction.__bases__ + (WalletTransactionSecurityMixin,)


__all__ = [
    'TransactionType',
    'TransactionStatus', 
    'BudgetPeriod',
    'PaymentMethodType',
    'UserWallet',
    'WalletTransaction',
    'TransactionCategory',
    'WalletBudget',
    'PaymentMethod',
    'RecurringTransaction',
    'WalletAudit',
    'SecureWalletTransaction'
]