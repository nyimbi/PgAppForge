"""
pgappforge/plugins/erp/finance/gl/realtime.py

RealtimeGLService — Workday-style continuous accounting.

Reads from pre-aggregated GLAccountBalance rows (updated atomically by post_journal)
rather than scanning all journal entries. Result: O(accounts) not O(entries).
Supports dimensional filtering via JSONB @> operator.

Usage::

    svc = RealtimeGLService()
    pnl = svc.get_live_pnl(tenant_id, "January 2026", session)
    bs  = svc.get_live_balance_sheet(tenant_id, "January 2026", session)

All amounts returned as integer cents (BigInteger). account_type strings match
GLAccount.account_type enum: ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE | COST_OF_GOODS
"""
from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

log = logging.getLogger(__name__)

__all__ = ["RealtimeGLService"]


class RealtimeGLService:
	"""Continuous accounting analytics sourced from pre-aggregated balance rows."""

	# ------------------------------------------------------------------
	# get_live_pnl
	# ------------------------------------------------------------------

	def get_live_pnl(
		self,
		tenant_id: str,
		period: str,
		session: Any,
		*,
		dimension_filters: dict[str, Any] | None = None,
		account_types: list[str] | None = None,
	) -> dict:
		"""Real-time P&L from pre-aggregated GLAccountBalance. O(accounts) complexity.

		Args:
		    tenant_id:         Tenant UUID string.
		    period:            GLPeriod.period_name e.g. "January 2026".
		    session:           SQLAlchemy session.
		    dimension_filters: JSONB @> filter e.g. {"project": "PRJ001"}.
		                       Applied against GLAccountBalance.dimensions.
		    account_types:     Optional allow-list of account types to include.
		                       Default: REVENUE, EXPENSE, COST_OF_GOODS.

		Returns::

		    {
		        "period": str,
		        "revenue_cents": int,
		        "expense_cents": int,
		        "gross_profit_cents": int,   # revenue - expense
		        "net_income_cents": int,     # same as gross_profit_cents
		        "accounts": [
		            {
		                "account_code": str,
		                "account_type": str,
		                "period_debit": int,
		                "period_credit": int,
		                "net": int,
		            }
		        ]
		    }
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLAccount,
			GLAccountBalance,
			GLPeriod,
		)

		_types = account_types or ["REVENUE", "EXPENSE", "COST_OF_GOODS"]

		stmt = (
			sa.select(
				GLAccountBalance.account_code,
				GLAccount.account_type,
				GLAccountBalance.period_debit,
				GLAccountBalance.period_credit,
			)
			.join(GLAccount, GLAccountBalance.account_code == GLAccount.account_code)
			.join(GLPeriod, GLAccountBalance.period_id == GLPeriod.id)
			.where(
				GLAccountBalance.tenant_id == tenant_id,
				GLPeriod.period_name == period,
				GLAccount.account_type.in_(_types),
			)
		)

		if dimension_filters:
			stmt = stmt.where(
				GLAccountBalance.dimensions.op("@>")(
					sa.cast(json.dumps(dimension_filters), JSONB)
				)
			)

		rows = session.execute(stmt).all()

		revenue = 0
		expense = 0
		accounts: list[dict] = []

		for r in rows:
			dr = r.period_debit or 0
			cr = r.period_credit or 0

			if r.account_type == "REVENUE":
				# Revenue: normal credit balance — net = CR - DR
				net = cr - dr
				revenue += abs(net)
			elif r.account_type in ("EXPENSE", "COST_OF_GOODS"):
				# Expense: normal debit balance — net = DR - CR
				net = dr - cr
				expense += abs(net)
			else:
				net = dr - cr

			accounts.append({
				"account_code": r.account_code,
				"account_type": r.account_type,
				"period_debit": dr,
				"period_credit": cr,
				"net": net,
			})

		gross_profit = revenue - expense

		return {
			"period": period,
			"revenue_cents": revenue,
			"expense_cents": expense,
			"gross_profit_cents": gross_profit,
			"net_income_cents": gross_profit,
			"accounts": accounts,
		}

	# ------------------------------------------------------------------
	# get_live_balance_sheet
	# ------------------------------------------------------------------

	def get_live_balance_sheet(
		self,
		tenant_id: str,
		period: str,
		session: Any,
		*,
		dimension_filters: dict[str, Any] | None = None,
	) -> dict:
		"""Real-time balance sheet from pre-aggregated GLAccountBalance. O(accounts) complexity.

		Uses closing_debit / closing_credit (YTD cumulative) for ASSET/LIABILITY/EQUITY.
		Net income for the period is NOT included here — compose with get_live_pnl() if needed.

		Args:
		    tenant_id:         Tenant UUID string.
		    period:            GLPeriod.period_name e.g. "January 2026".
		    session:           SQLAlchemy session.
		    dimension_filters: JSONB @> filter e.g. {"department": "FINANCE"}.

		Returns::

		    {
		        "period": str,
		        "assets_cents": int,
		        "liabilities_cents": int,
		        "equity_cents": int,
		        "balanced": bool,    # assets == liabilities + equity
		        "accounts": [
		            {"account_code": str, "account_type": str, "balance_cents": int}
		        ]
		    }
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLAccount,
			GLAccountBalance,
			GLPeriod,
		)

		stmt = (
			sa.select(
				GLAccountBalance.account_code,
				GLAccount.account_type,
				GLAccountBalance.closing_debit,
				GLAccountBalance.closing_credit,
			)
			.join(GLAccount, GLAccountBalance.account_code == GLAccount.account_code)
			.join(GLPeriod, GLAccountBalance.period_id == GLPeriod.id)
			.where(
				GLAccountBalance.tenant_id == tenant_id,
				GLPeriod.period_name == period,
				GLAccount.account_type.in_(["ASSET", "LIABILITY", "EQUITY"]),
			)
		)

		if dimension_filters:
			stmt = stmt.where(
				GLAccountBalance.dimensions.op("@>")(
					sa.cast(json.dumps(dimension_filters), JSONB)
				)
			)

		rows = session.execute(stmt).all()

		assets = 0
		liabilities = 0
		equity = 0
		accounts: list[dict] = []

		for r in rows:
			closing_dr = r.closing_debit or 0
			closing_cr = r.closing_credit or 0

			if r.account_type == "ASSET":
				# Assets: normal debit balance
				net = closing_dr - closing_cr
				assets += net
			elif r.account_type == "LIABILITY":
				# Liabilities: normal credit balance
				net = closing_cr - closing_dr
				liabilities += net
			else:
				# EQUITY: normal credit balance
				net = closing_cr - closing_dr
				equity += net

			accounts.append({
				"account_code": r.account_code,
				"account_type": r.account_type,
				"balance_cents": net,
			})

		return {
			"period": period,
			"assets_cents": assets,
			"liabilities_cents": liabilities,
			"equity_cents": equity,
			"balanced": assets == liabilities + equity,
			"accounts": accounts,
		}
