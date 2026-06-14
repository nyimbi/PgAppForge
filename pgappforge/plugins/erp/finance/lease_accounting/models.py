"""IFRS 16 / ASC 842 lease models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class Lease(Model):
	__tablename__ = "fin_lease"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	lease_type = sa.Column(sa.String(20), nullable=False, default="LESSEE", comment="LESSEE or LESSOR")
	counterparty = sa.Column(sa.String(200), nullable=True)
	start_date = sa.Column(sa.Date, nullable=False)
	end_date = sa.Column(sa.Date, nullable=False)
	discount_rate = sa.Column(sa.Numeric(10, 6), nullable=False, comment="Annual implicit/incremental borrowing rate")
	currency_code = sa.Column(sa.String(3), nullable=False, default="KES")
	payment_schedule = sa.Column(JSONB, nullable=False, comment="[{period, payment_cents, due_date}]")
	rou_asset_cents = sa.Column(sa.BigInteger, nullable=True, comment="Right-of-use asset (computed on creation)")
	lease_liability_cents = sa.Column(sa.BigInteger, nullable=True, comment="Present value of future lease payments")
	status = sa.Column(sa.String(20), nullable=False, default="ACTIVE")
	standard = sa.Column(sa.String(10), nullable=False, default="IFRS16", comment="IFRS16 or ASC842")


class LeasePaymentSchedule(Model):
	__tablename__ = "fin_lease_payment_schedule"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	lease_id = sa.Column(sa.String(36), sa.ForeignKey("fin_lease.id"), nullable=False, index=True)
	period = sa.Column(sa.String(7), nullable=False, comment="YYYY-MM")
	payment_cents = sa.Column(sa.BigInteger, nullable=False)
	interest_cents = sa.Column(sa.BigInteger, nullable=False)
	principal_cents = sa.Column(sa.BigInteger, nullable=False)
	rou_balance_cents = sa.Column(sa.BigInteger, nullable=False, comment="Carrying amount of ROU asset after period")
	liability_balance_cents = sa.Column(sa.BigInteger, nullable=False)
	gl_posted = sa.Column(sa.Boolean, nullable=False, default=False)


class LeaseModification(Model):
	__tablename__ = "fin_lease_modification"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	lease_id = sa.Column(sa.String(36), sa.ForeignKey("fin_lease.id"), nullable=False, index=True)
	effective_date = sa.Column(sa.Date, nullable=False)
	new_payments = sa.Column(JSONB, nullable=False)
	new_discount_rate = sa.Column(sa.Numeric(10, 6), nullable=True)
	reason = sa.Column(sa.Text, nullable=True)
	remeasured_liability_cents = sa.Column(sa.BigInteger, nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
