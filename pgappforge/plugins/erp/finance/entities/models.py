"""
pgappforge/plugins/erp/finance/entities/models.py

SQLAlchemy models for the Legal Entities plugin.

Design invariants (mirroring GL plugin):
  - All PKs:         UUID(as_uuid=False) + default=lambda: str(uuid.uuid4())
                     + server_default=gen_random_uuid()
  - All timestamps:  DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - All models:      tenant_id UUID NOT NULL
  - All amounts:     BigInteger (integer cents) — NEVER float or Numeric
  - AuditMixin:      applied to all mutable entities
  - JSONB:           used for extensible attributes
  - Table prefix:    erp_entity_*

Supported entity types for a Kenyan banking group:
  HOLDING_CO | BANK | INSURANCE | MICROFINANCE | BROKER | SPV | OTHER

Inter-entity transaction types:
  LOAN | DIVIDEND | MGMT_FEE | EXPENSE_SHARE | CAPITAL_INJECTION | SETTLEMENT

Consolidation elimination types:
  INTERCO_RECEIVABLE | INTERCO_PAYABLE | INVESTMENT_IN_SUB | DIVIDEND | MGMT_FEE
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# LegalEntity
# ---------------------------------------------------------------------------

class LegalEntity(AuditMixin, Model):
	"""A discrete legal entity within the corporate group.

	Supports a self-referential hierarchy (holding company → subsidiaries)
	with a max recommended depth of 5 levels enforced by the service layer.

	entity_type discriminates between:
	  HOLDING_CO    — group holding company (level 0, is_consolidation_parent=True)
	  BANK          — licensed commercial bank
	  INSURANCE     — insurance subsidiary
	  MICROFINANCE  — microfinance institution (MFI)
	  BROKER        — stock/forex broker
	  SPV           — special purpose vehicle
	  OTHER         — catch-all

	functional_currency  — currency used for GL bookkeeping within this entity
	reporting_currency   — currency used for group consolidation reports
	cbk_license_number   — Central Bank of Kenya licence number (banks/MFIs)

	Each entity maintains completely separate GL books; inter-entity cash flows
	are recorded via InterEntityTransaction and eliminated via
	ConsolidationElimination at group reporting time.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_entity_legal"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "entity_code",
			name="uq_erp_entity_legal_tenant_code",
		),
		Index("ix_erp_entity_legal_tenant_type", "tenant_id", "entity_type"),
		Index("ix_erp_entity_legal_parent", "parent_entity_id"),
		Index("ix_erp_entity_legal_active", "tenant_id", "is_active"),
		Index("ix_erp_entity_legal_consolidation", "tenant_id", "is_consolidation_parent"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	# Identity
	entity_code = Column(
		String(20),
		nullable=False,
		comment="Short mnemonic unique per tenant, e.g. HCO, KCB, INS",
	)
	entity_name = Column(String(200), nullable=False)
	entity_type = Column(
		String(20),
		nullable=False,
		comment="HOLDING_CO|BANK|INSURANCE|MICROFINANCE|BROKER|SPV|OTHER",
	)

	# Hierarchy
	parent_entity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_entity_legal.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
		comment="NULL = root / holding company",
	)
	level = Column(
		Integer,
		nullable=False,
		default=0,
		comment="0=root holding, 1=direct subsidiary, 2+=deeper",
	)

	# Regulatory / legal identifiers
	incorporation_number = Column(String(50), nullable=True, comment="Companies Registry number")
	tax_pin = Column(String(30), nullable=True, comment="KRA PIN")
	cbk_license_number = Column(
		String(30),
		nullable=True,
		comment="Central Bank of Kenya licence (banks / MFIs)",
	)

	# Currency settings
	functional_currency = Column(
		String(3),
		nullable=False,
		default="KES",
		comment="ISO 4217 — currency of GL bookkeeping for this entity",
	)
	reporting_currency = Column(
		String(3),
		nullable=False,
		default="KES",
		comment="ISO 4217 — currency used in group consolidated reports",
	)

	# Flags
	is_consolidation_parent = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True on the holding company that owns the consolidated P&L",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	# Extensible attributes
	attributes: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Arbitrary extra metadata (regulator codes, addresses, etc.)",
	)

	# Timestamps
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

	# Relationships
	parent: LegalEntity = relationship(
		"LegalEntity",
		remote_side="LegalEntity.id",
		foreign_keys=[parent_entity_id],
		back_populates="children",
		lazy="select",
	)
	children: list[LegalEntity] = relationship(
		"LegalEntity",
		foreign_keys=[parent_entity_id],
		back_populates="parent",
		lazy="select",
	)
	transactions_from: list[InterEntityTransaction] = relationship(
		"InterEntityTransaction",
		foreign_keys="InterEntityTransaction.from_entity_id",
		back_populates="from_entity",
		lazy="select",
	)
	transactions_to: list[InterEntityTransaction] = relationship(
		"InterEntityTransaction",
		foreign_keys="InterEntityTransaction.to_entity_id",
		back_populates="to_entity",
		lazy="select",
	)
	eliminations_from: list[ConsolidationElimination] = relationship(
		"ConsolidationElimination",
		foreign_keys="ConsolidationElimination.from_entity_id",
		back_populates="from_entity",
		lazy="select",
	)
	eliminations_to: list[ConsolidationElimination] = relationship(
		"ConsolidationElimination",
		foreign_keys="ConsolidationElimination.to_entity_id",
		back_populates="to_entity",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LegalEntity {self.id!r} code={self.entity_code!r} "
			f"type={self.entity_type!r} level={self.level}>"
		)


# ---------------------------------------------------------------------------
# InterEntityTransaction
# ---------------------------------------------------------------------------

class InterEntityTransaction(AuditMixin, Model):
	"""A financial transaction between two legal entities in the same group.

	Lifecycle:
	  DRAFT     — created, awaiting approval
	  POSTED    — GL journal entries created in both entity books; immutable
	  CANCELLED — voided before posting

	GL posting convention (POSTED status):
	  from-entity books:  DR from_gl_account  /  CR intercompany_payable (2400)
	  to-entity books:    DR intercompany_receivable (1400)  /  CR to_gl_account

	journal_id_from / journal_id_to are the GL journal entry UUIDs created
	in each entity's GL book.  They may be NULL if the GL plugin is not
	installed (service records a warning but does not fail).

	IMMUTABLE LEDGER: Once status=POSTED, no fields may be changed.
	Corrections require a new transaction of the opposite sign or type.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_entity_interco_txn"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "transaction_ref",
			name="uq_erp_entity_interco_txn_tenant_ref",
		),
		Index("ix_erp_interco_txn_from_entity", "from_entity_id"),
		Index("ix_erp_interco_txn_to_entity", "to_entity_id"),
		Index("ix_erp_interco_txn_tenant_status", "tenant_id", "status"),
		Index("ix_erp_interco_txn_value_date", "value_date"),
		Index("ix_erp_interco_txn_type", "transaction_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Reference
	transaction_ref = Column(
		String(50),
		nullable=False,
		comment="Human-readable reference, unique per tenant",
	)

	# Parties
	from_entity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_entity_legal.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
		comment="Entity originating the transaction (pays / transfers)",
	)
	to_entity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_entity_legal.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
		comment="Entity receiving the transaction",
	)

	# Classification
	transaction_type = Column(
		String(20),
		nullable=False,
		comment="LOAN|DIVIDEND|MGMT_FEE|EXPENSE_SHARE|CAPITAL_INJECTION|SETTLEMENT",
	)

	# Amount
	amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Amount in integer minor units (cents) of currency_code",
	)
	currency_code = Column(String(3), nullable=False, default="KES")

	# Date & description
	value_date = Column(Date, nullable=False, comment="Economic date of the transaction")
	description = Column(Text, nullable=True)

	# GL account codes used when posting
	from_gl_account = Column(
		String(20),
		nullable=False,
		comment="GL account debited in from-entity books",
	)
	to_gl_account = Column(
		String(20),
		nullable=False,
		comment="GL account credited in to-entity books",
	)

	# Lifecycle
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT|POSTED|CANCELLED",
	)
	posted_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when status transitioned to POSTED",
	)

	# GL journal references (set by service after posting)
	journal_id_from = Column(
		String(36),
		nullable=True,
		comment="UUID of the GL journal entry in from-entity books",
	)
	journal_id_to = Column(
		String(36),
		nullable=True,
		comment="UUID of the GL journal entry in to-entity books",
	)

	# Timestamps
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

	# Relationships
	from_entity: LegalEntity = relationship(
		"LegalEntity",
		foreign_keys=[from_entity_id],
		back_populates="transactions_from",
		lazy="select",
	)
	to_entity: LegalEntity = relationship(
		"LegalEntity",
		foreign_keys=[to_entity_id],
		back_populates="transactions_to",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InterEntityTransaction {self.transaction_ref!r} "
			f"type={self.transaction_type!r} "
			f"amount={self.amount_cents} {self.currency_code} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ConsolidationElimination
# ---------------------------------------------------------------------------

class ConsolidationElimination(AuditMixin, Model):
	"""Inter-company elimination entry for group consolidation.

	Created by LegalEntityService.generate_eliminations() for a reporting
	period.  Each row eliminates one side of an inter-company balance:

	  INTERCO_RECEIVABLE  — eliminate receivable in to-entity
	  INTERCO_PAYABLE     — eliminate payable in from-entity
	  INVESTMENT_IN_SUB   — eliminate investment in subsidiary vs equity
	  DIVIDEND            — eliminate inter-company dividend income/expense
	  MGMT_FEE            — eliminate management fee income/expense

	period format: 'YYYY-QN' (e.g. '2026-Q1') or 'YYYY-MM' for monthly.
	amount_cents is always positive; the elimination direction is implicit
	in the elimination_type.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_entity_consol_elim"
	__table_args__ = (
		Index("ix_erp_consol_elim_period_tenant", "tenant_id", "period"),
		Index("ix_erp_consol_elim_from_entity", "from_entity_id"),
		Index("ix_erp_consol_elim_to_entity", "to_entity_id"),
		Index("ix_erp_consol_elim_type", "elimination_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: str(uuid.uuid4()),
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Period
	period = Column(
		String(10),
		nullable=False,
		comment="Reporting period, e.g. '2026-Q1' or '2026-01'",
	)

	# Type
	elimination_type = Column(
		String(25),
		nullable=False,
		comment=(
			"INTERCO_RECEIVABLE|INTERCO_PAYABLE|"
			"INVESTMENT_IN_SUB|DIVIDEND|MGMT_FEE"
		),
	)

	# Entities
	from_entity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_entity_legal.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)
	to_entity_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_entity_legal.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Amount
	amount_cents = Column(
		BigInteger,
		nullable=False,
		comment="Elimination amount in integer minor units (always positive)",
	)
	currency_code = Column(String(3), nullable=False, default="KES")

	# GL reference
	gl_account_code = Column(
		String(20),
		nullable=False,
		comment="GL account affected by this elimination entry",
	)
	notes = Column(Text, nullable=True)

	# Authorship
	created_by = Column(String(100), nullable=True, comment="Username that triggered generation")

	# Timestamps
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

	# Relationships
	from_entity: LegalEntity = relationship(
		"LegalEntity",
		foreign_keys=[from_entity_id],
		back_populates="eliminations_from",
		lazy="select",
	)
	to_entity: LegalEntity = relationship(
		"LegalEntity",
		foreign_keys=[to_entity_id],
		back_populates="eliminations_to",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ConsolidationElimination period={self.period!r} "
			f"type={self.elimination_type!r} "
			f"amount={self.amount_cents} {self.currency_code}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LegalEntity",
	"InterEntityTransaction",
	"ConsolidationElimination",
]
