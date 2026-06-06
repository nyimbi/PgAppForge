from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	Text,
	Time,
	UniqueConstraint,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"LunchSupplier",
	"LunchMenu",
	"LunchOrder",
	"LunchSubsidyPolicy",
]


def _uuid4() -> str:
	import uuid
	return str(uuid.uuid4())


class LunchSupplier(AuditMixin, Model):
	__tablename__ = "lun_supplier"
	__table_args__ = (
		Index("ix_lun_supplier_tenant_id", "tenant_id"),
		Index("ix_lun_supplier_is_active", "is_active"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	name = Column(VARCHAR(200), nullable=False)
	contact_email = Column(VARCHAR(200), nullable=True)
	contact_phone = Column(VARCHAR(50), nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	# list of weekday ints: 0=Mon … 6=Sun
	delivery_days = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	notes = Column(Text, nullable=True)

	# relationships
	menus = relationship("LunchMenu", back_populates="supplier", lazy="select")


class LunchMenu(AuditMixin, Model):
	__tablename__ = "lun_menu"
	__table_args__ = (
		Index("ix_lun_menu_tenant_date", "tenant_id", "menu_date"),
		Index("ix_lun_menu_supplier_date", "supplier_id", "menu_date"),
		Index("ix_lun_menu_status", "status"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	supplier_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lun_supplier.id", ondelete="CASCADE"),
		nullable=False,
	)
	menu_date = Column(Date, nullable=False)
	# DRAFT / PUBLISHED / CLOSED
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")
	cutoff_time = Column(Time, nullable=True)
	# list of {id, name, description, price_cents, category, dietary_tags: [], available: True}
	items = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))

	# relationships
	supplier = relationship("LunchSupplier", back_populates="menus", lazy="select")
	orders = relationship("LunchOrder", back_populates="menu", lazy="select")


class LunchOrder(AuditMixin, Model):
	__tablename__ = "lun_order"
	__table_args__ = (
		UniqueConstraint("employee_id", "menu_id", name="uq_lun_order_employee_menu"),
		Index("ix_lun_order_tenant_date", "tenant_id", "order_date"),
		Index("ix_lun_order_employee_status", "employee_id", "status"),
		Index("ix_lun_order_menu_id", "menu_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)

	employee_id = Column(VARCHAR(50), nullable=False)
	menu_id = Column(
		UUID(as_uuid=False),
		ForeignKey("lun_menu.id", ondelete="CASCADE"),
		nullable=False,
	)
	order_date = Column(Date, nullable=False)
	# list of {item_id, name, qty, unit_price_cents}
	items = Column(JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb"))
	subtotal_cents = Column(BigInteger, nullable=False, default=0)
	subsidy_cents = Column(BigInteger, nullable=False, default=0)
	employee_pays_cents = Column(BigInteger, nullable=False, default=0)
	# DRAFT / PLACED / CONFIRMED / DELIVERED / CANCELLED
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")
	placed_at = Column(DateTime(timezone=True), nullable=True)
	special_instructions = Column(Text, nullable=True)

	# relationships
	menu = relationship("LunchMenu", back_populates="orders", lazy="select")


class LunchSubsidyPolicy(AuditMixin, Model):
	__tablename__ = "lun_subsidy_policy"
	__table_args__ = (
		Index("ix_lun_subsidy_policy_tenant_active", "tenant_id", "is_active"),
		Index("ix_lun_subsidy_policy_entity", "entity_id"),
		Index("ix_lun_subsidy_policy_effective", "effective_from", "effective_to"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	entity_id = Column(VARCHAR(50), nullable=True)

	# FIXED / PERCENTAGE / CAPPED
	subsidy_type = Column(VARCHAR(20), nullable=False)
	fixed_amount_cents = Column(BigInteger, nullable=False, default=0)
	percentage = Column(Numeric(5, 2), nullable=False, default=0)
	max_daily_cents = Column(BigInteger, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)
