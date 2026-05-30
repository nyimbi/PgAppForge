"""
Database migration for Multi-Factor Authentication tables.

This migration creates the necessary database tables for MFA functionality:
- ab_user_mfa: User MFA settings and configuration
- ab_mfa_backup_code: Backup codes for MFA recovery
- ab_mfa_verification_attempt: Audit trail for MFA attempts
- ab_mfa_policy: MFA enforcement policies

Revision ID: mfa_001
Revises: 
Create Date: 2025-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Numeric


def upgrade():
    """Create MFA tables."""
    
    # Create ab_user_mfa table
    op.create_table(
        'ab_user_mfa',
        Column('id', Integer, primary_key=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('mfa_type', String(20), nullable=False),
        Column('secret_key', String(255)),
        Column('phone_number', String(20)),
        Column('email', String(120)),
        Column('is_active', Boolean, default=False, nullable=False),
        Column('is_verified', Boolean, default=False, nullable=False),
        Column('last_used', DateTime),
        Column('verification_attempts', Integer, default=0),
        Column('locked_until', DateTime),
        Column('config_options', Text),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_user_mfa
    op.create_index('idx_user_mfa_user_id', 'ab_user_mfa', ['user_id'])
    op.create_index('idx_user_mfa_type_active', 'ab_user_mfa', ['mfa_type', 'is_active'])
    
    # Create ab_mfa_backup_code table
    op.create_table(
        'ab_mfa_backup_code',
        Column('id', Integer, primary_key=True),
        Column('user_mfa_id', Integer, ForeignKey('ab_user_mfa.id'), nullable=False),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('code_hash', String(255), nullable=False),
        Column('is_used', Boolean, default=False, nullable=False),
        Column('used_on', DateTime),
        Column('used_ip', String(45)),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_mfa_backup_code
    op.create_index('idx_backup_code_user_mfa', 'ab_mfa_backup_code', ['user_mfa_id'])
    op.create_index('idx_backup_code_user_used', 'ab_mfa_backup_code', ['user_id', 'is_used'])
    
    # Create ab_mfa_verification_attempt table
    op.create_table(
        'ab_mfa_verification_attempt',
        Column('id', Integer, primary_key=True),
        Column('user_id', Integer, ForeignKey('ab_user.id'), nullable=False),
        Column('user_mfa_id', Integer, ForeignKey('ab_user_mfa.id')),
        Column('mfa_type', String(20), nullable=False),
        Column('success', Boolean, nullable=False),
        Column('ip_address', String(45)),
        Column('user_agent', Text),
        Column('failure_reason', String(100)),
        Column('login_session_id', String(100)),
        Column('attempt_timestamp', DateTime, default=sa.func.now(), nullable=False),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_mfa_verification_attempt
    op.create_index('idx_mfa_attempt_user_time', 'ab_mfa_verification_attempt', ['user_id', 'attempt_timestamp'])
    op.create_index('idx_mfa_attempt_success', 'ab_mfa_verification_attempt', ['success', 'attempt_timestamp'])
    op.create_index('idx_mfa_attempt_session', 'ab_mfa_verification_attempt', ['login_session_id'])
    
    # Create ab_mfa_policy table
    op.create_table(
        'ab_mfa_policy',
        Column('id', Integer, primary_key=True),
        Column('name', String(100), nullable=False, unique=True),
        Column('description', Text),
        Column('is_active', Boolean, default=True, nullable=False),
        Column('enforcement_level', String(20), default='optional'),
        Column('scope_config', Text),
        Column('allowed_mfa_types', Text),
        Column('require_backup_codes', Boolean, default=True),
        Column('max_verification_attempts', Integer, default=5),
        Column('lockout_duration_minutes', Integer, default=30),
        Column('grace_period_days', Integer, default=7),
        Column('reminder_days_before', Integer, default=3),
        Column('created_on', DateTime, default=sa.func.now()),
        Column('changed_on', DateTime, default=sa.func.now(), onupdate=sa.func.now()),
        Column('created_by_fk', Integer, ForeignKey('ab_user.id')),
        Column('changed_by_fk', Integer, ForeignKey('ab_user.id')),
    )
    
    # Create indexes for ab_mfa_policy
    op.create_index('idx_mfa_policy_active', 'ab_mfa_policy', ['is_active'])
    op.create_index('idx_mfa_policy_enforcement', 'ab_mfa_policy', ['enforcement_level'])


def downgrade():
    """Drop MFA tables."""
    
    # Drop tables in reverse order
    op.drop_table('ab_mfa_policy')
    op.drop_table('ab_mfa_verification_attempt')
    op.drop_table('ab_mfa_backup_code')
    op.drop_table('ab_user_mfa')


def create_default_mfa_policy():
    """
    Helper function to create a default MFA policy.
    This should be called after the migration is complete.
    """
    from pgappforge import db
    from pgappforge.security.mfa.models import MFAPolicy
    
    # Check if default policy already exists
    existing_policy = db.session.query(MFAPolicy).filter_by(name='Default MFA Policy').first()
    
    if not existing_policy:
        default_policy = MFAPolicy(
            name='Default MFA Policy',
            description='Default MFA policy for all users',
            enforcement_level='optional',
            is_active=True,
            allowed_mfa_types='["totp", "sms", "email"]',
            require_backup_codes=True,
            max_verification_attempts=5,
            lockout_duration_minutes=30,
            grace_period_days=7,
            reminder_days_before=3
        )
        
        db.session.add(default_policy)
        db.session.commit()
        
        print("Created default MFA policy")


def add_user_mfa_relationship():
    """
    Helper function to add MFA relationship to User model.
    This needs to be called to update the User model with MFA relationships.
    """
    # This would be done by modifying the User model directly
    # to include the relationship:
    # mfa_methods = relationship('UserMFA', back_populates='user', cascade='all, delete-orphan')
    pass


if __name__ == '__main__':
    """
    This migration can be run directly for testing purposes.
    In production, it should be run through Alembic/Flask-Migrate.
    """
    print("MFA Migration Script")
    print("==================")
    print("This script creates the necessary database tables for Multi-Factor Authentication.")
    print("\nTables to be created:")
    print("- ab_user_mfa: User MFA settings and configuration")
    print("- ab_mfa_backup_code: Backup codes for MFA recovery") 
    print("- ab_mfa_verification_attempt: Audit trail for MFA attempts")
    print("- ab_mfa_policy: MFA enforcement policies")
    print("\nTo run this migration:")
    print("1. Using Alembic: alembic upgrade head")
    print("2. Using Flask-Migrate: flask db upgrade")
    print("3. Directly in Python: Run upgrade() function")
    print("\nAfter migration, call create_default_mfa_policy() to set up default policies.")