"""Lean / Kanban service."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.operations.lean.models import KanbanBoard, KanbanColumn, KanbanCard, PullSignal


def _uuid() -> str:
	return str(uuid.uuid4())


class LeanService:
	def create_board(self, tenant_id: str, name: str, session: Any) -> KanbanBoard:
		board = KanbanBoard(id=_uuid(), tenant_id=tenant_id, name=name)
		session.add(board)
		return board

	def add_column(
		self,
		board_id: str,
		name: str,
		order_num: int,
		wip_limit: int = 5,
		is_consume: bool = False,
		session: Any = None,
	) -> KanbanColumn:
		col = KanbanColumn(
			id=_uuid(),
			board_id=board_id,
			name=name,
			order_num=order_num,
			wip_limit=wip_limit,
			is_consume=is_consume,
		)
		if session:
			session.add(col)
		return col

	def add_card(
		self,
		column_id: str,
		tenant_id: str,
		title: str,
		product_id: str | None = None,
		quantity: float | None = None,
		session: Any = None,
	) -> KanbanCard:
		card = KanbanCard(
			id=_uuid(),
			column_id=column_id,
			tenant_id=tenant_id,
			title=title,
			product_id=product_id,
			quantity=quantity,
		)
		if session:
			session.add(card)
		return card

	def move_card(self, card_id: str, target_column_id: str, session: Any) -> PullSignal | None:
		col = session.get(KanbanColumn, target_column_id)
		current_count = session.execute(
			sa.select(sa.func.count(KanbanCard.id)).where(KanbanCard.column_id == target_column_id)
		).scalar() or 0
		assert current_count < col.wip_limit, f"WIP limit {col.wip_limit} reached for column {col.name}"
		card = session.get(KanbanCard, card_id)
		session.execute(
			sa.update(KanbanCard).where(KanbanCard.id == card_id).values(
				column_id=target_column_id,
				moved_at=datetime.now(timezone.utc),
			)
		)
		if col.is_consume:
			signal = PullSignal(
				id=_uuid(),
				card_id=card_id,
				from_column_id=card.column_id,
				quantity=card.quantity or 1,
			)
			session.add(signal)
			return signal
		return None

	def get_cycle_time_days(self, board_id: str, session: Any) -> float | None:
		cards = session.execute(
			sa.select(KanbanCard)
			.join(KanbanColumn, KanbanCard.column_id == KanbanColumn.id)
			.where(KanbanColumn.board_id == board_id)
			.where(KanbanCard.moved_at.isnot(None))
		).scalars().all()
		if not cards:
			return None
		deltas = [(c.moved_at - c.created_at).days for c in cards if c.moved_at and c.created_at]
		return round(sum(deltas) / len(deltas), 2) if deltas else None


__all__ = ["LeanService"]
