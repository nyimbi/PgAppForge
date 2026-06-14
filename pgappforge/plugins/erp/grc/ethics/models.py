"""Ethics hotline models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class EthicsReport(Model):
	__tablename__ = "grc_ethics_report"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	anonymous_token_hash = sa.Column(sa.String(64), nullable=False, unique=True, comment="SHA-256 of raw token — never store raw")
	category = sa.Column(sa.String(20), nullable=False, comment="BRIBERY, FRAUD, HARASSMENT, SAFETY, OTHER")
	description = sa.Column(sa.Text, nullable=False)
	severity = sa.Column(sa.String(10), nullable=False, default="MEDIUM")
	status = sa.Column(sa.String(25), nullable=False, default="SUBMITTED")
	submitted_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class EthicsCase(Model):
	__tablename__ = "grc_ethics_case"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	report_id = sa.Column(sa.String(36), sa.ForeignKey("grc_ethics_report.id"), nullable=False, index=True)
	assigned_to = sa.Column(sa.String(36), nullable=True)
	findings = sa.Column(sa.Text, nullable=True)
	resolution = sa.Column(sa.Text, nullable=True)
	timeline = sa.Column(JSONB, nullable=True, comment="[{datetime, actor, action, note}]")
	status = sa.Column(sa.String(20), nullable=False, default="OPEN")
	opened_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	closed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
