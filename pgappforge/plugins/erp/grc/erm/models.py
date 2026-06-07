"""
pgappforge/plugins/erp/grc/erm/models.py

Enterprise Risk Management models.

Tables:
  erm_risk        — risk register entry (likelihood × impact heat map)
  erm_mitigation  — action items linked to a risk
  erm_kri         — key risk indicators with threshold monitoring
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RiskRegister  (erm_risk)
# ---------------------------------------------------------------------------

class RiskRegister(AuditMixin, Model):
	"""Enterprise risk register entry.

	risk_score = likelihood_score × impact_score (1–25).
	risk_level is derived on write:
	  1–4   → LOW
	  5–9   → MEDIUM
	  10–19 → HIGH
	  20–25 → CRITICAL

	treatment:
	  ACCEPT | MITIGATE | TRANSFER | AVOID
	"""

	__allow_unmapped__ = True
	__tablename__ = "erm_risk"
	__table_args__ = (
		Index("ix_erm_risk_cat_level", "tenant_id", "category", "risk_level"),
		Index("ix_erm_risk_status", "tenant_id", "status"),
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
	description = Column(Text, nullable=True)
	category = Column(
		String(50),
		nullable=False,
		comment=(
			"FINANCIAL | OPERATIONAL | STRATEGIC | "
			"COMPLIANCE | REPUTATIONAL | TECHNOLOGY"
		),
	)
	likelihood_score = Column(
		Integer,
		nullable=False,
		comment="1 (Rare) to 5 (Almost Certain)",
	)
	impact_score = Column(
		Integer,
		nullable=False,
		comment="1 (Negligible) to 5 (Catastrophic)",
	)
	risk_score = Column(
		Integer,
		nullable=False,
		comment="likelihood_score × impact_score; computed on write",
	)
	risk_level = Column(
		String(20),
		nullable=False,
		comment="LOW | MEDIUM | HIGH | CRITICAL — derived from risk_score",
	)
	treatment = Column(
		String(20),
		nullable=False,
		default="ACCEPT",
		comment="ACCEPT | MITIGATE | TRANSFER | AVOID",
	)
	owner_id = Column(String(50), nullable=True, comment="Logical FK to FAB user or erp_party")
	entity_id = Column(String(50), nullable=True, comment="Business entity owning the risk")
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | CLOSED | MONITORING",
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

	mitigations: list[RiskMitigationAction] = relationship(
		"RiskMitigationAction",
		back_populates="risk",
		cascade="all, delete-orphan",
		lazy="select",
	)
	kris: list[KeyRiskIndicator] = relationship(
		"KeyRiskIndicator",
		back_populates="risk",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RiskRegister {self.name!r} score={self.risk_score}"
			f" level={self.risk_level!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# RiskMitigationAction  (erm_mitigation)
# ---------------------------------------------------------------------------

class RiskMitigationAction(AuditMixin, Model):
	"""Action item to reduce likelihood or impact of a risk.

	status lifecycle:
	  PLANNED → IN_PROGRESS → COMPLETED
	  PLANNED/IN_PROGRESS → OVERDUE  (set by monitor job when due_date passed)
	"""

	__allow_unmapped__ = True
	__tablename__ = "erm_mitigation"
	__table_args__ = (
		Index("ix_erm_mitigation_risk_status", "risk_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	risk_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erm_risk.id", ondelete="CASCADE"),
		nullable=False,
	)
	action_description = Column(Text, nullable=False)
	owner_id = Column(String(50), nullable=False)
	due_date = Column(Date, nullable=False)
	status = Column(
		String(20),
		nullable=False,
		default="PLANNED",
		comment="PLANNED | IN_PROGRESS | COMPLETED | OVERDUE",
	)
	completion_date = Column(Date, nullable=True)
	evidence = Column(Text, nullable=True)

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

	risk: RiskRegister = relationship(
		"RiskRegister",
		back_populates="mitigations",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RiskMitigationAction risk={self.risk_id!r}"
			f" status={self.status!r} due={self.due_date!r}>"
		)


# ---------------------------------------------------------------------------
# KeyRiskIndicator  (erm_kri)
# ---------------------------------------------------------------------------

class KeyRiskIndicator(AuditMixin, Model):
	"""Quantitative metric monitored against a threshold to detect risk movement.

	breach_direction:
	  ABOVE — breach when current_value > threshold_value
	  BELOW — breach when current_value < threshold_value

	breach_status:
	  OK | WARNING | BREACH
	"""

	__allow_unmapped__ = True
	__tablename__ = "erm_kri"
	__table_args__ = (
		Index("ix_erm_kri_risk", "risk_id"),
		Index("ix_erm_kri_breach", "tenant_id", "breach_status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	risk_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erm_risk.id", ondelete="CASCADE"),
		nullable=False,
	)
	metric_name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	threshold_value = Column(Numeric(15, 4), nullable=False)
	current_value = Column(Numeric(15, 4), nullable=True)
	breach_direction = Column(
		String(10),
		nullable=False,
		default="ABOVE",
		comment="ABOVE | BELOW",
	)
	breach_status = Column(
		String(20),
		nullable=False,
		default="OK",
		comment="OK | WARNING | BREACH",
	)
	last_updated = Column(DateTime(timezone=True), nullable=True)

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

	risk: RiskRegister = relationship(
		"RiskRegister",
		back_populates="kris",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KeyRiskIndicator {self.metric_name!r} threshold={self.threshold_value}"
			f" current={self.current_value} status={self.breach_status!r}>"
		)


__all__ = ["RiskRegister", "RiskMitigationAction", "KeyRiskIndicator"]
