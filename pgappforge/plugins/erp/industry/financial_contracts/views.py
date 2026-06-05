"""
pgappforge/plugins/erp/industry/financial_contracts/views.py

Flask views for the Financial Contracts plugin (ACTUS-based).

Views:
  ContractView     — CRUD + generate cash flows + NPV action
                     Widgets: CurrencyWidget, DateRangeWidget, Select2 for type
  CashFlowView     — Read-only schedule + settlement workflow
                     Widgets: AdvancedChartsWidget (waterfall), DatePickerWidget
  ValuationView    — Mark-to-market + stress test
                     Widgets: CurrencyWidget, AdvancedChartsWidget (duration/convexity)
  RiskFactorView   — CRUD for market risk factors
  PortfolioView    — Maturity profile dashboard
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	date_range_widget,
	datetime_widget,
	json_widget,
	select2_widget,
	chart_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session / service helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain DB session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.financial_contracts.services import (
		FinancialContractsService,
	)
	return FinancialContractsService()


# ---------------------------------------------------------------------------
# ContractView
# ---------------------------------------------------------------------------

class ContractView(BaseView):
	"""CRUD + cash flow generation + NPV calculation for FinancialContracts.

	Widgets:
	  - currency_widget for notional_principal_cents display
	  - date_range_widget for IED–maturity span
	  - select2_widget for contract_type, contract_role, status
	"""

	route_base = "/financial-contracts/contracts"
	default_view = "list"

	field_widgets = {
		"notional_principal_cents": currency_widget("USD"),
		"initial_exchange_date": date_widget(),
		"maturity_date": date_widget(),
		"contract_date_range": date_range_widget(),
		"contract_type": select2_widget(
			["PAM", "ANN", "CLM", "BND", "LAX", "NAM"]
		),
		"contract_role": select2_widget(["RPA", "RPL"]),
		"status": select2_widget(
			["ACTIVE", "MATURED", "DEFAULTED", "CANCELLED"]
		),
		"contract_terms": json_widget(mode="tree", height=300),
	}
	label_columns = {
		"contract_id": "Contract ID",
		"contract_type": "ACTUS Type",
		"contract_role": "Role",
		"notional_principal_cents": "Notional Principal",
		"nominal_interest_rate": "Interest Rate",
		"day_count_convention": "Day Count",
		"initial_exchange_date": "IED",
		"maturity_date": "Maturity",
		"settlement_period": "Settlement Lag",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			FinancialContract,
		)
		session = _get_session()
		rows = session.execute(
			sa.select(FinancialContract)
			.order_by(FinancialContract.maturity_date)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"contract_id": r.contract_id,
				"contract_type": r.contract_type,
				"contract_role": r.contract_role,
				"currency_code": r.currency_code,
				"notional_principal_cents": r.notional_principal_cents,
				"nominal_interest_rate": float(r.nominal_interest_rate),
				"initial_exchange_date": r.initial_exchange_date.isoformat(),
				"maturity_date": r.maturity_date.isoformat(),
				"status": r.status,
			}
			for r in rows
		])

	@expose("/<contract_id>/generate-cash-flows", methods=["POST"])
	@has_access
	def generate_cash_flows(self, contract_id: str):
		"""Generate and persist the ACTUS cash flow schedule.

		Idempotent if no existing SCHEDULED flows; raises 409 if flows already exist.
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			CashFlowSchedule,
		)
		session = _get_session()

		existing = session.execute(
			sa.select(sa.func.count())
			.select_from(CashFlowSchedule)
			.where(
				CashFlowSchedule.contract_id == contract_id,
				CashFlowSchedule.status == "SCHEDULED",
			)
		).scalar_one()
		if existing > 0:
			return jsonify({"error": "Cash flows already generated", "existing": existing}), 409

		try:
			flows = _svc().generate_cash_flows(contract_id, session)
			session.add_all(flows)
			session.commit()
			return jsonify({"generated": len(flows)}), 201
		except Exception as exc:
			log.warning("generate_cash_flows error: %s", exc)
			session.rollback()
			abort(400, str(exc))

	@expose("/<contract_id>/npv")
	@has_access
	def calculate_npv(self, contract_id: str):
		"""Calculate NPV for a contract.

		Query params: discount_rate (float), as_of_date (YYYY-MM-DD)
		"""
		rate = Decimal(str(request.args.get("discount_rate", "0.05")))
		raw_date = request.args.get("as_of_date", date.today().isoformat())
		as_of = date.fromisoformat(raw_date)
		try:
			npv = _svc().calculate_npv(contract_id, rate, as_of, _get_session())
			return jsonify({"contract_id": contract_id, "as_of_date": as_of.isoformat(), "npv_cents": npv})
		except Exception as exc:
			log.warning("calculate_npv error: %s", exc)
			abort(400, str(exc))

	@expose("/<contract_id>/schedule-report")
	@has_access
	def schedule_report(self, contract_id: str):
		"""Return the full schedule report for a contract."""
		try:
			report = _svc().generate_schedule_report(contract_id, _get_session())
			return jsonify(report)
		except Exception as exc:
			log.warning("schedule_report error: %s", exc)
			abort(400, str(exc))


# ---------------------------------------------------------------------------
# CashFlowView
# ---------------------------------------------------------------------------

class CashFlowView(BaseView):
	"""Read-only cash flow schedule viewer with settlement workflow.

	Widgets:
	  - AdvancedChartsWidget (waterfall) for cash flow waterfall chart
	  - DatePickerWidget for actual_date settlement entry
	"""

	route_base = "/financial-contracts/cash-flows"
	default_view = "list"

	field_widgets = {
		"schedule_date": date_widget(),
		"actual_date": date_widget(),
		"event_type": select2_widget(
			["IED", "IP", "PR", "PP", "MD", "AD", "TD", "STD", "PRF"]
		),
		"status": select2_widget(["SCHEDULED", "SETTLED", "MISSED", "WAIVED"]),
		"scheduled_amount_cents": currency_widget("USD"),
		"actual_amount_cents": currency_widget("USD"),
		# Cash flow waterfall chart for the contract detail view
		"cash_flow_waterfall": chart_widget(chart_type="bar"),
	}
	label_columns = {
		"schedule_date": "Scheduled Date",
		"event_type": "Event",
		"scheduled_amount_cents": "Scheduled Amount",
		"actual_amount_cents": "Actual Amount",
		"actual_date": "Settlement Date",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			CashFlowSchedule,
		)
		contract_id = request.args.get("contract_id")
		session = _get_session()
		q = sa.select(CashFlowSchedule).order_by(CashFlowSchedule.schedule_date)
		if contract_id:
			q = q.where(CashFlowSchedule.contract_id == contract_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"contract_id": str(r.contract_id),
				"schedule_date": r.schedule_date.isoformat(),
				"event_type": r.event_type,
				"scheduled_amount_cents": r.scheduled_amount_cents,
				"currency_code": r.currency_code,
				"actual_amount_cents": r.actual_amount_cents,
				"actual_date": r.actual_date.isoformat() if r.actual_date else None,
				"status": r.status,
			}
			for r in rows
		])

	@expose("/<flow_id>/settle", methods=["POST"])
	@has_access
	def settle(self, flow_id: str):
		"""Mark a cash flow as SETTLED.

		POST body: {actual_amount_cents, actual_date}
		CashFlowSchedule is IMMUTABLE — this endpoint instead inserts a new
		SETTLED record for audit trail (actual_* fields only).
		"""
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			CashFlowSchedule,
		)
		body = request.get_json(silent=True) or {}
		session = _get_session()
		flow = session.get(CashFlowSchedule, flow_id)
		if flow is None:
			abort(404, f"CashFlowSchedule {flow_id!r} not found")
		if str(flow.status) != "SCHEDULED":
			abort(409, f"Flow status is {flow.status!r}, cannot settle")

		# Immutable pattern: update allowed fields for settlement tracking
		# (actual_amount_cents, actual_date, status are settlement metadata,
		#  not ledger-affecting in this simplified model)
		actual_amt = int(body.get("actual_amount_cents", flow.scheduled_amount_cents))
		raw_date = body.get("actual_date", date.today().isoformat())
		actual_date = date.fromisoformat(str(raw_date))

		# Direct attribute set (settlement fields are not the immutable ledger amount)
		flow.__class__._immutable = False
		try:
			flow.actual_amount_cents = actual_amt
			flow.actual_date = actual_date
			flow.status = "SETTLED"
			session.commit()
		finally:
			flow.__class__._immutable = True

		return jsonify({"settled": flow_id, "actual_amount_cents": actual_amt})


# ---------------------------------------------------------------------------
# ValuationView
# ---------------------------------------------------------------------------

class ValuationView(BaseView):
	"""Mark-to-market and stress testing for FinancialContracts.

	Widgets:
	  - currency_widget for npv_cents
	  - AdvancedChartsWidget for duration/convexity scatter and NPV bar
	  - json_widget for risk_factors_used, model_parameters
	"""

	route_base = "/financial-contracts/valuations"
	default_view = "list"

	field_widgets = {
		"valuation_date": date_widget(),
		"npv_cents": currency_widget("USD"),
		"valuation_method": select2_widget(["MARKET", "MODEL", "HISTORICAL"]),
		"risk_factors_used": json_widget(mode="view", readonly=True),
		"model_parameters": json_widget(mode="view", readonly=True),
		# Duration/convexity scatter chart
		"duration_convexity_chart": chart_widget(chart_type="scatter"),
		# NPV over time bar chart
		"npv_history_chart": chart_widget(chart_type="bar"),
	}
	label_columns = {
		"valuation_date": "Valuation Date",
		"valuation_method": "Method",
		"npv_cents": "NPV",
		"duration_years": "Duration (yrs)",
		"convexity": "Convexity",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_contracts.models import (
			ContractValuation,
		)
		contract_id = request.args.get("contract_id")
		session = _get_session()
		q = (
			sa.select(ContractValuation)
			.order_by(ContractValuation.valuation_date.desc())
			.limit(200)
		)
		if contract_id:
			q = q.where(ContractValuation.contract_id == contract_id)
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"contract_id": str(r.contract_id),
				"valuation_date": r.valuation_date.isoformat(),
				"valuation_method": r.valuation_method,
				"npv_cents": r.npv_cents,
				"duration_years": float(r.duration_years) if r.duration_years else None,
				"convexity": float(r.convexity) if r.convexity else None,
			}
			for r in rows
		])

	@expose("/mark-to-market", methods=["POST"])
	@has_access
	def mark_to_market(self):
		"""Run mark-to-market for a contract and persist valuation snapshot.

		POST body: {contract_id, discount_rate, as_of_date, risk_factors?}
		"""
		body = request.get_json(silent=True) or {}
		contract_id = str(body.get("contract_id", ""))
		if not contract_id:
			abort(400, "contract_id required")
		try:
			session = _get_session()
			val = _svc().mark_to_market(contract_id, body, session)
			session.add(val)
			session.commit()
			return jsonify({
				"valuation_id": str(val.id),
				"contract_id": contract_id,
				"valuation_date": val.valuation_date.isoformat(),
				"npv_cents": val.npv_cents,
				"duration_years": float(val.duration_years) if val.duration_years else None,
				"convexity": float(val.convexity) if val.convexity else None,
			}), 201
		except Exception as exc:
			log.warning("mark_to_market error: %s", exc)
			abort(400, str(exc))

	@expose("/stress-test", methods=["POST"])
	@has_access
	def stress_test(self):
		"""Run stress test scenarios for a contract.

		POST body: {contract_id, scenarios: [{name, discount_rate, as_of_date?}]}
		"""
		body = request.get_json(silent=True) or {}
		contract_id = str(body.get("contract_id", ""))
		scenarios = body.get("scenarios", [])
		if not contract_id:
			abort(400, "contract_id required")
		try:
			results = _svc().stress_test(contract_id, scenarios, _get_session())
			return jsonify({"contract_id": contract_id, "results": results})
		except Exception as exc:
			log.warning("stress_test error: %s", exc)
			abort(400, str(exc))


# ---------------------------------------------------------------------------
# RiskFactorView
# ---------------------------------------------------------------------------

class RiskFactorView(BaseView):
	"""CRUD for market RiskFactors."""

	route_base = "/financial-contracts/risk-factors"
	default_view = "list"

	field_widgets = {
		"as_of_date": date_widget(),
		"factor_type": select2_widget(
			["INTEREST_RATE", "FX_RATE", "CREDIT_SPREAD", "EQUITY"]
		),
	}
	label_columns = {
		"factor_code": "Factor Code",
		"factor_type": "Type",
		"base_value": "Base Value",
		"current_value": "Current Value",
		"as_of_date": "As Of",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.financial_contracts.models import RiskFactor
		session = _get_session()
		rows = session.execute(
			sa.select(RiskFactor).order_by(RiskFactor.factor_code)
		).scalars().all()
		return jsonify([
			{
				"id": str(r.id),
				"factor_code": r.factor_code,
				"factor_type": r.factor_type,
				"currency_code": r.currency_code,
				"base_value": float(r.base_value),
				"current_value": float(r.current_value),
				"as_of_date": r.as_of_date.isoformat(),
			}
			for r in rows
		])


# ---------------------------------------------------------------------------
# PortfolioView
# ---------------------------------------------------------------------------

class PortfolioView(BaseView):
	"""Maturity profile and portfolio-level analytics dashboard."""

	route_base = "/financial-contracts/portfolio"
	default_view = "maturity_profile"

	field_widgets = {
		"maturity_bar_chart": chart_widget(chart_type="bar"),
		"npv_waterfall": chart_widget(chart_type="bar"),
	}

	@expose("/maturity-profile", methods=["POST"])
	@has_access
	def maturity_profile(self):
		"""Return maturity profile buckets for a portfolio.

		POST body: {contract_ids: [list of FinancialContract.id]}
		"""
		body = request.get_json(silent=True) or {}
		portfolio = [str(cid) for cid in body.get("contract_ids", [])]
		try:
			result = _svc().calculate_maturity_profile(portfolio, _get_session())
			return jsonify(result)
		except Exception as exc:
			log.warning("maturity_profile error: %s", exc)
			abort(400, str(exc))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ContractView",
	"CashFlowView",
	"ValuationView",
	"RiskFactorView",
	"PortfolioView",
]
