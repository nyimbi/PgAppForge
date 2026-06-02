"""
pgappforge/plugins/erp/grc/privacy/models.py

GDPR / Privacy models — consent tracking, data subject requests, and
Article 30 data processing records.

Entities:
  ConsentRecord         — per-party, per-purpose consent lifecycle
  DataSubjectRequest    — DSR workflow (access/erasure/portability/etc.)
  DataProcessingRecord  — Article 30 register of processing activities

Design:
  - ConsentRecord is APPEND-ONLY (withdrawn_at set; never delete rows)
  - DSR numbers are unique, human-readable (service generates DSR-YYYYMM-NNNNN)
  - ip_address stored as String(45) for IPv4/IPv6
  - legal_basis uses GDPR Article 6 vocabulary
  - All PKs: UUID v4; all timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id on all entities
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# Legal basis vocabulary (GDPR Art. 6)
_LEGAL_BASIS = (
	"CONSENT | CONTRACT | LEGAL_OBLIGATION | VITAL_INTERESTS"
	" | PUBLIC_TASK | LEGITIMATE_INTERESTS"
)


# ---------------------------------------------------------------------------
# ConsentRecord
# ---------------------------------------------------------------------------

class ConsentRecord(Model):
	"""Point-in-time consent grant or withdrawal for a party and purpose.

	APPEND-ONLY: never update rows.  To record a withdrawal, set withdrawn_at
	on a new row with the same party_id + purpose, or use the service's
	withdraw_consent() method which inserts a new record.

	version: document version the party consented to (e.g. 'PP-2025-01').
	source:  acquisition channel e.g. 'WEB_FORM', 'API', 'PAPER'.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_consent_record"
	__table_args__ = (
		Index("ix_erp_consent_party", "party_id"),
		Index("ix_erp_consent_tenant", "tenant_id"),
		Index("ix_erp_consent_purpose", "purpose"),
		Index("ix_erp_consent_granted", "granted_at", postgresql_using="brin"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="The data subject (foundation.Party)",
	)
	purpose = Column(
		String(500),
		nullable=False,
		comment="Processing purpose e.g. 'marketing_emails', 'analytics'",
	)
	legal_basis = Column(
		String(30),
		nullable=False,
		comment=_LEGAL_BASIS,
	)
	granted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	withdrawn_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = consent still active",
	)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = no expiry; set for time-limited consent",
	)
	source = Column(
		String(100),
		nullable=True,
		comment="Acquisition channel: WEB_FORM | API | PAPER | IMPORT",
	)
	version = Column(
		String(50),
		nullable=True,
		comment="Privacy policy / terms version the party consented to",
	)
	ip_address = Column(
		String(45),
		nullable=True,
		comment="IP address at time of consent (IPv4 or IPv6)",
	)

	def __repr__(self) -> str:
		active = self.withdrawn_at is None
		return (
			f"<ConsentRecord {self.id!r} party={self.party_id!r}"
			f" purpose={self.purpose!r} active={active}>"
		)


# ---------------------------------------------------------------------------
# DataSubjectRequest
# ---------------------------------------------------------------------------

class DataSubjectRequest(AuditMixin, Model):
	"""Data Subject Request (DSR) workflow record.

	dsr_number: unique human-readable reference (e.g. 'DSR-202501-00042').
	due_at: computed from received_at + regulatory deadline (typically 30 days).
	response_url: link to the packaged data export or erasure confirmation.

	Status flow: RECEIVED → VERIFIED → IN_PROGRESS → COMPLETED | REJECTED
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_dsr"
	__table_args__ = (
		UniqueConstraint("dsr_number", name="uq_erp_dsr_number"),
		Index("ix_erp_dsr_party", "party_id"),
		Index("ix_erp_dsr_tenant", "tenant_id"),
		Index("ix_erp_dsr_status", "status"),
		Index("ix_erp_dsr_due", "due_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	dsr_number = Column(
		String(50),
		nullable=False,
		unique=True,
		comment="Human-readable ref e.g. DSR-202501-00042",
	)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)
	request_type = Column(
		String(15),
		nullable=False,
		comment=(
			"ACCESS | ERASURE | RECTIFICATION | PORTABILITY"
			" | RESTRICTION | OBJECTION"
		),
	)
	status = Column(
		String(15),
		nullable=False,
		default="RECEIVED",
		comment="RECEIVED | VERIFIED | IN_PROGRESS | COMPLETED | REJECTED",
	)
	received_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	due_at = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Regulatory deadline (typically received_at + 30 days)",
	)
	completed_at = Column(DateTime(timezone=True), nullable=True)
	response_url = Column(
		Text,
		nullable=True,
		comment="URL to the packaged data export or confirmation document",
	)
	notes = Column(Text, nullable=True)

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
			f"<DataSubjectRequest {self.dsr_number!r}"
			f" type={self.request_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# DataProcessingRecord
# ---------------------------------------------------------------------------

class DataProcessingRecord(AuditMixin, Model):
	"""Article 30 GDPR record of processing activities (RoPA).

	One row per distinct processing activity.
	recipients: JSONB list of recipient category objects
	  e.g. [{"name": "Mailchimp", "role": "processor", "country": "US"}]
	safeguards: JSONB list of transfer mechanism objects
	  e.g. [{"mechanism": "SCCs", "reference": "EU2021/914"}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_data_processing_record"
	__table_args__ = (
		Index("ix_erp_dpr_tenant", "tenant_id"),
		Index("ix_erp_dpr_legal_basis", "legal_basis"),
		Index("ix_erp_dpr_cross_border", "is_cross_border"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	processing_purpose = Column(String(500), nullable=False)
	data_categories = Column(
		ARRAY(String),
		nullable=False,
		default=list,
		comment="Categories of personal data e.g. ARRAY['name','email','health']",
	)
	data_subjects_description = Column(
		Text,
		nullable=False,
		comment="Description of data subject categories",
	)
	recipients: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of recipient / processor objects",
	)
	retention_period_days = Column(
		Integer,
		nullable=False,
		comment="Retention period in days; -1 = indefinite",
	)
	legal_basis = Column(String(30), nullable=False, comment=_LEGAL_BASIS)
	controller_name = Column(String(300), nullable=False)
	processor_name = Column(
		String(300),
		nullable=True,
		comment="NULL if no separate processor",
	)
	is_cross_border = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True if personal data is transferred outside EEA",
	)
	safeguards: list[dict] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="Transfer safeguard mechanisms e.g. SCCs, BCRs",
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
			f"<DataProcessingRecord {self.id!r}"
			f" purpose={self.processing_purpose!r}"
			f" cross_border={self.is_cross_border}>"
		)


__all__ = [
	"ConsentRecord",
	"DataSubjectRequest",
	"DataProcessingRecord",
]
