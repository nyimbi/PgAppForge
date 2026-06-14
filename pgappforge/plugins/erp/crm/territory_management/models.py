"""Territory management models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class SalesTerritory(Model):
	__tablename__ = "crm_sales_territory"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	region = sa.Column(sa.String(100), nullable=True)
	rules = sa.Column(JSONB, nullable=False, comment="[{field, op, values}] — e.g. {field: country_code, op: in, values: [KE,UG]}")
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class TerritoryAssignment(Model):
	__tablename__ = "crm_territory_assignment"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	territory_id = sa.Column(sa.String(36), sa.ForeignKey("crm_sales_territory.id"), nullable=False, index=True)
	salesperson_id = sa.Column(sa.String(36), nullable=False, index=True)
	effective_from = sa.Column(sa.Date, nullable=False)
	effective_to = sa.Column(sa.Date, nullable=True)
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)
