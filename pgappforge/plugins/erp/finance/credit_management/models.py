"""
pgappforge/plugins/erp/finance/credit_management/models.py

SQLAlchemy models for the Credit Management plugin.

Design rules enforced:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - Every model: tenant_id UUID NOT NULL
  - Monetary amounts: BigInteger cents ONLY — never Numeric/float for money
  - AuditMixin on all mutable entities
  - PostgreSQL-only: JSONB, UUID, gen_random_uuid()

Table name convention: crm_crd_<entity>
(prefix avoids collision with AR customer and CRM customer tables)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# CustomerCreditProfile
# ---------------------------------------------------------------------------

class CustomerCreditProfile(AuditMixin, Model):
	"""Live credit profile for a customer.

	current_exposure_cents is a denormalised sum — updated by
	CreditManagementService.update_exposure() whenever AR invoices or
	sales orders are opened/closed.

	available_credit_cents = credit_limit_cents - current_exposure_cents.
	May be negative when limit is breached.

	is_on_hold blocks new orders and invoices when True.
	One profile per customer per tenant — enforced by UniqueConstraint.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_crd_profile"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "customer_id",
			name="uq_crm_crd_profile_tenant_customer",
		),
		Index("ix_crm_crd_profile_tenant_hold", "tenant_id", "is_on_hold"),
		Index("ix_crm_crd_profile_tenant_customer", "tenant_id", "customer_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Soft FK — customer lives in CRM/AR domain; no DB-level FK for domain decoupling
	customer_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK to CRM/AR customer; unique per tenant",
	)

	# Limit — integer cents
	credit_limit_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Approved credit ceiling in cents; 0 = no credit approved",
	)
	currency_code = Column(String(3), nullable=False, default="USD", server_default="USD")

	# Live exposure — maintained by update_exposure()
	current_exposure_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="Denormalised sum of open AR invoices + unshipped orders in cents",
	)
	available_credit_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		server_default="0",
		comment="credit_limit - current_exposure; may be negative when breached",
	)

	# Credit rating — informal; not a hard DB enum
	credit_rating = Column(
		String(10),
		nullable=True,
		comment="AAA | AA | A | BBB | BB | CCC | D — internal credit rating",
	)
	payment_terms_days = Column(
		Integer,
		nullable=False,
		default=30,
		server_default="30",
	)

	# Hold state
	is_on_hold = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="When true, new orders and shipments are blocked",
	)
	hold_reason = Column(Text, nullable=True)
	hold_placed_by = Column(String(50), nullable=True)
	hold_placed_at = Column(DateTime(timezone=True), nullable=True)

	last_exposure_update = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp of most recent update_exposure() call",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	components: list[CreditExposureComponent] = relationship(
		"CreditExposureComponent",
		back_populates="profile",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CustomerCreditProfile customer={self.customer_id!r} "
			f"limit={self.credit_limit_cents}¢ exposure={self.current_exposure_cents}¢ "
			f"hold={self.is_on_hold}>"
		)


# ---------------------------------------------------------------------------
# CreditExposureComponent
# ---------------------------------------------------------------------------

class CreditExposureComponent(AuditMixin, Model):
	"""One open document contributing to a customer's credit exposure.

	source_type distinguishes invoices from sales orders from deliveries.
	Upserted by CreditManagementService.register_exposure_component();
	deleted by remove_exposure_component().

	UniqueConstraint on (profile_id, source_type, source_id) ensures each
	document appears exactly once in the exposure calculation.
	"""

	__allow_unmapped__ = True
	__tablename__ = "crm_crd_exposure"
	__table_args__ = (
		UniqueConstraint(
			"profile_id", "source_type", "source_id",
			name="uq_crm_crd_exposure_profile_source",
		),
		Index("ix_crm_crd_exposure_profile_type", "profile_id", "source_type"),
		Index("ix_crm_crd_exposure_tenant_due", "tenant_id", "due_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	profile_id = Column(
		UUID(as_uuid=False),
		ForeignKey("crm_crd_profile.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	# Source document identification
	source_type = Column(
		String(30),
		nullable=False,
		comment="INVOICE | SALES_ORDER | DELIVERY",
	)
	source_id = Column(
		String(50),
		nullable=False,
		comment="PK of the source document (UUID string or order number)",
	)
	amount_cents = Column(BigInteger, nullable=False, comment="Outstanding amount in cents")
	due_date = Column(Date, nullable=True, comment="Due date of source document; null for orders")
	is_overdue = Column(
		Boolean,
		nullable=False,
		default=False,
		server_default="false",
		comment="True when due_date < today and amount not cleared",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	profile: CustomerCreditProfile = relationship(
		"CustomerCreditProfile",
		back_populates="components",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<CreditExposureComponent type={self.source_type!r} "
			f"src={self.source_id!r} amount={self.amount_cents}¢ overdue={self.is_overdue}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CustomerCreditProfile",
	"CreditExposureComponent",
]
