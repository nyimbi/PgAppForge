"""
pgappforge/plugins/erp/crm/territory_management/models.py

SQLAlchemy models for the Territory Management plugin.

Table prefix: ter_
PostgreSQL ONLY — JSONB for rules and country_codes arrays.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


class SalesTerritory(AuditMixin, Model):
	"""Defines a named sales territory with optional rule-based account matching."""

	__tablename__ = "ter_territory"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	region = Column(String(100), nullable=False)

	# List of ISO 3166-1 alpha-2 country codes e.g. ["KE","UG","TZ"]
	country_codes = Column(JSONB, nullable=True, default=list)

	# Rules: [{field, op, values}] — evaluated against Customer records
	rules = Column(JSONB, nullable=True, default=list)

	# Optional FK to an entity (e.g. sales region entity) for hierarchical territories
	entity_id = Column(String(36), nullable=True)

	is_active = Column(Boolean, nullable=False, default=True)

	# Relationships
	assignments = relationship("TerritoryAssignment", back_populates="territory", lazy="select")

	__table_args__ = (
		UniqueConstraint("tenant_id", "name", name="uq_ter_territory_name_tenant"),
		Index("ix_ter_territory_tenant_active", "tenant_id", "is_active"),
	)

	def __repr__(self) -> str:
		return f"<SalesTerritory {self.name!r} [{self.region}]>"


class TerritoryAssignment(AuditMixin, Model):
	"""Assigns a salesperson to a territory for a date range."""

	__tablename__ = "ter_assignment"

	id = Column(String(36), primary_key=True, default=_uuid4)
	tenant_id = Column(String(36), nullable=False, index=True)

	territory_id = Column(
		String(36),
		ForeignKey("ter_territory.id", ondelete="CASCADE"),
		nullable=False,
	)
	salesperson_id = Column(String(50), nullable=False)

	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)

	# Relationships
	territory = relationship("SalesTerritory", back_populates="assignments", lazy="select")

	__table_args__ = (
		Index("ix_ter_assignment_territory_person", "territory_id", "salesperson_id"),
		Index("ix_ter_assignment_person_active", "salesperson_id", "effective_to"),
	)

	def __repr__(self) -> str:
		return f"<TerritoryAssignment territory={self.territory_id} person={self.salesperson_id}>"
