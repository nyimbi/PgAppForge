"""
Migration for Wallet System Tables

This migration creates all the necessary tables for the wallet system:
- ab_user_wallets: User wallet configurations and balances
- ab_wallet_transactions: Transaction records with audit trails  
- ab_transaction_categories: Hierarchical transaction categories
- ab_wallet_budgets: Budget management and tracking
- ab_payment_methods: Encrypted payment method storage
- ab_recurring_transactions: Automated recurring payments
- ab_wallet_audits: Comprehensive audit logging
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Numeric, ForeignKey


def upgrade():
    """Create wallet system tables."""
    
    # Create ab_user_wallets table
    op.create_table(
        'ab_user_wallets',
        Column('id', Integer, primary_key=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('wallet_name', String(100), nullable=False, default='Default Wallet'),
        Column('currency_code', String(3), nullable=False, default='USD'),
        Column('balance', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('is_active', Boolean, nullable=False, default=True),
        Column('is_primary', Boolean, nullable=False, default=False),
        Column('allow_negative_balance', Boolean, nullable=False, default=False),
        Column('daily_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('monthly_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('description', Text, nullable=True),
        Column('wallet_type', String(50), nullable=False, default='personal'),
        Column('icon', String(50), nullable=True),
        Column('color', String(7), nullable=True),
        Column('is_locked', Boolean, nullable=False, default=False),
        Column('locked_until', DateTime, nullable=True),
        Column('require_approval', Boolean, nullable=False, default=False),
        Column('approval_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('available_balance', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('pending_balance', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('last_transaction_date', DateTime, nullable=True),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_user_wallets
    op.create_index('ix_user_wallets_user_currency', 'ab_user_wallets', ['user_id', 'currency_code'])
    op.create_index('ix_user_wallets_active', 'ab_user_wallets', ['is_active'])
    
    # Create unique constraint
    op.create_unique_constraint('uq_user_wallet_currency_name', 'ab_user_wallets', 
                               ['user_id', 'currency_code', 'wallet_name'])
    
    # Create ab_transaction_categories table
    op.create_table(
        'ab_transaction_categories',
        Column('id', Integer, primary_key=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=True),
        Column('name', String(100), nullable=False),
        Column('description', Text, nullable=True),
        Column('icon', String(50), nullable=True),
        Column('color', String(7), nullable=True),
        Column('parent_id', Integer, ForeignKey('ab_transaction_categories.id'), nullable=True),
        Column('category_type', String(20), nullable=False, default='expense'),
        Column('is_system', Boolean, nullable=False, default=False),
        Column('is_active', Boolean, nullable=False, default=True),
        Column('sort_order', Integer, nullable=False, default=0),
        Column('has_budget', Boolean, nullable=False, default=False),
        Column('budget_alert_threshold', Integer, nullable=True),
        Column('is_deleted', Boolean, default=False),
        Column('deleted_on', DateTime, nullable=True),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_transaction_categories
    op.create_index('ix_transaction_categories_parent', 'ab_transaction_categories', ['parent_id'])
    op.create_index('ix_transaction_categories_type', 'ab_transaction_categories', ['category_type'])
    
    # Create unique constraint for categories
    op.create_unique_constraint('uq_category_name_parent_user', 'ab_transaction_categories',
                               ['name', 'parent_id', 'user_id'])
    
    # Create ab_payment_methods table
    op.create_table(
        'ab_payment_methods',
        Column('id', Integer, primary_key=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('name', String(100), nullable=False),
        Column('method_type', String(20), nullable=False),
        Column('description', Text, nullable=True),
        Column('account_number', String(200), nullable=True),  # Encrypted
        Column('account_holder', String(100), nullable=True),  # Encrypted
        Column('bank_name', String(100), nullable=True),
        Column('is_active', Boolean, nullable=False, default=True),
        Column('is_primary', Boolean, nullable=False, default=False),
        Column('currency_code', String(3), nullable=False, default='USD'),
        Column('daily_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('monthly_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('per_transaction_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('last_used_date', DateTime, nullable=True),
        Column('total_transactions', Integer, nullable=False, default=0),
        Column('total_amount', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('requires_verification', Boolean, nullable=False, default=False),
        Column('verification_method', String(50), nullable=True),
        Column('is_deleted', Boolean, default=False),
        Column('deleted_on', DateTime, nullable=True),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_payment_methods
    op.create_index('ix_payment_methods_user_type', 'ab_payment_methods', ['user_id', 'method_type'])
    op.create_index('ix_payment_methods_active', 'ab_payment_methods', ['is_active'])
    
    # Create ab_wallet_transactions table
    op.create_table(
        'ab_wallet_transactions',
        Column('id', Integer, primary_key=True),
        Column('wallet_id', Integer, ForeignKey('ab_user_wallets.id'), nullable=False),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('amount', Numeric(precision=15, scale=2), nullable=False),
        Column('transaction_type', String(20), nullable=False),
        Column('status', String(20), nullable=False, default='completed'),
        Column('transaction_date', DateTime, nullable=False, default=sa.func.now()),
        Column('description', Text, nullable=True),
        Column('reference_number', String(100), nullable=True),
        Column('external_id', String(100), nullable=True),
        Column('category_id', Integer, ForeignKey('ab_transaction_categories.id'), nullable=True),
        Column('tags', Text, nullable=True),  # JSON array
        Column('payment_method_id', Integer, ForeignKey('ab_payment_methods.id'), nullable=True),
        Column('metadata_json', Text, nullable=True),
        Column('receipt_url', String(500), nullable=True),
        Column('location', String(200), nullable=True),
        Column('processed_date', DateTime, nullable=True),
        Column('processor_id', String(100), nullable=True),
        Column('processing_fee', Numeric(precision=15, scale=2), nullable=True, default=0.00),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_wallet_transactions
    op.create_index('ix_wallet_transactions_wallet_date', 'ab_wallet_transactions', ['wallet_id', 'transaction_date'])
    op.create_index('ix_wallet_transactions_type_status', 'ab_wallet_transactions', ['transaction_type', 'status'])
    op.create_index('ix_wallet_transactions_category', 'ab_wallet_transactions', ['category_id'])
    op.create_index('ix_wallet_transactions_user_date', 'ab_wallet_transactions', ['user_id', 'transaction_date'])
    
    # Create ab_wallet_budgets table
    op.create_table(
        'ab_wallet_budgets',
        Column('id', Integer, primary_key=True),
        Column('wallet_id', Integer, ForeignKey('ab_user_wallets.id'), nullable=False),
        Column('category_id', Integer, ForeignKey('ab_transaction_categories.id'), nullable=True),
        Column('name', String(100), nullable=False),
        Column('description', Text, nullable=True),
        Column('budget_amount', Numeric(precision=15, scale=2), nullable=False),
        Column('period_type', String(20), nullable=False),
        Column('period_start', DateTime, nullable=False),
        Column('period_end', DateTime, nullable=False),
        Column('is_active', Boolean, nullable=False, default=True),
        Column('auto_rollover', Boolean, nullable=False, default=False),
        Column('rollover_limit', Numeric(precision=15, scale=2), nullable=True),
        Column('alert_threshold_1', Integer, nullable=False, default=75),
        Column('alert_threshold_2', Integer, nullable=False, default=90),
        Column('alert_threshold_3', Integer, nullable=False, default=100),
        Column('spent_amount', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('remaining_amount', Numeric(precision=15, scale=2), nullable=False, default=0.00),
        Column('last_updated', DateTime, nullable=False, default=sa.func.now()),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_wallet_budgets
    op.create_index('ix_wallet_budgets_wallet_period', 'ab_wallet_budgets', ['wallet_id', 'period_type'])
    op.create_index('ix_wallet_budgets_category', 'ab_wallet_budgets', ['category_id'])
    
    # Create unique constraint for budgets
    op.create_unique_constraint('uq_budget_wallet_category_period', 'ab_wallet_budgets',
                               ['wallet_id', 'category_id', 'period_type', 'period_start'])
    
    # Create ab_recurring_transactions table
    op.create_table(
        'ab_recurring_transactions',
        Column('id', Integer, primary_key=True),
        Column('wallet_id', Integer, ForeignKey('ab_user_wallets.id'), nullable=False),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('name', String(100), nullable=False),
        Column('description', Text, nullable=True),
        Column('amount', Numeric(precision=15, scale=2), nullable=False),
        Column('transaction_type', String(20), nullable=False),
        Column('category_id', Integer, ForeignKey('ab_transaction_categories.id'), nullable=True),
        Column('payment_method_id', Integer, ForeignKey('ab_payment_methods.id'), nullable=True),
        Column('recurrence_pattern', String(20), nullable=False),
        Column('recurrence_interval', Integer, nullable=False, default=1),
        Column('start_date', DateTime, nullable=False),
        Column('end_date', DateTime, nullable=True),
        Column('next_execution_date', DateTime, nullable=False),
        Column('last_execution_date', DateTime, nullable=True),
        Column('is_active', Boolean, nullable=False, default=True),
        Column('execution_count', Integer, nullable=False, default=0),
        Column('max_executions', Integer, nullable=True),
        Column('auto_execute', Boolean, nullable=False, default=True),
        Column('requires_approval', Boolean, nullable=False, default=False),
        Column('retry_count', Integer, nullable=False, default=0),
        Column('max_retries', Integer, nullable=False, default=3),
        Column('last_error', Text, nullable=True),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_recurring_transactions
    op.create_index('ix_recurring_transactions_wallet', 'ab_recurring_transactions', ['wallet_id'])
    op.create_index('ix_recurring_transactions_next_date', 'ab_recurring_transactions', ['next_execution_date'])
    op.create_index('ix_recurring_transactions_active', 'ab_recurring_transactions', ['is_active'])
    
    # Create ab_wallet_audits table
    op.create_table(
        'ab_wallet_audits',
        Column('id', Integer, primary_key=True),
        Column('wallet_id', Integer, ForeignKey('ab_user_wallets.id'), nullable=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('transaction_id', Integer, ForeignKey('ab_wallet_transactions.id'), nullable=True),
        Column('event_type', String(50), nullable=False),
        Column('event_description', Text, nullable=False),
        Column('audit_date', DateTime, nullable=False, default=sa.func.now()),
        Column('ip_address', String(45), nullable=True),
        Column('user_agent', String(500), nullable=True),
        Column('session_id', String(100), nullable=True),
        Column('old_values', Text, nullable=True),  # JSON
        Column('new_values', Text, nullable=True),  # JSON
        Column('metadata_json', Text, nullable=True),
        Column('risk_score', Integer, nullable=False, default=0),
        Column('is_suspicious', Boolean, nullable=False, default=False),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_wallet_audits
    op.create_index('ix_wallet_audits_wallet_date', 'ab_wallet_audits', ['wallet_id', 'audit_date'])
    op.create_index('ix_wallet_audits_event_type', 'ab_wallet_audits', ['event_type'])
    op.create_index('ix_wallet_audits_user', 'ab_wallet_audits', ['user_id'])
    
    print("Wallet system tables created successfully!")


def downgrade():
    """Drop wallet system tables."""
    
    # Drop tables in reverse order due to foreign key constraints
    op.drop_table('ab_wallet_audits')
    op.drop_table('ab_recurring_transactions')
    op.drop_table('ab_wallet_budgets')
    op.drop_table('ab_wallet_transactions')
    op.drop_table('ab_payment_methods')
    op.drop_table('ab_transaction_categories')
    op.drop_table('ab_user_wallets')
    
    print("Wallet system tables dropped successfully!")


def create_default_transaction_categories():
    """Create default system transaction categories."""
    from sqlalchemy import text
    
    # This would typically be called after the migration
    # to populate default categories for expenses and income
    categories_data = [
        # Income categories
        ('Salary', 'income', True, None, 'fa-money', '#28a745'),
        ('Freelance', 'income', True, None, 'fa-laptop', '#17a2b8'),
        ('Investment', 'income', True, None, 'fa-chart-line', '#6f42c1'),
        ('Gift', 'income', True, None, 'fa-gift', '#e83e8c'),
        
        # Expense categories
        ('Food & Dining', 'expense', True, None, 'fa-utensils', '#dc3545'),
        ('Transportation', 'expense', True, None, 'fa-car', '#fd7e14'),
        ('Shopping', 'expense', True, None, 'fa-shopping-bag', '#6f42c1'),
        ('Entertainment', 'expense', True, None, 'fa-film', '#20c997'),
        ('Bills & Utilities', 'expense', True, None, 'fa-file-invoice', '#ffc107'),
        ('Healthcare', 'expense', True, None, 'fa-heartbeat', '#dc3545'),
        ('Education', 'expense', True, None, 'fa-graduation-cap', '#007bff'),
        ('Travel', 'expense', True, None, 'fa-plane', '#17a2b8'),
    ]
    
    return categories_data


if __name__ == "__main__":
    print("Wallet System Migration")
    print("=" * 50)
    print("This migration creates the following tables:")
    print("- ab_user_wallets: User wallet configurations and balances")
    print("- ab_wallet_transactions: Transaction records with audit trails")
    print("- ab_transaction_categories: Hierarchical transaction categories")
    print("- ab_wallet_budgets: Budget management and tracking")
    print("- ab_payment_methods: Encrypted payment method storage")
    print("- ab_recurring_transactions: Automated recurring payments")
    print("- ab_wallet_audits: Comprehensive audit logging")