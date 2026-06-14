"""ERM models."""
from __future__ import annotations
import sqlalchemy as sa
from pgappforge.models.sqla import Model


class RiskRegister(Model):
	__tablename__ = "grc_risk_register"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	description = sa.Column(sa.Text, nullable=True)
	category = sa.Column(sa.String(50), nullable=False, comment="STRATEGIC, OPERATIONAL, FINANCIAL, COMPLIANCE, REPUTATIONAL")
	likelihood_score = sa.Column(sa.Integer, nullable=False, comment="1-5")
	impact_score = sa.Column(sa.Integer, nullable=False, comment="1-5")
	risk_score = sa.Column(sa.Integer, nullable=False, comment="likelihood * impact (computed)")
	owner_id = sa.Column(sa.String(36), nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="OPEN")
	treatment = sa.Column(sa.String(10), nullable=False, default="MITIGATE", comment="ACCEPT, MITIGATE, TRANSFER, AVOID")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	updated_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"), onupdate=sa.text("NOW()"))


class RiskMitigationAction(Model):
	__tablename__ = "grc_risk_mitigation_action"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	risk_id = sa.Column(sa.String(36), sa.ForeignKey("grc_risk_register.id"), nullable=False, index=True)
	action = sa.Column(sa.Text, nullable=False)
	owner_id = sa.Column(sa.String(36), nullable=True)
	due_date = sa.Column(sa.Date, nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="OPEN")


class KRI(Model):
	__tablename__ = "grc_kri"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	risk_id = sa.Column(sa.String(36), sa.ForeignKey("grc_risk_register.id"), nullable=False, index=True)
	metric_name = sa.Column(sa.String(100), nullable=False)
	threshold_value = sa.Column(sa.Numeric(18, 4), nullable=False)
	current_value = sa.Column(sa.Numeric(18, 4), nullable=True)
	breach_status = sa.Column(sa.Boolean, nullable=False, default=False)
	last_checked_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
