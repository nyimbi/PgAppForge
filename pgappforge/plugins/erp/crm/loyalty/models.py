"""Loyalty engine models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class LoyaltyProgram(Model):
	__tablename__ = "crm_loyalty_program"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	program_type = sa.Column(sa.String(20), nullable=False, default="POINTS", comment="POINTS, CASHBACK, TIER")
	points_per_cent = sa.Column(sa.Numeric(8, 4), nullable=False, default=1)
	redemption_rate_pct = sa.Column(sa.Numeric(6, 4), nullable=False, default=1)
	tiers = sa.Column(JSONB, nullable=True, comment="[{name, min_points, benefits:[]}]")
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class LoyaltyAccount(Model):
	__tablename__ = "crm_loyalty_account"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	customer_id = sa.Column(sa.String(36), nullable=False, index=True)
	program_id = sa.Column(sa.String(36), sa.ForeignKey("crm_loyalty_program.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	tier = sa.Column(sa.String(50), nullable=True)
	points_balance = sa.Column(sa.BigInteger, nullable=False, default=0)
	lifetime_points = sa.Column(sa.BigInteger, nullable=False, default=0)
	last_activity_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class LoyaltyTransaction(Model):
	__tablename__ = "crm_loyalty_transaction"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	account_id = sa.Column(sa.String(36), sa.ForeignKey("crm_loyalty_account.id"), nullable=False, index=True)
	transaction_type = sa.Column(sa.String(15), nullable=False, comment="EARN, REDEEM, EXPIRE, ADJUSTMENT")
	points = sa.Column(sa.BigInteger, nullable=False)
	reference_order_id = sa.Column(sa.String(36), nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
