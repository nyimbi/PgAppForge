"""
pgappforge/plugins/erp/hcm/position_management/models.py

SQLAlchemy models for the HCM Position Management plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary values: BigInteger cents
  - FTE headcount: Numeric(6,2) — supports 0.5 FTE part-time
  - ALL models: tenant_id NOT NULL + AuditMixin
  - PostgreSQL only: JSONB, UUID types
  - lazy='select' throughout (SA 2.x)

Table prefix: pos_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Column,
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

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class Position(AuditMixin, Model):
	"""An approved organisational position (slot) in the establishment register.

	position_code is unique per tenant — enforced at the DB level.

	incumbent_employee_id: soft FK to the HCM employee table; NULL when VACANT.
	headcount_budget: FTE allocation (1.0 for full-time, 0.5 for half-time, etc.).

	Status machine:
	  PROPOSED → VACANT → FILLED
	  VACANT   → FROZEN  (budget freeze)
	  FROZEN   → VACANT  (freeze lifted)
	  FILLED   → VACANT  (incumbent leaves)
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_position"
	__table_args__ = (
		Index("ix_pos_position_tenant_entity_status", "tenant_id", "entity_id", "status"),
		Index("ix_pos_position_tenant_code", "tenant_id", "position_code"),
		Index("ix_pos_position_tenant", "tenant_id"),
		UniqueConstraint("tenant_id", "position_code", name="uq_pos_position_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	position_code = Column(String(100), nullable=False)
	title = Column(String(200), nullable=False)
	department_id = Column(String(50), nullable=True)
	entity_id = Column(String(50), nullable=True, index=True)
	grade_level = Column(String(50), nullable=True)
	employment_type = Column(
		String(20),
		nullable=False,
		default="FULL_TIME",
		comment="FULL_TIME | PART_TIME | CONTRACT",
	)
	status = Column(
		String(20),
		nullable=False,
		default="VACANT",
		comment="FILLED | VACANT | FROZEN | PROPOSED",
	)
	budget_salary_cents = Column(BigInteger, nullable=True)
	incumbent_employee_id = Column(String(50), nullable=True, comment="Soft FK to HCM employee")
	approved_by = Column(String(50), nullable=True)
	headcount_budget = Column(
		Numeric(6, 2),
		nullable=False,
		default=1.0,
		comment="FTE allocation: 1.0 = full-time, 0.5 = half-time",
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

	def __repr__(self) -> str:
		return (
			f"<Position {self.position_code!r} {self.title!r} "
			f"status={self.status!r} entity={self.entity_id!r}>"
		)


# ---------------------------------------------------------------------------
# HeadcountRequest
# ---------------------------------------------------------------------------

class HeadcountRequest(AuditMixin, Model):
	"""Annual headcount planning request for an entity / cost centre.

	positions JSONB: list of proposed position slots with individual budgets.
	  [{
	    "position_code": str,
	    "fte": float,
	    "budget_salary_cents": int,
	    "start_date": "YYYY-MM-DD",
	    "justification": str
	  }]

	Status machine:
	  DRAFT → SUBMITTED → APPROVED
	                    → REJECTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "pos_headcount_request"
	__table_args__ = (
		Index("ix_pos_hcreq_tenant_entity_year", "tenant_id", "entity_id", "request_year"),
		Index("ix_pos_hcreq_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	entity_id = Column(String(50), nullable=False, index=True)
	request_year = Column(Integer, nullable=False)
	total_fte_requested = Column(Numeric(8, 2), nullable=False, default=0)
	total_fte_approved = Column(Numeric(8, 2), nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | SUBMITTED | APPROVED | REJECTED",
	)
	submitted_by = Column(String(50), nullable=True)
	approved_by = Column(String(50), nullable=True)
	positions = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{position_code, fte, budget_salary_cents, start_date, justification}]",
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

	def __repr__(self) -> str:
		return (
			f"<HeadcountRequest entity={self.entity_id!r} year={self.request_year} "
			f"fte_req={self.total_fte_requested} status={self.status!r}>"
		)


__all__ = [
	"Position",
	"HeadcountRequest",
]
