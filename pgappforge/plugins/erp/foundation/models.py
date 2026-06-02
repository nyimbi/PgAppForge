"""
pgappforge/plugins/erp/foundation/models.py

Core shared entities for the ERP Foundation plugin.

Design rules enforced here:
  - All PKs: UUID v4 via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL (except lookup tables Currency/Country/CodeTable)
  - Monetary amounts: never stored here (foundation has no financials), but
    ExchangeRate.rate is NUMERIC(20,8) — never float
  - AuditMixin applied to all mutable entities
  - JSONB for semi-structured attributes
  - GeoAlchemy2 Point for address geocoordinates (optional dep — graceful fallback)
  - Financial correction pattern: DomainEventLog is append-only (no UPDATE path)

Table name conventions: erp_<entity>
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
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
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Try to import GeoAlchemy2; fall back to a plain Text column if not installed
# ---------------------------------------------------------------------------
try:
	from geoalchemy2 import Geometry as _Geometry
	_GEO_AVAILABLE = True
except ImportError:
	_GEO_AVAILABLE = False
	log.debug("geoalchemy2 not installed — Address.geo_point stored as Text (WKT)")


def _geo_point_column():
	if _GEO_AVAILABLE:
		from geoalchemy2 import Geometry
		return Column(Geometry("POINT", srid=4326), nullable=True)
	return Column(Text, nullable=True, comment="WKT POINT fallback (install geoalchemy2)")


# ---------------------------------------------------------------------------
# Party
# ---------------------------------------------------------------------------

class Party(AuditMixin, Model):
	"""Universal party entity — any actor in the business domain.

	Organisations, individuals, and groups all share this table (type
	discriminator: party_type).  The self-referential parent_id enables
	corporate hierarchies (subsidiary → parent).

	Immutable ledger note: do NOT update Party rows directly in financial
	plugins.  Emit a PartyUpdatedEvent and append a correction entry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_party"
	__table_args__ = (
		Index("ix_erp_party_tenant_type", "tenant_id", "party_type"),
		Index("ix_erp_party_tax_id", "tax_id"),
		Index("ix_erp_party_lei", "lei"),
		Index("ix_erp_party_name_trgm", "name", postgresql_using="gin",
		      postgresql_ops={"name": "gin_trgm_ops"}),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		index=True,
		comment="Multi-tenant isolation key",
	)

	# Discriminator
	party_type = Column(
		String(20),
		nullable=False,
		comment="ORGANIZATION | INDIVIDUAL | GROUP",
	)

	# Identity
	name = Column(String(500), nullable=False)
	short_name = Column(String(100), nullable=True)
	legal_name = Column(String(500), nullable=True)
	tax_id = Column(String(50), nullable=True, comment="TIN / EIN / UTR")
	vat_number = Column(String(50), nullable=True)
	registration_number = Column(String(100), nullable=True)
	lei = Column(String(20), nullable=True, comment="Legal Entity Identifier (ISO 17442)")
	website = Column(String(500), nullable=True)

	# State
	is_active = Column(Boolean, nullable=False, default=True)

	# Hierarchy (self-referential)
	parent_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
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
	parent: Party = relationship(
		"Party",
		remote_side="Party.id",
		foreign_keys=[parent_id],
		lazy="select",
	)
	children: list[Party] = relationship(
		"Party",
		foreign_keys=[parent_id],
		back_populates="parent",
		lazy="select",
	)
	roles: list[PartyRole] = relationship(
		"PartyRole",
		back_populates="party",
		cascade="all, delete-orphan",
		lazy="select",
	)
	addresses: list[Address] = relationship(
		"Address",
		back_populates="party",
		cascade="all, delete-orphan",
		lazy="select",
	)
	contacts: list[Contact] = relationship(
		"Contact",
		back_populates="party",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Party {self.id!r} type={self.party_type!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# PartyRole
# ---------------------------------------------------------------------------

class PartyRole(AuditMixin, Model):
	"""Typed role a Party plays in the business domain.

	A single Party can hold multiple roles simultaneously (e.g. a company that
	is both a CUSTOMER and a SUPPLIER).  Temporal validity is tracked via
	effective_from / effective_to (NULL effective_to = currently active).

	``attributes`` carries role-specific data in JSONB — e.g. credit_limit,
	payment_terms, employee_number — without schema migrations per role type.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_party_role"
	__table_args__ = (
		Index("ix_erp_party_role_party", "party_id"),
		Index("ix_erp_party_role_type", "role_type"),
		Index("ix_erp_party_role_tenant", "tenant_id"),
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
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
	)
	role_type = Column(
		String(20),
		nullable=False,
		comment="CUSTOMER | SUPPLIER | EMPLOYEE | PARTNER | OTHER",
	)
	effective_from = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	effective_to = Column(DateTime(timezone=True), nullable=True)
	attributes: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Role-specific attributes: credit_limit, payment_terms, etc.",
	)

	party: Party = relationship("Party", back_populates="roles", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PartyRole {self.id!r} party={self.party_id!r} "
			f"role={self.role_type!r} from={self.effective_from!r}>"
		)


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

class Address(AuditMixin, Model):
	"""Physical or postal address for a Party.

	geo_point stores a PostGIS GEOMETRY(Point,4326) for spatial queries when
	geoalchemy2 is installed; falls back to Text (WKT) otherwise.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_address"
	__table_args__ = (
		Index("ix_erp_address_party", "party_id"),
		Index("ix_erp_address_tenant", "tenant_id"),
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
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
	)
	address_type = Column(
		String(20),
		nullable=False,
		comment="BILLING | SHIPPING | REGISTERED | WORK",
	)

	# Address lines
	line1 = Column(String(500), nullable=False)
	line2 = Column(String(500), nullable=True)
	city = Column(String(200), nullable=False)
	state = Column(String(200), nullable=True, comment="State / Province / County")
	postal_code = Column(String(20), nullable=True)
	country_code = Column(
		String(2),
		ForeignKey("erp_country.iso_alpha2"),
		nullable=False,
		index=True,
	)

	# Geocoordinate — dynamic column type depending on GeoAlchemy2 availability
	geo_point = _geo_point_column()

	is_default = Column(Boolean, nullable=False, default=False)
	is_verified = Column(Boolean, nullable=False, default=False)

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

	party: Party = relationship("Party", back_populates="addresses", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Address {self.id!r} party={self.party_id!r} "
			f"type={self.address_type!r} city={self.city!r}>"
		)


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------

class Contact(AuditMixin, Model):
	"""Communication channel (email, phone, etc.) for a Party."""

	__allow_unmapped__ = True
	__tablename__ = "erp_contact"
	__table_args__ = (
		Index("ix_erp_contact_party", "party_id"),
		Index("ix_erp_contact_type_value", "contact_type", "value"),
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
		ForeignKey("erp_party.id", ondelete="CASCADE"),
		nullable=False,
	)
	contact_type = Column(
		String(20),
		nullable=False,
		comment="EMAIL | PHONE | MOBILE | FAX | SOCIAL",
	)
	value = Column(String(500), nullable=False, comment="The contact value e.g. email address")
	is_primary = Column(Boolean, nullable=False, default=False)
	is_verified = Column(Boolean, nullable=False, default=False)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	party: Party = relationship("Party", back_populates="contacts", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<Contact {self.id!r} party={self.party_id!r} "
			f"type={self.contact_type!r} value={self.value!r}>"
		)


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

class Currency(Model):
	"""ISO 4217 currency master.

	No tenant_id — currencies are global lookup data.
	decimal_places: number of minor units (e.g. NGN=2, JPY=0, KWD=3).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_currency"
	__table_args__ = {"extend_existing": True}

	code = Column(
		String(3),
		primary_key=True,
		comment="ISO 4217 alpha-3 code e.g. USD, NGN, EUR",
	)
	name = Column(String(100), nullable=False)
	symbol = Column(String(10), nullable=False)
	decimal_places = Column(
		Integer,
		nullable=False,
		default=2,
		comment="Minor unit decimal places (0=JPY, 2=USD, 3=KWD)",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	exchange_rates_from: list[ExchangeRate] = relationship(
		"ExchangeRate",
		foreign_keys="ExchangeRate.from_currency",
		back_populates="from_currency_rel",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Currency {self.code!r} {self.symbol!r} dp={self.decimal_places}>"


# ---------------------------------------------------------------------------
# ExchangeRate
# ---------------------------------------------------------------------------

class ExchangeRate(Model):
	"""Point-in-time exchange rate between two currencies.

	Immutable ledger pattern: never UPDATE existing rows.  To correct a rate,
	INSERT a new row with the corrected value; the service layer always queries
	the most recent row for a given (from, to, date) triple.

	rate is NUMERIC(20,8) — never float.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_exchange_rate"
	__table_args__ = (
		Index("ix_erp_exrate_pair_date", "from_currency", "to_currency", "rate_date"),
		Index("ix_erp_exrate_expires", "expires_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	from_currency = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
	)
	to_currency = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=False,
	)
	rate = Column(
		Numeric(20, 8),
		nullable=False,
		comment="Multiplier: 1 from_currency = rate to_currency",
	)
	rate_date = Column(
		DateTime(timezone=True),
		nullable=False,
		comment="Effective date of this rate",
	)
	source = Column(
		String(20),
		nullable=False,
		default="MANUAL",
		comment="MANUAL | ECB | CENTRAL_BANK | OPENEXCHANGE",
	)
	expires_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="NULL = never expires",
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	from_currency_rel: Currency = relationship(
		"Currency",
		foreign_keys=[from_currency],
		back_populates="exchange_rates_from",
		lazy="select",
	)
	to_currency_rel: Currency = relationship(
		"Currency",
		foreign_keys=[to_currency],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ExchangeRate {self.from_currency}->{self.to_currency} "
			f"rate={self.rate!r} date={self.rate_date!r}>"
		)


# ---------------------------------------------------------------------------
# Country
# ---------------------------------------------------------------------------

class Country(Model):
	"""ISO 3166-1 country master.

	No tenant_id — global lookup data.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_country"
	__table_args__ = (
		Index("ix_erp_country_alpha3", "iso_alpha3"),
		{"extend_existing": True},
	)

	iso_alpha2 = Column(
		String(2),
		primary_key=True,
		comment="ISO 3166-1 alpha-2 e.g. NG, US, DE",
	)
	iso_alpha3 = Column(String(3), nullable=False, unique=True)
	name = Column(String(200), nullable=False)
	phone_prefix = Column(String(10), nullable=True, comment="e.g. +234")
	currency_code = Column(
		String(3),
		ForeignKey("erp_currency.code"),
		nullable=True,
		comment="Default currency for this country",
	)
	is_eu = Column(Boolean, nullable=False, default=False)
	is_active = Column(Boolean, nullable=False, default=True)

	currency: Currency = relationship("Currency", foreign_keys=[currency_code], lazy="select")

	def __repr__(self) -> str:
		return f"<Country {self.iso_alpha2!r} {self.name!r}>"


# ---------------------------------------------------------------------------
# CodeTable  (generic key/value lookup — replaces dozens of small enum tables)
# ---------------------------------------------------------------------------

class CodeTable(Model):
	"""Generic configurable lookup table.

	``domain`` namespaces the codes, e.g. "payment_terms", "industry_code",
	"document_type".  Within a domain, ``code`` is unique.

	``metadata_`` carries domain-specific extra fields in JSONB (column named
	metadata_ to avoid clash with SQLAlchemy's reserved ``metadata``).

	No tenant_id — codes are global by default; tenants can add their own
	domain namespaces without conflicts via naming convention e.g.
	"acme.payment_terms".
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_code_table"
	__table_args__ = (
		UniqueConstraint("domain", "code", name="uq_erp_code_table_domain_code"),
		Index("ix_erp_code_table_domain", "domain"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	domain = Column(String(100), nullable=False, comment="Namespace e.g. payment_terms")
	code = Column(String(100), nullable=False)
	label = Column(String(500), nullable=False)
	sort_order = Column(Integer, nullable=False, default=0)
	is_active = Column(Boolean, nullable=False, default=True)
	metadata_: dict[str, Any] = Column(
		"metadata",
		JSONB,
		nullable=False,
		default=dict,
		comment="Domain-specific extra fields",
	)

	def __repr__(self) -> str:
		return f"<CodeTable {self.domain!r}.{self.code!r} {self.label!r}>"


# ---------------------------------------------------------------------------
# Note
# ---------------------------------------------------------------------------

class Note(AuditMixin, Model):
	"""Polymorphic free-text note attached to any entity.

	entity_type + entity_id form a logical foreign key (no DB FK — supports
	any entity type across all ERP plugins without circular deps).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_note"
	__table_args__ = (
		Index("ix_erp_note_entity", "entity_type", "entity_id"),
		Index("ix_erp_note_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_type = Column(String(100), nullable=False, comment="Model class name e.g. Invoice")
	entity_id = Column(String(64), nullable=False)
	note_type = Column(
		String(20),
		nullable=False,
		default="INTERNAL",
		comment="INTERNAL | CUSTOMER | SYSTEM",
	)
	body = Column(Text, nullable=False)
	is_pinned = Column(Boolean, nullable=False, default=False)
	author_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
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
			f"<Note {self.id!r} on={self.entity_type!r}/{self.entity_id!r} "
			f"type={self.note_type!r}>"
		)


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

class Attachment(AuditMixin, Model):
	"""Binary file attachment associated with any entity.

	storage_url references the file in S3 / GCS / local storage.
	checksum_sha256 enables integrity verification.
	size_bytes allows quota enforcement.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_attachment"
	__table_args__ = (
		Index("ix_erp_attachment_entity", "entity_type", "entity_id"),
		Index("ix_erp_attachment_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	entity_type = Column(String(100), nullable=False)
	entity_id = Column(String(64), nullable=False)
	filename = Column(String(500), nullable=False)
	mime_type = Column(String(200), nullable=False)
	size_bytes = Column(Integer, nullable=False, default=0)
	storage_url = Column(String(2000), nullable=False)
	checksum_sha256 = Column(String(64), nullable=True)
	uploaded_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<Attachment {self.id!r} {self.filename!r} "
			f"on={self.entity_type!r}/{self.entity_id!r}>"
		)


# ---------------------------------------------------------------------------
# DomainEventLog  (append-only — NEVER UPDATE)
# ---------------------------------------------------------------------------

class DomainEventLog(Model):
	"""Durable, append-only log of all ERP domain events.

	Written by emit_event() atomically with the business transaction.

	CRITICAL: This table must NEVER be updated.  If an event was recorded in
	error, emit a compensating event (e.g. InvoiceVoidedEvent) — do not delete
	or modify rows.

	correlation_id: groups all events in one business transaction (e.g. one
	HTTP request).
	causation_id: the event_id of the event that caused this one (for causal
	chains across plugins).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_domain_event_log"
	__table_args__ = (
		Index("ix_erp_evlog_type", "event_type"),
		Index("ix_erp_evlog_aggregate", "aggregate_type", "aggregate_id"),
		Index("ix_erp_evlog_tenant_published", "tenant_id", "published_at",
		      postgresql_using="brin"),
		Index("ix_erp_evlog_correlation", "correlation_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	event_id = Column(
		String(36),
		nullable=False,
		unique=True,
		comment="UUID from DomainEvent.event_id",
	)
	event_type = Column(String(200), nullable=False)
	aggregate_type = Column(String(100), nullable=True)
	aggregate_id = Column(String(64), nullable=True)
	tenant_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	payload: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
	published_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	correlation_id = Column(String(36), nullable=True)
	causation_id = Column(String(36), nullable=True)

	def __repr__(self) -> str:
		return (
			f"<DomainEventLog {self.event_id!r} type={self.event_type!r} "
			f"agg={self.aggregate_type!r}/{self.aggregate_id!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Party",
	"PartyRole",
	"Address",
	"Contact",
	"Currency",
	"ExchangeRate",
	"Country",
	"CodeTable",
	"Note",
	"Attachment",
	"DomainEventLog",
]
