"""
pgappforge/plugins/erp/operations/lean/models.py

SQLAlchemy models for the Lean / Kanban plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ
  - ALL monetary amounts: BigInteger cents (NEVER Numeric/float for money)
  - ALL models: tenant_id VARCHAR(50) NOT NULL
  - Soft FKs only across plugin boundaries (VARCHAR)
  - PostgreSQL: JSONB, TIMESTAMPTZ, Numeric(15,4) for quantities
  - AuditMixin on every mutable entity

Table prefix: kbn_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	CheckConstraint,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
)
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# KanbanBoard
# ---------------------------------------------------------------------------

class KanbanBoard(AuditMixin, Model):
	"""A Kanban board grouping columns and cards for a value stream.

	entity_id provides optional multi-entity scoping (e.g. plant, department).
	"""

	__allow_unmapped__ = True
	__tablename__ = "kbn_board"
	__table_args__ = (
		Index("ix_kbn_board_tenant_active", "tenant_id", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	name = Column(String(200), nullable=False)
	description = Column(Text, nullable=True)
	entity_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Multi-entity scoping; soft FK to entity registry",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	columns: list[KanbanColumn] = relationship(
		"KanbanColumn",
		back_populates="board",
		cascade="all, delete-orphan",
		order_by="KanbanColumn.order_num",
		lazy="select",
	)
	cards: list[KanbanCard] = relationship(
		"KanbanCard",
		back_populates="board",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<KanbanBoard id={self.id!r} name={self.name!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# KanbanColumn
# ---------------------------------------------------------------------------

class KanbanColumn(AuditMixin, Model):
	"""A stage/column within a Kanban board.

	wip_limit=NULL means unlimited WIP.
	column_type drives special behaviour:
	  BACKLOG  — input queue; cycle timer not started here
	  WORK     — active work; cycle timer started on first entry
	  REVIEW   — quality gate
	  DONE     — cycle timer stopped here
	  CONSUME  — triggers pull signal when a product card enters
	"""

	__allow_unmapped__ = True
	__tablename__ = "kbn_column"
	__table_args__ = (
		Index("ix_kbn_column_board_order", "board_id", "order_num"),
		CheckConstraint(
			"column_type IN ('BACKLOG','WORK','REVIEW','DONE','CONSUME')",
			name="ck_kbn_column_type",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	board_id = Column(
		String(50),
		ForeignKey("kbn_board.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	name = Column(String(100), nullable=False)
	order_num = Column(Integer, nullable=False, comment="Display order within board; ascending")
	wip_limit = Column(
		Integer,
		nullable=True,
		comment="Maximum ACTIVE cards allowed; NULL = unlimited",
	)
	column_type = Column(
		String(20),
		nullable=False,
		default="WORK",
		comment="BACKLOG | WORK | REVIEW | DONE | CONSUME",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	board: KanbanBoard = relationship(
		"KanbanBoard",
		back_populates="columns",
		lazy="select",
	)
	cards: list[KanbanCard] = relationship(
		"KanbanCard",
		back_populates="column",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KanbanColumn id={self.id!r} name={self.name!r} "
			f"type={self.column_type!r} wip={self.wip_limit}>"
		)


# ---------------------------------------------------------------------------
# KanbanCard
# ---------------------------------------------------------------------------

class KanbanCard(AuditMixin, Model):
	"""A work item card on a Kanban board.

	Cycle time measurement:
	  cycle_start_at — set when card first enters a WORK-type column
	  cycle_end_at   — set when card enters a DONE-type column

	product_id / quantity enable pull-signal triggering when the card enters a
	CONSUME column.

	linked_production_order_id is a soft FK to any production order.
	assigned_to is a soft FK to user/employee registry.
	"""

	__allow_unmapped__ = True
	__tablename__ = "kbn_card"
	__table_args__ = (
		Index("ix_kbn_card_board_status", "board_id", "status"),
		Index("ix_kbn_card_column_priority", "column_id", "priority"),
		Index("ix_kbn_card_product", "product_id"),
		CheckConstraint(
			"status IN ('ACTIVE','DONE','CANCELLED')",
			name="ck_kbn_card_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	column_id = Column(
		String(50),
		ForeignKey("kbn_column.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		comment="Current column this card resides in",
	)
	board_id = Column(
		String(50),
		ForeignKey("kbn_board.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)

	title = Column(String(300), nullable=False)
	product_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Soft FK → inv_product.id; enables pull-signal triggering",
	)
	quantity = Column(Numeric(15, 4), nullable=True, comment="Replenishment quantity for pull signals")
	assigned_to = Column(String(50), nullable=True, comment="Soft FK to user/employee registry")
	due_date = Column(Date, nullable=True)
	priority = Column(
		Integer,
		nullable=False,
		default=5,
		comment="1=highest urgency, 10=lowest",
	)
	status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | DONE | CANCELLED",
	)
	linked_production_order_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Soft FK to production order created from this card",
	)

	# Timing
	moved_at = Column(DateTime(timezone=True), nullable=True, comment="Last column-move timestamp")
	cycle_start_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when card first entered a non-BACKLOG column (cycle timer start)",
	)
	cycle_end_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Timestamp when card entered DONE column (cycle timer end)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	column: KanbanColumn = relationship(
		"KanbanColumn",
		back_populates="cards",
		lazy="select",
	)
	board: KanbanBoard = relationship(
		"KanbanBoard",
		back_populates="cards",
		lazy="select",
	)
	pull_signals: list[PullSignal] = relationship(
		"PullSignal",
		back_populates="source_card",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KanbanCard id={self.id!r} title={self.title!r} "
			f"column={self.column_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PullSignal
# ---------------------------------------------------------------------------

class PullSignal(AuditMixin, Model):
	"""A replenishment signal triggered when a product card enters a CONSUME column.

	fulfillment_order_id is set once a purchase order or production order is created.
	"""

	__allow_unmapped__ = True
	__tablename__ = "kbn_pull_signal"
	__table_args__ = (
		Index("ix_kbn_pull_status_triggered", "status", "triggered_at"),
		Index("ix_kbn_pull_product", "product_id"),
		CheckConstraint(
			"status IN ('PENDING','FULFILLED','CANCELLED')",
			name="ck_kbn_pull_status",
		),
		{"extend_existing": True},
	)

	id = Column(
		String(50),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(50), nullable=False, index=True)

	source_card_id = Column(
		String(50),
		ForeignKey("kbn_card.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
		comment="Kanban card that triggered this pull signal",
	)
	product_id = Column(
		String(50),
		nullable=False,
		index=True,
		comment="Soft FK → inv_product.id: product to replenish",
	)
	quantity = Column(Numeric(15, 4), nullable=False, comment="Replenishment quantity")
	triggered_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | FULFILLED | CANCELLED",
	)
	fulfillment_order_id = Column(
		String(50),
		nullable=True,
		index=True,
		comment="Soft FK to PO or production order created to fulfill this signal",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	source_card: KanbanCard = relationship(
		"KanbanCard",
		back_populates="pull_signals",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<PullSignal id={self.id!r} product={self.product_id!r} "
			f"qty={self.quantity} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"KanbanBoard",
	"KanbanColumn",
	"KanbanCard",
	"PullSignal",
]
