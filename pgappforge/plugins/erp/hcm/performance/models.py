"""
pgappforge/plugins/erp/hcm/performance/models.py

SQLAlchemy models for the HCM Performance Review plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - Ratings: Numeric(4,2) — stored as exact decimal, never float
  - ALL models: tenant_id NOT NULL + AuditMixin
  - PostgreSQL only: JSONB used for structured flexible columns
  - lazy='select' throughout (SA 2.x)

Table prefix: prf_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Numeric,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PerformanceCycle
# ---------------------------------------------------------------------------

class PerformanceCycle(AuditMixin, Model):
	"""A performance review cycle (annual, quarterly, or rolling).

	review_form JSONB shape:
	  {
	    "competencies": [{"name": str, "description": str, "max_rating": 5}],
	    "weights": {"self": 20, "manager": 60, "peer": 20}
	  }

	Status machine:
	  DRAFT → ACTIVE → CALIBRATING → CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "prf_cycle"
	__table_args__ = (
		Index("ix_prf_cycle_tenant_status_type", "tenant_id", "status", "cycle_type"),
		Index("ix_prf_cycle_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	cycle_type = Column(
		String(20),
		nullable=False,
		comment="ANNUAL | QUARTERLY | CONTINUOUS",
	)
	start_date = Column(Date, nullable=False)
	end_date = Column(Date, nullable=False)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | ACTIVE | CALIBRATING | CLOSED",
	)
	review_form = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment='{"competencies": [{name, description, max_rating}], "weights": {self, manager, peer}}',
	)
	entity_id = Column(String(50), nullable=True, index=True)

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
	reviews: list[PerformanceReview] = relationship(
		"PerformanceReview", back_populates="cycle", cascade="all, delete-orphan", lazy="select"
	)
	goals: list[Goal] = relationship(
		"Goal", back_populates="cycle", lazy="select"
	)

	def __repr__(self) -> str:
		return f"<PerformanceCycle {self.name!r} type={self.cycle_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# PerformanceReview
# ---------------------------------------------------------------------------

class PerformanceReview(AuditMixin, Model):
	"""An individual review form submitted by a reviewer for an employee.

	competency_scores JSONB: {competency_name: score}
	  e.g. {"Leadership": 4.0, "Execution": 3.5}

	Status machine:
	  PENDING → IN_PROGRESS → SUBMITTED → ACKNOWLEDGED
	"""

	__allow_unmapped__ = True
	__tablename__ = "prf_review"
	__table_args__ = (
		Index("ix_prf_review_cycle_emp_type", "cycle_id", "employee_id", "review_type"),
		Index("ix_prf_review_reviewer_status", "reviewer_id", "status"),
		Index("ix_prf_review_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	cycle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("prf_cycle.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	employee_id = Column(String(50), nullable=False, index=True)
	reviewer_id = Column(String(50), nullable=False, index=True)
	review_type = Column(
		String(20),
		nullable=False,
		comment="SELF | MANAGER | PEER | 360_UPWARD",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | IN_PROGRESS | SUBMITTED | ACKNOWLEDGED",
	)
	overall_rating = Column(
		Numeric(4, 2),
		nullable=True,
		comment="1.00 – 5.00",
	)
	competency_scores = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="{competency_name: score}",
	)
	strengths = Column(Text, nullable=True)
	development_areas = Column(Text, nullable=True)
	development_notes = Column(Text, nullable=True)
	submitted_at = Column(DateTime(timezone=True), nullable=True)

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
	cycle: PerformanceCycle = relationship(
		"PerformanceCycle", back_populates="reviews", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<PerformanceReview emp={self.employee_id!r} "
			f"type={self.review_type!r} rating={self.overall_rating} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

class Goal(AuditMixin, Model):
	"""An employee goal / OKR.

	key_results JSONB: [{kr_text, target, current, unit}]
	  e.g. [{"kr_text": "Increase NPS", "target": 50, "current": 42, "unit": "points"}]

	period: free-form string; convention "2025-Q1" or "2025".
	progress_pct: 0–100 overall; updated by update_progress().

	Status machine:
	  DRAFT → ACTIVE → COMPLETED
	  ACTIVE → CANCELLED
	"""

	__allow_unmapped__ = True
	__tablename__ = "prf_goal"
	__table_args__ = (
		Index("ix_prf_goal_emp_period_status", "employee_id", "period", "status"),
		Index("ix_prf_goal_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	employee_id = Column(String(50), nullable=False, index=True)
	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=True)
	goal_type = Column(
		String(20),
		nullable=False,
		default="OKR",
		comment="OKR | SMART | STRETCH | OPERATIONAL",
	)
	key_results = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{kr_text, target, current, unit}]",
	)
	weight_pct = Column(Numeric(6, 2), nullable=False, default=0)
	progress_pct = Column(Numeric(6, 2), nullable=False, default=0)
	period = Column(String(20), nullable=False, comment="e.g. '2025-Q1' or '2025'")
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="DRAFT | ACTIVE | COMPLETED | CANCELLED",
	)
	cycle_id = Column(
		UUID(as_uuid=False),
		ForeignKey("prf_cycle.id", ondelete="SET NULL"),
		nullable=True,
		index=True,
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

	# Relationships
	cycle: PerformanceCycle | None = relationship(
		"PerformanceCycle", back_populates="goals", lazy="select"
	)

	def __repr__(self) -> str:
		return (
			f"<Goal emp={self.employee_id!r} {self.title[:40]!r} "
			f"period={self.period!r} progress={self.progress_pct}%>"
		)


# ---------------------------------------------------------------------------
# ContinuousFeedback
# ---------------------------------------------------------------------------

class ContinuousFeedback(AuditMixin, Model):
	"""Lightweight peer / manager / upward feedback outside a formal cycle.

	tags JSONB: list of free-form strings, e.g. ["collaboration","innovation"].
	visibility controls who can read the feedback besides HR admin.
	"""

	__allow_unmapped__ = True
	__tablename__ = "prf_feedback"
	__table_args__ = (
		Index("ix_prf_feedback_to_visibility", "to_employee_id", "visibility"),
		Index("ix_prf_feedback_from", "from_employee_id"),
		Index("ix_prf_feedback_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	from_employee_id = Column(String(50), nullable=False, index=True)
	to_employee_id = Column(String(50), nullable=False, index=True)
	feedback_text = Column(Text, nullable=False)
	visibility = Column(
		String(20),
		nullable=False,
		default="PRIVATE",
		comment="PUBLIC | MANAGER_VISIBLE | PRIVATE",
	)
	tags = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='["collaboration", "innovation", ...]',
	)
	context = Column(String(200), nullable=True, comment="e.g. 'Q2 2025 project'")

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
			f"<ContinuousFeedback from={self.from_employee_id!r} "
			f"to={self.to_employee_id!r} visibility={self.visibility!r}>"
		)


__all__ = [
	"PerformanceCycle",
	"PerformanceReview",
	"Goal",
	"ContinuousFeedback",
]
