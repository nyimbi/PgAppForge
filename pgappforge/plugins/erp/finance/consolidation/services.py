"""
pgappforge/plugins/erp/finance/consolidation/services.py

ConsolidationService — stateless business logic for Group Consolidation.

All methods receive an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents (BigInteger). Never float.
  - FX translation uses Decimal arithmetic; rates stored as strings in events.
  - Intercompany detection: match AR on entity A vs AP on entity B, same amount.
  - Minority interest: (100 - ownership_pct) / 100 * subsidiary_equity_cents.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

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
		log.debug("consolidation._emit: non-fatal event emission failure: %s", exc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConsolidationServiceError(Exception):
	"""Base error for consolidation domain violations."""


class GroupNotFoundError(ConsolidationServiceError):
	"""No ConsolidationGroup with the given id."""


class RunNotFoundError(ConsolidationServiceError):
	"""No ConsolidationRun with the given id."""


class InvalidMembersError(ConsolidationServiceError):
	"""Members data fails validation."""


# ---------------------------------------------------------------------------
# FX translation helpers
# ---------------------------------------------------------------------------

# Account type → translation rate type mapping (IFRS IAS 21)
# INCOME/EXPENSE: period average rate
# ASSET/LIABILITY: closing (period-end) rate
# EQUITY: historical rate (approximated here by opening rate from period start)
_FX_RATE_TYPE = {
	"REVENUE": "AVERAGE",
	"EXPENSE": "AVERAGE",
	"ASSET": "CLOSING",
	"LIABILITY": "CLOSING",
	"EQUITY": "HISTORICAL",
}


def _get_fx_rate(
	from_currency: str,
	to_currency: str,
	rate_type: str,
	period: str,
	session: Any,
) -> Decimal:
	"""Fetch an FX rate from the GL foundation exchange rate table.

	Falls back to 1.0 (same currency) if no rate is configured, logging a warning.
	Rate type: AVERAGE | CLOSING | HISTORICAL.
	"""
	if from_currency == to_currency:
		return Decimal("1")

	try:
		from pgappforge.plugins.erp.foundation.models import ERPExchangeRate
		row = session.execute(
			select(ERPExchangeRate).where(
				ERPExchangeRate.from_currency == from_currency,
				ERPExchangeRate.to_currency == to_currency,
				ERPExchangeRate.period == period,
				ERPExchangeRate.rate_type == rate_type,
			).order_by(ERPExchangeRate.effective_date.desc()).limit(1)
		).scalar_one_or_none()
		if row is not None:
			return Decimal(str(row.rate))
	except Exception as exc:
		log.debug("_get_fx_rate: foundation rate lookup failed (%s) — using 1.0", exc)

	log.warning(
		"_get_fx_rate: no %s rate found for %s→%s period=%s — using 1.0",
		rate_type, from_currency, to_currency, period,
	)
	return Decimal("1")


def _translate_amount(
	amount_cents: int,
	rate: Decimal,
) -> int:
	"""Translate an integer-cent amount by multiplying by rate, rounding to int."""
	result = Decimal(amount_cents) * rate
	return int(result.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# ConsolidationService
# ---------------------------------------------------------------------------

class ConsolidationService:
	"""Stateless service for Group Consolidation operations.

	Instantiate once per app (or per request).  All methods accept a
	SQLAlchemy Session; callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# create_group
	# ------------------------------------------------------------------

	def create_group(
		self,
		name: str,
		reporting_entity_id: str,
		members_data: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		reporting_currency: str = "USD",
		description: str | None = None,
	) -> Any:
		"""Create a ConsolidationGroup with validated membership list.

		members_data format:
		    [{"entity_id": str, "ownership_pct": float, "method": "FULL|EQUITY|PROPORTIONAL"}]

		Validation: sum(ownership_pct) must be < 100 or == 100 (minority = 0).
		The reporting_entity_id must NOT appear in members_data — it is the parent.

		Returns the persisted ConsolidationGroup.
		"""
		from pgappforge.plugins.erp.finance.consolidation.models import ConsolidationGroup

		assert name, "name must not be empty"
		assert reporting_entity_id, "reporting_entity_id must not be empty"
		assert tenant_id, "tenant_id must not be empty"
		assert isinstance(members_data, list), "members_data must be a list"

		_VALID_METHODS = {"FULL", "EQUITY", "PROPORTIONAL"}
		total_pct = Decimal("0")
		seen_ids: set[str] = set()
		for m in members_data:
			eid = m.get("entity_id", "")
			pct = Decimal(str(m.get("ownership_pct", 0)))
			method = m.get("method", "")
			if not eid:
				raise InvalidMembersError("Each member must have a non-empty entity_id")
			if eid == reporting_entity_id:
				raise InvalidMembersError(
					f"reporting_entity_id {reporting_entity_id!r} cannot also be a member"
				)
			if eid in seen_ids:
				raise InvalidMembersError(f"Duplicate entity_id {eid!r} in members_data")
			if method not in _VALID_METHODS:
				raise InvalidMembersError(
					f"Invalid method {method!r} for entity {eid!r}. "
					f"Must be one of {_VALID_METHODS}"
				)
			if pct <= 0 or pct > 100:
				raise InvalidMembersError(
					f"ownership_pct must be between 0 and 100 for entity {eid!r}, got {pct}"
				)
			total_pct += pct
			seen_ids.add(eid)

		if total_pct > Decimal("100"):
			raise InvalidMembersError(
				f"Sum of ownership_pct ({total_pct}) exceeds 100%. "
				"The remainder is minority interest."
			)

		group = ConsolidationGroup(
			tenant_id=tenant_id,
			name=name,
			description=description,
			reporting_entity_id=reporting_entity_id,
			reporting_currency=reporting_currency,
			is_active=True,
			members=members_data,
		)
		session.add(group)
		session.flush()

		log.info(
			"ConsolidationService.create_group: created %r id=%s members=%d",
			name, group.id, len(members_data),
		)
		return group

	# ------------------------------------------------------------------
	# run_consolidation
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"finance.consolidation.run",
		"Run group consolidation for period",
	)
	def run_consolidation(
		self,
		group_id: str,
		period: str,
		session: Any,
		**_kw: Any,
	) -> Any:
		"""Execute a full consolidation run for the given group and period.

		Steps:
		  1. Create ConsolidationRun (IN_PROGRESS), emit ConsolidationRunStartedEvent.
		  2. For each member entity: fetch GL trial balance via GLService.get_trial_balance().
		     (Matched by entity_id — entities must have a GL period open for the period.)
		  3. Apply FX translation (IAS 21):
		       Income/expense accounts  → period average rate
		       Balance sheet accounts   → closing rate
		       Equity accounts          → historical rate
		     Emit FXTranslationAppliedEvent per entity whose currency differs.
		  4. Identify intercompany balances: match AR lines in entity A vs AP lines in
		     entity B with matching amounts and account codes.
		  5. Post IntercompanyElimination entries. Emit IntercompanyEliminationPostedEvent.
		  6. Compute minority interest for each subsidiary below 100% ownership.
		     Emit MinorityInterestComputedEvent.
		  7. Aggregate translated + eliminated trial balances → consolidated trial balance.
		  8. Store consolidated result in run.result_data. Update status → COMPLETED.
		     Emit ConsolidationRunCompletedEvent.

		Returns the ConsolidationRun.
		Raises ConsolidationServiceError on unrecoverable failure (run set to FAILED).
		"""
		from pgappforge.plugins.erp.finance.consolidation.models import (
			ConsolidationGroup,
			ConsolidationRun,
			IntercompanyElimination,
			MinorityInterest,
		)
		from pgappforge.plugins.erp.finance.consolidation.events import (
			ConsolidationRunStartedEvent,
			IntercompanyEliminationPostedEvent,
			FXTranslationAppliedEvent,
			ConsolidationRunCompletedEvent,
			MinorityInterestComputedEvent,
		)

		# ── 1. Load group ────────────────────────────────────────────────
		group = session.get(ConsolidationGroup, group_id)
		if group is None:
			raise GroupNotFoundError(f"ConsolidationGroup {group_id!r} not found")

		run = ConsolidationRun(
			tenant_id=group.tenant_id,
			group_id=group_id,
			period=period,
			status="IN_PROGRESS",
			started_at=datetime.now(timezone.utc),
			entities_processed=0,
			eliminations_count=0,
			result_data={},
		)
		session.add(run)
		session.flush()

		_emit(
			ConsolidationRunStartedEvent(
				aggregate_id=run.id,
				aggregate_type="ConsolidationRun",
				tenant_id=group.tenant_id,
				run_id=run.id,
				reporting_entity_id=group.reporting_entity_id,
				period=period,
			),
			session,
		)

		try:
			result = self._do_consolidation(
				run=run,
				group=group,
				period=period,
				session=session,
				IntercompanyElimination=IntercompanyElimination,
				MinorityInterest=MinorityInterest,
				FXTranslationAppliedEvent=FXTranslationAppliedEvent,
				IntercompanyEliminationPostedEvent=IntercompanyEliminationPostedEvent,
				MinorityInterestComputedEvent=MinorityInterestComputedEvent,
			)
		except Exception as exc:
			run.status = "FAILED"
			run.error_message = str(exc)
			run.completed_at = datetime.now(timezone.utc)
			session.flush()
			log.error("ConsolidationService.run_consolidation: run %s FAILED: %s", run.id, exc)
			raise

		run.status = "COMPLETED"
		run.completed_at = datetime.now(timezone.utc)
		run.entities_processed = result["entities_processed"]
		run.eliminations_count = result["eliminations_count"]
		run.result_data = result["result_data"]
		session.flush()

		_emit(
			ConsolidationRunCompletedEvent(
				aggregate_id=run.id,
				aggregate_type="ConsolidationRun",
				tenant_id=group.tenant_id,
				run_id=run.id,
				period=period,
				entities_consolidated=result["entities_processed"],
				eliminations_count=result["eliminations_count"],
			),
			session,
		)

		log.info(
			"ConsolidationService.run_consolidation: run %s COMPLETED "
			"entities=%d eliminations=%d",
			run.id, result["entities_processed"], result["eliminations_count"],
		)
		return run

	def _do_consolidation(
		self,
		run: Any,
		group: Any,
		period: str,
		session: Any,
		IntercompanyElimination: Any,
		MinorityInterest: Any,
		FXTranslationAppliedEvent: Any,
		IntercompanyEliminationPostedEvent: Any,
		MinorityInterestComputedEvent: Any,
	) -> dict[str, Any]:
		"""Internal consolidation engine — called by run_consolidation."""
		from pgappforge.plugins.erp.finance.gl.services import GLService

		gl_svc = GLService()
		reporting_currency = group.reporting_currency
		members: list[dict] = group.members or []

		# ── 2. Fetch trial balances per entity ───────────────────────────
		# entity_id → list of TB rows
		entity_tb: dict[str, list[dict]] = {}
		# entity_id → functional currency
		entity_currency: dict[str, str] = {}

		for member in members:
			entity_id = member["entity_id"]
			# Find the GL period for this entity + period string
			period_row = self._find_gl_period(entity_id, period, session)
			if period_row is None:
				log.warning(
					"_do_consolidation: no GL period found for entity=%s period=%s — skipping",
					entity_id, period,
				)
				entity_tb[entity_id] = []
				entity_currency[entity_id] = reporting_currency
				continue

			tb = gl_svc.get_trial_balance(period_row.id, session)
			entity_tb[entity_id] = tb
			# Functional currency from the period/entity configuration
			func_currency = getattr(period_row, "functional_currency", None) or reporting_currency
			entity_currency[entity_id] = func_currency

		# ── 3. FX translation ────────────────────────────────────────────
		# translated_tb: entity_id → list of rows with net_cents in reporting currency
		translated_tb: dict[str, list[dict]] = {}

		for member in members:
			entity_id = member["entity_id"]
			func_currency = entity_currency.get(entity_id, reporting_currency)
			tb = entity_tb.get(entity_id, [])

			if func_currency == reporting_currency:
				translated_tb[entity_id] = [
					{**row, "translated_net_cents": row.get("net", 0)}
					for row in tb
				]
				continue

			# Determine rates needed
			avg_rate = _get_fx_rate(func_currency, reporting_currency, "AVERAGE", period, session)
			closing_rate = _get_fx_rate(func_currency, reporting_currency, "CLOSING", period, session)
			hist_rate = _get_fx_rate(func_currency, reporting_currency, "HISTORICAL", period, session)

			translated_rows = []
			for row in tb:
				acct_type = row.get("account_type", "ASSET")
				rate_type = _FX_RATE_TYPE.get(acct_type, "CLOSING")
				rate = avg_rate if rate_type == "AVERAGE" else (
					closing_rate if rate_type == "CLOSING" else hist_rate
				)
				net = row.get("net", 0)
				translated_net = _translate_amount(net, rate)
				translated_rows.append({**row, "translated_net_cents": translated_net})
			translated_tb[entity_id] = translated_rows

			_emit(
				FXTranslationAppliedEvent(
					aggregate_id=run.id,
					aggregate_type="ConsolidationRun",
					tenant_id=group.tenant_id,
					run_id=run.id,
					entity_id=entity_id,
					period=period,
					reporting_currency=reporting_currency,
					functional_currency=func_currency,
					rate_used=str(closing_rate),
				),
				session,
			)

		# ── 4 & 5. Intercompany elimination ─────────────────────────────
		eliminations_count = 0
		# Build IC matrix: (entity_a, entity_b, account_code) → amount_cents
		ic_matrix = self._build_ic_matrix(
			translated_tb, members,
			session=session,
			tenant_id=str(group.tenant_id),
			period=run.period,
		)

		for (entity_a, entity_b, account_code), amount_cents in ic_matrix.items():
			if amount_cents <= 0:
				continue
			elim = IntercompanyElimination(
				tenant_id=group.tenant_id,
				run_id=run.id,
				debtor_entity_id=entity_a,
				creditor_entity_id=entity_b,
				elimination_type="AR_AP",
				amount_cents=amount_cents,
				currency_code=reporting_currency,
				account_code=account_code,
				description=f"IC elimination {entity_a}↔{entity_b} acct {account_code} period {period}",
			)
			session.add(elim)
			session.flush()
			eliminations_count += 1

			_emit(
				IntercompanyEliminationPostedEvent(
					aggregate_id=elim.id,
					aggregate_type="IntercompanyElimination",
					tenant_id=group.tenant_id,
					run_id=run.id,
					elimination_id=elim.id,
					dr_entity=entity_a,
					cr_entity=entity_b,
					amount_cents=amount_cents,
					account=account_code,
				),
				session,
			)

		# ── 6. Minority interest ─────────────────────────────────────────
		for member in members:
			entity_id = member["entity_id"]
			ownership_pct = Decimal(str(member.get("ownership_pct", 100)))
			if ownership_pct >= Decimal("100"):
				continue

			minority_pct = Decimal("100") - ownership_pct

			# Subsidiary equity = sum of EQUITY account translated net
			tb_rows = translated_tb.get(entity_id, [])
			subsidiary_equity_cents = sum(
				r.get("translated_net_cents", 0)
				for r in tb_rows
				if r.get("account_type") == "EQUITY"
			)
			minority_interest_cents = int(
				(Decimal(subsidiary_equity_cents) * minority_pct / Decimal("100"))
				.to_integral_value(rounding=ROUND_HALF_UP)
			)

			mi = MinorityInterest(
				tenant_id=group.tenant_id,
				run_id=run.id,
				subsidiary_entity_id=entity_id,
				minority_ownership_pct=minority_pct,
				subsidiary_equity_cents=subsidiary_equity_cents,
				minority_interest_cents=minority_interest_cents,
				period=period,
			)
			session.add(mi)
			session.flush()

			_emit(
				MinorityInterestComputedEvent(
					aggregate_id=mi.id,
					aggregate_type="MinorityInterest",
					tenant_id=group.tenant_id,
					run_id=run.id,
					subsidiary_id=entity_id,
					minority_pct=str(minority_pct),
					minority_equity_cents=minority_interest_cents,
				),
				session,
			)

		# ── 7. Aggregate consolidated trial balance ──────────────────────
		consolidated: dict[str, int] = {}
		for entity_id, tb_rows in translated_tb.items():
			for row in tb_rows:
				code = row.get("account_code", "")
				net = row.get("translated_net_cents", 0)
				consolidated[code] = consolidated.get(code, 0) + net

		# Subtract eliminations from affected accounts
		for (entity_a, entity_b, account_code), amount_cents in ic_matrix.items():
			if amount_cents > 0:
				consolidated[account_code] = consolidated.get(account_code, 0) - amount_cents

		# ── 8. Build result_data ─────────────────────────────────────────
		consolidated_tb = [
			{"account_code": code, "net_cents": net}
			for code, net in sorted(consolidated.items())
		]
		result_data = {
			"period": period,
			"reporting_currency": reporting_currency,
			"trial_balance": consolidated_tb,
			"entities": [m["entity_id"] for m in members],
			"ic_eliminations_count": eliminations_count,
		}

		return {
			"entities_processed": len(members),
			"eliminations_count": eliminations_count,
			"result_data": result_data,
		}

	def _find_gl_period(self, entity_id: str, period: str, session: Any) -> Any | None:
		"""Locate a GLPeriod whose period_name or YYYY-MM matches the given period string."""
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLPeriod
			# Try matching by period_name (e.g. "January 2025") or by start_date prefix
			# Convention: period = "YYYY-MM" → match start_date beginning with that prefix
			import datetime as _dt
			try:
				year, month = period.split("-")
				target_start = _dt.date(int(year), int(month), 1)
			except (ValueError, AttributeError):
				return None

			row = session.execute(
				select(GLPeriod).where(
					GLPeriod.start_date == target_start,
					GLPeriod.status == "OPEN",
				).limit(1)
			).scalar_one_or_none()
			return row
		except Exception as exc:
			log.debug("_find_gl_period: %s", exc)
			return None

	def _build_ic_matrix(
		self,
		translated_tb: dict[str, list[dict]],
		members: list[dict],
		session: Any = None,
		tenant_id: str = "",
		period: str = "",
	) -> dict[tuple[str, str, str], int]:
		"""Identify intercompany balances for elimination.

		Priority 1 (authoritative): Load ICOutboxTransaction records (ACCEPTED)
		between group entities for the period — explicit IC postings registered
		via the intercompany module. These are deterministic eliminations.

		Priority 2 (fallback heuristic): Amount-sign matching across entity TBs
		for any IC balances not captured by Priority 1. Kept as a safety net.

		Returns: {(entity_a, entity_b, account_code): amount_cents}
		"""
		entity_ids = [m["entity_id"] for m in members]
		entity_id_set = set(entity_ids)
		matrix: dict[tuple[str, str, str], int] = {}

		# Priority 1: authoritative IC eliminations from ICOutboxTransaction
		if session is not None and tenant_id and period:
			try:
				from pgappforge.plugins.erp.finance.intercompany.models import ICOutboxTransaction  # type: ignore[import]
				import sqlalchemy as _sa

				# Parse period "YYYY-MM" → date range for sent_at filter
				from datetime import date as _dt
				_year, _month = int(period[:4]), int(period[5:7])
				_period_start = _dt(_year, _month, 1)
				_next_y, _next_m = (_year, _month + 1) if _month < 12 else (_year + 1, 1)
				_period_end = _dt(_next_y, _next_m, 1)

				ic_txs = session.execute(
					_sa.select(ICOutboxTransaction).where(
						ICOutboxTransaction.tenant_id == tenant_id,
						ICOutboxTransaction.status == "ACCEPTED",
						ICOutboxTransaction.source_entity_id.in_(list(entity_id_set)),
						ICOutboxTransaction.target_entity_id.in_(list(entity_id_set)),
						# Bound to period to avoid unbounded cross-year fetches
						ICOutboxTransaction.sent_at >= _sa.cast(_period_start, _sa.Date),
						ICOutboxTransaction.sent_at < _sa.cast(_period_end, _sa.Date),
					)
				).scalars().all()

				for tx in ic_txs:
					doc = tx.document_data or {}
					# document_data carries {amount_cents, account_code, currency_code}
					amount = int(doc.get("amount_cents", 0))
					acct = str(doc.get("account_code", "1100"))
					if amount > 0:
						key = (str(tx.source_entity_id), str(tx.target_entity_id), acct)
						matrix[key] = matrix.get(key, 0) + amount
			except ImportError:
				log.debug("_build_ic_matrix: intercompany plugin not loaded")
			except Exception as exc:
				log.warning("_build_ic_matrix: IC transaction query failed: %s", exc)

		# Priority 2: heuristic fallback — same-account, opposite-sign balances
		entity_acct_map: dict[str, dict[str, int]] = {}
		for member in members:
			eid = member["entity_id"]
			tb = translated_tb.get(eid, [])
			entity_acct_map[eid] = {
				row["account_code"]: row.get("translated_net_cents", 0)
				for row in tb
			}

		for i, entity_a in enumerate(entity_ids):
			for entity_b in entity_ids[i + 1:]:
				accts_a = entity_acct_map.get(entity_a, {})
				accts_b = entity_acct_map.get(entity_b, {})
				for account_code, net_a in accts_a.items():
					net_b = accts_b.get(account_code, 0)
					# Only add heuristic match if not already captured by authoritative path
					if net_a > 0 and net_b < 0:
						heuristic_key = (entity_a, entity_b, account_code)
						reverse_key = (entity_b, entity_a, account_code)
						# Check both directions to prevent double-counting (P1 may have captured reverse)
						if heuristic_key not in matrix and reverse_key not in matrix:
							matrix[heuristic_key] = min(net_a, abs(net_b))

		return matrix

	# ------------------------------------------------------------------
	# get_consolidated_trial_balance
	# ------------------------------------------------------------------

	def get_consolidated_trial_balance(self, run_id: str, session: Any) -> dict[str, Any]:
		"""Return the consolidated trial balance stored in a completed run.

		Returns:
		    {
		        "run_id": str,
		        "period": str,
		        "reporting_currency": str,
		        "trial_balance": [{"account_code": str, "net_cents": int}],
		        "entities_processed": int,
		        "eliminations_count": int,
		    }
		Raises RunNotFoundError if the run does not exist.
		"""
		from pgappforge.plugins.erp.finance.consolidation.models import ConsolidationRun

		run = session.get(ConsolidationRun, run_id)
		if run is None:
			raise RunNotFoundError(f"ConsolidationRun {run_id!r} not found")

		return {
			"run_id": run_id,
			"period": run.period,
			"status": run.status,
			"entities_processed": run.entities_processed,
			"eliminations_count": run.eliminations_count,
			**run.result_data,
		}

	# ------------------------------------------------------------------
	# get_intercompany_matrix
	# ------------------------------------------------------------------

	def get_intercompany_matrix(
		self,
		group_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a matrix showing IC balances per entity pair.

		Finds the most recent COMPLETED run for the group+period and summarises
		the IntercompanyElimination rows by (debtor_entity_id, creditor_entity_id).

		Returns:
		    {
		        "group_id": str,
		        "period": str,
		        "run_id": str | None,
		        "matrix": [
		            {
		                "debtor_entity_id": str,
		                "creditor_entity_id": str,
		                "elimination_type": str,
		                "account_code": str,
		                "amount_cents": int,
		                "currency_code": str,
		            }
		        ]
		    }
		"""
		from pgappforge.plugins.erp.finance.consolidation.models import (
			ConsolidationRun,
			IntercompanyElimination,
		)

		run = session.execute(
			select(ConsolidationRun).where(
				ConsolidationRun.group_id == group_id,
				ConsolidationRun.period == period,
				ConsolidationRun.tenant_id == tenant_id,
				ConsolidationRun.status == "COMPLETED",
			).order_by(ConsolidationRun.completed_at.desc()).limit(1)
		).scalar_one_or_none()

		if run is None:
			return {
				"group_id": group_id,
				"period": period,
				"run_id": None,
				"matrix": [],
			}

		rows = session.execute(
			select(IntercompanyElimination).where(
				IntercompanyElimination.run_id == run.id
			).order_by(
				IntercompanyElimination.debtor_entity_id,
				IntercompanyElimination.creditor_entity_id,
			)
		).scalars().all()

		matrix = [
			{
				"debtor_entity_id": r.debtor_entity_id,
				"creditor_entity_id": r.creditor_entity_id,
				"elimination_type": r.elimination_type,
				"account_code": r.account_code,
				"amount_cents": r.amount_cents,
				"currency_code": r.currency_code,
			}
			for r in rows
		]

		return {
			"group_id": group_id,
			"period": period,
			"run_id": run.id,
			"matrix": matrix,
		}


# ---------------------------------------------------------------------------
# BPM action wrapper (module-level registration for non-instance method)
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"finance.consolidation.get_trial_balance",
	"Retrieve consolidated trial balance for a run",
)
def _bpm_get_consolidated_tb(
	record_ctx: dict,
	session: Any,
	run_id: str = "",
	**kw: Any,
) -> dict:
	try:
		svc = ConsolidationService()
		return {"status": "ok", **svc.get_consolidated_trial_balance(run_id, session)}
	except ConsolidationServiceError as exc:
		return {"status": "error", "message": str(exc)}
	except Exception as exc:
		log.error("BPM finance.consolidation.get_trial_balance error: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"ConsolidationService",
	"ConsolidationServiceError",
	"GroupNotFoundError",
	"RunNotFoundError",
	"InvalidMembersError",
]
