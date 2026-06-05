"""
pgappforge/plugins/erp/industry/intl_aid/views.py

Flask views for the International Aid plugin.

Views:
  AidOrganizationView   — CRUD for IATI publishing organisations
  ProjectView           — CRUD + IATI XML export + budget vs disbursed chart
  TransactionView       — Immutable read-only detail (insert via POST)
  ResultsView           — Result indicator CRUD + progress sliders + trend charts
  BeneficiaryCountView  — Beneficiary measurement CRUD
  AidDashboard          — Portfolio dashboard + geographic heatmap

Widget usage:
  CurrencyWidget              — all cent fields
  DatePickerWidget            — start_date, end_date, transaction_date
  DateRangeWidget             — project period
  AdvancedChartsWidget        — budget vs disbursed bar, disbursement trend line
  RangeSliderWidget           — progress toward target (ResultIndicator)
  GeographicHeatmapWidget     — project locations by recipient_country_code
  JSONEditorWidget            — sectors (readonly on detail)
  MapWidget                   — recipient country pin
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	chart_widget,
	currency_widget,
	date_widget,
	date_range_widget,
	heatmap_widget,
	json_widget,
	map_widget,
	progress_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
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
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.intl_aid.services import IntlAidService
	return IntlAidService()


# ---------------------------------------------------------------------------
# AidOrganizationView
# ---------------------------------------------------------------------------

class AidOrganizationView(BaseView):
	"""IATI publishing organisation CRUD.

	GET  /aid/organisations/        — list
	GET  /aid/organisations/<id>    — detail + portfolio summary
	POST /aid/organisations/        — create
	"""

	route_base = "/aid/organisations"
	default_view = "list"

	widgets = {
		"total_disbursements_cents": currency_widget("USD"),
	}

	list_columns = [
		"iati_identifier", "org_type", "total_disbursements_cents", "active_projects",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		org_type = request.args.get("org_type")

		q = sa.select(AidOrganization).order_by(AidOrganization.iati_identifier)
		if tenant_id:
			q = q.where(AidOrganization.tenant_id == tenant_id)
		if org_type:
			q = q.where(AidOrganization.org_type == org_type)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": o.id,
				"iati_identifier": o.iati_identifier,
				"org_type": o.org_type,
				"total_disbursements_cents": o.total_disbursements_cents,
				"active_projects": o.active_projects,
			}
			for o in rows
		])

	@expose("/<string:org_id>")
	@has_access
	def detail(self, org_id: str):
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization
		session = _get_session()
		o = session.get(AidOrganization, org_id)
		if o is None:
			abort(404)
		return jsonify({
			"id": o.id,
			"tenant_id": o.tenant_id,
			"party_id": o.party_id,
			"iati_identifier": o.iati_identifier,
			"org_type": o.org_type,
			"total_disbursements_cents": o.total_disbursements_cents,
			"active_projects": o.active_projects,
			"_widget_hints": AidOrganizationView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "iati_identifier", "org_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		org = AidOrganization(
			tenant_id=data["tenant_id"],
			party_id=data.get("party_id"),
			iati_identifier=data["iati_identifier"],
			org_type=data["org_type"],
		)
		session.add(org)
		session.commit()
		return jsonify({"org_id": org.id, "iati_identifier": org.iati_identifier}), 201


# ---------------------------------------------------------------------------
# ProjectView
# ---------------------------------------------------------------------------

class ProjectView(BaseView):
	"""IATI activity (project) CRUD + IATI XML + budget vs disbursed chart.

	Widgets used:
	  MapWidget           — recipient country pin
	  CurrencyWidget      — total_budget_cents, total_committed_cents, total_disbursed_cents
	  DateRangeWidget     — start_date–end_date
	  AdvancedChartsWidget — budget vs committed vs disbursed bar chart
	  JSONEditorWidget    — sectors (readonly on detail)

	GET  /aid/projects/                  — list
	GET  /aid/projects/<id>              — detail
	POST /aid/projects/                  — create project with initial commitments
	GET  /aid/projects/<id>/iati-xml     — IATI Activity Standard 2.03 XML
	POST /aid/projects/<id>/disburse     — record disbursement
	GET  /aid/projects/<id>/budget-chart — chart data
	"""

	route_base = "/aid/projects"
	default_view = "list"

	widgets = {
		"recipient_country": map_widget(zoom=5),
		"total_budget_cents": currency_widget("USD"),
		"total_committed_cents": currency_widget("USD"),
		"total_disbursed_cents": currency_widget("USD"),
		"project_period": date_range_widget(),
		"sectors": json_widget(mode="view", readonly=True),
		"budget_chart": {
			**chart_widget("bar"),
			"label": "Budget vs Committed vs Disbursed",
			"data_endpoint": "/aid/projects/{id}/budget-chart",
		},
	}

	list_columns = [
		"iati_identifier", "title", "recipient_country_code",
		"total_budget_cents", "total_disbursed_cents", "status",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		country = request.args.get("country")
		org_id = request.args.get("implementing_org_id")

		q = sa.select(AidProject).order_by(AidProject.iati_identifier).limit(500)
		if tenant_id:
			q = q.where(AidProject.tenant_id == tenant_id)
		if status:
			q = q.where(AidProject.status == status)
		if country:
			q = q.where(AidProject.recipient_country_code == country)
		if org_id:
			q = q.where(AidProject.implementing_org_id == org_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"iati_identifier": p.iati_identifier,
				"title": p.title,
				"implementing_org_id": p.implementing_org_id,
				"funding_org_id": p.funding_org_id,
				"recipient_country_code": p.recipient_country_code,
				"total_budget_cents": p.total_budget_cents,
				"total_committed_cents": p.total_committed_cents,
				"total_disbursed_cents": p.total_disbursed_cents,
				"start_date": p.start_date.isoformat() if p.start_date else None,
				"end_date": p.end_date.isoformat() if p.end_date else None,
				"status": p.status,
				"humanitarian": p.humanitarian,
			}
			for p in rows
		])

	@expose("/<string:project_id>")
	@has_access
	def detail(self, project_id: str):
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject
		session = _get_session()
		p = session.get(AidProject, project_id)
		if p is None:
			abort(404)
		disbursement_rate = (
			round(p.total_disbursed_cents / max(p.total_committed_cents, 1) * 100, 1)
			if p.total_committed_cents
			else 0.0
		)
		return jsonify({
			"id": p.id,
			"tenant_id": p.tenant_id,
			"iati_identifier": p.iati_identifier,
			"title": p.title,
			"description": p.description,
			"implementing_org_id": p.implementing_org_id,
			"funding_org_id": p.funding_org_id,
			"recipient_country_code": p.recipient_country_code,
			"recipient_region": p.recipient_region,
			"sectors": p.sectors,
			"sdg_targets": p.sdg_targets,
			"start_date": p.start_date.isoformat() if p.start_date else None,
			"end_date": p.end_date.isoformat() if p.end_date else None,
			"status": p.status,
			"total_budget_cents": p.total_budget_cents,
			"total_committed_cents": p.total_committed_cents,
			"total_disbursed_cents": p.total_disbursed_cents,
			"disbursement_rate_pct": disbursement_rate,
			"humanitarian": p.humanitarian,
			"tied_status": p.tied_status,
			"_widget_hints": ProjectView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Create an AidProject with initial funding commitments."""
		from datetime import date
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "iati_identifier", "title",
			"implementing_org_id", "funding_org_id",
			"recipient_country_code", "total_budget_cents",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		try:
			start = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
			end = date.fromisoformat(data["end_date"]) if data.get("end_date") else None
			project = _svc().create_project(
				tenant_id=data["tenant_id"],
				iati_identifier=data["iati_identifier"],
				title=data["title"],
				implementing_org_id=data["implementing_org_id"],
				funding_org_id=data["funding_org_id"],
				recipient_country_code=data["recipient_country_code"],
				total_budget_cents=int(data["total_budget_cents"]),
				funding_commitments=data.get("funding_commitments", []),
				description=data.get("description"),
				recipient_region=data.get("recipient_region"),
				sectors=data.get("sectors", []),
				sdg_targets=data.get("sdg_targets", []),
				start_date=start,
				end_date=end,
				humanitarian=data.get("humanitarian", False),
				tied_status=data.get("tied_status", "FREE"),
				session=session,
			)
			session.commit()
			return jsonify({
				"project_id": project.id,
				"iati_identifier": project.iati_identifier,
				"status": project.status,
				"total_committed_cents": project.total_committed_cents,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:project_id>/iati-xml")
	@has_access
	def iati_xml(self, project_id: str):
		"""Return IATI Activity Standard 2.03 XML."""
		from flask import Response
		session = _get_session()
		try:
			xml_str = _svc().generate_iati_xml(project_id, session)
			return Response(xml_str, mimetype="application/xml")
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:project_id>/disburse", methods=["POST"])
	@has_access
	def disburse(self, project_id: str):
		"""Record a disbursement transaction against this project."""
		from datetime import date
		from decimal import Decimal
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("amount_cents", "currency_code", "receiver_id")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			txn = _svc().record_disbursement(
				project_id=project_id,
				amount_cents=int(data["amount_cents"]),
				currency_code=data["currency_code"],
				receiver_id=data["receiver_id"],
				provider_id=data.get("provider_id"),
				transaction_date=date.fromisoformat(data["transaction_date"]) if data.get("transaction_date") else None,
				exchange_rate=Decimal(str(data.get("exchange_rate", 1))),
				description=data.get("description"),
				reference=data.get("reference"),
				session=session,
			)
			session.commit()
			return jsonify({
				"transaction_id": txn.id,
				"project_id": project_id,
				"amount_cents": txn.value_cents,
				"usd_value_cents": txn.usd_value_cents,
				"transaction_type": "DISBURSEMENT",
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:project_id>/budget-chart")
	@has_access
	def budget_chart(self, project_id: str):
		"""Budget vs committed vs disbursed bar chart data."""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject
		session = _get_session()
		p = session.get(AidProject, project_id)
		if p is None:
			abort(404)
		return jsonify({
			"chart_type": "bar",
			"title": "Budget vs Committed vs Disbursed",
			"labels": ["Budget", "Committed", "Disbursed"],
			"data": [
				p.total_budget_cents,
				p.total_committed_cents,
				p.total_disbursed_cents,
			],
			"disbursement_gap_cents": max(0, p.total_committed_cents - p.total_disbursed_cents),
		})


# ---------------------------------------------------------------------------
# TransactionView — immutable, read-only detail + insert endpoint
# ---------------------------------------------------------------------------

class TransactionView(BaseView):
	"""Read-only view of immutable IATI transaction ledger.

	POST /aid/transactions/                  — record transaction (insert-only)
	GET  /aid/transactions/                  — list (filter by project_id)
	GET  /aid/transactions/<id>              — detail (immutable, no edit)
	"""

	route_base = "/aid/transactions"
	default_view = "list"

	widgets = {
		"value_cents": currency_widget("USD"),
		"usd_value_cents": currency_widget("USD"),
		"transaction_date": date_widget("YYYY-MM-DD"),
	}

	list_columns = [
		"project_id", "transaction_type", "transaction_date",
		"value_cents", "currency_code", "usd_value_cents",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import ProjectTransaction
		session = _get_session()
		project_id = request.args.get("project_id")
		txn_type = request.args.get("transaction_type")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(ProjectTransaction)
			.order_by(ProjectTransaction.transaction_date.desc())
			.limit(500)
		)
		if project_id:
			q = q.where(ProjectTransaction.project_id == project_id)
		if txn_type:
			q = q.where(ProjectTransaction.transaction_type == txn_type)
		if tenant_id:
			q = q.where(ProjectTransaction.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": t.id,
				"project_id": t.project_id,
				"transaction_type": t.transaction_type,
				"transaction_date": t.transaction_date.isoformat(),
				"value_cents": t.value_cents,
				"currency_code": t.currency_code,
				"usd_value_cents": t.usd_value_cents,
				"provider_id": t.provider_id,
				"receiver_id": t.receiver_id,
				"reference": t.reference,
			}
			for t in rows
		])

	@expose("/<string:txn_id>")
	@has_access
	def detail(self, txn_id: str):
		from pgappforge.plugins.erp.industry.intl_aid.models import ProjectTransaction
		session = _get_session()
		t = session.get(ProjectTransaction, txn_id)
		if t is None:
			abort(404)
		return jsonify({
			"id": t.id,
			"tenant_id": t.tenant_id,
			"project_id": t.project_id,
			"transaction_type": t.transaction_type,
			"transaction_date": t.transaction_date.isoformat(),
			"value_cents": t.value_cents,
			"currency_code": t.currency_code,
			"exchange_rate": str(t.exchange_rate),
			"usd_value_cents": t.usd_value_cents,
			"provider_id": t.provider_id,
			"receiver_id": t.receiver_id,
			"description": t.description,
			"reference": t.reference,
			"_immutable": True,
			"_widget_hints": TransactionView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record an immutable IATI transaction (non-disbursement types)."""
		from datetime import date
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject, ProjectTransaction
		from pgappforge.plugins.erp.industry.intl_aid.events import CommitmentRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "project_id", "transaction_type",
			"transaction_date", "value_cents", "currency_code",
			"provider_id", "receiver_id",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		valid_types = {"COMMITMENT", "DISBURSEMENT", "EXPENDITURE", "REPAYMENT"}
		if data["transaction_type"] not in valid_types:
			return jsonify({"error": f"transaction_type must be one of {sorted(valid_types)}"}), 400

		project = session.get(AidProject, data["project_id"])
		if project is None:
			return jsonify({"error": f"AidProject {data['project_id']!r} not found"}), 404

		rate = Decimal(str(data.get("exchange_rate", 1)))
		amt = int(data["value_cents"])
		usd_cents = int((Decimal(str(amt)) * rate).to_integral_value())
		txn_date = date.fromisoformat(data["transaction_date"])

		txn = ProjectTransaction(
			tenant_id=data["tenant_id"],
			project_id=data["project_id"],
			transaction_type=data["transaction_type"],
			transaction_date=txn_date,
			value_cents=amt,
			currency_code=data["currency_code"],
			exchange_rate=rate,
			usd_value_cents=usd_cents,
			provider_id=data["provider_id"],
			receiver_id=data["receiver_id"],
			description=data.get("description"),
			reference=data.get("reference"),
		)
		session.add(txn)
		session.flush()

		# Update project aggregate
		if data["transaction_type"] == "COMMITMENT":
			project.total_committed_cents = (project.total_committed_cents or 0) + amt
			emit_event(
				CommitmentRecordedEvent(
					aggregate_id=txn.id,
					aggregate_type="ProjectTransaction",
					tenant_id=data["tenant_id"],
					transaction_id=txn.id,
					project_id=data["project_id"],
					amount_cents=amt,
					currency_code=data["currency_code"],
					provider_id=data["provider_id"],
					transaction_date=txn_date.isoformat(),
				),
				session,
			)
		elif data["transaction_type"] == "DISBURSEMENT":
			project.total_disbursed_cents = (project.total_disbursed_cents or 0) + amt

		session.commit()
		return jsonify({
			"transaction_id": txn.id,
			"transaction_type": txn.transaction_type,
			"value_cents": txn.value_cents,
			"usd_value_cents": txn.usd_value_cents,
			"_immutable": True,
		}), 201


# ---------------------------------------------------------------------------
# ResultsView
# ---------------------------------------------------------------------------

class ResultsView(BaseView):
	"""Result indicator CRUD + progress sliders + trend charts.

	Widgets used:
	  RangeSliderWidget    — progress toward target (0–100%)
	  AdvancedChartsWidget — indicator progress trend (line)

	GET  /aid/results/                     — list
	GET  /aid/results/<id>                 — detail with progress
	POST /aid/results/                     — create indicator
	POST /aid/results/update               — batch update current values
	GET  /aid/results/<id>/trend           — trend chart data
	"""

	route_base = "/aid/results"
	default_view = "list"

	widgets = {
		"progress_pct": {
			**progress_widget(max_value=100),
			"label": "Progress toward Target",
		},
		"indicator_trend": {
			**chart_widget("line"),
			"label": "Indicator Progress Trend",
			"data_endpoint": "/aid/results/{id}/trend",
		},
	}

	list_columns = [
		"project_id", "indicator_name", "indicator_type",
		"target_value", "current_value", "last_updated",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import ResultIndicator
		session = _get_session()
		project_id = request.args.get("project_id")
		ind_type = request.args.get("indicator_type")
		tenant_id = request.args.get("tenant_id")

		q = sa.select(ResultIndicator).order_by(ResultIndicator.indicator_name).limit(500)
		if project_id:
			q = q.where(ResultIndicator.project_id == project_id)
		if ind_type:
			q = q.where(ResultIndicator.indicator_type == ind_type)
		if tenant_id:
			q = q.where(ResultIndicator.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": i.id,
				"project_id": i.project_id,
				"indicator_name": i.indicator_name,
				"indicator_type": i.indicator_type,
				"unit_of_measure": i.unit_of_measure,
				"target_value": str(i.target_value),
				"current_value": str(i.current_value),
				"target_year": i.target_year,
				"last_updated": i.last_updated.isoformat() if i.last_updated else None,
				"progress_pct": min(
					100.0,
					round(float(i.current_value) / max(float(i.target_value), 0.0001) * 100, 1),
				),
				"on_track": i.current_value >= i.target_value,
			}
			for i in rows
		])

	@expose("/<string:indicator_id>")
	@has_access
	def detail(self, indicator_id: str):
		from pgappforge.plugins.erp.industry.intl_aid.models import ResultIndicator
		session = _get_session()
		i = session.get(ResultIndicator, indicator_id)
		if i is None:
			abort(404)
		progress_pct = min(
			100.0,
			round(float(i.current_value) / max(float(i.target_value), 0.0001) * 100, 1),
		)
		return jsonify({
			"id": i.id,
			"tenant_id": i.tenant_id,
			"project_id": i.project_id,
			"indicator_name": i.indicator_name,
			"indicator_type": i.indicator_type,
			"unit_of_measure": i.unit_of_measure,
			"baseline_value": str(i.baseline_value),
			"baseline_year": i.baseline_year,
			"target_value": str(i.target_value),
			"target_year": i.target_year,
			"current_value": str(i.current_value),
			"last_updated": i.last_updated.isoformat() if i.last_updated else None,
			"progress_pct": progress_pct,
			"on_track": i.current_value >= i.target_value,
			"_widget_hints": ResultsView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Create a result indicator for a project."""
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.intl_aid.models import ResultIndicator
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "project_id", "indicator_name",
			"indicator_type", "baseline_value", "baseline_year",
			"target_value", "target_year",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		ind = ResultIndicator(
			tenant_id=data["tenant_id"],
			project_id=data["project_id"],
			indicator_name=data["indicator_name"],
			indicator_type=data["indicator_type"],
			unit_of_measure=data.get("unit_of_measure"),
			baseline_value=Decimal(str(data["baseline_value"])),
			baseline_year=int(data["baseline_year"]),
			target_value=Decimal(str(data["target_value"])),
			target_year=int(data["target_year"]),
			current_value=Decimal(str(data.get("current_value", 0))),
		)
		session.add(ind)
		session.commit()
		return jsonify({
			"indicator_id": ind.id,
			"indicator_name": ind.indicator_name,
			"indicator_type": ind.indicator_type,
		}), 201

	@expose("/update", methods=["POST"])
	@has_access
	def batch_update(self):
		"""Batch-update current values for a project's result indicators."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("project_id", "indicator_updates")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			updated = _svc().update_results(
				project_id=data["project_id"],
				indicator_updates=data["indicator_updates"],
				session=session,
			)
			session.commit()
			return jsonify({
				"project_id": data["project_id"],
				"updated_count": len(updated),
				"indicator_ids": [i.id for i in updated],
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:indicator_id>/trend")
	@has_access
	def trend(self, indicator_id: str):
		"""Trend chart data for AdvancedChartsWidget (line chart).

		Returns time-series of current_value snapshots for this indicator.
		Since ResultIndicator stores only the latest value, the trend data
		is synthesised from the baseline, and current value with last_updated.
		For richer time-series, add a ResultIndicatorHistory model.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import ResultIndicator
		session = _get_session()
		i = session.get(ResultIndicator, indicator_id)
		if i is None:
			abort(404)

		data_points = [
			{"x": f"{i.baseline_year}-01-01", "y": float(i.baseline_value), "label": "Baseline"},
		]
		if i.last_updated:
			data_points.append({
				"x": i.last_updated.isoformat(),
				"y": float(i.current_value),
				"label": "Current",
			})
		data_points.append({
			"x": f"{i.target_year}-12-31",
			"y": float(i.target_value),
			"label": "Target",
		})

		return jsonify({
			"chart_type": "line",
			"indicator_name": i.indicator_name,
			"unit_of_measure": i.unit_of_measure,
			"data": data_points,
		})


# ---------------------------------------------------------------------------
# BeneficiaryCountView
# ---------------------------------------------------------------------------

class BeneficiaryCountView(BaseView):
	"""Beneficiary count CRUD.

	GET  /aid/beneficiaries/              — list (filter by project_id)
	GET  /aid/beneficiaries/<id>          — detail
	POST /aid/beneficiaries/              — record count
	"""

	route_base = "/aid/beneficiaries"
	default_view = "list"

	widgets = {
		"measurement_date": date_widget("YYYY-MM-DD"),
	}

	list_columns = [
		"project_id", "measurement_date", "total_beneficiaries",
		"female_beneficiaries", "male_beneficiaries",
	]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.intl_aid.models import BeneficiaryCount
		session = _get_session()
		project_id = request.args.get("project_id")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(BeneficiaryCount)
			.order_by(BeneficiaryCount.measurement_date.desc())
			.limit(500)
		)
		if project_id:
			q = q.where(BeneficiaryCount.project_id == project_id)
		if tenant_id:
			q = q.where(BeneficiaryCount.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": b.id,
				"project_id": b.project_id,
				"measurement_date": b.measurement_date.isoformat(),
				"total_beneficiaries": b.total_beneficiaries,
				"female_beneficiaries": b.female_beneficiaries,
				"male_beneficiaries": b.male_beneficiaries,
				"children_beneficiaries": b.children_beneficiaries,
				"location_detail": b.location_detail,
			}
			for b in rows
		])

	@expose("/<string:count_id>")
	@has_access
	def detail(self, count_id: str):
		from pgappforge.plugins.erp.industry.intl_aid.models import BeneficiaryCount
		session = _get_session()
		b = session.get(BeneficiaryCount, count_id)
		if b is None:
			abort(404)
		return jsonify({
			"id": b.id,
			"tenant_id": b.tenant_id,
			"project_id": b.project_id,
			"measurement_date": b.measurement_date.isoformat(),
			"total_beneficiaries": b.total_beneficiaries,
			"female_beneficiaries": b.female_beneficiaries,
			"male_beneficiaries": b.male_beneficiaries,
			"children_beneficiaries": b.children_beneficiaries,
			"location_detail": b.location_detail,
			"_widget_hints": BeneficiaryCountView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from datetime import date
		from pgappforge.plugins.erp.industry.intl_aid.models import BeneficiaryCount
		from pgappforge.plugins.erp.industry.intl_aid.events import BeneficiariesCountedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "project_id", "measurement_date", "total_beneficiaries")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		mdate = date.fromisoformat(data["measurement_date"])
		b = BeneficiaryCount(
			tenant_id=data["tenant_id"],
			project_id=data["project_id"],
			measurement_date=mdate,
			total_beneficiaries=int(data["total_beneficiaries"]),
			female_beneficiaries=data.get("female_beneficiaries"),
			male_beneficiaries=data.get("male_beneficiaries"),
			children_beneficiaries=data.get("children_beneficiaries"),
			location_detail=data.get("location_detail"),
		)
		session.add(b)
		session.flush()

		emit_event(
			BeneficiariesCountedEvent(
				aggregate_id=b.id,
				aggregate_type="BeneficiaryCount",
				tenant_id=data["tenant_id"],
				count_id=b.id,
				project_id=data["project_id"],
				measurement_date=mdate.isoformat(),
				total_beneficiaries=b.total_beneficiaries,
			),
			session,
		)
		session.commit()
		return jsonify({
			"count_id": b.id,
			"total_beneficiaries": b.total_beneficiaries,
			"measurement_date": mdate.isoformat(),
		}), 201


# ---------------------------------------------------------------------------
# AidDashboard
# ---------------------------------------------------------------------------

class AidDashboard(BaseView):
	"""Portfolio dashboard + geographic heatmap for aid organisations.

	Widgets used:
	  GeographicHeatmapWidget — project density by recipient country
	  AdvancedChartsWidget    — disbursement rate bar per org

	GET /aid/dashboard/<org_id>              — full portfolio dashboard
	GET /aid/dashboard/<org_id>/heatmap      — heatmap data for GeographicHeatmapWidget
	GET /aid/dashboard/<org_id>/effectiveness — aid effectiveness over 5 years
	"""

	route_base = "/aid/dashboard"
	default_view = "index"

	widgets = {
		"project_heatmap": {
			**heatmap_widget(),
			"label": "Project Geographic Distribution",
			"data_endpoint": "/aid/dashboard/{org_id}/heatmap",
		},
		"disbursement_chart": {
			**chart_widget("bar"),
			"label": "Budget vs Disbursed by Project",
			"data_endpoint": "/aid/dashboard/{org_id}",
		},
	}

	@expose("/<string:org_id>")
	@has_access
	def index(self, org_id: str):
		"""Full portfolio KPI dashboard."""
		session = _get_session()
		try:
			result = _svc().get_portfolio_dashboard(org_id, session)
			result["_widget_hints"] = AidDashboard.widgets
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:org_id>/heatmap")
	@has_access
	def heatmap(self, org_id: str):
		"""Geographic heatmap data — project count by recipient country."""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject
		session = _get_session()

		rows = session.execute(
			sa.select(
				AidProject.recipient_country_code,
				sa.func.count(AidProject.id).label("project_count"),
				sa.func.sum(AidProject.total_budget_cents).label("total_budget"),
			)
			.where(AidProject.implementing_org_id == org_id)
			.group_by(AidProject.recipient_country_code)
		).all()

		# GeographicHeatmapWidget expects [{lat, lng, weight}] or [{country_code, weight}]
		heatmap_data = [
			{
				"country_code": r.recipient_country_code,
				"weight": r.project_count,
				"project_count": r.project_count,
				"total_budget_cents": r.total_budget or 0,
			}
			for r in rows
		]

		return jsonify({
			"type": "heatmap",
			"org_id": org_id,
			"data": heatmap_data,
		})

	@expose("/<string:org_id>/effectiveness")
	@has_access
	def effectiveness(self, org_id: str):
		"""Aid effectiveness metrics over configurable period."""
		session = _get_session()
		period_years = int(request.args.get("period_years", 5))
		try:
			result = _svc().calculate_aid_effectiveness(
				org_id=org_id,
				period_years=period_years,
				session=session,
			)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


__all__ = [
	"AidOrganizationView",
	"ProjectView",
	"TransactionView",
	"ResultsView",
	"BeneficiaryCountView",
	"AidDashboard",
]
