"""EDI models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class EDIPartner(Model):
	__tablename__ = "edi_partner"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	protocol = sa.Column(sa.String(20), nullable=False, comment="X12, EDIFACT, PEPPOL, ETIMS")
	direction = sa.Column(sa.String(10), nullable=False, comment="INBOUND, OUTBOUND, BOTH")
	message_types = sa.Column(JSONB, nullable=False, comment="[850, 810, 856] for X12 etc.")
	connectivity = sa.Column(JSONB, nullable=True, comment="{transport: SFTP|AS2|HTTPS, endpoint, credentials_ref}")
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))


class EDIMessage(Model):
	__tablename__ = "edi_message"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	partner_id = sa.Column(sa.String(36), sa.ForeignKey("edi_partner.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	message_type = sa.Column(sa.String(10), nullable=False, comment="850, ORDERS, INVOIC, UBL, ETIMS")
	payload = sa.Column(sa.Text, nullable=False)
	direction = sa.Column(sa.String(10), nullable=False)
	status = sa.Column(sa.String(10), nullable=False, default="PENDING", comment="PENDING, SENT, ACKED, ERROR")
	error_log = sa.Column(sa.Text, nullable=True)
	reference_id = sa.Column(sa.String(100), nullable=True, comment="Order/invoice ID being transmitted")
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
