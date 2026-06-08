"""
pgappforge/plugins/erp/operations/lean/views.py

Flask views for the Operations / Lean / Kanban plugin.

Registered views:
  KanbanBoardView  — board list + per-board column/card view
"""
from __future__ import annotations

import logging
from datetime import date

import sqlalchemy as sa
from flask import current_app

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


# ---------------------------------------------------------------------------
# KanbanBoardView
# ---------------------------------------------------------------------------

class KanbanBoardView(BaseView):
	"""Kanban board list and per-board card view.

	GET /operations/kanban/                     — list all boards
	GET /operations/kanban/board/<board_id>     — full board with columns and cards
	"""

	route_base = "/operations/kanban"
	default_view = "list_boards"

	@expose("/")
	@has_access
	def list_boards(self):
		from flask import render_template

		boards = []
		try:
			from pgappforge.plugins.erp.operations.lean.models import KanbanBoard
			session = _get_session()
			q = (
				sa.select(KanbanBoard)
				.where(KanbanBoard.tenant_id == _tenant_id())
				.order_by(KanbanBoard.name)
				.limit(200)
			)
			boards = session.execute(q).scalars().all()
		except Exception:
			log.exception("KanbanBoardView.list_boards: failed to load boards")
			boards = []

		return render_template("operations/lean_board_list.html", boards=boards)

	@expose("/board/<string:board_id>")
	@has_access
	def board(self, board_id: str):
		from flask import abort, render_template

		board = None
		columns = []
		cards = []

		try:
			from pgappforge.plugins.erp.operations.lean.models import KanbanBoard
			session = _get_session()
			board = session.get(KanbanBoard, board_id)
		except Exception:
			log.exception("KanbanBoardView.board: failed to load board %s", board_id)

		if board is None:
			abort(404)

		try:
			from pgappforge.plugins.erp.operations.lean.models import KanbanColumn
			session = _get_session()
			q = (
				sa.select(KanbanColumn)
				.where(KanbanColumn.board_id == board_id)
				.order_by(KanbanColumn.position)
			)
			columns = session.execute(q).scalars().all()
		except Exception:
			log.exception("KanbanBoardView.board: failed to load columns for %s", board_id)
			columns = []

		try:
			from pgappforge.plugins.erp.operations.lean.models import KanbanCard
			session = _get_session()
			q = (
				sa.select(KanbanCard)
				.where(KanbanCard.board_id == board_id)
				.order_by(KanbanCard.position)
			)
			raw_cards = session.execute(q).scalars().all()
			today = date.today()
			for card in raw_cards:
				card.is_overdue = (
					card.due_date is not None and card.due_date < today
				)
			cards = raw_cards
		except Exception:
			log.exception("KanbanBoardView.board: failed to load cards for %s", board_id)
			cards = []

		return render_template(
			"operations/lean_board.html",
			board=board,
			columns=columns,
			cards=cards,
		)


__all__ = ["KanbanBoardView"]
