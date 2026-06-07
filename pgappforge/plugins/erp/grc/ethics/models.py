"""
pgappforge/plugins/erp/grc/ethics/models.py

Ethics Hotline models.

Tables:
  eth_report   — anonymous/named reports submitted via hotline
  eth_case     — investigation case opened against a report

PII discipline:
  anonymous_token stores SHA-256(raw_token) only.
  reporter_contact is stored encrypted if the reporter opts in.
  Neither field appears in domain events.
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
# EthicsReport  (eth_report)
# ---------------------------------------------------------------------------

class EthicsReport(AuditMixin, Model):
	"""An ethics hotline submission.

	anonymous_token: SHA-256 hex digest of the raw token given to the reporter.
	  Reporters supply the raw token to check_status(); the service hashes it
	  server-side and looks up this column — the raw token is never stored.

	reporter_contact: nullable; stored encrypted when reporter opts in; used
	  only by the assigned investigator.

	status lifecycle:
	  SUBMITTED → ACKNOWLEDGED → UNDER_INVESTIGATION → RESOLVED | UNFOUNDED | CLOSED
	"""

	__allow_unmapped__ = True
	__tablename__ = "eth_report"
	__table_args__ = (
		Index("ix_eth_report_status_sev", "tenant_id", "status", "severity"),
		Index("ix_eth_report_token", "anonymous_token"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	anonymous_token = Column(
		String(64),
		nullable=False,
		unique=True,
		comment="SHA-256 hex of the raw reporter token — raw token never stored",
	)
	category = Column(
		String(30),
		nullable=False,
		comment=(
			"BRIBERY | FRAUD | HARASSMENT | DISCRIMINATION | "
			"SAFETY | CONFLICT_OF_INTEREST | OTHER"
		),
	)
	description = Column(Text, nullable=False)
	occurred_at = Column(Date, nullable=True)
	location = Column(String(200), nullable=True)
	severity = Column(
		String(20),
		nullable=False,
		default="MEDIUM",
		comment="LOW | MEDIUM | HIGH | CRITICAL",
	)
	status = Column(
		String(30),
		nullable=False,
		default="SUBMITTED",
		comment=(
			"SUBMITTED | ACKNOWLEDGED | UNDER_INVESTIGATION | "
			"RESOLVED | CLOSED | UNFOUNDED"
		),
	)
	is_anonymous = Column(Boolean, nullable=False, default=True)
	reporter_contact = Column(
		String(200),
		nullable=True,
		comment="Encrypted contact details — opt-in only",
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

	case: EthicsCase | None = relationship(
		"EthicsCase",
		back_populates="report",
		uselist=False,
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EthicsReport id={self.id!r} category={self.category!r}"
			f" severity={self.severity!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# EthicsCase  (eth_case)
# ---------------------------------------------------------------------------

class EthicsCase(AuditMixin, Model):
	"""Investigation case for an ethics report.

	One-to-one with EthicsReport.
	timeline: JSONB append-only log [{ts, action, by}, ...].

	resolution_category:
	  SUBSTANTIATED | UNSUBSTANTIATED | UNABLE_TO_DETERMINE
	"""

	__allow_unmapped__ = True
	__tablename__ = "eth_case"
	__table_args__ = (
		Index("ix_eth_case_assigned", "assigned_to", "report_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	report_id = Column(
		UUID(as_uuid=False),
		ForeignKey("eth_report.id", ondelete="CASCADE"),
		nullable=False,
		unique=True,
	)
	assigned_to = Column(String(50), nullable=False)
	opened_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	findings = Column(Text, nullable=True)
	resolution = Column(Text, nullable=True)
	resolution_category = Column(
		String(30),
		nullable=True,
		comment="SUBSTANTIATED | UNSUBSTANTIATED | UNABLE_TO_DETERMINE",
	)
	closed_at = Column(DateTime(timezone=True), nullable=True)
	is_confidential = Column(Boolean, nullable=False, default=True)
	timeline: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="Append-only log: [{ts, action, by}, ...]",
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

	report: EthicsReport = relationship(
		"EthicsReport",
		back_populates="case",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<EthicsCase id={self.id!r} report={self.report_id!r}"
			f" assigned_to={self.assigned_to!r}>"
		)


__all__ = ["EthicsReport", "EthicsCase"]
