from __future__ import annotations

from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


class ServiceContract(AuditMixin, Model):
	__tablename__ = "svc_contract"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default="gen_random_uuid()",
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	customer_id = Column(String(50), nullable=False)
	contract_ref = Column(String(50), nullable=False)
	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	contract_type = Column(String(30), nullable=False, default="MAINTENANCE")
	status = Column(String(20), nullable=False, default="ACTIVE")
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	billing_frequency = Column(String(20), nullable=False, default="MONTHLY")
	contract_value_cents = Column(BigInteger, nullable=False, default=0)
	billing_amount_cents = Column(BigInteger, nullable=False, default=0)
	currency_code = Column(String(3), nullable=False, default="USD")
	covered_assets = Column(JSONB, nullable=False, default=list)
	sla_response_hours = Column(Integer, nullable=False, default=8)
	sla_resolution_hours = Column(Integer, nullable=False, default=48)
	auto_renew = Column(Boolean, nullable=False, default=True)
	renewal_notice_days = Column(Integer, nullable=False, default=30)
	next_billing_date = Column(Date, nullable=True)
	last_invoiced_at = Column(Date, nullable=True)
	metadata_ = Column(JSONB, nullable=False, default=dict)

	__table_args__ = (
		UniqueConstraint("tenant_id", "contract_ref", name="uq_svc_contract_ref"),
		Index("ix_svc_contract_tenant_status", "tenant_id", "status"),
		Index("ix_svc_contract_customer_tenant", "customer_id", "tenant_id"),
		Index("ix_svc_contract_tenant_next_billing", "tenant_id", "next_billing_date"),
	)


class ContractRenewal(AuditMixin, Model):
	__tablename__ = "svc_renewal"

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		server_default="gen_random_uuid()",
		nullable=False,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	contract_id = Column(
		UUID(as_uuid=False),
		ForeignKey("svc_contract.id", ondelete="CASCADE"),
		nullable=False,
	)
	old_end_date = Column(Date, nullable=False)
	new_end_date = Column(Date, nullable=False)
	renewal_value_cents = Column(BigInteger, nullable=False, default=0)
	renewed_by = Column(String(50), nullable=True)

	__table_args__ = (
		Index("ix_svc_renewal_contract_id", "contract_id"),
	)


__all__ = ["ServiceContract", "ContractRenewal"]
