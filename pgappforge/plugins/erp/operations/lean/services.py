"""
pgappforge/plugins/erp/operations/lean/services.py

LeanManufacturingService — stateless Lean / Kanban domain service.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

BPM registrations:
  ops.lean.move_card      — Move kanban card to next column
  ops.lean.trigger_pull   — Trigger kanban pull signal for replenishment

Public API:
  create_board(name, entity_id, tenant_id, session, *, columns=None) -> KanbanBoard
  add_card(board_id, column_id, title, tenant_id, session, *, ...) -> KanbanCard
  move_card(card_id, target_column_id, moved_by, session) -> KanbanCard
  trigger_pull_signal(card, session) -> PullSignal
  get_cycle_time(board_id, from_date, to_date, tenant_id, session) -> dict
  get_flow_efficiency(board_id, period, session) -> dict
  get_board_metrics(board_id, session) -> dict
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BPM action registry
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	_bpm_available = True
except Exception:
	_bpm_available = False

	class _FakeBPMRegistry:
		@staticmethod
		def register(action_id: str, description: str):
			def decorator(fn):
				return fn
			return decorator

	BPMActionRegistry = _FakeBPMRegistry()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LeanServiceError(Exception):
	"""Base domain error for lean/kanban operations."""


class BoardNotFoundError(LeanServiceError):
	pass


class ColumnNotFoundError(LeanServiceError):
	pass


class CardNotFoundError(LeanServiceError):
	pass


class WIPLimitError(LeanServiceError):
	"""Raised when moving a card would breach the target column's WIP limit."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("LeanManufacturingService._emit: non-fatal event emission failure: %s", exc)


# Default columns specification: (name, column_type, wip_limit, order_num)
_DEFAULT_COLUMNS: list[tuple[str, str, int | None, int]] = [
	("Backlog",     "BACKLOG", None, 1),
	("In Progress", "WORK",    5,    2),
	("Review",      "REVIEW",  3,    3),
	("Done",        "DONE",    None, 4),
]


# ---------------------------------------------------------------------------
# LeanManufacturingService
# ---------------------------------------------------------------------------

class LeanManufacturingService:
	"""Stateless Lean / Kanban domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.
	"""

	# ------------------------------------------------------------------
	# create_board
	# ------------------------------------------------------------------

	def create_board(
		self,
		name: str,
		entity_id: str | None,
		tenant_id: str,
		session: Any,
		*,
		columns: list[dict[str, Any]] | None = None,
	) -> Any:
		"""Create a Kanban board with default or custom columns.

		Default columns (if columns=None):
		  Backlog (BACKLOG, unlimited), In Progress (WORK, WIP=5),
		  Review (REVIEW, WIP=3), Done (DONE, unlimited).

		Args:
			name: Board name.
			entity_id: Optional multi-entity scoping (plant, department).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			columns: Optional list of column specs:
			         [{name, column_type, wip_limit?, order_num?}].

		Returns:
			The created KanbanBoard.
		"""
		from pgappforge.plugins.erp.operations.lean.models import KanbanBoard, KanbanColumn
		from pgappforge.plugins.erp.operations.lean.events import KanbanBoardCreatedEvent

		assert name, "Board name must not be empty"

		board = KanbanBoard(
			tenant_id=tenant_id,
			name=name,
			entity_id=entity_id,
			is_active=True,
		)
		session.add(board)
		session.flush()

		column_specs: list[tuple[str, str, int | None, int]]
		if columns:
			column_specs = [
				(
					str(c["name"]),
					str(c.get("column_type", "WORK")),
					c.get("wip_limit"),
					int(c.get("order_num", i + 1)),
				)
				for i, c in enumerate(columns)
			]
		else:
			column_specs = list(_DEFAULT_COLUMNS)

		for col_name, col_type, wip_limit, order_num in column_specs:
			session.add(KanbanColumn(
				tenant_id=tenant_id,
				board_id=board.id,
				name=col_name,
				order_num=order_num,
				wip_limit=wip_limit,
				column_type=col_type,
			))

		log.info(
			"LeanManufacturingService.create_board: board=%s name=%r columns=%d",
			board.id, name, len(column_specs),
		)

		_emit(
			KanbanBoardCreatedEvent(
				aggregate_id=board.id,
				aggregate_type="KanbanBoard",
				tenant_id=tenant_id,
				board_id=board.id,
				name=name,
			),
			session,
		)

		return board

	# ------------------------------------------------------------------
	# add_card
	# ------------------------------------------------------------------

	def add_card(
		self,
		board_id: str,
		column_id: str,
		title: str,
		tenant_id: str,
		session: Any,
		*,
		product_id: str | None = None,
		quantity: Any | None = None,
		assigned_to: str | None = None,
		due_date: date | None = None,
		priority: int = 5,
	) -> Any:
		"""Add a new card to a Kanban column.

		Args:
			board_id: UUID of the parent KanbanBoard.
			column_id: UUID of the target KanbanColumn.
			title: Card title.
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			product_id: Optional soft FK → inv_product.id.
			quantity: Optional replenishment quantity.
			assigned_to: Optional assignee user/employee ID.
			due_date: Optional due date.
			priority: 1=highest urgency, 10=lowest (default 5).

		Returns:
			The created KanbanCard.

		Raises:
			ColumnNotFoundError: column_id not found or belongs to different board.
		"""
		from pgappforge.plugins.erp.operations.lean.models import KanbanColumn, KanbanCard

		col = session.execute(
			sa.select(KanbanColumn).where(
				KanbanColumn.id == column_id,
				KanbanColumn.board_id == board_id,
			)
		).scalar_one_or_none()

		if col is None:
			raise ColumnNotFoundError(
				f"KanbanColumn {column_id!r} not found on board {board_id!r}"
			)

		assert title, "Card title must not be empty"

		card = KanbanCard(
			tenant_id=tenant_id,
			board_id=board_id,
			column_id=column_id,
			title=title,
			product_id=product_id,
			quantity=_d(quantity) if quantity is not None else None,
			assigned_to=assigned_to,
			due_date=due_date,
			priority=priority,
			status="ACTIVE",
			moved_at=_now(),
		)
		session.add(card)
		session.flush()

		log.info(
			"LeanManufacturingService.add_card: card=%s board=%s column=%s title=%r",
			card.id, board_id, column_id, title,
		)

		return card

	# ------------------------------------------------------------------
	# move_card
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"ops.lean.move_card",
		"Move kanban card to next column",
	)
	def move_card(
		self,
		card_id: str,
		target_column_id: str,
		moved_by: str,
		session: Any,
	) -> Any:
		"""Move a Kanban card to the target column.

		WIP limit enforcement:
		  If target column has a wip_limit, count active cards currently in that
		  column. If count >= wip_limit: emit WIPLimitBreachedEvent and raise WIPLimitError.

		Cycle time tracking:
		  - card.cycle_start_at is set when card first enters a WORK-type column
		    (only if cycle_start_at is not already set).
		  - card.cycle_end_at is set when card enters a DONE-type column.

		Pull signal:
		  - When target column type is CONSUME and card.product_id is set,
		    trigger_pull_signal() is called automatically.

		Args:
			card_id: UUID of the KanbanCard to move.
			target_column_id: UUID of the destination KanbanColumn.
			moved_by: User ID performing the move.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated KanbanCard.

		Raises:
			CardNotFoundError: card_id not found.
			ColumnNotFoundError: target_column_id not found.
			WIPLimitError: target column WIP limit would be breached.
		"""
		from pgappforge.plugins.erp.operations.lean.models import (
			KanbanCard, KanbanColumn,
		)
		from pgappforge.plugins.erp.operations.lean.events import (
			KanbanCardMovedEvent,
			WIPLimitBreachedEvent,
		)

		card = session.execute(
			sa.select(KanbanCard).where(KanbanCard.id == card_id)
		).scalar_one_or_none()

		if card is None:
			raise CardNotFoundError(f"KanbanCard {card_id!r} not found")

		target_col = session.execute(
			sa.select(KanbanColumn).where(KanbanColumn.id == target_column_id)
		).scalar_one_or_none()

		if target_col is None:
			raise ColumnNotFoundError(f"KanbanColumn {target_column_id!r} not found")

		# Load current column for from_column name
		from_col = session.execute(
			sa.select(KanbanColumn).where(KanbanColumn.id == card.column_id)
		).scalar_one_or_none()
		from_column_name = from_col.name if from_col else card.column_id

		# WIP limit check: count ACTIVE cards currently in target column
		if target_col.wip_limit is not None:
			current_count = session.execute(
				sa.select(sa.func.count()).select_from(KanbanCard).where(
					KanbanCard.column_id == target_column_id,
					KanbanCard.status == "ACTIVE",
				)
			).scalar_one()

			if current_count >= target_col.wip_limit:
				_emit(
					WIPLimitBreachedEvent(
						aggregate_id=target_col.id,
						aggregate_type="KanbanColumn",
						tenant_id=card.tenant_id,
						column_id=target_col.id,
						column_name=target_col.name,
						current_cards=current_count,
						wip_limit=target_col.wip_limit,
					),
					session,
				)
				raise WIPLimitError(
					f"Column {target_col.name!r} WIP limit {target_col.wip_limit} "
					f"reached (current={current_count})"
				)

		# Cycle time: start timer when entering first WORK-type column
		if target_col.column_type == "WORK" and card.cycle_start_at is None:
			card.cycle_start_at = _now()

		# Cycle time: stop timer when entering DONE column
		if target_col.column_type == "DONE":
			card.cycle_end_at = _now()
			card.status = "DONE"

		# Move the card
		old_column_id = card.column_id
		card.column_id = target_column_id
		card.moved_at = _now()

		log.info(
			"LeanManufacturingService.move_card: card=%s %r→%r moved_by=%s",
			card_id, from_column_name, target_col.name, moved_by,
		)

		_emit(
			KanbanCardMovedEvent(
				aggregate_id=card.id,
				aggregate_type="KanbanCard",
				tenant_id=card.tenant_id,
				card_id=card.id,
				from_column=from_column_name,
				to_column=target_col.name,
				moved_by=moved_by,
			),
			session,
		)

		# Pull signal on CONSUME column
		if target_col.column_type == "CONSUME" and card.product_id:
			self.trigger_pull_signal(card, session)

		return card

	# ------------------------------------------------------------------
	# trigger_pull_signal
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"ops.lean.trigger_pull",
		"Trigger kanban pull signal for replenishment",
	)
	def trigger_pull_signal(self, card: Any, session: Any) -> Any:
		"""Create a PullSignal for a product card entering a CONSUME column.

		Attempts to create a production order or PO via MRP/SCM plugins
		(ImportError-safe — failure is non-fatal, signal still recorded).

		Args:
			card: The KanbanCard instance with product_id set.
			session: SQLAlchemy session (caller commits).

		Returns:
			The created PullSignal.
		"""
		from pgappforge.plugins.erp.operations.lean.models import PullSignal
		from pgappforge.plugins.erp.operations.lean.events import PullSignalTriggeredEvent

		assert card.product_id, "card.product_id must be set to trigger pull signal"

		pull = PullSignal(
			tenant_id=card.tenant_id,
			source_card_id=card.id,
			product_id=card.product_id,
			quantity=card.quantity or Decimal("1"),
			status="PENDING",
		)
		session.add(pull)
		session.flush()

		fulfillment_order_id = ""

		# Attempt to create fulfillment order (best-effort)
		try:
			from pgappforge.plugins.erp.operations.mrp.services import MRPService
			mrp = MRPService()
			order = mrp.create_planned_order(
				product_id=card.product_id,
				quantity=card.quantity or Decimal("1"),
				tenant_id=card.tenant_id,
				session=session,
				source="KANBAN_PULL",
			)
			fulfillment_order_id = str(order.id)
			pull.fulfillment_order_id = fulfillment_order_id
			pull.status = "FULFILLED"
			log.info(
				"LeanManufacturingService.trigger_pull_signal: pull=%s → MRP order=%s",
				pull.id, fulfillment_order_id,
			)
		except ImportError:
			log.debug(
				"LeanManufacturingService.trigger_pull_signal: MRP plugin not loaded; "
				"trying SCM for pull signal %s",
				pull.id,
			)
			try:
				from pgappforge.plugins.erp.operations.scm.services import SCMService
				scm = SCMService()
				po = scm.create_purchase_order(
					product_id=card.product_id,
					quantity=card.quantity or Decimal("1"),
					tenant_id=card.tenant_id,
					session=session,
					source="KANBAN_PULL",
				)
				fulfillment_order_id = str(po.id)
				pull.fulfillment_order_id = fulfillment_order_id
				pull.status = "FULFILLED"
				log.info(
					"LeanManufacturingService.trigger_pull_signal: pull=%s → SCM PO=%s",
					pull.id, fulfillment_order_id,
				)
			except ImportError:
				log.debug(
					"LeanManufacturingService.trigger_pull_signal: SCM plugin also not loaded; "
					"pull signal %s remains PENDING",
					pull.id,
				)
		except Exception as exc:
			log.debug(
				"LeanManufacturingService.trigger_pull_signal: fulfillment order creation failed "
				"(non-fatal): %s",
				exc,
			)

		_emit(
			PullSignalTriggeredEvent(
				aggregate_id=pull.id,
				aggregate_type="PullSignal",
				tenant_id=card.tenant_id,
				card_id=card.id,
				product_id=card.product_id,
				quantity=str(card.quantity or Decimal("1")),
				order_id=fulfillment_order_id,
			),
			session,
		)

		return pull

	# ------------------------------------------------------------------
	# get_cycle_time
	# ------------------------------------------------------------------

	def get_cycle_time(
		self,
		board_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute average cycle time for cards completed within the date range.

		Cycle time = cycle_end_at − cycle_start_at (days).

		Args:
			board_id: UUID of the KanbanBoard.
			from_date: Start of window (inclusive, by cycle_end_at date).
			to_date: End of window (inclusive).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session.

		Returns:
			Dict: {board_id, period, avg_cycle_time_days, card_count,
			       min_cycle_time_days, max_cycle_time_days}.
		"""
		from pgappforge.plugins.erp.operations.lean.models import KanbanCard
		from pgappforge.plugins.erp.operations.lean.events import KanbanCycleTimeRecordedEvent

		from_dt = datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0, tzinfo=timezone.utc)
		to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc)

		cards = session.execute(
			sa.select(KanbanCard).where(
				KanbanCard.board_id == board_id,
				KanbanCard.tenant_id == tenant_id,
				KanbanCard.cycle_start_at.isnot(None),
				KanbanCard.cycle_end_at.isnot(None),
				KanbanCard.cycle_end_at >= from_dt,
				KanbanCard.cycle_end_at <= to_dt,
			)
		).scalars().all()

		period_str = f"{from_date.isoformat()}/{to_date.isoformat()}"

		if not cards:
			return {
				"board_id": board_id,
				"period": period_str,
				"avg_cycle_time_days": "0",
				"card_count": 0,
				"min_cycle_time_days": "0",
				"max_cycle_time_days": "0",
			}

		cycle_times_days = [
			_d((c.cycle_end_at - c.cycle_start_at).total_seconds()) / Decimal("86400")
			for c in cards
		]

		avg_ct = (sum(cycle_times_days) / Decimal(len(cycle_times_days))).quantize(
			Decimal("0.01"), rounding=ROUND_HALF_UP
		)
		min_ct = min(cycle_times_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		max_ct = max(cycle_times_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		_emit(
			KanbanCycleTimeRecordedEvent(
				aggregate_id=board_id,
				aggregate_type="KanbanBoard",
				tenant_id=tenant_id,
				board_id=board_id,
				period=period_str,
				avg_cycle_time_days=str(avg_ct),
			),
			session,
		)

		return {
			"board_id": board_id,
			"period": period_str,
			"avg_cycle_time_days": str(avg_ct),
			"card_count": len(cards),
			"min_cycle_time_days": str(min_ct),
			"max_cycle_time_days": str(max_ct),
		}

	# ------------------------------------------------------------------
	# get_flow_efficiency
	# ------------------------------------------------------------------

	def get_flow_efficiency(
		self,
		board_id: str,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute flow efficiency: ratio of touch time (WORK columns) to total cycle time.

		Flow efficiency = touch_time / total_time × 100

		Note: This implementation approximates touch-time as the fraction of WORK columns
		vs total columns traversed, since per-column time is not stored. For precise
		touch-time tracking, instrument column entry/exit events separately.

		Args:
			board_id: UUID of the KanbanBoard.
			period: ISO date range string "YYYY-MM-DD/YYYY-MM-DD".
			session: SQLAlchemy session.

		Returns:
			Dict: {flow_efficiency_pct, avg_wait_time_days, avg_touch_time_days,
			       card_count, period}.
		"""
		from pgappforge.plugins.erp.operations.lean.models import KanbanCard, KanbanColumn

		# Parse period
		parts = period.split("/")
		from_date = date.fromisoformat(parts[0])
		to_date = date.fromisoformat(parts[1])

		from_dt = datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0, tzinfo=timezone.utc)
		to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc)

		# Count WORK vs non-WORK (wait) columns on this board
		columns = session.execute(
			sa.select(KanbanColumn).where(KanbanColumn.board_id == board_id)
		).scalars().all()

		total_cols = len(columns)
		work_cols = sum(1 for c in columns if c.column_type == "WORK")
		wait_cols = total_cols - work_cols

		# Approximation: touch_fraction = work_cols / total_cols
		if total_cols == 0:
			touch_fraction = Decimal("0")
		else:
			touch_fraction = _d(work_cols) / _d(total_cols)

		# Completed cards in period
		cards = session.execute(
			sa.select(KanbanCard).where(
				KanbanCard.board_id == board_id,
				KanbanCard.cycle_start_at.isnot(None),
				KanbanCard.cycle_end_at.isnot(None),
				KanbanCard.cycle_end_at >= from_dt,
				KanbanCard.cycle_end_at <= to_dt,
			)
		).scalars().all()

		if not cards:
			return {
				"flow_efficiency_pct": "0",
				"avg_wait_time_days": "0",
				"avg_touch_time_days": "0",
				"card_count": 0,
				"period": period,
			}

		total_times = [
			_d((c.cycle_end_at - c.cycle_start_at).total_seconds()) / Decimal("86400")
			for c in cards
		]
		avg_total = sum(total_times) / _d(len(total_times))
		avg_touch = (avg_total * touch_fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		avg_wait = (avg_total - avg_touch).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		flow_eff = (touch_fraction * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		return {
			"flow_efficiency_pct": str(flow_eff),
			"avg_wait_time_days": str(max(avg_wait, Decimal("0"))),
			"avg_touch_time_days": str(avg_touch),
			"card_count": len(cards),
			"period": period,
		}

	# ------------------------------------------------------------------
	# get_board_metrics
	# ------------------------------------------------------------------

	def get_board_metrics(self, board_id: str, session: Any) -> dict[str, Any]:
		"""Compute snapshot board metrics for operational dashboards.

		Returns:
		  cards_by_column        — {column_name: count} for ACTIVE cards
		  wip_violations         — list of columns currently over WIP limit
		  avg_age_per_column     — {column_name: avg_days_since_moved_at}
		  blocked_cards          — count of cards past due_date with status=ACTIVE
		  throughput_per_week    — completed cards (status=DONE) in last 7 days
		"""
		from pgappforge.plugins.erp.operations.lean.models import (
			KanbanBoard, KanbanColumn, KanbanCard,
		)

		board = session.execute(
			sa.select(KanbanBoard).where(KanbanBoard.id == board_id)
		).scalar_one_or_none()

		if board is None:
			raise BoardNotFoundError(f"KanbanBoard {board_id!r} not found")

		columns = session.execute(
			sa.select(KanbanColumn).where(KanbanColumn.board_id == board_id)
			.order_by(KanbanColumn.order_num.asc())
		).scalars().all()

		col_map = {c.id: c for c in columns}
		now = _now()
		week_ago = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - __import__("datetime").timedelta(days=7)

		active_cards = session.execute(
			sa.select(KanbanCard).where(
				KanbanCard.board_id == board_id,
				KanbanCard.status == "ACTIVE",
			)
		).scalars().all()

		done_cards_week = session.execute(
			sa.select(sa.func.count()).select_from(KanbanCard).where(
				KanbanCard.board_id == board_id,
				KanbanCard.status == "DONE",
				KanbanCard.cycle_end_at >= week_ago,
			)
		).scalar_one()

		# cards_by_column
		cards_by_column: dict[str, int] = {c.name: 0 for c in columns}
		age_accumulator: dict[str, list[Decimal]] = {c.name: [] for c in columns}
		blocked_count = 0

		for card in active_cards:
			col = col_map.get(card.column_id)
			if col:
				cards_by_column[col.name] = cards_by_column.get(col.name, 0) + 1
				if card.moved_at:
					age_days = _d((now - card.moved_at).total_seconds()) / Decimal("86400")
					age_accumulator.setdefault(col.name, []).append(age_days)

			if card.due_date and card.due_date < now.date():
				blocked_count += 1

		# WIP violations
		wip_violations = []
		for col in columns:
			if col.wip_limit is not None:
				count = cards_by_column.get(col.name, 0)
				if count > col.wip_limit:
					wip_violations.append({
						"column": col.name,
						"current": count,
						"limit": col.wip_limit,
					})

		# avg age per column
		avg_age_per_column: dict[str, str] = {}
		for col_name, ages in age_accumulator.items():
			if ages:
				avg = (sum(ages) / _d(len(ages))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
				avg_age_per_column[col_name] = str(avg)
			else:
				avg_age_per_column[col_name] = "0"

		return {
			"board_id": board_id,
			"cards_by_column": cards_by_column,
			"wip_violations": wip_violations,
			"avg_age_per_column": avg_age_per_column,
			"blocked_cards": blocked_count,
			"throughput_per_week": done_cards_week,
		}


__all__ = [
	"LeanManufacturingService",
	"LeanServiceError",
	"BoardNotFoundError",
	"ColumnNotFoundError",
	"CardNotFoundError",
	"WIPLimitError",
]
