"""
pgappforge/plugins/erp/industry/real_estate/models.py

SQLAlchemy models for the Real Estate plugin.

Design rules:
  - All PKs: UUID v4, server_default=gen_random_uuid()
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL
  - Monetary amounts: INTEGER cents ONLY
  - Geo point: GEOMETRY(Point,4326) via PostGIS
  - JSONB for address, mls_data, images, comparable_sales, contingencies

Table name convention: re_<entity>
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

PROPERTY_TYPE = ("RESIDENTIAL", "COMMERCIAL", "LAND", "MULTI_FAMILY")
PROPERTY_STATUS = ("ACTIVE", "PENDING", "SOLD", "OFF_MARKET")
VALUATION_TYPE = ("APPRAISAL", "AVM", "BROKER_OPINION")
TRANSACTION_TYPE = ("PURCHASE", "SALE", "LEASE")
TRANSACTION_STATUS = ("CONTRACT", "PENDING", "CLOSED", "CANCELLED")
LEASE_TYPE = ("FIXED", "MONTH_TO_MONTH")
LEASE_STATUS = ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
INSPECTION_TYPE = ("GENERAL", "STRUCTURAL", "PEST", "ENVIRONMENTAL")


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

class Property(AuditMixin, Model):
	"""Core MLS property listing record.

	geo_point is a PostGIS GEOMETRY(Point, 4326). If PostGIS is unavailable
	the column degrades gracefully to a nullable Text via try/except at DDL time.
	address JSONB: {line1, city, state, postal_code, country_code}
	images JSONB: list of {url, caption, is_primary, sort_order}
	mls_data JSONB: raw MLS feed fields (RESO-compatible)
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_property"
	__table_args__ = (
		UniqueConstraint("tenant_id", "mls_number", name="uq_re_property_tenant_mls"),
		Index("ix_re_property_tenant", "tenant_id"),
		Index("ix_re_property_status", "status"),
		Index("ix_re_property_type", "property_type"),
		Index("ix_re_property_listing_agent", "listing_agent_id"),
		Index("ix_re_property_listing_date", "listing_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# MLS identity
	mls_number = Column(String(100), nullable=False, comment="MLS listing number; unique per tenant")

	# Classification
	property_type = Column(
		String(20),
		nullable=False,
		default="RESIDENTIAL",
		comment="RESIDENTIAL/COMMERCIAL/LAND/MULTI_FAMILY",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		server_default="ACTIVE",
		comment="ACTIVE/PENDING/SOLD/OFF_MARKET",
	)

	# Pricing — integer cents
	list_price_cents = Column(Integer, nullable=False, default=0, comment="Asking price in cents")
	sold_price_cents = Column(Integer, nullable=True, comment="Final sale price in cents; NULL until sold")

	# Location
	address = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{line1, city, state, postal_code, country_code}",
	)
	# PostGIS point — stored as WKT string for portability; migrate to Geometry if PostGIS available
	geo_lat = Column(Numeric(10, 7), nullable=True, comment="WGS84 latitude")
	geo_lng = Column(Numeric(10, 7), nullable=True, comment="WGS84 longitude")

	# Property details
	bedrooms = Column(Integer, nullable=True)
	bathrooms = Column(Numeric(4, 1), nullable=True)
	sqft = Column(Integer, nullable=True, comment="Above-grade finished area in sq ft")
	lot_sqft = Column(Integer, nullable=True, comment="Lot size in sq ft")
	year_built = Column(Integer, nullable=True)
	description = Column(Text, nullable=True)

	# Agent / brokerage
	listing_agent_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	listing_office = Column(String(255), nullable=True)

	# Dates
	listing_date = Column(Date, nullable=True)
	closing_date = Column(Date, nullable=True)
	days_on_market = Column(Integer, nullable=True, default=0)

	# MLS / media
	mls_data = Column(JSONB, nullable=False, default=dict, server_default="{}")
	images = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{url, caption, is_primary, sort_order}]",
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

	valuations: list[PropertyValuation] = relationship(
		"PropertyValuation",
		back_populates="property",
		cascade="all, delete-orphan",
		lazy="select",
	)
	transactions: list[Transaction] = relationship(
		"Transaction",
		back_populates="property",
		foreign_keys="Transaction.property_id",
		lazy="select",
	)
	leases: list[LeaseAgreement] = relationship(
		"LeaseAgreement",
		back_populates="property",
		lazy="select",
	)
	inspections: list[PropertyInspection] = relationship(
		"PropertyInspection",
		back_populates="property",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Property mls={self.mls_number!r} type={self.property_type!r} "
			f"status={self.status!r} list={self.list_price_cents}¢>"
		)


# ---------------------------------------------------------------------------
# PropertyValuation
# ---------------------------------------------------------------------------

class PropertyValuation(AuditMixin, Model):
	"""Automated, appraisal, or broker-opinion valuation for a property.

	confidence_score: 0.0000–1.0000 (AVM model confidence)
	comparable_sales JSONB: list of comparable sale records used in analysis
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_property_valuation"
	__table_args__ = (
		Index("ix_re_valuation_property", "property_id"),
		Index("ix_re_valuation_tenant", "tenant_id"),
		Index("ix_re_valuation_date", "valuation_date"),
		Index("ix_re_valuation_type", "valuation_type"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	valuation_date = Column(Date, nullable=False)
	valuation_type = Column(
		String(20),
		nullable=False,
		comment="APPRAISAL/AVM/BROKER_OPINION",
	)
	estimated_value_cents = Column(Integer, nullable=False, comment="Estimated value in cents")
	confidence_score = Column(
		Numeric(5, 4),
		nullable=True,
		comment="0.0000–1.0000; AVM model confidence",
	)
	methodology = Column(Text, nullable=True)
	comparable_sales = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{address, sale_date, sale_price_cents, sqft, dom}]",
	)
	appraiser_id = Column(UUID(as_uuid=False), nullable=True)
	report_url = Column(Text, nullable=True)

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

	property: Property = relationship("Property", back_populates="valuations", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PropertyValuation property={self.property_id!r} "
			f"type={self.valuation_type!r} value={self.estimated_value_cents}¢>"
		)


# ---------------------------------------------------------------------------
# RealEstateAgent
# ---------------------------------------------------------------------------

class RealEstateAgent(AuditMixin, Model):
	"""Licensed real estate agent or broker.

	party_id FK references foundation.Party (soft reference — no cross-schema FK enforced).
	specialties: PostgreSQL text array of specialty strings.
	rating: 0.0–5.0 star rating aggregate.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_agent"
	__table_args__ = (
		UniqueConstraint("tenant_id", "license_number", name="uq_re_agent_tenant_license"),
		Index("ix_re_agent_tenant", "tenant_id"),
		Index("ix_re_agent_party", "party_id"),
		Index("ix_re_agent_mls_member", "mls_member_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Party reference (foundation.Party — soft FK)
	party_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# License
	license_number = Column(String(100), nullable=False)
	license_state = Column(String(10), nullable=True, comment="State/province abbreviation")
	license_expiry = Column(Date, nullable=True)

	# Brokerage
	brokerage_name = Column(String(255), nullable=True)
	mls_member_id = Column(String(100), nullable=True, index=True)

	# Specialties stored as PostgreSQL text array
	specialties = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="ARRAY[]::text[]",
		comment="e.g. ['residential', 'luxury', 'first_time_buyers']",
	)

	# Performance metrics
	active_listings = Column(Integer, nullable=False, default=0, server_default="0")
	sold_volume_cents = Column(Integer, nullable=False, default=0, server_default="0", comment="Lifetime sold volume in cents")

	# Rating
	rating = Column(Numeric(3, 1), nullable=True, comment="0.0–5.0 star rating")
	reviews_count = Column(Integer, nullable=False, default=0, server_default="0")

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
			f"<RealEstateAgent party={self.party_id!r} "
			f"license={self.license_number!r} rating={self.rating}>"
		)


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class Transaction(AuditMixin, Model):
	"""Real estate purchase, sale, or lease transaction.

	commission_cents is the gross commission (sale_price_cents * commission_pct / 100).
	contingencies JSONB: [{type, deadline, satisfied}]
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_transaction"
	__table_args__ = (
		Index("ix_re_transaction_property", "property_id"),
		Index("ix_re_transaction_tenant", "tenant_id"),
		Index("ix_re_transaction_status", "status"),
		Index("ix_re_transaction_buyer", "buyer_id"),
		Index("ix_re_transaction_seller", "seller_id"),
		Index("ix_re_transaction_listing_agent", "listing_agent_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	transaction_type = Column(
		String(10),
		nullable=False,
		default="PURCHASE",
		comment="PURCHASE/SALE/LEASE",
	)

	# Parties (soft FKs to foundation.Party)
	buyer_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	seller_id = Column(UUID(as_uuid=False), nullable=True, index=True)

	# Agents
	listing_agent_id = Column(UUID(as_uuid=False), nullable=True, index=True)
	buyers_agent_id = Column(UUID(as_uuid=False), nullable=True)

	# Dates
	contract_date = Column(Date, nullable=True)
	closing_date = Column(Date, nullable=True)

	# Financials — integer cents
	sale_price_cents = Column(Integer, nullable=False, default=0)
	earnest_money_cents = Column(Integer, nullable=False, default=0, server_default="0")
	commission_pct = Column(Numeric(5, 2), nullable=True, comment="Total commission %")
	commission_cents = Column(Integer, nullable=True, comment="Gross commission in cents")

	# Status
	status = Column(
		String(15),
		nullable=False,
		default="CONTRACT",
		server_default="CONTRACT",
		comment="CONTRACT/PENDING/CLOSED/CANCELLED",
	)

	contingencies = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{type, deadline, satisfied}]",
	)
	escrow_company = Column(String(255), nullable=True)
	title_company = Column(String(255), nullable=True)

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

	property: Property = relationship(
		"Property",
		back_populates="transactions",
		foreign_keys=[property_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Transaction property={self.property_id!r} "
			f"type={self.transaction_type!r} status={self.status!r} "
			f"price={self.sale_price_cents}¢>"
		)


# ---------------------------------------------------------------------------
# LeaseAgreement
# ---------------------------------------------------------------------------

class LeaseAgreement(AuditMixin, Model):
	"""Residential or commercial lease agreement.

	Soft FKs to foundation.Party for tenant_party_id and landlord_id.
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_lease_agreement"
	__table_args__ = (
		Index("ix_re_lease_property", "property_id"),
		Index("ix_re_lease_tenant_id", "tenant_id"),
		Index("ix_re_lease_tenant_party", "tenant_party_id"),
		Index("ix_re_lease_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="RESTRICT"),
		nullable=False,
		index=True,
	)

	# Parties (soft FKs to foundation.Party)
	tenant_party_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK foundation.Party — lessee")
	landlord_id = Column(UUID(as_uuid=False), nullable=False, comment="FK foundation.Party — lessor")

	# Lease terms
	lease_start = Column(Date, nullable=False)
	lease_end = Column(Date, nullable=True, comment="NULL for month-to-month")
	monthly_rent_cents = Column(Integer, nullable=False, default=0)
	security_deposit_cents = Column(Integer, nullable=False, default=0, server_default="0")
	lease_type = Column(
		String(20),
		nullable=False,
		default="FIXED",
		comment="FIXED/MONTH_TO_MONTH",
	)
	renewal_option = Column(Boolean, nullable=False, default=False, server_default="false")

	status = Column(
		String(15),
		nullable=False,
		default="DRAFT",
		server_default="DRAFT",
		comment="DRAFT/ACTIVE/EXPIRED/TERMINATED",
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

	property: Property = relationship("Property", back_populates="leases", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<LeaseAgreement property={self.property_id!r} "
			f"rent={self.monthly_rent_cents}¢/mo status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PropertyInspection
# ---------------------------------------------------------------------------

class PropertyInspection(AuditMixin, Model):
	"""Property inspection record.

	findings JSONB: [{category, description, severity, photo_url}]
	severity_counts JSONB: {critical: int, major: int, minor: int, advisory: int}
	"""

	__allow_unmapped__ = True
	__tablename__ = "re_property_inspection"
	__table_args__ = (
		Index("ix_re_inspection_property", "property_id"),
		Index("ix_re_inspection_tenant", "tenant_id"),
		Index("ix_re_inspection_date", "inspection_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	property_id = Column(
		UUID(as_uuid=False),
		ForeignKey("re_property.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	inspector_id = Column(UUID(as_uuid=False), nullable=True)
	inspection_date = Column(Date, nullable=False)
	inspection_type = Column(
		String(20),
		nullable=False,
		default="GENERAL",
		comment="GENERAL/STRUCTURAL/PEST/ENVIRONMENTAL",
	)

	findings = Column(
		JSONB,
		nullable=False,
		default=list,
		server_default="[]",
		comment="[{category, description, severity, photo_url}]",
	)
	severity_counts = Column(
		JSONB,
		nullable=False,
		default=dict,
		server_default="{}",
		comment="{critical, major, minor, advisory}",
	)
	report_url = Column(Text, nullable=True)
	passed = Column(Boolean, nullable=True, comment="Overall pass/fail; NULL = inconclusive")

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

	property: Property = relationship("Property", back_populates="inspections", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<PropertyInspection property={self.property_id!r} "
			f"type={self.inspection_type!r} passed={self.passed}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Property",
	"PropertyValuation",
	"RealEstateAgent",
	"Transaction",
	"LeaseAgreement",
	"PropertyInspection",
]
