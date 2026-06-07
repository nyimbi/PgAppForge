"""
pgappforge/plugins/erp/finance/profit_center/services.py

ProfitCenterService — stateless business logic for Profit Center Accounting.

All methods receive an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents (BigInteger). Never float.
  - post_to_profit_center: exactly one of debit_cents or credit_cents is non-zero.
  - Revenue accounts: GL code prefix 4xxx (credit normal balance).
  - Cost/expense accounts: GL code prefix 5xxx-6xxx (debit normal balance).
  - Hierarchy report uses recursive CTE on parent_id.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func, text

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("profit_center._emit: non-fatal event emission failure: %s", exc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ProfitCenterServiceError(Exception):
	"""Base error for profit center domain violations."""


class ProfitCenterNotFoundError(ProfitCenterServiceError):
	"""No ProfitCenter with the given id."""


class AllocationRuleNotFoundError(ProfitCenterServiceError):
	"""No ProfitCenterAllocationRule with the given id."""


class InvalidJournalError(ProfitCenterServiceError):
	"""Journal entry failed validation."""


class InvalidAllocationError(ProfitCenterServiceError):
	"""Allocation rule or targets are invalid."""


# ---------------------------------------------------------------------------
# ProfitCenterService
# ---------------------------------------------------------------------------

class ProfitCenterService:
	"""Stateless service for Profit Center Accounting operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session; callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# create_profit_center
	# ------------------------------------------------------------------

	def create_profit_center(
		self,
		code: str,
		name: str,
		tenant_id: str,
		session: Any,
		*,
		parent_id: str | None = None,
		entity_id: str | None = None,
		manager_id: str | None = None,
		cost_center_code: str | None = None,
		budget_annual_cents: int = 0,
	) -> Any:
		"""Create and persist a ProfitCenter.

		code must be unique per tenant — a database UniqueConstraint enforces this;
		callers should catch IntegrityError if code is already taken.

		Returns the persisted ProfitCenter.
		"""
		from pgappforge.plugins.erp.finance.profit_center.models import ProfitCenter
		from pgappforge.plugins.erp.finance.profit_center.events import ProfitCenterCreatedEvent

		assert code, "code must not be empty"
		assert name, "name must not be empty"
		assert tenant_id, "tenant_id must not be empty"

		# Validate parent exists if provided
		if parent_id:
			parent = session.get(ProfitCenter, parent_id)
			if parent is None:
				raise ProfitCenterNotFoundError(
					f"Parent ProfitCenter {parent_id!r} not found"
				)

		pc = ProfitCenter(
			tenant_id=tenant_id,
			code=code,
			name=name,
			parent_id=parent_id,
			manager_id=manager_id,
			cost_center_code=cost_center_code,
			entity_id=entity_id,
			budget_annual_cents=budget_annual_cents,
			is_active=True,
		)
		session.add(pc)
		session.flush()

		_emit(
			ProfitCenterCreatedEvent(
				aggregate_id=pc.id,
				aggregate_type="ProfitCenter",
				tenant_id=tenant_id,
				pc_id=pc.id,
				code=code,
				name=name,
			),
			session,
		)

		log.info(
			"ProfitCenterService.create_profit_center: created %r code=%s id=%s",
			name, code, pc.id,
		)
		return pc

	# ------------------------------------------------------------------
	# post_to_profit_center
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"finance.profit_center.post_journal",
		"Post to profit center",
	)
	def post_to_profit_center(
		self,
		profit_center_id: str,
		gl_account: str,
		debit_cents: int,
		credit_cents: int,
		period: str,
		session: Any,
		*,
		reference_id: str | None = None,
		description: str | None = None,
		**_kw: Any,
	) -> Any:
		"""Post a debit or credit line to a profit center for a GL account and period.

		Exactly one of debit_cents or credit_cents must be non-zero.
		Both being zero is invalid; both being non-zero is also invalid.

		Returns the persisted ProfitCenterJournal.
		"""
		from pgappforge.plugins.erp.finance.profit_center.models import (
			ProfitCenter,
			ProfitCenterJournal,
		)
		from pgappforge.plugins.erp.finance.profit_center.events import (
			ProfitCenterJournalPostedEvent,
		)

		assert profit_center_id, "profit_center_id must not be empty"
		assert gl_account, "gl_account must not be empty"
		assert period, "period must not be empty"

		if debit_cents < 0 or credit_cents < 0:
			raise InvalidJournalError("debit_cents and credit_cents must be non-negative")
		if debit_cents == 0 and credit_cents == 0:
			raise InvalidJournalError(
				"Both debit_cents and credit_cents are zero — at least one must be non-zero"
			)
		if debit_cents > 0 and credit_cents > 0:
			raise InvalidJournalError(
				"Both debit_cents and credit_cents are non-zero — "
				"a journal line must be either debit OR credit"
			)

		pc = session.get(ProfitCenter, profit_center_id)
		if pc is None:
			raise ProfitCenterNotFoundError(
				f"ProfitCenter {profit_center_id!r} not found"
			)
		if not pc.is_active:
			raise ProfitCenterServiceError(
				f"ProfitCenter {pc.code!r} is inactive"
			)

		journal = ProfitCenterJournal(
			tenant_id=pc.tenant_id,
			profit_center_id=profit_center_id,
			gl_account=gl_account,
			debit_cents=debit_cents,
			credit_cents=credit_cents,
			period=period,
			description=description,
			reference_id=reference_id,
		)
		session.add(journal)
		session.flush()

		_emit(
			ProfitCenterJournalPostedEvent(
				aggregate_id=journal.id,
				aggregate_type="ProfitCenterJournal",
				tenant_id=pc.tenant_id,
				journal_id=journal.id,
				pc_id=profit_center_id,
				debit_cents=debit_cents,
				credit_cents=credit_cents,
				period=period,
			),
			session,
		)

		log.info(
			"ProfitCenterService.post_to_profit_center: pc=%s acct=%s "
			"DR=%d CR=%d period=%s",
			profit_center_id, gl_account, debit_cents, credit_cents, period,
		)
		return journal

	# ------------------------------------------------------------------
	# get_pnl
	# ------------------------------------------------------------------

	def get_pnl(
		self,
		profit_center_id: str,
		from_period: str,
		to_period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a P&L summary for a profit center over a range of periods.

		Revenue: sum of credit_cents on GL accounts starting with '4'
		Cost of sales: sum of debit_cents on accounts starting with '5'
		Operating expenses: sum of debit_cents on accounts starting with '6'

		Returns:
		    {
		        "profit_center_id": str,
		        "from_period": str,
		        "to_period": str,
		        "revenue_cents": int,
		        "cost_of_sales_cents": int,
		        "gross_profit_cents": int,
		        "operating_expenses_cents": int,
		        "operating_profit_cents": int,
		        "net_profit_cents": int,
		        "revenue_lines": [{"gl_account": str, "amount_cents": int}],
		        "cost_lines": [{"gl_account": str, "amount_cents": int}],
		    }
		"""
		from pgappforge.plugins.erp.finance.profit_center.models import ProfitCenterJournal

		pc = session.get(
			__import__(
				"pgappforge.plugins.erp.finance.profit_center.models",
				fromlist=["ProfitCenter"],
			).ProfitCenter,
			profit_center_id,
		)
		if pc is None:
			raise ProfitCenterNotFoundError(f"ProfitCenter {profit_center_id!r} not found")

		# Fetch all journal rows for the PC in the period range
		rows = session.execute(
			select(ProfitCenterJournal).where(
				ProfitCenterJournal.profit_center_id == profit_center_id,
				ProfitCenterJournal.period >= from_period,
				ProfitCenterJournal.period <= to_period,
			)
		).scalars().all()

		# Aggregate by account prefix
		revenue_by_acct: dict[str, int] = {}
		cogs_by_acct: dict[str, int] = {}
		opex_by_acct: dict[str, int] = {}

		for row in rows:
			code = row.gl_account
			if code.startswith("4"):
				# Revenue: credit normal balance
				net = row.credit_cents - row.debit_cents
				revenue_by_acct[code] = revenue_by_acct.get(code, 0) + net
			elif code.startswith("5"):
				# Cost of sales: debit normal balance
				net = row.debit_cents - row.credit_cents
				cogs_by_acct[code] = cogs_by_acct.get(code, 0) + net
			elif code.startswith("6"):
				# Operating expenses: debit normal balance
				net = row.debit_cents - row.credit_cents
				opex_by_acct[code] = opex_by_acct.get(code, 0) + net

		revenue_cents = sum(revenue_by_acct.values())
		cost_of_sales_cents = sum(cogs_by_acct.values())
		gross_profit_cents = revenue_cents - cost_of_sales_cents
		operating_expenses_cents = sum(opex_by_acct.values())
		operating_profit_cents = gross_profit_cents - operating_expenses_cents

		return {
			"profit_center_id": profit_center_id,
			"profit_center_code": pc.code,
			"profit_center_name": pc.name,
			"from_period": from_period,
			"to_period": to_period,
			"revenue_cents": revenue_cents,
			"cost_of_sales_cents": cost_of_sales_cents,
			"gross_profit_cents": gross_profit_cents,
			"gross_margin_pct": (
				round(gross_profit_cents / revenue_cents * 100, 2)
				if revenue_cents else None
			),
			"operating_expenses_cents": operating_expenses_cents,
			"operating_profit_cents": operating_profit_cents,
			"net_profit_cents": operating_profit_cents,  # extend for tax/interest below the line
			"revenue_lines": [
				{"gl_account": k, "amount_cents": v}
				for k, v in sorted(revenue_by_acct.items())
			],
			"cost_lines": [
				{"gl_account": k, "amount_cents": v}
				for k, v in sorted({**cogs_by_acct, **opex_by_acct}.items())
			],
		}

	# ------------------------------------------------------------------
	# run_allocation
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"finance.profit_center.run_allocation",
		"Run cost allocation between profit centers",
	)
	def run_allocation(
		self,
		rule_id: str,
		period: str,
		session: Any,
		**_kw: Any,
	) -> list[Any]:
		"""Execute a ProfitCenterAllocationRule for the given period.

		Allocation methods:
		  FIXED_PERCENTAGE — apply explicit percentages from rule.targets
		  HEADCOUNT        — allocate proportional to headcount stored in
		                     ProfitCenter.metadata_["headcount"] (default 1)
		  REVENUE          — allocate proportional to revenue of each target PC
		                     in the same period (from ProfitCenterJournal 4xxx)

		Fetches source amounts for the period (respecting gl_accounts filter),
		posts allocation journals to each target PC, and emits
		ProfitCenterAllocationDoneEvent.

		Returns list of posted ProfitCenterJournal rows.
		"""
		from pgappforge.plugins.erp.finance.profit_center.models import (
			ProfitCenter,
			ProfitCenterAllocationRule,
			ProfitCenterJournal,
		)
		from pgappforge.plugins.erp.finance.profit_center.events import (
			ProfitCenterAllocationDoneEvent,
		)

		rule = session.get(ProfitCenterAllocationRule, rule_id)
		if rule is None:
			raise AllocationRuleNotFoundError(
				f"ProfitCenterAllocationRule {rule_id!r} not found"
			)
		if not rule.is_active:
			raise ProfitCenterServiceError(f"AllocationRule {rule.name!r} is inactive")

		source_pc = session.get(ProfitCenter, rule.source_profit_center_id)
		if source_pc is None:
			raise ProfitCenterNotFoundError(
				f"Source ProfitCenter {rule.source_profit_center_id!r} not found"
			)

		# ── Fetch source amounts for the period ──────────────────────────
		q = select(ProfitCenterJournal).where(
			ProfitCenterJournal.profit_center_id == rule.source_profit_center_id,
			ProfitCenterJournal.period == period,
		)
		if rule.gl_accounts:
			q = q.where(ProfitCenterJournal.gl_account.in_(rule.gl_accounts))
		source_rows = session.execute(q).scalars().all()

		if not source_rows:
			log.info(
				"ProfitCenterService.run_allocation: no source amounts for "
				"rule=%s period=%s — nothing to allocate",
				rule_id, period,
			)
			return []

		# Aggregate source by account
		source_by_acct: dict[str, int] = {}
		for row in source_rows:
			net = row.debit_cents - row.credit_cents
			source_by_acct[row.gl_account] = source_by_acct.get(row.gl_account, 0) + net

		# ── Compute allocation weights ────────────────────────────────────
		targets: list[dict] = rule.targets or []
		if not targets:
			raise InvalidAllocationError(f"Rule {rule.name!r} has no allocation targets")

		weights: dict[str, Decimal] = {}

		if rule.allocation_method == "FIXED_PERCENTAGE":
			total_pct = Decimal("0")
			for t in targets:
				pct = Decimal(str(t.get("percentage", 0)))
				weights[t["profit_center_id"]] = pct
				total_pct += pct
			if total_pct != Decimal("100"):
				raise InvalidAllocationError(
					f"FIXED_PERCENTAGE targets sum to {total_pct}, must be 100"
				)

		elif rule.allocation_method == "HEADCOUNT":
			total_hc = Decimal("0")
			raw: dict[str, Decimal] = {}
			for t in targets:
				pc_id = t["profit_center_id"]
				target_pc = session.get(ProfitCenter, pc_id)
				hc = Decimal(str(
					(target_pc.metadata_ or {}).get("headcount", 1)
					if target_pc else 1
				))
				raw[pc_id] = hc
				total_hc += hc
			if total_hc == 0:
				raise InvalidAllocationError("All target profit centers have headcount=0")
			for pc_id, hc in raw.items():
				weights[pc_id] = hc / total_hc * Decimal("100")

		elif rule.allocation_method == "REVENUE":
			total_rev = Decimal("0")
			raw_rev: dict[str, Decimal] = {}
			for t in targets:
				pc_id = t["profit_center_id"]
				rev_rows = session.execute(
					select(func.sum(ProfitCenterJournal.credit_cents)).where(
						ProfitCenterJournal.profit_center_id == pc_id,
						ProfitCenterJournal.period == period,
						ProfitCenterJournal.gl_account.like("4%"),
					)
				).scalar() or 0
				raw_rev[pc_id] = Decimal(str(rev_rows))
				total_rev += raw_rev[pc_id]
			if total_rev == 0:
				raise InvalidAllocationError(
					"All target profit centers have zero revenue in period "
					f"{period!r} — cannot allocate by REVENUE"
				)
			for pc_id, rev in raw_rev.items():
				weights[pc_id] = rev / total_rev * Decimal("100")

		else:
			raise InvalidAllocationError(
				f"Unknown allocation_method {rule.allocation_method!r}"
			)

		# ── Post allocation journals ──────────────────────────────────────
		posted_journals: list[Any] = []
		allocation_events: list[dict] = []

		for account_code, source_net in source_by_acct.items():
			if source_net == 0:
				continue
			for t in targets:
				pc_id = t["profit_center_id"]
				weight = weights.get(pc_id, Decimal("0"))
				alloc_amount = int(
					(Decimal(source_net) * weight / Decimal("100"))
					.to_integral_value(rounding=ROUND_HALF_UP)
				)
				if alloc_amount == 0:
					continue

				# Debit target if source was a cost (debit), credit target if source was revenue
				debit_c = alloc_amount if source_net > 0 else 0
				credit_c = 0 if source_net > 0 else abs(alloc_amount)

				j = self.post_to_profit_center(
					profit_center_id=pc_id,
					gl_account=account_code,
					debit_cents=debit_c,
					credit_cents=credit_c,
					period=period,
					session=session,
					reference_id=rule_id,
					description=f"Allocation from {source_pc.code}: {rule.name}",
				)
				posted_journals.append(j)
				allocation_events.append({
					"profit_center_id": pc_id,
					"amount_cents": alloc_amount,
					"period": period,
					"gl_account": account_code,
				})

		_emit(
			ProfitCenterAllocationDoneEvent(
				aggregate_id=rule_id,
				aggregate_type="ProfitCenterAllocationRule",
				tenant_id=source_pc.tenant_id,
				source_pc_id=rule.source_profit_center_id,
				allocations=allocation_events,
			),
			session,
		)

		log.info(
			"ProfitCenterService.run_allocation: rule=%s period=%s posted %d journals",
			rule_id, period, len(posted_journals),
		)
		return posted_journals

	# ------------------------------------------------------------------
	# get_hierarchy_report
	# ------------------------------------------------------------------

	def get_hierarchy_report(
		self,
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
		period: str | None = None,
	) -> dict[str, Any]:
		"""Return a P&L hierarchy report for all profit centers under the tenant.

		Uses a recursive CTE on parent_id to build the org tree.  Each node includes:
		  - code, name, parent_id
		  - revenue_cents, costs_cents, margin_cents
		  - budget_annual_cents, budget_variance_cents
		  - children: []  (nested list; populated by tree assembly)

		Optionally filters by entity_id and/or period range.

		Returns:
		    {
		        "tenant_id": str,
		        "period": str | None,
		        "entity_id": str | None,
		        "nodes": [<flat list of nodes with children nested>],
		        "totals": {"revenue_cents": int, "costs_cents": int, "margin_cents": int},
		    }
		"""
		from pgappforge.plugins.erp.finance.profit_center.models import (
			ProfitCenter,
			ProfitCenterJournal,
		)

		# Load all PCs for tenant (optionally filtered by entity_id)
		q = select(ProfitCenter).where(
			ProfitCenter.tenant_id == tenant_id,
			ProfitCenter.is_active == True,
		)
		if entity_id:
			q = q.where(ProfitCenter.entity_id == entity_id)
		pcs = session.execute(q).scalars().all()
		pc_map: dict[str, Any] = {pc.id: pc for pc in pcs}

		# Load aggregated journal amounts per PC
		jq = select(
			ProfitCenterJournal.profit_center_id,
			ProfitCenterJournal.gl_account,
			func.sum(ProfitCenterJournal.debit_cents).label("total_debit"),
			func.sum(ProfitCenterJournal.credit_cents).label("total_credit"),
		).where(
			ProfitCenterJournal.tenant_id == tenant_id,
			ProfitCenterJournal.profit_center_id.in_(list(pc_map.keys())),
		)
		if period:
			jq = jq.where(ProfitCenterJournal.period == period)
		jq = jq.group_by(
			ProfitCenterJournal.profit_center_id,
			ProfitCenterJournal.gl_account,
		)
		journal_rows = session.execute(jq).all()

		# Aggregate per PC
		pc_revenue: dict[str, int] = {}
		pc_costs: dict[str, int] = {}
		for row in journal_rows:
			pc_id = row.profit_center_id
			code = row.gl_account
			if code.startswith("4"):
				net = (row.total_credit or 0) - (row.total_debit or 0)
				pc_revenue[pc_id] = pc_revenue.get(pc_id, 0) + net
			elif code.startswith("5") or code.startswith("6"):
				net = (row.total_debit or 0) - (row.total_credit or 0)
				pc_costs[pc_id] = pc_costs.get(pc_id, 0) + net

		# Build node dict
		nodes: dict[str, dict] = {}
		for pc_id, pc in pc_map.items():
			revenue = pc_revenue.get(pc_id, 0)
			costs = pc_costs.get(pc_id, 0)
			margin = revenue - costs
			budget = pc.budget_annual_cents or 0
			nodes[pc_id] = {
				"id": pc_id,
				"code": pc.code,
				"name": pc.name,
				"parent_id": pc.parent_id,
				"entity_id": pc.entity_id,
				"manager_id": pc.manager_id,
				"revenue_cents": revenue,
				"costs_cents": costs,
				"margin_cents": margin,
				"budget_annual_cents": budget,
				"budget_variance_cents": revenue - costs - budget,
				"children": [],
			}

		# Assemble tree (attach children to parents)
		roots: list[dict] = []
		for node in nodes.values():
			parent_id = node["parent_id"]
			if parent_id and parent_id in nodes:
				nodes[parent_id]["children"].append(node)
			else:
				roots.append(node)

		# Compute totals across all PCs (not just roots)
		total_revenue = sum(pc_revenue.values())
		total_costs = sum(pc_costs.values())

		return {
			"tenant_id": tenant_id,
			"period": period,
			"entity_id": entity_id,
			"nodes": roots,
			"totals": {
				"revenue_cents": total_revenue,
				"costs_cents": total_costs,
				"margin_cents": total_revenue - total_costs,
			},
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProfitCenterService",
	"ProfitCenterServiceError",
	"ProfitCenterNotFoundError",
	"AllocationRuleNotFoundError",
	"InvalidJournalError",
	"InvalidAllocationError",
]
