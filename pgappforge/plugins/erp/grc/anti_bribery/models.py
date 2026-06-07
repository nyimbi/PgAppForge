"""
pgappforge/plugins/erp/grc/anti_bribery/models.py

Anti-Bribery & Corruption models.

Tables:
  ab_gift             — gifts & entertainment log (FCPA / UK Bribery Act)
  ab_coi_declaration  — conflict of interest declarations
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
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GiftEntertainmentLog  (ab_gift)
# ---------------------------------------------------------------------------

class GiftEntertainmentLog(AuditMixin, Model):
	"""Gift, meal, travel, or entertainment entry for FCPA / UK Bribery Act compliance.

	value_cents: BigInteger (pence/cents); avoids floating-point rounding.
	is_government_official: triggers stricter threshold (often $0 under FCPA).
	direction: GIVEN (employee gave) | RECEIVED (employee received).

	status lifecycle:
	  PENDING → APPROVED | REJECTED
	  PENDING → AUTO_APPROVED  (value below configured threshold)
	"""

	__allow_unmapped__ = True
	__tablename__ = "ab_gift"
	__table_args__ = (
		Index("ix_ab_gift_status", "tenant_id", "status"),
		Index("ix_ab_gift_employee_date", "employee_id", "given_date"),
		Index("ix_ab_gift_govt_status", "is_government_official", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	given_to_name = Column(String(200), nullable=False)
	given_to_organization = Column(String(200), nullable=True)
	gift_type = Column(
		String(30),
		nullable=False,
		comment="GIFT | MEAL | ENTERTAINMENT | TRAVEL | TRAINING | OTHER",
	)
	value_cents = Column(
		BigInteger,
		nullable=False,
		comment="Value in smallest currency unit (cents/pence)",
	)
	given_date = Column(Date, nullable=False)
	purpose = Column(Text, nullable=False)
	is_government_official = Column(Boolean, nullable=False, default=False)
	employee_id = Column(String(50), nullable=False, comment="FAB user ID of giver/receiver")
	direction = Column(
		String(10),
		nullable=False,
		default="GIVEN",
		comment="GIVEN | RECEIVED",
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | APPROVED | REJECTED | AUTO_APPROVED",
	)
	approved_by = Column(String(50), nullable=True)
	approval_notes = Column(Text, nullable=True)
	country_code = Column(String(3), nullable=True, comment="ISO 3166-1 alpha-3")

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
			f"<GiftEntertainmentLog id={self.id!r} type={self.gift_type!r}"
			f" value_cents={self.value_cents} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# ConflictOfInterestDeclaration  (ab_coi_declaration)
# ---------------------------------------------------------------------------

class ConflictOfInterestDeclaration(AuditMixin, Model):
	"""Employee self-declaration of a potential conflict of interest.

	category:
	  FINANCIAL_INTEREST | FAMILY_MEMBER | OUTSIDE_EMPLOYMENT |
	  BOARD_SEAT | OTHER

	status lifecycle:
	  PENDING → REVIEWED → CLOSED | ESCALATED
	"""

	__allow_unmapped__ = True
	__tablename__ = "ab_coi_declaration"
	__table_args__ = (
		Index("ix_ab_coi_status", "tenant_id", "status"),
		Index("ix_ab_coi_employee", "employee_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	employee_id = Column(String(50), nullable=False)
	category = Column(
		String(50),
		nullable=False,
		comment=(
			"FINANCIAL_INTEREST | FAMILY_MEMBER | OUTSIDE_EMPLOYMENT | "
			"BOARD_SEAT | OTHER"
		),
	)
	description = Column(Text, nullable=False)
	declaration_date = Column(Date, nullable=False)
	relates_to_supplier = Column(String(200), nullable=True)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | REVIEWED | CLOSED | ESCALATED",
	)
	reviewed_by = Column(String(50), nullable=True)
	reviewed_at = Column(DateTime(timezone=True), nullable=True)
	review_notes = Column(Text, nullable=True)

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
			f"<ConflictOfInterestDeclaration employee={self.employee_id!r}"
			f" category={self.category!r} status={self.status!r}>"
		)


__all__ = ["GiftEntertainmentLog", "ConflictOfInterestDeclaration"]
