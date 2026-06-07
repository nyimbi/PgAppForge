"""
pgappforge/plugins/erp/finance/grants/services.py

GrantService — business logic for Grant/Fund Accounting.

Responsibilities:
  - Fund lifecycle (create, deactivate)
  - Grant award and close-out
  - Expenditure recording with indirect cost calculation and GL posting
  - Fund balance maintenance (upsert per period)
  - Utilization reporting

Monetary arithmetic uses Decimal + ROUND_HALF_UP throughout.
All cross-plugin calls (GL) are wrapped in try/except so a missing GL
plugin never blocks grant accounting.

BPM actions registered in this module:
  finance.grants.record_expenditure        — record expenditure + GL post
  finance.grants.generate_utilization_report — utilization summary
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.grants.models import (
	Fund,
	FundBalance,
	Grant,
	GrantExpenditure,
)
from pgappforge.plugins.erp.finance.grants.events import (
	FundBalanceUpdatedEvent,
	FundCreatedEvent,
	GrantAwardedEvent,
	GrantCloseOutEvent,
	GrantExpenditureRecordedEvent,
	GrantReportGeneratedEvent,
)
from pgappforge.plugins.erp.foundation.events import emit_event

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: %s suppressed: %s", type(event).__name__, exc)


def _new_grant_ref(tenant_id: str, session: Any) -> str:
	"""Generate GNT-YYYYMMDD-NNNN style reference, unique within tenant."""
	today = date.today().strftime("%Y%m%d")
	prefix = f"GNT-{today}-"
	count_q = sa.select(sa.func.count()).select_from(Grant).where(
		Grant.tenant_id == tenant_id,
		Grant.grant_ref.like(f"{prefix}%"),
	)
	n = (session.execute(count_q).scalar() or 0) + 1
	return f"{prefix}{n:04d}"


# ---------------------------------------------------------------------------
# GrantService
# ---------------------------------------------------------------------------

class GrantService:
	"""Stateless service — instantiate per request or share as singleton."""

	# ------------------------------------------------------------------
	# Fund operations
	# ------------------------------------------------------------------

	def create_fund(
		self,
		name: str,
		fund_type: str,
		fund_code: str,
		tenant_id: str,
		session: Any,
		*,
		entity_id: str | None = None,
		description: str | None = None,
		gl_dimension_value: str | None = None,
	) -> Fund:
		"""Register a new fund.

		fund_type must be one of: UNRESTRICTED, TEMP_RESTRICTED, PERM_RESTRICTED.
		fund_code must be unique within the tenant.
		"""
		assert fund_type in ("UNRESTRICTED", "TEMP_RESTRICTED", "PERM_RESTRICTED"), (
			f"Invalid fund_type {fund_type!r}"
		)
		assert name and fund_code, "name and fund_code are required"

		fund = Fund(
			tenant_id=tenant_id,
			name=name,
			fund_type=fund_type,
			fund_code=fund_code,
			entity_id=entity_id,
			description=description,
			gl_dimension_value=gl_dimension_value,
			is_active=True,
		)
		session.add(fund)
		session.flush()

		_emit(
			FundCreatedEvent(
				aggregate_id=fund.id,
				aggregate_type="Fund",
				tenant_id=tenant_id,
				fund_id=fund.id,
				name=name,
				fund_type=fund_type,
			),
			session,
		)
		log.info("create_fund: fund_id=%s code=%s tenant=%s", fund.id, fund_code, tenant_id)
		return fund

	# ------------------------------------------------------------------
	# Grant operations
	# ------------------------------------------------------------------

	def award_grant(
		self,
		fund_id: str,
		grantor_name: str,
		amount_cents: int,
		start_date: date,
		end_date: date,
		tenant_id: str,
		session: Any,
		*,
		indirect_cost_rate: Decimal | float = 0,
		reporting_requirements: list[dict] | None = None,
		approved_by: str | None = None,
	) -> Grant:
		"""Award a grant to a fund and create the opening period balance.

		grant_ref is auto-generated as GNT-YYYYMMDD-NNNN.
		An initial FundBalance for the first period (YYYY-MM of start_date) is
		created with receipts_cents = amount_cents, representing the award receipt.
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		assert start_date <= end_date, "start_date must not be after end_date"

		grant_ref = _new_grant_ref(tenant_id, session)
		grant = Grant(
			tenant_id=tenant_id,
			fund_id=fund_id,
			grant_ref=grant_ref,
			grantor_name=grantor_name,
			amount_cents=amount_cents,
			start_date=start_date,
			end_date=end_date,
			status="ACTIVE",
			indirect_cost_rate=Decimal(str(indirect_cost_rate)),
			reporting_requirements=reporting_requirements or [],
			approved_by=approved_by,
		)
		session.add(grant)
		session.flush()

		# Create opening period balance representing the award receipt
		opening_period = start_date.strftime("%Y-%m")
		balance = FundBalance(
			tenant_id=tenant_id,
			fund_id=fund_id,
			period=opening_period,
			opening_cents=0,
			receipts_cents=amount_cents,
			expenditures_cents=0,
			closing_cents=amount_cents,
		)
		session.add(balance)
		session.flush()

		_emit(
			GrantAwardedEvent(
				aggregate_id=grant.id,
				aggregate_type="Grant",
				tenant_id=tenant_id,
				grant_id=grant.id,
				fund_id=fund_id,
				grantor=grantor_name,
				amount_cents=amount_cents,
			),
			session,
		)
		log.info(
			"award_grant: grant_id=%s ref=%s amount=%d tenant=%s",
			grant.id, grant_ref, amount_cents, tenant_id,
		)
		return grant

	# ------------------------------------------------------------------
	# Expenditure
	# ------------------------------------------------------------------

	def record_expenditure(
		self,
		grant_id: str,
		amount_cents: int,
		purpose: str,
		period: str,
		tenant_id: str,
		session: Any,
		*,
		approved_by: str | None = None,
		expenditure_date: date | None = None,
	) -> GrantExpenditure:
		"""Record an expenditure against an active grant.

		Indirect cost is calculated as ROUND_HALF_UP(amount_cents * indirect_cost_rate).
		Total posted to GL = amount_cents + indirect_cost_cents.
		Fund balance is updated atomically in the same session.

		GL posting:
		  DR 5100 (Grant Expense)    total_cents
		  CR 1000 (Cash/Bank)        total_cents
		  Dimensions: grant=grant_ref [, fund=gl_dimension_value]
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		assert purpose, "purpose is required"
		assert period, "period is required"

		grant: Grant | None = session.execute(
			sa.select(Grant).where(Grant.id == grant_id, Grant.tenant_id == tenant_id)
		).scalar_one_or_none()
		assert grant is not None, f"Grant {grant_id!r} not found"
		assert grant.status == "ACTIVE", f"Grant {grant_id!r} is not ACTIVE (status={grant.status!r})"

		# Indirect cost — ROUND_HALF_UP
		indirect = (
			Decimal(str(amount_cents)) * Decimal(str(grant.indirect_cost_rate))
		).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		indirect_cost_cents = int(indirect)
		total_cents = amount_cents + indirect_cost_cents

		expenditure = GrantExpenditure(
			tenant_id=tenant_id,
			grant_id=grant_id,
			period=period,
			amount_cents=amount_cents,
			indirect_cost_cents=indirect_cost_cents,
			purpose=purpose,
			approved_by=approved_by,
			expenditure_date=expenditure_date or date.today(),
		)
		session.add(expenditure)
		session.flush()

		# GL posting — best-effort, never blocks expenditure recording
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService

			fund: Fund | None = session.execute(
				sa.select(Fund).where(Fund.id == grant.fund_id)
			).scalar_one_or_none()

			dims: dict[str, str] = {"grant": grant.grant_ref}
			if fund and fund.gl_dimension_value:
				dims["fund"] = fund.gl_dimension_value

			gl_journal_id = GLService().post_simple_journal(
				lines=[
					{
						"account_code": "5100",
						"debit_cents": total_cents,
						"credit_cents": 0,
						"dimensions": dims,
					},
					{
						"account_code": "1000",
						"debit_cents": 0,
						"credit_cents": total_cents,
						"dimensions": dims,
					},
				],
				session=session,
				tenant_id=tenant_id,
				description=f"Grant expenditure: {purpose}",
				source_doc_id=str(grant_id),
				source_doc_type="GRANT_EXPENDITURE",
			)
			expenditure.gl_journal_id = str(gl_journal_id) if gl_journal_id else None
			session.flush()
		except Exception as exc:
			log.warning("record_expenditure: GL post failed: %s", exc)

		# Update fund balance
		self._update_fund_balance(
			grant.fund_id, period, amount_cents, tenant_id, session
		)

		_emit(
			GrantExpenditureRecordedEvent(
				aggregate_id=expenditure.id,
				aggregate_type="GrantExpenditure",
				tenant_id=tenant_id,
				expenditure_id=expenditure.id,
				grant_id=grant_id,
				amount_cents=amount_cents,
				purpose=purpose,
			),
			session,
		)
		log.info(
			"record_expenditure: exp_id=%s grant=%s amount=%d indirect=%d period=%s",
			expenditure.id, grant_id, amount_cents, indirect_cost_cents, period,
		)
		return expenditure

	# ------------------------------------------------------------------
	# Fund balance maintenance
	# ------------------------------------------------------------------

	def _update_fund_balance(
		self,
		fund_id: str,
		period: str,
		expenditure_cents: int,
		tenant_id: str,
		session: Any,
	) -> FundBalance:
		"""Upsert the FundBalance for (fund_id, period), adding expenditure_cents.

		closing_cents = opening_cents + receipts_cents - expenditures_cents
		"""
		balance: FundBalance | None = session.execute(
			sa.select(FundBalance).where(
				FundBalance.fund_id == fund_id,
				FundBalance.period == period,
			)
		).scalar_one_or_none()

		if balance is None:
			balance = FundBalance(
				tenant_id=tenant_id,
				fund_id=fund_id,
				period=period,
				opening_cents=0,
				receipts_cents=0,
				expenditures_cents=expenditure_cents,
				closing_cents=-expenditure_cents,
			)
			session.add(balance)
		else:
			balance.expenditures_cents = balance.expenditures_cents + expenditure_cents
			balance.closing_cents = (
				balance.opening_cents + balance.receipts_cents - balance.expenditures_cents
			)

		session.flush()

		_emit(
			FundBalanceUpdatedEvent(
				aggregate_id=balance.id,
				aggregate_type="FundBalance",
				tenant_id=tenant_id,
				fund_id=fund_id,
				period=period,
				closing_cents=balance.closing_cents,
			),
			session,
		)
		return balance

	# ------------------------------------------------------------------
	# Reporting
	# ------------------------------------------------------------------

	def get_grant_utilization_report(
		self,
		tenant_id: str,
		session: Any,
		*,
		grant_id: str | None = None,
	) -> list[dict]:
		"""Return utilization summary for all grants (or a single grant).

		Each dict:
		  grant_ref, grantor, amount_cents, total_spent_cents,
		  utilization_pct (float, 0–100+), remaining_cents, status, end_date
		"""
		q = sa.select(Grant).where(Grant.tenant_id == tenant_id)
		if grant_id:
			q = q.where(Grant.id == grant_id)
		grants: list[Grant] = list(session.execute(q).scalars().all())

		results = []
		for g in grants:
			# Sum direct + indirect costs
			spent_q = sa.select(
				sa.func.coalesce(
					sa.func.sum(GrantExpenditure.amount_cents + GrantExpenditure.indirect_cost_cents),
					0,
				)
			).where(GrantExpenditure.grant_id == g.id)
			total_spent: int = session.execute(spent_q).scalar() or 0

			utilization_pct = (
				round(total_spent / g.amount_cents * 100, 2) if g.amount_cents else 0.0
			)
			remaining_cents = g.amount_cents - total_spent

			row = {
				"grant_ref": g.grant_ref,
				"grantor": g.grantor_name,
				"amount_cents": g.amount_cents,
				"total_spent_cents": total_spent,
				"utilization_pct": utilization_pct,
				"remaining_cents": remaining_cents,
				"status": g.status,
				"end_date": g.end_date.isoformat() if g.end_date else None,
			}
			results.append(row)

			# Emit report-generated event for each grant included
			_emit(
				GrantReportGeneratedEvent(
					aggregate_id=g.id,
					aggregate_type="Grant",
					tenant_id=tenant_id,
					grant_id=g.id,
					period="ALL",
					utilization_pct=utilization_pct,
				),
				session,
			)

		return results

	# ------------------------------------------------------------------
	# Close-out
	# ------------------------------------------------------------------

	def close_out_grant(self, grant_id: str, session: Any) -> Grant:
		"""Transition an ACTIVE grant to CLOSED and emit GrantCloseOutEvent.

		Calculates total_spent and remaining from GrantExpenditure records.
		"""
		grant: Grant | None = session.execute(
			sa.select(Grant).where(Grant.id == grant_id)
		).scalar_one_or_none()
		assert grant is not None, f"Grant {grant_id!r} not found"
		assert grant.status == "ACTIVE", (
			f"Grant {grant_id!r} cannot be closed from status {grant.status!r}"
		)

		spent_q = sa.select(
			sa.func.coalesce(
				sa.func.sum(GrantExpenditure.amount_cents + GrantExpenditure.indirect_cost_cents),
				0,
			)
		).where(GrantExpenditure.grant_id == grant_id)
		total_spent: int = session.execute(spent_q).scalar() or 0
		remaining = grant.amount_cents - total_spent

		grant.status = "CLOSED"
		session.flush()

		_emit(
			GrantCloseOutEvent(
				aggregate_id=grant.id,
				aggregate_type="Grant",
				tenant_id=grant.tenant_id,
				grant_id=grant.id,
				total_spent_cents=total_spent,
				remaining_cents=remaining,
			),
			session,
		)
		log.info(
			"close_out_grant: grant_id=%s spent=%d remaining=%d",
			grant_id, total_spent, remaining,
		)
		return grant


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry

	@BPMActionRegistry.register(
		"finance.grants.record_expenditure",
		"Record grant expenditure with GL posting",
	)
	def _bpm_record_expenditure(
		record_ctx: dict,
		session: Any,
		grant_id: str = "",
		amount_cents: int = 0,
		purpose: str = "",
		period: str = "",
		approved_by: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = GrantService()
			exp = svc.record_expenditure(
				grant_id=grant_id,
				amount_cents=amount_cents,
				purpose=purpose,
				period=period,
				tenant_id=tenant_id,
				session=session,
				approved_by=approved_by,
			)
			return {
				"status": "ok",
				"expenditure_id": exp.id,
				"amount_cents": exp.amount_cents,
				"indirect_cost_cents": exp.indirect_cost_cents,
			}
		except Exception as exc:
			log.warning("bpm finance.grants.record_expenditure failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"finance.grants.generate_utilization_report",
		"Generate grant utilization report",
	)
	def _bpm_utilization_report(
		record_ctx: dict,
		session: Any,
		grant_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = GrantService()
			rows = svc.get_grant_utilization_report(
				tenant_id=tenant_id,
				session=session,
				grant_id=grant_id or None,
			)
			return {"status": "ok", "grants": rows, "count": len(rows)}
		except Exception as exc:
			log.warning("bpm finance.grants.generate_utilization_report failed: %s", exc)
			return {"status": "error", "message": str(exc)}

except ImportError:
	log.debug("grants.services: BPMActionRegistry not available, skipping BPM registrations")


__all__ = ["GrantService"]
