"""Lean / Kanban models."""
from __future__ import annotations
import sqlalchemy as sa
from pgappforge.models.sqla import Model


class KanbanBoard(Model):
	__tablename__ = "ops_kanban_board"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	entity_id = sa.Column(sa.String(36), nullable=True)
	wip_limit_per_column = sa.Column(sa.Integer, nullable=False, default=5)
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class KanbanColumn(Model):
	__tablename__ = "ops_kanban_column"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	board_id = sa.Column(sa.String(36), sa.ForeignKey("ops_kanban_board.id"), nullable=False, index=True)
	name = sa.Column(sa.String(100), nullable=False)
	order_num = sa.Column(sa.Integer, nullable=False)
	wip_limit = sa.Column(sa.Integer, nullable=False, default=5)
	is_consume = sa.Column(sa.Boolean, nullable=False, default=False, comment="Cards moved here trigger pull signal")


class KanbanCard(Model):
	__tablename__ = "ops_kanban_card"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	column_id = sa.Column(sa.String(36), sa.ForeignKey("ops_kanban_column.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	title = sa.Column(sa.String(200), nullable=False)
	product_id = sa.Column(sa.String(36), nullable=True)
	quantity = sa.Column(sa.Numeric(18, 4), nullable=True)
	assigned_to = sa.Column(sa.String(36), nullable=True)
	due_date = sa.Column(sa.Date, nullable=True)
	priority = sa.Column(sa.Integer, nullable=False, default=3, comment="1=critical, 5=low")
	linked_production_order_id = sa.Column(sa.String(36), nullable=True)
	created_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	moved_at = sa.Column(sa.DateTime(timezone=True), nullable=True)


class PullSignal(Model):
	__tablename__ = "ops_pull_signal"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	card_id = sa.Column(sa.String(36), sa.ForeignKey("ops_kanban_card.id"), nullable=False, index=True)
	from_column_id = sa.Column(sa.String(36), nullable=False)
	quantity = sa.Column(sa.Numeric(18, 4), nullable=False)
	triggered_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	status = sa.Column(sa.String(20), nullable=False, default="PENDING")
