"""
pgappforge/plugins/erp/procurement/trade_compliance/models.py

Trade Compliance models.

Tables:
  trd_restriction_list  — OFAC/UN/EU/UK/LOCAL sanctions lists with embedded entries
  trd_screening_result  — per-entity screening results with fuzzy match scores
  trd_hs_code           — product HS code mappings with duty rates
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	CheckConstraint,
	Column,
	DateTime,
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
# TradeRestrictionList
# ---------------------------------------------------------------------------

class TradeRestrictionList(AuditMixin, Model):
	"""Sanctions / denied-party list with embedded entries.

	list_name: OFAC_SDN | UN_CONSOLIDATED | EU_SANCTIONS | UK_SANCTIONS | LOCAL
	entries: [{name, aliases:[], nationality, entity_type}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "trd_restriction_list"
	__table_args__ = (
		UniqueConstraint("tenant_id", "list_name", name="uq_trd_list_tenant_name"),
		Index("ix_trd_list_active", "tenant_id", "list_name", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	list_name = Column(
		String(50),
		nullable=False,
		comment="OFAC_SDN | UN_CONSOLIDATED | EU_SANCTIONS | UK_SANCTIONS | LOCAL",
	)
	description = Column(Text, nullable=True)
	last_updated = Column(DateTime(timezone=True), nullable=True)
	entry_count = Column(Integer, nullable=False, default=0)
	is_active = Column(Boolean, nullable=False, default=True)
	entries: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{name, aliases:[], nationality, entity_type}]",
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
		return f"<TradeRestrictionList {self.list_name!r} entries={self.entry_count}>"


# ---------------------------------------------------------------------------
# TradeScreeningResult
# ---------------------------------------------------------------------------

class TradeScreeningResult(AuditMixin, Model):
	"""Record of a single entity name screened against active restriction lists.

	status: CLEAR | MATCH | POSSIBLE_MATCH
	top_match_score: Jaro-Winkler similarity 0.0–1.0
	"""

	__allow_unmapped__ = True
	__tablename__ = "trd_screening_result"
	__table_args__ = (
		Index("ix_trd_screen_status_date", "tenant_id", "status", "screened_at"),
		Index("ix_trd_screen_entity", "entity_name", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	entity_name = Column(String(300), nullable=False)
	screened_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	hit_count = Column(Integer, nullable=False, default=0)
	top_match_name = Column(String(300), nullable=True)
	top_match_score: Decimal | None = Column(
		Numeric(6, 4),
		nullable=True,
		comment="Jaro-Winkler score 0.0–1.0",
	)
	matched_list = Column(String(50), nullable=True)
	status = Column(
		String(20),
		nullable=False,
		comment="CLEAR | MATCH | POSSIBLE_MATCH",
	)
	source_document_type = Column(
		String(50),
		nullable=True,
		comment="SUPPLIER | CUSTOMER | EMPLOYEE",
	)
	source_document_id = Column(String(50), nullable=True)

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
			f"<TradeScreeningResult {self.entity_name!r} status={self.status!r}"
			f" score={self.top_match_score}>"
		)


# ---------------------------------------------------------------------------
# HSCodeMapping
# ---------------------------------------------------------------------------

class HSCodeMapping(AuditMixin, Model):
	"""Product-to-HS-code mapping with duty rate and export control flag.

	country_code: NULL = universal; set for country-specific overrides.
	"""

	__allow_unmapped__ = True
	__tablename__ = "trd_hs_code"
	__table_args__ = (
		Index("ix_trd_hs_product", "tenant_id", "product_code"),
		Index("ix_trd_hs_code", "hs_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	product_code = Column(String(100), nullable=False)
	hs_code = Column(String(12), nullable=False)
	description = Column(Text, nullable=True)
	country_code = Column(
		String(3),
		nullable=True,
		comment="NULL = universal; ISO-3166-1 alpha-3 for country-specific override",
	)
	duty_rate_pct: Decimal = Column(
		Numeric(8, 4),
		nullable=False,
		default=Decimal("0"),
	)
	is_controlled = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="Export-controlled item",
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
			f"<HSCodeMapping product={self.product_code!r} hs={self.hs_code!r}"
			f" duty={self.duty_rate_pct}%>"
		)


# ---------------------------------------------------------------------------
# CustomsDeclaration
# ---------------------------------------------------------------------------

class CustomsDeclaration(AuditMixin, Model):
	"""Customs declaration assembled from HS-code duty calculations."""

	__allow_unmapped__ = True
	__tablename__ = "trd_customs_declaration"
	__table_args__ = (
		Index("ix_trd_decl_shipment", "shipment_id"),
		Index("ix_trd_decl_tenant_status", "tenant_id", "status"),
		CheckConstraint(
			"status IN ('DRAFT','SUBMITTED','CLEARED','REJECTED')",
			name="ck_trd_decl_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	shipment_id = Column(String(50), nullable=False, index=True)
	export_country = Column(String(2), nullable=False)
	import_country = Column(String(2), nullable=False)
	total_value_cents = Column(Integer, nullable=False, default=0)
	total_duty_cents = Column(Integer, nullable=False, default=0)
	lines = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="[{hs_code, description, value_cents, duty_cents, duty_rate_pct}]",
	)
	status = Column(String(20), nullable=False, default="DRAFT")
	submitted_at = Column(DateTime(timezone=True), nullable=True)
	cleared_at = Column(DateTime(timezone=True), nullable=True)
	declaration_reference = Column(String(100), nullable=True)

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
		return f"<CustomsDeclaration shipment={self.shipment_id!r} status={self.status!r}>"


__all__ = [
	"TradeRestrictionList",
	"TradeScreeningResult",
	"HSCodeMapping",
	"CustomsDeclaration",
]
