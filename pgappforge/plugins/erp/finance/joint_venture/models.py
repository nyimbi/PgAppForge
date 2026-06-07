"""
pgappforge/plugins/erp/finance/joint_venture/models.py

Joint Venture Accounting models (COPAS/SORP-aligned).

Design rules:
  - All PKs: UUID v4 via gen_random_uuid()
  - All monetary amounts: INTEGER cents — never float
  - All percentages: NUMERIC(8,6) — e.g. 0.500000 = 50%
  - Table prefix: erp_jv_

Key entities:
  JointVenture       — JV master (oil & gas / mining / general)
  JvPartner          — working interest / partner share record
  JvCostAllocation   — period cost allocation header + lines
  JvBillingStatement — monthly billing statement to partners (COPAS format)
  JvCashCall         — advance cash call notice
  JvAuditQuery       — partner audit query (dispute management)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.rules.mixin import RulesMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# JointVenture
# ---------------------------------------------------------------------------

class JointVenture(RulesMixin, AuditMixin, Model):
	"""Joint venture master record.

	venture_type:
	  OIL_GAS     — upstream oil & gas (COPAS accounting)
	  MINING      — mining JV
	  REAL_ESTATE — property JV
	  GENERAL     — other

	accounting_method:
	  PROPORTIONATE_CONSOLIDATION — each partner books their % share
	  EQUITY_METHOD               — investor books equity share of net assets

	status:
	  ACTIVE | SUSPENDED | WOUND_UP
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_venture"
	__table_args__ = (
		UniqueConstraint("tenant_id", "venture_code", name="uq_erp_jv_venture_code"),
		Index("ix_erp_jv_venture_tenant", "tenant_id"),
		Index("ix_erp_jv_venture_status", "status"),
		{"extend_existing": True},
	)

	_rules_mutable_fields = frozenset({"status"})

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	venture_code = Column(String(20), nullable=False)
	venture_name = Column(String(300), nullable=False)
	venture_type = Column(String(20), nullable=False, default="GENERAL",
						  comment="OIL_GAS | MINING | REAL_ESTATE | GENERAL")
	accounting_method = Column(String(30), nullable=False,
							   default="PROPORTIONATE_CONSOLIDATION",
							   comment="PROPORTIONATE_CONSOLIDATION | EQUITY_METHOD")

	# Operator (managing party)
	operator_party_id = Column(UUID(as_uuid=False), nullable=False,
							   comment="FK to erp_party.id — operator/managing party")
	operator_wi_pct = Column(Numeric(8, 6), nullable=False,
							 comment="Operator's working interest 0.000000–1.000000")

	effective_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=True)
	currency_code = Column(String(3), ForeignKey("erp_currency.code"), nullable=False)

	# GL cost centre for JV cost accumulation
	cost_centre = Column(String(20), nullable=True,
						 comment="GL cost centre / WBS element for JV costs")
	gl_jv_control_account = Column(String(50), nullable=True,
								   comment="Balance sheet JV receivable/payable control account")

	status = Column(String(20), nullable=False, default="ACTIVE")
	description = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	partners: list[JvPartner] = relationship(
		"JvPartner", back_populates="venture",
		lazy="select", order_by="JvPartner.effective_date",
	)
	billing_statements: list[JvBillingStatement] = relationship(
		"JvBillingStatement", back_populates="venture",
		lazy="select",
	)
	cash_calls: list[JvCashCall] = relationship(
		"JvCashCall", back_populates="venture",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<JointVenture {self.venture_code!r} {self.venture_name!r} "
			f"type={self.venture_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# JvPartner
# ---------------------------------------------------------------------------

class JvPartner(AuditMixin, Model):
	"""Working interest partner in a joint venture.

	Multiple partners can exist for a venture; working_interest_pct for all
	active partners must sum to 1.000000. The service layer enforces this.

	Non-operated WI may differ from participating interest (PI) where one
	partner pays a disproportionate share during a promote period.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_partner"
	__table_args__ = (
		UniqueConstraint("venture_id", "party_id", "effective_date",
						 name="uq_erp_jv_partner_venture_party_date"),
		Index("ix_erp_jv_partner_venture", "venture_id"),
		Index("ix_erp_jv_partner_party", "party_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	venture_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_venture.id", ondelete="RESTRICT"),
						nullable=False)
	party_id = Column(UUID(as_uuid=False), nullable=False,
					  comment="FK to erp_party.id")
	partner_name = Column(String(300), nullable=False,
						  comment="Denormalised for billing statements")
	working_interest_pct = Column(Numeric(8, 6), nullable=False,
								  comment="WI 0.000000–1.000000")
	net_profit_interest_pct = Column(Numeric(8, 6), nullable=True,
									 comment="NPI if applicable")
	is_operator = Column(Boolean, nullable=False, default=False)
	effective_date = Column(Date, nullable=False)
	expiry_date = Column(Date, nullable=True)
	billing_address = Column(Text, nullable=True)
	payment_terms_days = Column(Integer, nullable=False, default=30)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	venture: JointVenture = relationship(
		"JointVenture", back_populates="partners", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<JvPartner venture={self.venture_id!r} "
			f"party={self.party_id!r} WI={float(self.working_interest_pct):.4%}>"
		)


# ---------------------------------------------------------------------------
# JvBillingStatement
# ---------------------------------------------------------------------------

class JvBillingStatement(AuditMixin, Model):
	"""Monthly billing statement (JIB — Joint Interest Billing).

	Contains the period costs allocated to each partner based on their WI.
	status: DRAFT | ISSUED | SETTLED | DISPUTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_billing_statement"
	__table_args__ = (
		UniqueConstraint("venture_id", "billing_period", "partner_id",
						 name="uq_erp_jv_billing_period_partner"),
		Index("ix_erp_jv_bs_venture", "venture_id"),
		Index("ix_erp_jv_bs_period", "billing_period"),
		Index("ix_erp_jv_bs_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	venture_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_venture.id", ondelete="RESTRICT"),
						nullable=False)
	partner_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_partner.id", ondelete="RESTRICT"),
						nullable=False)
	billing_period = Column(String(7), nullable=False,
							comment="YYYY-MM format e.g. '2026-05'")
	working_interest_pct = Column(Numeric(8, 6), nullable=False,
								  comment="WI applied for this billing period")
	gross_costs_cents = Column(Integer, nullable=False,
							   comment="Total JV costs for the period")
	partner_share_cents = Column(Integer, nullable=False,
								 comment="gross_costs × working_interest_pct")
	operator_overhead_cents = Column(Integer, nullable=False, default=0,
									 comment="COPAS overhead charge (if applicable)")
	total_billed_cents = Column(Integer, nullable=False,
								comment="partner_share + operator_overhead")
	due_date = Column(Date, nullable=True)
	status = Column(String(20), nullable=False, default="DRAFT",
					comment="DRAFT | ISSUED | SETTLED | DISPUTED")
	issued_at = Column(DateTime(timezone=True), nullable=True)
	settled_at = Column(DateTime(timezone=True), nullable=True)
	cost_breakdown: list[dict] = Column(JSONB, nullable=False, default=list,
										comment="[{cost_category, description, amount_cents}]")
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	venture: JointVenture = relationship(
		"JointVenture", back_populates="billing_statements", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<JvBillingStatement venture={self.venture_id!r} "
			f"period={self.billing_period!r} partner={self.partner_id!r} "
			f"billed={self.total_billed_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# JvCashCall
# ---------------------------------------------------------------------------

class JvCashCall(AuditMixin, Model):
	"""Advance cash call notice to JV partners.

	Operators issue cash calls to collect advance funding for upcoming
	expenditure. Partners must remit by due_date.

	status: ISSUED | PARTIALLY_RECEIVED | FULLY_RECEIVED | OVERDUE | CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_cash_call"
	__table_args__ = (
		UniqueConstraint("venture_id", "call_reference", name="uq_erp_jv_cash_call_ref"),
		Index("ix_erp_jv_cc_venture", "venture_id"),
		Index("ix_erp_jv_cc_due_date", "due_date"),
		Index("ix_erp_jv_cc_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	venture_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_venture.id", ondelete="RESTRICT"),
						nullable=False)
	call_reference = Column(String(50), nullable=False)
	call_date = Column(Date, nullable=False)
	due_date = Column(Date, nullable=False)
	period_covered = Column(String(7), nullable=True,
							comment="YYYY-MM — period this cash call funds")
	total_amount_cents = Column(Integer, nullable=False,
								comment="Total amount called from all non-operator partners")
	narration = Column(Text, nullable=True)
	status = Column(String(30), nullable=False, default="ISSUED")
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	# Relationships
	venture: JointVenture = relationship(
		"JointVenture", back_populates="cash_calls", lazy="select",
	)
	lines: list[JvCashCallLine] = relationship(
		"JvCashCallLine", back_populates="cash_call",
		cascade="all, delete-orphan", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<JvCashCall {self.call_reference!r} venture={self.venture_id!r} "
			f"due={self.due_date!r} total={self.total_amount_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# JvCashCallLine
# ---------------------------------------------------------------------------

class JvCashCallLine(Model):
	"""Per-partner line within a cash call."""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_cash_call_line"
	__table_args__ = (
		UniqueConstraint("cash_call_id", "partner_id", name="uq_erp_jv_ccl_partner"),
		Index("ix_erp_jv_ccl_call", "cash_call_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	cash_call_id = Column(UUID(as_uuid=False),
						  ForeignKey("erp_jv_cash_call.id", ondelete="CASCADE"),
						  nullable=False)
	partner_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_partner.id", ondelete="RESTRICT"),
						nullable=False)
	working_interest_pct = Column(Numeric(8, 6), nullable=False)
	amount_cents = Column(Integer, nullable=False)
	amount_received_cents = Column(Integer, nullable=False, default=0)
	is_fully_paid = Column(Boolean, nullable=False, default=False)
	payment_reference = Column(String(100), nullable=True)

	# Relationships
	cash_call: JvCashCall = relationship(
		"JvCashCall", back_populates="lines", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<JvCashCallLine call={self.cash_call_id!r} "
			f"partner={self.partner_id!r} amount={self.amount_cents} "
			f"received={self.amount_received_cents}>"
		)


# ---------------------------------------------------------------------------
# JvAuditQuery
# ---------------------------------------------------------------------------

class JvAuditQuery(AuditMixin, Model):
	"""Partner audit query (dispute management).

	Partners have the right under COPAS/JOA to audit JV costs and raise
	queries. This model tracks the query lifecycle.

	status: OPEN | UNDER_REVIEW | RESOLVED | WITHDRAWN
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_jv_audit_query"
	__table_args__ = (
		UniqueConstraint("venture_id", "query_reference", name="uq_erp_jv_aq_ref"),
		Index("ix_erp_jv_aq_venture", "venture_id"),
		Index("ix_erp_jv_aq_partner", "partner_id"),
		Index("ix_erp_jv_aq_status", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4,
				server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	venture_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_venture.id", ondelete="RESTRICT"),
						nullable=False)
	partner_id = Column(UUID(as_uuid=False),
						ForeignKey("erp_jv_partner.id", ondelete="RESTRICT"),
						nullable=False)
	query_reference = Column(String(50), nullable=False)
	raised_date = Column(Date, nullable=False)
	period_under_audit = Column(String(7), nullable=True, comment="YYYY-MM")
	description = Column(Text, nullable=False)
	amount_disputed_cents = Column(Integer, nullable=False, default=0)
	status = Column(String(20), nullable=False, default="OPEN",
					comment="OPEN | UNDER_REVIEW | RESOLVED | WITHDRAWN")
	resolution_notes = Column(Text, nullable=True)
	resolved_at = Column(DateTime(timezone=True), nullable=True)
	resolution_amount_cents = Column(Integer, nullable=True,
									 comment="Amount agreed in resolution (may differ from disputed)")
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)
	created_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False,
						default=lambda: datetime.now(timezone.utc),
						onupdate=lambda: datetime.now(timezone.utc),
						server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return (
			f"<JvAuditQuery {self.query_reference!r} venture={self.venture_id!r} "
			f"disputed={self.amount_disputed_cents} status={self.status!r}>"
		)


__all__ = [
	"JointVenture",
	"JvPartner",
	"JvBillingStatement",
	"JvCashCall",
	"JvCashCallLine",
	"JvAuditQuery",
]
