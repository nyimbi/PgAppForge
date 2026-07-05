"""Hedge accounting models."""
from __future__ import annotations
import sqlalchemy as sa
from pgappforge.models.sqla import Model


class HedgeRelationship(Model):
	__tablename__ = "fin_hedge_relationship"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	hedged_item_type = sa.Column(sa.String(30), nullable=False, comment="CASH_FLOW, FAIR_VALUE, NET_INVESTMENT")
	hedging_instrument_type = sa.Column(sa.String(20), nullable=False, comment="FORWARD, OPTION, SWAP")
	notional_cents = sa.Column(sa.BigInteger, nullable=False)
	currency_code = sa.Column(sa.String(3), nullable=False)
	start_date = sa.Column(sa.Date, nullable=False)
	maturity_date = sa.Column(sa.Date, nullable=False)
	effectiveness_lower = sa.Column(sa.Numeric(5, 2), nullable=False, default=80)
	effectiveness_upper = sa.Column(sa.Numeric(5, 2), nullable=False, default=125)
	status = sa.Column(sa.String(20), nullable=False, default="ACTIVE")


class HedgeJournalEntry(Model):
	__tablename__ = "fin_hedge_journal_entry"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	hedge_id = sa.Column(sa.String(36), sa.ForeignKey("fin_hedge_relationship.id"), nullable=False, index=True)
	period = sa.Column(sa.String(7), nullable=False, comment="YYYY-MM")
	hedging_instrument_change_cents = sa.Column(sa.BigInteger, nullable=False)
	hedged_item_change_cents = sa.Column(sa.BigInteger, nullable=False)
	effectiveness_ratio = sa.Column(sa.Numeric(8, 4), nullable=True)
	effective_gain_cents = sa.Column(sa.BigInteger, nullable=False, default=0)
	ineffective_gain_cents = sa.Column(sa.BigInteger, nullable=False, default=0)
	oci_cents = sa.Column(sa.BigInteger, nullable=False, default=0, comment="Other Comprehensive Income")
	pl_cents = sa.Column(sa.BigInteger, nullable=False, default=0, comment="Profit and loss recognition")
	gl_posted = sa.Column(sa.Boolean, nullable=False, default=False)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
