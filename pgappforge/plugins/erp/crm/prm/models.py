"""
pgappforge/plugins/erp/crm/prm/models.py

SQLAlchemy models for the Partner Relationship Management plugin.

Design rules:
  - PostgreSQL ONLY — no SQLite/MySQL portability shims
  - All PKs: UUID v4 string default
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True))
  - All monetary amounts: BigInteger CENTS — never float
  - JSONB for semi-structured data
  - AuditMixin on every mutable entity
  - Table prefix: prm_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

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
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumeration constants
# ---------------------------------------------------------------------------

PARTNER_TIER = ("PLATINUM", "GOLD", "SILVER", "BRONZE", "REGISTERED")
PARTNER_STATUS = ("ACTIVE", "INACTIVE", "SUSPENDED")
DEAL_STAGE = ("SUBMITTED", "APPROVED", "PURSUING", "WON", "LOST", "EXPIRED")
MDF_STATUS = ("PENDING", "APPROVED", "REJECTED", "SPENT")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PartnerAccount(AuditMixin, Model):
	"""Represents a channel partner company registered in the PRM system."""

	__tablename__ = "prm_partner"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	company_name = Column(String(300), nullable=False)
	partner_code = Column(String(50), nullable=False)

	partner_tier = Column(String(20), nullable=False, default="SILVER")
	region = Column(String(100), nullable=True)
	country_code = Column(String(3), nullable=True)

	contact_name = Column(String(200), nullable=True)
	contact_email = Column(String(320), nullable=True)

	status = Column(String(20), nullable=False, default="ACTIVE")

	annual_revenue_target_cents = Column(BigInteger, nullable=False, default=0)
	ytd_revenue_cents = Column(BigInteger, nullable=False, default=0)

	# Relationships
	deals = relationship("DealRegistration", back_populates="partner", lazy="select")
	mdf_requests = relationship("MDFRequest", back_populates="partner", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "partner_code", name="uq_prm_partner_code_tenant"),
		Index("ix_prm_partner_tier_status", "tenant_id", "partner_tier", "status"),
	)

	def __repr__(self) -> str:
		return f"<PartnerAccount {self.partner_code} [{self.partner_tier}]>"


class DealRegistration(AuditMixin, Model):
	"""A partner-submitted deal registration linking a partner to a customer opportunity."""

	__tablename__ = "prm_deal"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	partner_id = Column(
		String(36),
		ForeignKey("prm_partner.id", ondelete="CASCADE"),
		nullable=False,
	)

	opportunity_name = Column(String(300), nullable=False)
	customer_name = Column(String(300), nullable=False)
	customer_domain = Column(String(200), nullable=True)

	estimated_value_cents = Column(BigInteger, nullable=False)
	actual_value_cents = Column(BigInteger, nullable=True)

	stage = Column(String(30), nullable=False, default="SUBMITTED")

	close_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)

	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	approved_by = Column(String(50), nullable=True)
	approved_at = Column(DateTime(timezone=True), nullable=True)

	notes = Column(Text, nullable=True)

	# Relationships
	partner = relationship("PartnerAccount", back_populates="deals", lazy="select")

	__table_args__ = (
		Index("ix_prm_deal_partner_stage", "partner_id", "stage"),
		Index("ix_prm_deal_tenant_stage", "tenant_id", "stage"),
	)

	def __repr__(self) -> str:
		return f"<DealRegistration {self.id} [{self.stage}]>"


class MDFRequest(AuditMixin, Model):
	"""Market Development Fund request from a partner."""

	__tablename__ = "prm_mdf"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	partner_id = Column(
		String(36),
		ForeignKey("prm_partner.id", ondelete="CASCADE"),
		nullable=False,
	)

	campaign_name = Column(String(300), nullable=False)
	purpose = Column(Text, nullable=False)

	amount_requested_cents = Column(BigInteger, nullable=False)
	approved_cents = Column(BigInteger, nullable=True)

	period = Column(String(20), nullable=False)
	status = Column(String(20), nullable=False, default="PENDING")

	approved_by = Column(String(50), nullable=True)

	# Relationships
	partner = relationship("PartnerAccount", back_populates="mdf_requests", lazy="select")

	__table_args__ = (
		Index("ix_prm_mdf_partner_status", "partner_id", "status"),
		Index("ix_prm_mdf_tenant_period", "tenant_id", "period"),
	)

	def __repr__(self) -> str:
		return f"<MDFRequest {self.id} [{self.status}]>"
