"""
Wallet Services Layer

This module provides business logic services for the wallet system,
including transaction processing, budget management, and analytics.
"""

import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum

from flask import current_app
from flask_appbuilder import db
from flask_appbuilder.security import current_user
from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import sessionmaker

from .models import (
    UserWallet, WalletTransaction, TransactionCategory, WalletBudget,
    PaymentMethod, RecurringTransaction, WalletAudit,
    TransactionType, TransactionStatus, BudgetPeriod, PaymentMethodType
)

log = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


class InsufficientFundsError(Exception):
    """Custom exception for insufficient funds."""
    pass


class TransactionNotAllowedError(Exception):
    """Custom exception for disallowed transactions."""
    pass


@dataclass
class TransactionRequest:
    """Data class for transaction requests."""
    amount: Decimal
    transaction_type: TransactionType
    description: str = None
    category_id: int = None
    payment_method_id: int = None
    metadata: dict = None
    reference_number: str = None
    external_id: str = None
    location: str = None
    receipt_url: str = None
    tags: List[str] = None


@dataclass
class TransferRequest:
    """Data class for transfer requests."""
    source_wallet_id: int
    target_wallet_id: int
    amount: Decimal
    description: str = None
    metadata: dict = None


@dataclass
class BudgetAnalytics:
    """Data class for budget analytics."""
    budget_id: int
    budget_name: str
    budget_amount: Decimal
    spent_amount: Decimal
    remaining_amount: Decimal
    spent_percentage: float
    alert_level: int
    days_remaining: int
    daily_average_spending: Decimal
    projected_spending: Decimal
    is_on_track: bool


class WalletService:
    """
    Core wallet service for wallet management and operations.
    
    Provides high-level wallet operations with business logic,
    validation, and audit trails.
    """
    
    @staticmethod
    def create_wallet(user_id: int, wallet_name: str, currency_code: str = 'USD',
                      description: str = None, wallet_type: str = 'personal',
                      is_primary: bool = False, auto_commit: bool = True) -> UserWallet:
        """
        Create a new wallet for a user.
        
        Args:
            user_id: ID of the user
            wallet_name: Name of the wallet
            currency_code: Currency code (ISO 4217)
            description: Optional wallet description
            wallet_type: Type of wallet (personal, business, etc.)
            is_primary: Whether this is the primary wallet
            auto_commit: Whether to commit the transaction
            
        Returns:
            Created UserWallet instance
        """
        try:
            # Validate currency code
            if len(currency_code) != 3:
                raise ValidationError("Currency code must be 3 characters")
            
            # Check if wallet name already exists for user
            existing = UserWallet.query.filter_by(
                user_id=user_id,
                wallet_name=wallet_name,
                currency_code=currency_code.upper()
            ).first()
            
            if existing:
                raise ValidationError(f"Wallet '{wallet_name}' with currency {currency_code} already exists")
            
            # If this is the first wallet for user, make it primary
            user_wallet_count = UserWallet.query.filter_by(user_id=user_id).count()
            if user_wallet_count == 0:
                is_primary = True
            
            # If setting as primary, unset other primary wallets
            if is_primary:
                UserWallet.query.filter_by(
                    user_id=user_id,
                    is_primary=True
                ).update({'is_primary': False})
            
            # Create wallet
            wallet = UserWallet(
                user_id=user_id,
                wallet_name=wallet_name,
                currency_code=currency_code.upper(),
                description=description,
                wallet_type=wallet_type,
                is_primary=is_primary,
                balance=Decimal('0.00'),
                available_balance=Decimal('0.00'),
                pending_balance=Decimal('0.00')
            )
            
            db.session.add(wallet)
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=wallet.id,
                user_id=user_id,
                event_type='wallet_created',
                event_description=f"Wallet '{wallet_name}' created",
                new_values={
                    'wallet_name': wallet_name,
                    'currency_code': currency_code,
                    'wallet_type': wallet_type,
                    'is_primary': is_primary
                },
                auto_commit=auto_commit
            )
            
            log.info(f"Created wallet '{wallet_name}' for user {user_id}")
            return wallet
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to create wallet: {e}")
            raise
    
    @staticmethod
    def get_user_wallets(user_id: int, include_inactive: bool = False) -> List[UserWallet]:
        """
        Get all wallets for a user.
        
        Args:
            user_id: ID of the user
            include_inactive: Whether to include inactive wallets
            
        Returns:
            List of UserWallet instances
        """
        query = UserWallet.query.filter_by(user_id=user_id)
        
        if not include_inactive:
            query = query.filter_by(is_active=True)
        
        return query.order_by(
            UserWallet.is_primary.desc(),
            UserWallet.wallet_name.asc()
        ).all()
    
    @staticmethod
    def get_primary_wallet(user_id: int) -> Optional[UserWallet]:
        """
        Get the primary wallet for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Primary UserWallet or None if not found
        """
        return UserWallet.query.filter_by(
            user_id=user_id,
            is_primary=True,
            is_active=True
        ).first()
    
    @staticmethod
    def update_wallet_settings(wallet_id: int, user_id: int, updates: Dict[str, Any],
                             auto_commit: bool = True) -> UserWallet:
        """
        Update wallet settings.
        
        Args:
            wallet_id: ID of the wallet
            user_id: ID of the user (for security)
            updates: Dictionary of fields to update
            auto_commit: Whether to commit the transaction
            
        Returns:
            Updated UserWallet instance
        """
        try:
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            # Store old values for audit
            old_values = {}
            allowed_fields = [
                'wallet_name', 'description', 'daily_limit', 'monthly_limit',
                'allow_negative_balance', 'require_approval', 'approval_limit',
                'icon', 'color', 'is_active'
            ]
            
            for field, value in updates.items():
                if field in allowed_fields and hasattr(wallet, field):
                    old_values[field] = getattr(wallet, field)
                    setattr(wallet, field, value)
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=wallet_id,
                user_id=user_id,
                event_type='wallet_settings_updated',
                event_description=f"Wallet settings updated",
                old_values=old_values,
                new_values=updates,
                auto_commit=auto_commit
            )
            
            log.info(f"Updated wallet {wallet_id} settings")
            return wallet
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to update wallet settings: {e}")
            raise
    
    @staticmethod
    def delete_wallet(wallet_id: int, user_id: int, auto_commit: bool = True) -> bool:
        """
        Delete a wallet (soft delete if it has transactions).
        
        Args:
            wallet_id: ID of the wallet
            user_id: ID of the user (for security)
            auto_commit: Whether to commit the transaction
            
        Returns:
            True if successful
        """
        try:
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            if wallet.is_primary:
                raise ValidationError("Cannot delete primary wallet")
            
            # Check if wallet has transactions
            transaction_count = WalletTransaction.query.filter_by(
                wallet_id=wallet_id
            ).count()
            
            if transaction_count > 0:
                # Soft delete - just mark as inactive
                wallet.is_active = False
                operation = 'deactivated'
            else:
                # Hard delete - no transactions
                db.session.delete(wallet)
                operation = 'deleted'
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=wallet_id,
                user_id=user_id,
                event_type=f'wallet_{operation}',
                event_description=f"Wallet {operation}",
                old_values={
                    'wallet_name': wallet.wallet_name,
                    'balance': str(wallet.balance)
                },
                auto_commit=auto_commit
            )
            
            log.info(f"Wallet {wallet_id} {operation} for user {user_id}")
            return True
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to delete wallet: {e}")
            raise


class TransactionService:
    """
    Transaction service for processing wallet transactions.
    
    Provides transaction processing with validation, 
    categorization, and comprehensive audit trails.
    """
    
    @staticmethod
    def process_transaction(wallet_id: int, request: TransactionRequest,
                          user_id: int = None, auto_commit: bool = True) -> WalletTransaction:
        """
        Process a wallet transaction.
        
        Args:
            wallet_id: ID of the wallet
            request: TransactionRequest with transaction details
            user_id: ID of the user (optional, will use current_user if not provided)
            auto_commit: Whether to commit the transaction
            
        Returns:
            Created WalletTransaction instance
        """
        try:
            # Get user ID
            if user_id is None:
                user_id = current_user.id if current_user else None
            
            if not user_id:
                raise ValidationError("User not authenticated")
            
            # Get wallet
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            # Validate transaction
            can_transact, message = wallet.can_transact(request.amount, request.transaction_type)
            if not can_transact:
                raise TransactionNotAllowedError(message)
            
            # Validate payment method if provided
            if request.payment_method_id:
                payment_method = PaymentMethod.query.filter_by(
                    id=request.payment_method_id,
                    user_id=user_id
                ).first()
                
                if not payment_method:
                    raise ValidationError("Payment method not found")
                
                can_pay, pay_message = payment_method.can_transact(request.amount)
                if not can_pay:
                    raise TransactionNotAllowedError(pay_message)
            
            # Create transaction using wallet method
            transaction = wallet.add_transaction(
                amount=request.amount,
                transaction_type=request.transaction_type,
                description=request.description,
                category_id=request.category_id,
                payment_method_id=request.payment_method_id,
                metadata=request.metadata,
                auto_commit=False
            )
            
            # Set additional fields
            if request.reference_number:
                transaction.reference_number = request.reference_number
            if request.external_id:
                transaction.external_id = request.external_id
            if request.location:
                transaction.location = request.location
            if request.receipt_url:
                transaction.receipt_url = request.receipt_url
            if request.tags:
                transaction.tag_list = request.tags
            
            transaction.user_id = user_id
            
            # Update payment method stats
            if request.payment_method_id and transaction.status == TransactionStatus.COMPLETED.value:
                payment_method = PaymentMethod.query.get(request.payment_method_id)
                if payment_method:
                    payment_method.update_usage_stats(request.amount, auto_commit=False)
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=wallet_id,
                user_id=user_id,
                transaction_id=transaction.id,
                event_type='transaction_processed',
                event_description=f"{request.transaction_type.value} transaction of {wallet.currency_code} {request.amount}",
                new_values={
                    'amount': str(request.amount),
                    'type': request.transaction_type.value,
                    'description': request.description,
                    'category_id': request.category_id
                },
                auto_commit=auto_commit
            )
            
            log.info(f"Processed {request.transaction_type.value} transaction of {request.amount} for wallet {wallet_id}")
            return transaction
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to process transaction: {e}")
            raise
    
    @staticmethod
    def transfer_funds(request: TransferRequest, user_id: int = None,
                      auto_commit: bool = True) -> Tuple[WalletTransaction, WalletTransaction]:
        """
        Transfer funds between wallets.
        
        Args:
            request: TransferRequest with transfer details
            user_id: ID of the user (optional)
            auto_commit: Whether to commit the transaction
            
        Returns:
            Tuple of (outgoing_transaction, incoming_transaction)
        """
        try:
            # Get user ID
            if user_id is None:
                user_id = current_user.id if current_user else None
            
            if not user_id:
                raise ValidationError("User not authenticated")
            
            # Get wallets
            source_wallet = UserWallet.query.filter_by(
                id=request.source_wallet_id,
                user_id=user_id
            ).first()
            
            target_wallet = UserWallet.query.filter_by(
                id=request.target_wallet_id,
                user_id=user_id
            ).first()
            
            if not source_wallet:
                raise ValidationError("Source wallet not found or access denied")
            if not target_wallet:
                raise ValidationError("Target wallet not found or access denied")
            
            # Perform transfer using wallet method
            outgoing, incoming = source_wallet.transfer_to(
                target_wallet=target_wallet,
                amount=request.amount,
                description=request.description,
                auto_commit=False
            )
            
            # Set user IDs
            outgoing.user_id = user_id
            incoming.user_id = user_id
            
            # Add metadata if provided
            if request.metadata:
                outgoing.metadata = {**outgoing.metadata, **request.metadata}
                incoming.metadata = {**incoming.metadata, **request.metadata}
            
            if auto_commit:
                db.session.commit()
            
            # Log audit events
            for wallet_id, transaction, transaction_type in [
                (source_wallet.id, outgoing, 'outgoing'),
                (target_wallet.id, incoming, 'incoming')
            ]:
                WalletAudit.log_event(
                    wallet_id=wallet_id,
                    user_id=user_id,
                    transaction_id=transaction.id,
                    event_type=f'transfer_{transaction_type}',
                    event_description=f"Transfer {transaction_type}: {source_wallet.currency_code} {request.amount}",
                    new_values={
                        'amount': str(request.amount),
                        'description': request.description,
                        'source_wallet': source_wallet.wallet_name,
                        'target_wallet': target_wallet.wallet_name
                    },
                    auto_commit=auto_commit
                )
            
            log.info(f"Transferred {request.amount} from wallet {request.source_wallet_id} to {request.target_wallet_id}")
            return outgoing, incoming
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to transfer funds: {e}")
            raise
    
    @staticmethod
    def get_transaction_history(wallet_id: int, user_id: int, limit: int = 50,
                               offset: int = 0, transaction_type: TransactionType = None,
                               category_id: int = None, start_date: datetime = None,
                               end_date: datetime = None) -> Dict[str, Any]:
        """
        Get transaction history for a wallet.
        
        Args:
            wallet_id: ID of the wallet
            user_id: ID of the user
            limit: Maximum number of transactions to return
            offset: Offset for pagination
            transaction_type: Filter by transaction type
            category_id: Filter by category
            start_date: Filter by start date
            end_date: Filter by end date
            
        Returns:
            Dictionary with transactions and metadata
        """
        try:
            # Verify wallet access
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            # Build query
            query = WalletTransaction.query.filter_by(wallet_id=wallet_id)
            
            if transaction_type:
                query = query.filter_by(transaction_type=transaction_type.value)
            if category_id:
                query = query.filter_by(category_id=category_id)
            if start_date:
                query = query.filter(WalletTransaction.transaction_date >= start_date)
            if end_date:
                query = query.filter(WalletTransaction.transaction_date <= end_date)
            
            # Get total count
            total_count = query.count()
            
            # Get transactions
            transactions = query.order_by(
                WalletTransaction.transaction_date.desc()
            ).offset(offset).limit(limit).all()
            
            return {
                'transactions': transactions,
                'total_count': total_count,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total_count
            }
            
        except Exception as e:
            log.error(f"Failed to get transaction history: {e}")
            raise
    
    @staticmethod
    def void_transaction(transaction_id: int, user_id: int, reason: str,
                        auto_commit: bool = True) -> WalletTransaction:
        """
        Void a transaction (create a reversal).
        
        Args:
            transaction_id: ID of the transaction to void
            user_id: ID of the user
            reason: Reason for voiding
            auto_commit: Whether to commit the transaction
            
        Returns:
            Reversal transaction
        """
        try:
            # Get original transaction
            original = WalletTransaction.query.filter_by(
                id=transaction_id,
                user_id=user_id
            ).first()
            
            if not original:
                raise ValidationError("Transaction not found or access denied")
            
            if original.status != TransactionStatus.COMPLETED.value:
                raise ValidationError("Can only void completed transactions")
            
            # Create reversal transaction
            reversal_type = TransactionType.REFUND
            if original.transaction_type == TransactionType.INCOME.value:
                reversal_type = TransactionType.EXPENSE
            elif original.transaction_type == TransactionType.EXPENSE.value:
                reversal_type = TransactionType.REFUND
            
            reversal = original.wallet.add_transaction(
                amount=original.amount,
                transaction_type=reversal_type,
                description=f"VOID: {original.description} - {reason}",
                category_id=original.category_id,
                payment_method_id=original.payment_method_id,
                metadata={
                    'void_transaction_id': original.id,
                    'void_reason': reason,
                    'original_type': original.transaction_type
                },
                auto_commit=False
            )
            
            reversal.user_id = user_id
            reversal.reference_number = f"VOID-{original.id}"
            
            # Update original transaction
            original.status = TransactionStatus.CANCELLED.value
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=original.wallet_id,
                user_id=user_id,
                transaction_id=original.id,
                event_type='transaction_voided',
                event_description=f"Transaction voided: {reason}",
                old_values={
                    'status': TransactionStatus.COMPLETED.value
                },
                new_values={
                    'status': TransactionStatus.CANCELLED.value,
                    'reversal_transaction_id': reversal.id
                },
                auto_commit=auto_commit
            )
            
            log.info(f"Voided transaction {transaction_id} with reversal {reversal.id}")
            return reversal
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to void transaction: {e}")
            raise


class BudgetService:
    """
    Budget service for budget management and tracking.
    
    Provides comprehensive budget creation, monitoring,
    and analytics with alert capabilities.
    """
    
    @staticmethod
    def create_budget(wallet_id: int, user_id: int, name: str, budget_amount: Decimal,
                     period_type: BudgetPeriod, period_start: datetime = None,
                     category_id: int = None, description: str = None,
                     auto_rollover: bool = False, auto_commit: bool = True) -> WalletBudget:
        """
        Create a new budget for a wallet.
        
        Args:
            wallet_id: ID of the wallet
            user_id: ID of the user
            name: Budget name
            budget_amount: Budget amount
            period_type: Budget period type
            period_start: Start date (defaults to current period)
            category_id: Optional category to limit budget to
            description: Optional description
            auto_rollover: Whether to rollover unused budget
            auto_commit: Whether to commit the transaction
            
        Returns:
            Created WalletBudget instance
        """
        try:
            # Verify wallet access
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            # Calculate period dates
            if period_start is None:
                period_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            if period_type == BudgetPeriod.DAILY:
                period_end = period_start.replace(hour=23, minute=59, second=59)
            elif period_type == BudgetPeriod.WEEKLY:
                # Week starts on Monday
                days_since_monday = period_start.weekday()
                period_start = period_start - timedelta(days=days_since_monday)
                period_end = period_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif period_type == BudgetPeriod.MONTHLY:
                period_start = period_start.replace(day=1)
                if period_start.month == 12:
                    period_end = period_start.replace(year=period_start.year + 1, month=1) - timedelta(seconds=1)
                else:
                    period_end = period_start.replace(month=period_start.month + 1) - timedelta(seconds=1)
            elif period_type == BudgetPeriod.QUARTERLY:
                quarter_start_month = ((period_start.month - 1) // 3) * 3 + 1
                period_start = period_start.replace(month=quarter_start_month, day=1)
                if quarter_start_month + 3 > 12:
                    period_end = period_start.replace(year=period_start.year + 1, month=(quarter_start_month + 3) - 12) - timedelta(seconds=1)
                else:
                    period_end = period_start.replace(month=quarter_start_month + 3) - timedelta(seconds=1)
            elif period_type == BudgetPeriod.YEARLY:
                period_start = period_start.replace(month=1, day=1)
                period_end = period_start.replace(year=period_start.year + 1) - timedelta(seconds=1)
            else:
                raise ValidationError(f"Invalid period type: {period_type}")
            
            # Check for existing budget in same period
            existing = WalletBudget.query.filter(
                and_(
                    WalletBudget.wallet_id == wallet_id,
                    WalletBudget.category_id == category_id,
                    WalletBudget.period_type == period_type.value,
                    WalletBudget.period_start == period_start
                )
            ).first()
            
            if existing:
                raise ValidationError("Budget already exists for this period")
            
            # Create budget
            budget = WalletBudget(
                wallet_id=wallet_id,
                category_id=category_id,
                name=name,
                description=description,
                budget_amount=budget_amount,
                period_type=period_type.value,
                period_start=period_start,
                period_end=period_end,
                auto_rollover=auto_rollover,
                remaining_amount=budget_amount
            )
            
            db.session.add(budget)
            
            # Update spent amount
            budget.update_spent_amount(auto_commit=False)
            
            if auto_commit:
                db.session.commit()
            
            # Log audit event
            WalletAudit.log_event(
                wallet_id=wallet_id,
                user_id=user_id,
                event_type='budget_created',
                event_description=f"Budget '{name}' created for {budget_amount} {wallet.currency_code}",
                new_values={
                    'budget_name': name,
                    'budget_amount': str(budget_amount),
                    'period_type': period_type.value,
                    'period_start': period_start.isoformat(),
                    'period_end': period_end.isoformat()
                },
                auto_commit=auto_commit
            )
            
            log.info(f"Created budget '{name}' for wallet {wallet_id}")
            return budget
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to create budget: {e}")
            raise
    
    @staticmethod
    def get_budget_analytics(wallet_id: int, user_id: int,
                           period_type: BudgetPeriod = None) -> List[BudgetAnalytics]:
        """
        Get budget analytics for a wallet.
        
        Args:
            wallet_id: ID of the wallet
            user_id: ID of the user
            period_type: Filter by period type
            
        Returns:
            List of BudgetAnalytics instances
        """
        try:
            # Verify wallet access
            wallet = UserWallet.query.filter_by(
                id=wallet_id,
                user_id=user_id
            ).first()
            
            if not wallet:
                raise ValidationError("Wallet not found or access denied")
            
            # Build query
            query = WalletBudget.query.filter(
                and_(
                    WalletBudget.wallet_id == wallet_id,
                    WalletBudget.is_active == True,
                    WalletBudget.period_end >= datetime.now(tz=timezone.utc)
                )
            )
            
            if period_type:
                query = query.filter_by(period_type=period_type.value)
            
            budgets = query.all()
            analytics = []
            
            for budget in budgets:
                # Update spent amount
                budget.update_spent_amount(auto_commit=False)
                
                # Calculate analytics
                days_total = (budget.period_end - budget.period_start).days + 1
                days_remaining = (budget.period_end - datetime.now(tz=timezone.utc)).days + 1
                daily_avg = budget.get_daily_average_spending()
                projected = budget.get_projected_spending()
                
                # Determine if on track
                days_elapsed = days_total - days_remaining
                expected_spending = (budget.budget_amount / days_total) * days_elapsed if days_elapsed > 0 else Decimal('0')
                is_on_track = budget.spent_amount <= expected_spending * Decimal('1.1')  # 10% tolerance
                
                analytics.append(BudgetAnalytics(
                    budget_id=budget.id,
                    budget_name=budget.name,
                    budget_amount=budget.budget_amount,
                    spent_amount=budget.spent_amount,
                    remaining_amount=budget.remaining_amount,
                    spent_percentage=budget.spent_percentage,
                    alert_level=budget.alert_level,
                    days_remaining=max(0, days_remaining),
                    daily_average_spending=daily_avg,
                    projected_spending=projected,
                    is_on_track=is_on_track
                ))
            
            return analytics
            
        except Exception as e:
            log.error(f"Failed to get budget analytics: {e}")
            raise
    
    @staticmethod
    def update_all_budgets(wallet_id: int = None, auto_commit: bool = True):
        """
        Update spent amounts for all active budgets.
        
        Args:
            wallet_id: Optional wallet ID to limit updates
            auto_commit: Whether to commit the transaction
        """
        try:
            query = WalletBudget.query.filter_by(is_active=True)
            
            if wallet_id:
                query = query.filter_by(wallet_id=wallet_id)
            
            budgets = query.all()
            
            for budget in budgets:
                budget.update_spent_amount(auto_commit=False)
            
            if auto_commit:
                db.session.commit()
            
            log.info(f"Updated {len(budgets)} budgets")
            
        except Exception as e:
            if auto_commit:
                db.session.rollback()
            log.error(f"Failed to update budgets: {e}")
            raise


class CurrencyService:
    """
    Currency service for currency conversion and management.
    
    Provides currency conversion capabilities with caching
    and rate history tracking.
    """
    
    # Default exchange rates (would be replaced with live data in production)
    DEFAULT_RATES = {
        'USD': 1.0,
        'EUR': 0.85,
        'GBP': 0.73,
        'JPY': 110.0,
        'CAD': 1.25,
        'AUD': 1.35,
        'CHF': 0.92,
        'CNY': 6.45
    }
    
    @staticmethod
    def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
        """
        Get exchange rate between two currencies.
        
        Args:
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Exchange rate as Decimal
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        if from_currency == to_currency:
            return Decimal('1.0')
        
        # Simple conversion using USD as base
        from_rate = Decimal(str(CurrencyService.DEFAULT_RATES.get(from_currency, 1.0)))
        to_rate = Decimal(str(CurrencyService.DEFAULT_RATES.get(to_currency, 1.0)))
        
        if from_rate == 0 or to_rate == 0:
            raise ValidationError(f"Unsupported currency: {from_currency} or {to_currency}")
        
        # Convert: amount * (1 / from_rate) * to_rate
        rate = to_rate / from_rate
        return rate.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    
    @staticmethod
    def convert_amount(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """
        Convert an amount between currencies.
        
        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Converted amount as Decimal
        """
        rate = CurrencyService.get_exchange_rate(from_currency, to_currency)
        converted = amount * rate
        return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    @staticmethod
    def get_supported_currencies() -> List[str]:
        """
        Get list of supported currency codes.
        
        Returns:
            List of currency codes
        """
        return list(CurrencyService.DEFAULT_RATES.keys())


class AnalyticsService:
    """
    Analytics service for wallet and transaction analytics.
    
    Provides comprehensive financial analytics, reporting,
    and trend analysis capabilities.
    """
    
    @staticmethod
    def get_wallet_summary(user_id: int, currency: str = 'USD') -> Dict[str, Any]:
        """
        Get comprehensive wallet summary for a user.
        
        Args:
            user_id: ID of the user
            currency: Currency for summary (will convert if needed)
            
        Returns:
            Dictionary with wallet summary
        """
        try:
            wallets = WalletService.get_user_wallets(user_id, include_inactive=False)
            
            total_balance = Decimal('0.00')
            total_income = Decimal('0.00')
            total_expenses = Decimal('0.00')
            wallet_count = len(wallets)
            
            wallet_details = []
            
            for wallet in wallets:
                # Convert balance to target currency if needed
                balance_in_currency = wallet.balance
                if wallet.currency_code != currency:
                    balance_in_currency = CurrencyService.convert_amount(
                        wallet.balance, wallet.currency_code, currency
                    )
                
                # Convert income and expenses
                income_in_currency = wallet.total_income
                expenses_in_currency = wallet.total_expenses
                if wallet.currency_code != currency:
                    income_in_currency = CurrencyService.convert_amount(
                        wallet.total_income, wallet.currency_code, currency
                    )
                    expenses_in_currency = CurrencyService.convert_amount(
                        wallet.total_expenses, wallet.currency_code, currency
                    )
                
                total_balance += balance_in_currency
                total_income += income_in_currency
                total_expenses += expenses_in_currency
                
                wallet_details.append({
                    'id': wallet.id,
                    'name': wallet.wallet_name,
                    'currency': wallet.currency_code,
                    'balance': float(wallet.balance),
                    'balance_in_target_currency': float(balance_in_currency),
                    'is_primary': wallet.is_primary,
                    'last_transaction': wallet.last_transaction_date.isoformat() if wallet.last_transaction_date else None
                })
            
            return {
                'user_id': user_id,
                'summary_currency': currency,
                'total_balance': float(total_balance),
                'total_income': float(total_income),
                'total_expenses': float(total_expenses),
                'net_worth': float(total_income - total_expenses),
                'wallet_count': wallet_count,
                'wallets': wallet_details
            }
            
        except Exception as e:
            log.error(f"Failed to get wallet summary: {e}")
            raise
    
    @staticmethod
    def get_spending_analytics(user_id: int, wallet_id: int = None,
                             days: int = 30, group_by: str = 'category') -> Dict[str, Any]:
        """
        Get spending analytics for a user.
        
        Args:
            user_id: ID of the user
            wallet_id: Optional wallet ID to limit analysis
            days: Number of days to analyze
            group_by: How to group data ('category', 'day', 'week', 'payment_method')
            
        Returns:
            Dictionary with spending analytics
        """
        try:
            end_date = datetime.now(tz=timezone.utc)
            start_date = end_date - timedelta(days=days)
            
            # Build base query
            query = WalletTransaction.query.join(UserWallet).filter(
                and_(
                    UserWallet.user_id == user_id,
                    WalletTransaction.transaction_type == TransactionType.EXPENSE.value,
                    WalletTransaction.status == TransactionStatus.COMPLETED.value,
                    WalletTransaction.transaction_date >= start_date,
                    WalletTransaction.transaction_date <= end_date
                )
            )
            
            if wallet_id:
                query = query.filter(WalletTransaction.wallet_id == wallet_id)
            
            transactions = query.all()
            
            # Calculate totals
            total_spent = sum(t.amount for t in transactions)
            transaction_count = len(transactions)
            average_transaction = total_spent / transaction_count if transaction_count > 0 else Decimal('0')
            
            # Group data
            grouped_data = {}
            
            if group_by == 'category':
                category_totals = {}
                for transaction in transactions:
                    category_name = transaction.category.name if transaction.category else 'Uncategorized'
                    category_totals[category_name] = category_totals.get(category_name, Decimal('0')) + transaction.amount
                grouped_data = {k: float(v) for k, v in category_totals.items()}
            
            elif group_by == 'day':
                daily_totals = {}
                for transaction in transactions:
                    day_key = transaction.transaction_date.strftime('%Y-%m-%d')
                    daily_totals[day_key] = daily_totals.get(day_key, Decimal('0')) + transaction.amount
                grouped_data = {k: float(v) for k, v in daily_totals.items()}
            
            elif group_by == 'week':
                weekly_totals = {}
                for transaction in transactions:
                    # Get Monday of the week
                    monday = transaction.transaction_date - timedelta(days=transaction.transaction_date.weekday())
                    week_key = monday.strftime('%Y-W%W')
                    weekly_totals[week_key] = weekly_totals.get(week_key, Decimal('0')) + transaction.amount
                grouped_data = {k: float(v) for k, v in weekly_totals.items()}
            
            elif group_by == 'payment_method':
                method_totals = {}
                for transaction in transactions:
                    method_name = transaction.payment_method.name if transaction.payment_method else 'No Payment Method'
                    method_totals[method_name] = method_totals.get(method_name, Decimal('0')) + transaction.amount
                grouped_data = {k: float(v) for k, v in method_totals.items()}
            
            return {
                'user_id': user_id,
                'wallet_id': wallet_id,
                'period_days': days,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'group_by': group_by,
                'total_spent': float(total_spent),
                'transaction_count': transaction_count,
                'average_transaction': float(average_transaction),
                'daily_average': float(total_spent / days) if days > 0 else 0,
                'grouped_data': grouped_data
            }
            
        except Exception as e:
            log.error(f"Failed to get spending analytics: {e}")
            raise
    
    @staticmethod
    def get_trend_analysis(user_id: int, wallet_id: int = None,
                          metric: str = 'balance', periods: int = 12) -> Dict[str, Any]:
        """
        Get trend analysis for wallet metrics.
        
        Args:
            user_id: ID of the user
            wallet_id: Optional wallet ID
            metric: Metric to analyze ('balance', 'income', 'expenses')
            periods: Number of periods to analyze
            
        Returns:
            Dictionary with trend analysis
        """
        try:
            # For this example, we'll analyze monthly trends
            trends = []
            current_date = datetime.now(tz=timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            for i in range(periods):
                period_start = current_date.replace(month=current_date.month - i) if current_date.month > i else current_date.replace(year=current_date.year - 1, month=12 - (i - current_date.month))
                if period_start.month == 12:
                    period_end = period_start.replace(year=period_start.year + 1, month=1) - timedelta(seconds=1)
                else:
                    period_end = period_start.replace(month=period_start.month + 1) - timedelta(seconds=1)
                
                # Build query for period
                query = WalletTransaction.query.join(UserWallet).filter(
                    and_(
                        UserWallet.user_id == user_id,
                        WalletTransaction.status == TransactionStatus.COMPLETED.value,
                        WalletTransaction.transaction_date >= period_start,
                        WalletTransaction.transaction_date <= period_end
                    )
                )
                
                if wallet_id:
                    query = query.filter(WalletTransaction.wallet_id == wallet_id)
                
                if metric == 'income':
                    query = query.filter(WalletTransaction.transaction_type == TransactionType.INCOME.value)
                    value = query.with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0')
                elif metric == 'expenses':
                    query = query.filter(WalletTransaction.transaction_type == TransactionType.EXPENSE.value)
                    value = query.with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0')
                else:  # balance - calculate net change
                    income = query.filter(WalletTransaction.transaction_type == TransactionType.INCOME.value).with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0')
                    expenses = query.filter(WalletTransaction.transaction_type == TransactionType.EXPENSE.value).with_entities(func.sum(WalletTransaction.amount)).scalar() or Decimal('0')
                    value = income - expenses
                
                trends.append({
                    'period': period_start.strftime('%Y-%m'),
                    'period_start': period_start.isoformat(),
                    'period_end': period_end.isoformat(),
                    'value': float(value)
                })
            
            # Reverse to get chronological order
            trends.reverse()
            
            # Calculate trend metrics
            values = [t['value'] for t in trends]
            if len(values) > 1:
                trend_direction = 'increasing' if values[-1] > values[0] else 'decreasing'
                trend_slope = (values[-1] - values[0]) / len(values)
                average_value = sum(values) / len(values)
            else:
                trend_direction = 'stable'
                trend_slope = 0
                average_value = values[0] if values else 0
            
            return {
                'user_id': user_id,
                'wallet_id': wallet_id,
                'metric': metric,
                'periods': periods,
                'trends': trends,
                'trend_direction': trend_direction,
                'trend_slope': trend_slope,
                'average_value': average_value,
                'latest_value': values[-1] if values else 0,
                'earliest_value': values[0] if values else 0
            }
            
        except Exception as e:
            log.error(f"Failed to get trend analysis: {e}")
            raise


__all__ = [
    'ValidationError',
    'InsufficientFundsError', 
    'TransactionNotAllowedError',
    'TransactionRequest',
    'TransferRequest',
    'BudgetAnalytics',
    'WalletService',
    'TransactionService',
    'BudgetService', 
    'CurrencyService',
    'AnalyticsService'
]