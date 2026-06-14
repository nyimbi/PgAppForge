"""Position management models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class Position(Model):
	__tablename__ = "hcm_position"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	position_code = sa.Column(sa.String(50), nullable=False)
	title = sa.Column(sa.String(200), nullable=False)
	department_id = sa.Column(sa.String(36), nullable=True, index=True)
	entity_id = sa.Column(sa.String(36), nullable=True)
	grade_level = sa.Column(sa.String(20), nullable=True)
	status = sa.Column(sa.String(10), nullable=False, default="VACANT", comment="FILLED, VACANT, FROZEN")
	budget_salary_cents = sa.Column(sa.BigInteger, nullable=True)
	actual_salary_cents = sa.Column(sa.BigInteger, nullable=True)
	currency_code = sa.Column(sa.String(3), nullable=False, default="KES")
	incumbent_employee_id = sa.Column(sa.String(36), nullable=True)
	approved_by = sa.Column(sa.String(36), nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class HeadcountRequest(Model):
	__tablename__ = "hcm_headcount_request"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	entity_id = sa.Column(sa.String(36), nullable=True)
	department_id = sa.Column(sa.String(36), nullable=True)
	requisitions = sa.Column(JSONB, nullable=False, comment="[{position_code, fte, start_date, justification}]")
	status = sa.Column(sa.String(20), nullable=False, default="PENDING")
	approved_by = sa.Column(sa.String(36), nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
