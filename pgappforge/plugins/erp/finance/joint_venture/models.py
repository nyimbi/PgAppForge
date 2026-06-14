"""Joint venture models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class JointVenture(Model):
	__tablename__ = "fin_joint_venture"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	operator_entity_id = sa.Column(sa.String(36), nullable=False, comment="Entity that operates the JV")
	partners = sa.Column(JSONB, nullable=False, comment="[{entity_id, ownership_pct, billing_method}]")
	status = sa.Column(sa.String(20), nullable=False, default="ACTIVE")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class JVCashCall(Model):
	__tablename__ = "fin_jv_cash_call"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	jv_id = sa.Column(sa.String(36), sa.ForeignKey("fin_joint_venture.id"), nullable=False, index=True)
	period = sa.Column(sa.String(7), nullable=False)
	total_cents = sa.Column(sa.BigInteger, nullable=False)
	due_date = sa.Column(sa.Date, nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="PENDING")
	distribution = sa.Column(JSONB, nullable=True, comment="[{entity_id, amount_cents, invoice_id}]")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class JVBilling(Model):
	__tablename__ = "fin_jv_billing"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	jv_id = sa.Column(sa.String(36), sa.ForeignKey("fin_joint_venture.id"), nullable=False, index=True)
	expense_journal_id = sa.Column(sa.String(36), nullable=False, comment="GL journal being allocated")
	period = sa.Column(sa.String(7), nullable=False)
	distribution = sa.Column(JSONB, nullable=False, comment="[{entity_id, ownership_pct, amount_cents}]")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
