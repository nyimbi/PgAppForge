"""Anti-bribery models."""
from __future__ import annotations
import sqlalchemy as sa
from pgappforge.models.sqla import Model


class GiftEntertainmentLog(Model):
	__tablename__ = "grc_gift_entertainment_log"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	employee_id = sa.Column(sa.String(36), nullable=False, index=True)
	given_to_name = sa.Column(sa.String(200), nullable=False)
	given_to_organization = sa.Column(sa.String(200), nullable=True)
	gift_type = sa.Column(sa.String(20), nullable=False, comment="GIFT, MEAL, ENTERTAINMENT, TRAVEL")
	value_cents = sa.Column(sa.BigInteger, nullable=False)
	currency_code = sa.Column(sa.String(3), nullable=False, default="KES")
	gift_date = sa.Column(sa.Date, nullable=False)
	purpose = sa.Column(sa.Text, nullable=True)
	is_government_official = sa.Column(sa.Boolean, nullable=False, default=False)
	approved_by = sa.Column(sa.String(36), nullable=True)
	status = sa.Column(sa.String(20), nullable=False, default="PENDING", comment="PENDING, APPROVED, REJECTED, FLAGGED")
	flag_reason = sa.Column(sa.Text, nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class ConflictOfInterestDeclaration(Model):
	__tablename__ = "grc_coi_declaration"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	employee_id = sa.Column(sa.String(36), nullable=False, index=True)
	description = sa.Column(sa.Text, nullable=False)
	declaration_date = sa.Column(sa.Date, nullable=False)
	status = sa.Column(sa.String(20), nullable=False, default="PENDING")
	reviewed_by = sa.Column(sa.String(36), nullable=True)
	reviewed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
