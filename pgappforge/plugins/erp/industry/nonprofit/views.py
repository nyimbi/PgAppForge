"""
pgappforge/plugins/erp/industry/nonprofit/views.py

Flask views for the Nonprofit Cloud plugin.

Views:
  DonorView                 — CRUD + generate receipt + score prospect + pledge
  DonationView              — CRUD + generate receipt action
  ProgramView               — CRUD with theory-of-change rich text
  ImpactMeasurementView     — CRUD with progress slider
  GrantView                 — CRUD with conditions rich text
  DonorProspectDashboardView — major gift scoring with pipeline chart
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

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
	from pgappforge.plugins.erp.industry.nonprofit.services import NonprofitService
	return NonprofitService()


# ---------------------------------------------------------------------------
# DonorView
# ---------------------------------------------------------------------------

class DonorView(BaseView):
	"""Donor CRUD with fundraising actions.

	List columns : name (via party_id), giving_level, lifetime_giving,
	               last_gift_date, status
	Widgets used  : CurrencyWidget (lifetime_giving, largest_gift),
	                StarRatingWidget (giving_level: SMALL=1, MID=3, MAJOR=5),
	                DatePickerWidget (last_gift_date, first_gift_date)
	Actions       : Generate Receipt (last donation), Score Prospect, Pledge

	GET  /nonprofit/donors/                          — list
	GET  /nonprofit/donors/<id>                      — detail
	POST /nonprofit/donors/                          — create
	GET  /nonprofit/donors/<id>/score                — prospect score
	POST /nonprofit/donors/<id>/pledge               — create pledge
	"""

	route_base = "/nonprofit/donors"
	default_view = "list"

	widgets = {
		"lifetime_giving_cents": {
			"widget": "CurrencyWidget",
			"label": "Lifetime Giving",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"largest_gift_cents": {
			"widget": "CurrencyWidget",
			"label": "Largest Gift",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"giving_level": {
			"widget": "StarRatingWidget",
			"label": "Giving Level",
			"max_stars": 5,
			"level_map": {"SMALL": 1, "MID": 3, "MAJOR": 5},
			"readonly": True,
		},
		"last_gift_date": {
			"widget": "DatePickerWidget",
			"label": "Last Gift Date",
			"format": "YYYY-MM-DD",
		},
		"first_gift_date": {
			"widget": "DatePickerWidget",
			"label": "First Gift Date",
			"format": "YYYY-MM-DD",
		},
	}

	list_columns = ["donor_number", "giving_level", "lifetime_giving_cents", "last_gift_date", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Donor
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		giving_level = request.args.get("giving_level")
		status = request.args.get("status", "ACTIVE")

		q = sa.select(Donor).order_by(Donor.donor_number)
		if tenant_id:
			q = q.where(Donor.tenant_id == tenant_id)
		if giving_level:
			q = q.where(Donor.giving_level == giving_level)
		if status:
			q = q.where(Donor.status == status)

		donors = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"donor_number": d.donor_number,
				"giving_level": d.giving_level,
				"lifetime_giving_cents": d.lifetime_giving_cents,
				"largest_gift_cents": d.largest_gift_cents,
				"gift_count": d.gift_count,
				"last_gift_date": d.last_gift_date.isoformat() if d.last_gift_date else None,
				"first_gift_date": d.first_gift_date.isoformat() if d.first_gift_date else None,
				"status": d.status,
				"do_not_contact": d.do_not_contact,
				"preferred_cause": d.preferred_cause,
			}
			for d in donors
		])

	@expose("/<string:donor_id>")
	@has_access
	def detail(self, donor_id: str):
		from pgappforge.plugins.erp.industry.nonprofit.models import Donor
		session = _get_session()
		donor = session.get(Donor, donor_id)
		if donor is None:
			abort(404)
		return jsonify({
			"id": donor.id,
			"tenant_id": donor.tenant_id,
			"party_id": donor.party_id,
			"donor_number": donor.donor_number,
			"giving_level": donor.giving_level,
			"lifetime_giving_cents": donor.lifetime_giving_cents,
			"largest_gift_cents": donor.largest_gift_cents,
			"gift_count": donor.gift_count,
			"last_gift_date": donor.last_gift_date.isoformat() if donor.last_gift_date else None,
			"first_gift_date": donor.first_gift_date.isoformat() if donor.first_gift_date else None,
			"preferred_cause": donor.preferred_cause,
			"preferred_payment_method": donor.preferred_payment_method,
			"is_anonymous": donor.is_anonymous,
			"do_not_contact": donor.do_not_contact,
			"communication_preferences": donor.communication_preferences,
			"assigned_relationship_manager_id": donor.assigned_relationship_manager_id,
			"notes": donor.notes,
			"status": donor.status,
			"_widget_hints": DonorView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Donor
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "donor_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		donor = Donor(
			tenant_id=data["tenant_id"],
			donor_number=data["donor_number"],
			party_id=data.get("party_id"),
			giving_level=data.get("giving_level", "SMALL"),
			preferred_cause=data.get("preferred_cause"),
			preferred_payment_method=data.get("preferred_payment_method"),
			is_anonymous=data.get("is_anonymous", False),
			do_not_contact=data.get("do_not_contact", False),
			assigned_relationship_manager_id=data.get("assigned_relationship_manager_id"),
			notes=data.get("notes"),
			status=data.get("status", "ACTIVE"),
		)
		session.add(donor)
		session.commit()
		log.info("DonorView.create: %r", donor.donor_number)
		return jsonify({"donor_id": donor.id, "donor_number": donor.donor_number}), 201

	@expose("/<string:donor_id>/score")
	@has_access
	def score(self, donor_id: str):
		"""Return major-gift prospect score for a single donor."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.nonprofit.models import Donor
		donor = session.get(Donor, donor_id)
		if donor is None:
			abort(404)
		try:
			all_scores = _svc().score_major_gift_prospects(
				tenant_id=donor.tenant_id,
				session=session,
			)
			donor_score = next((s for s in all_scores if s["donor_id"] == donor_id), None)
			if donor_score is None:
				return jsonify({"donor_id": donor_id, "total_score": 0.0, "is_major_prospect": False})
			return jsonify(donor_score)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:donor_id>/pledge", methods=["POST"])
	@has_access
	def pledge(self, donor_id: str):
		"""Create a multi-installment pledge for a donor."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "total_amount_cents", "installments", "start_date")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			start_date = date.fromisoformat(data["start_date"])
			result = _svc().create_pledge(
				tenant_id=data["tenant_id"],
				donor_id=donor_id,
				total_amount_cents=int(data["total_amount_cents"]),
				installments=int(data["installments"]),
				start_date=start_date,
				campaign_id=data.get("campaign_id"),
				designation=data.get("designation"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# DonationView
# ---------------------------------------------------------------------------

class DonationView(BaseView):
	"""Donation CRUD + receipt generation.

	Widgets used : CurrencyWidget (amount_cents),
	               DatePickerWidget (donated_at)
	Actions      : Generate Receipt

	GET  /nonprofit/donations/                    — list
	GET  /nonprofit/donations/<id>               — detail
	POST /nonprofit/donations/                    — record donation
	POST /nonprofit/donations/<id>/receipt        — generate tax receipt
	"""

	route_base = "/nonprofit/donations"
	default_view = "list"

	widgets = {
		"amount_cents": {
			"widget": "CurrencyWidget",
			"label": "Amount",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"donated_at": {
			"widget": "DatePickerWidget",
			"label": "Donation Date",
			"format": "YYYY-MM-DD",
			"include_time": True,
		},
	}

	list_columns = ["donor_id", "campaign_name", "amount_cents", "payment_method", "donated_at", "acknowledged_at", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		donor_id = request.args.get("donor_id")
		status = request.args.get("status")

		q = (
			sa.select(Donation)
			.order_by(Donation.donated_at.desc())
			.limit(500)
		)
		if tenant_id:
			q = q.where(Donation.tenant_id == tenant_id)
		if donor_id:
			q = q.where(Donation.donor_id == donor_id)
		if status:
			q = q.where(Donation.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"donor_id": d.donor_id,
				"campaign_id": d.campaign_id,
				"campaign_name": d.campaign_name,
				"donated_at": d.donated_at.isoformat() if d.donated_at else None,
				"amount_cents": d.amount_cents,
				"currency_code": d.currency_code,
				"payment_method": d.payment_method,
				"designation": d.designation,
				"is_recurring": d.is_recurring,
				"acknowledged_at": d.acknowledged_at.isoformat() if d.acknowledged_at else None,
				"tax_receipt_number": d.tax_receipt_number,
				"status": d.status,
			}
			for d in rows
		])

	@expose("/<string:donation_id>")
	@has_access
	def detail(self, donation_id: str):
		from pgappforge.plugins.erp.industry.nonprofit.models import Donation
		session = _get_session()
		d = session.get(Donation, donation_id)
		if d is None:
			abort(404)
		return jsonify({
			"id": d.id,
			"tenant_id": d.tenant_id,
			"donor_id": d.donor_id,
			"campaign_id": d.campaign_id,
			"campaign_name": d.campaign_name,
			"donated_at": d.donated_at.isoformat() if d.donated_at else None,
			"amount_cents": d.amount_cents,
			"currency_code": d.currency_code,
			"exchange_rate": str(d.exchange_rate),
			"functional_amount_cents": d.functional_amount_cents,
			"payment_method": d.payment_method,
			"payment_reference": d.payment_reference,
			"designation": d.designation,
			"is_restricted": d.is_restricted,
			"is_recurring": d.is_recurring,
			"recurring_frequency": d.recurring_frequency,
			"acknowledged_at": d.acknowledged_at.isoformat() if d.acknowledged_at else None,
			"tax_receipt_number": d.tax_receipt_number,
			"tax_receipt_url": d.tax_receipt_url,
			"status": d.status,
			"notes": d.notes,
			"_widget_hints": DonationView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record a donation and update donor aggregate fields."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "donor_id", "amount_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			donation = _svc().process_donation(
				tenant_id=data["tenant_id"],
				donor_id=data["donor_id"],
				amount_cents=int(data["amount_cents"]),
				campaign_id=data.get("campaign_id"),
				campaign_name=data.get("campaign_name"),
				designation=data.get("designation"),
				payment_method=data.get("payment_method"),
				payment_reference=data.get("payment_reference"),
				currency_code=data.get("currency_code", "USD"),
				is_recurring=data.get("is_recurring", False),
				recurring_frequency=data.get("recurring_frequency"),
				is_restricted=data.get("is_restricted", False),
				session=session,
			)
			session.commit()
			return jsonify({
				"donation_id": donation.id,
				"donor_id": data["donor_id"],
				"amount_cents": donation.amount_cents,
				"status": donation.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:donation_id>/receipt", methods=["POST"])
	@has_access
	def generate_receipt(self, donation_id: str):
		"""Generate and store a tax receipt for the donation."""
		session = _get_session()
		try:
			receipt_url = _svc().generate_tax_receipt(donation_id, session)
			session.commit()
			return jsonify({
				"donation_id": donation_id,
				"tax_receipt_url": receipt_url,
				"status": "ACKNOWLEDGED",
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ProgramView
# ---------------------------------------------------------------------------

class ProgramView(BaseView):
	"""Nonprofit program CRUD.

	Widgets used : CurrencyWidget (budget_cents, spent_cents),
	               DateRangeWidget (start_date–end_date),
	               RichTextEditorWidget (theory_of_change)

	GET  /nonprofit/programs/           — list
	GET  /nonprofit/programs/<id>       — detail + impact summary
	POST /nonprofit/programs/           — create
	GET  /nonprofit/programs/<id>/impact — impact calculation
	"""

	route_base = "/nonprofit/programs"
	default_view = "list"

	widgets = {
		"budget_cents": {
			"widget": "CurrencyWidget",
			"label": "Budget",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"spent_cents": {
			"widget": "CurrencyWidget",
			"label": "Spent",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"program_period": {
			"widget": "DateRangeWidget",
			"label": "Program Period",
			"start_field": "start_date",
			"end_field": "end_date",
			"format": "YYYY-MM-DD",
		},
		"theory_of_change": {
			"widget": "RichTextEditorWidget",
			"label": "Theory of Change",
			"toolbar": ["bold", "italic", "ul", "ol", "link", "h2", "h3"],
		},
	}

	list_columns = ["program_code", "program_name", "budget_cents", "start_date", "end_date", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = sa.select(Program).order_by(Program.program_code)
		if tenant_id:
			q = q.where(Program.tenant_id == tenant_id)
		if status:
			q = q.where(Program.status == status)

		programs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"program_code": p.program_code,
				"program_name": p.program_name,
				"budget_cents": p.budget_cents,
				"spent_cents": p.spent_cents,
				"start_date": p.start_date.isoformat() if p.start_date else None,
				"end_date": p.end_date.isoformat() if p.end_date else None,
				"target_beneficiaries": p.target_beneficiaries,
				"actual_beneficiaries": p.actual_beneficiaries,
				"status": p.status,
			}
			for p in programs
		])

	@expose("/<string:program_id>")
	@has_access
	def detail(self, program_id: str):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		p = session.get(Program, program_id)
		if p is None:
			abort(404)
		return jsonify({
			"id": p.id,
			"tenant_id": p.tenant_id,
			"program_code": p.program_code,
			"program_name": p.program_name,
			"description": p.description,
			"theory_of_change": p.theory_of_change,
			"program_manager_id": p.program_manager_id,
			"budget_cents": p.budget_cents,
			"spent_cents": p.spent_cents,
			"currency_code": p.currency_code,
			"start_date": p.start_date.isoformat() if p.start_date else None,
			"end_date": p.end_date.isoformat() if p.end_date else None,
			"geographic_focus": p.geographic_focus,
			"target_beneficiaries": p.target_beneficiaries,
			"actual_beneficiaries": p.actual_beneficiaries,
			"outcomes_tracked": p.outcomes_tracked,
			"status": p.status,
			"notes": p.notes,
			"_widget_hints": ProgramView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "program_code", "program_name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		program = Program(
			tenant_id=data["tenant_id"],
			program_code=data["program_code"],
			program_name=data["program_name"],
			description=data.get("description"),
			theory_of_change=data.get("theory_of_change"),
			program_manager_id=data.get("program_manager_id"),
			budget_cents=int(data.get("budget_cents", 0)),
			currency_code=data.get("currency_code", "USD"),
			start_date=data.get("start_date"),
			end_date=data.get("end_date"),
			target_beneficiaries=data.get("target_beneficiaries"),
			outcomes_tracked=data.get("outcomes_tracked", []),
			status=data.get("status", "ACTIVE"),
		)
		session.add(program)
		session.commit()
		return jsonify({"program_id": program.id, "program_code": program.program_code}), 201

	@expose("/<string:program_id>/impact")
	@has_access
	def impact(self, program_id: str):
		"""Return calculated impact summary for a program."""
		session = _get_session()
		try:
			result = _svc().calculate_program_impact(program_id, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# ImpactMeasurementView
# ---------------------------------------------------------------------------

class ImpactMeasurementView(BaseView):
	"""Impact measurement CRUD.

	Widgets used : RangeSliderWidget (progress toward target 0–100%),
	               AdvancedChartsWidget (impact trend in detail view)

	GET  /nonprofit/impact/             — list
	GET  /nonprofit/impact/<id>        — detail with trend chart data
	POST /nonprofit/impact/             — record measurement
	"""

	route_base = "/nonprofit/impact"
	default_view = "list"

	widgets = {
		"progress_pct": {
			"widget": "RangeSliderWidget",
			"label": "Progress toward Target",
			"min": 0,
			"max": 100,
			"step": 0.1,
			"unit": "%",
			"readonly": True,
		},
		"impact_trend": {
			"widget": "AdvancedChartsWidget",
			"chart_type": "line",
			"label": "Impact Trend",
			"x_label": "Measurement Date",
			"y_label": "Actual Value",
			"data_endpoint": "/nonprofit/impact/{id}/trend-data",
		},
	}

	list_columns = ["program_id", "metric_name", "target_value", "actual_value", "measurement_date"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import ImpactMeasurement
		session = _get_session()
		program_id = request.args.get("program_id")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(ImpactMeasurement)
			.order_by(ImpactMeasurement.measurement_date.desc())
			.limit(500)
		)
		if program_id:
			q = q.where(ImpactMeasurement.program_id == program_id)
		if tenant_id:
			q = q.where(ImpactMeasurement.tenant_id == tenant_id)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": m.id,
				"program_id": m.program_id,
				"metric_name": m.metric_name,
				"metric_unit": m.metric_unit,
				"target_value": str(m.target_value),
				"actual_value": str(m.actual_value),
				"measurement_date": m.measurement_date.isoformat(),
				"progress_pct": min(
					100.0,
					round(float(m.actual_value) / max(float(m.target_value), 0.0001) * 100, 1),
				),
				"achieved": m.actual_value >= m.target_value,
			}
			for m in rows
		])

	@expose("/<string:measurement_id>")
	@has_access
	def detail(self, measurement_id: str):
		from pgappforge.plugins.erp.industry.nonprofit.models import ImpactMeasurement
		session = _get_session()
		m = session.get(ImpactMeasurement, measurement_id)
		if m is None:
			abort(404)
		progress_pct = min(
			100.0,
			round(float(m.actual_value) / max(float(m.target_value), 0.0001) * 100, 1),
		)
		return jsonify({
			"id": m.id,
			"tenant_id": m.tenant_id,
			"program_id": m.program_id,
			"metric_name": m.metric_name,
			"metric_unit": m.metric_unit,
			"target_value": str(m.target_value),
			"actual_value": str(m.actual_value),
			"measurement_date": m.measurement_date.isoformat(),
			"progress_pct": progress_pct,
			"achieved": m.actual_value >= m.target_value,
			"evidence_url": m.evidence_url,
			"methodology": m.methodology,
			"verified_by": m.verified_by,
			"notes": m.notes,
			"_widget_hints": ImpactMeasurementView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import ImpactMeasurement
		from pgappforge.plugins.erp.industry.nonprofit.events import ImpactMeasurementRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		from decimal import Decimal

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "program_id", "metric_name", "target_value", "actual_value", "measurement_date")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		m = ImpactMeasurement(
			tenant_id=data["tenant_id"],
			program_id=data["program_id"],
			metric_name=data["metric_name"],
			metric_unit=data.get("metric_unit"),
			target_value=Decimal(str(data["target_value"])),
			actual_value=Decimal(str(data["actual_value"])),
			measurement_date=date.fromisoformat(data["measurement_date"]),
			evidence_url=data.get("evidence_url"),
			methodology=data.get("methodology"),
			verified_by=data.get("verified_by"),
			notes=data.get("notes"),
		)
		session.add(m)
		session.flush()

		emit_event(
			ImpactMeasurementRecordedEvent(
				aggregate_id=m.id,
				aggregate_type="ImpactMeasurement",
				tenant_id=data["tenant_id"],
				measurement_id=m.id,
				program_id=data["program_id"],
				metric_name=data["metric_name"],
				target_value=str(data["target_value"]),
				actual_value=str(data["actual_value"]),
				measurement_date=data["measurement_date"],
			),
			session,
		)
		session.commit()
		return jsonify({
			"measurement_id": m.id,
			"metric_name": m.metric_name,
			"achieved": m.actual_value >= m.target_value,
		}), 201

	@expose("/<string:measurement_id>/trend-data")
	@has_access
	def trend_data(self, measurement_id: str):
		"""Return time-series data for the same metric across all measurements."""
		from pgappforge.plugins.erp.industry.nonprofit.models import ImpactMeasurement
		session = _get_session()
		m = session.get(ImpactMeasurement, measurement_id)
		if m is None:
			abort(404)

		history = session.execute(
			sa.select(ImpactMeasurement)
			.where(
				ImpactMeasurement.program_id == m.program_id,
				ImpactMeasurement.metric_name == m.metric_name,
			)
			.order_by(ImpactMeasurement.measurement_date)
		).scalars().all()

		return jsonify({
			"chart_type": "line",
			"metric_name": m.metric_name,
			"metric_unit": m.metric_unit,
			"data": [
				{
					"x": h.measurement_date.isoformat(),
					"y": float(h.actual_value),
					"target": float(h.target_value),
				}
				for h in history
			],
		})


# ---------------------------------------------------------------------------
# GrantView
# ---------------------------------------------------------------------------

class GrantView(BaseView):
	"""Grant tracking CRUD.

	Note: A full Grant model is pending addition to nonprofit/models.py.
	This view provides a lightweight grant-as-program wrapper until then.
	Grants are tracked as Program rows with program_code prefixed "GR-".

	Widgets used : CurrencyWidget (budget_cents as grant amount),
	               DatePickerWidget (start_date as award_date, end_date as close_date),
	               RichTextEditorWidget (theory_of_change as grant conditions)

	GET  /nonprofit/grants/         — list
	GET  /nonprofit/grants/<id>     — detail
	POST /nonprofit/grants/         — create
	"""

	route_base = "/nonprofit/grants"
	default_view = "list"

	widgets = {
		"budget_cents": {
			"widget": "CurrencyWidget",
			"label": "Grant Amount",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"spent_cents": {
			"widget": "CurrencyWidget",
			"label": "Disbursed",
			"display_unit": "dollars",
			"decimal_places": 2,
		},
		"start_date": {
			"widget": "DatePickerWidget",
			"label": "Award Date",
			"format": "YYYY-MM-DD",
		},
		"end_date": {
			"widget": "DatePickerWidget",
			"label": "Close Date",
			"format": "YYYY-MM-DD",
		},
		"theory_of_change": {
			"widget": "RichTextEditorWidget",
			"label": "Grant Conditions",
			"toolbar": ["bold", "italic", "ul", "ol", "link"],
		},
	}

	list_columns = ["program_code", "program_name", "budget_cents", "spent_cents", "start_date", "end_date", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = (
			sa.select(Program)
			.where(Program.program_code.like("GR-%"))
			.order_by(Program.program_code)
		)
		if tenant_id:
			q = q.where(Program.tenant_id == tenant_id)
		if status:
			q = q.where(Program.status == status)

		grants = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": g.id,
				"grant_number": g.program_code,
				"grantor": g.program_name,
				"amount_cents": g.budget_cents,
				"disbursed_cents": g.spent_cents,
				"award_date": g.start_date.isoformat() if g.start_date else None,
				"close_date": g.end_date.isoformat() if g.end_date else None,
				"purpose": g.description,
				"status": g.status,
			}
			for g in grants
		])

	@expose("/<string:grant_id>")
	@has_access
	def detail(self, grant_id: str):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		g = session.get(Program, grant_id)
		if g is None or not g.program_code.startswith("GR-"):
			abort(404)
		return jsonify({
			"id": g.id,
			"grant_number": g.program_code,
			"grantor": g.program_name,
			"amount_cents": g.budget_cents,
			"disbursed_cents": g.spent_cents,
			"currency_code": g.currency_code,
			"award_date": g.start_date.isoformat() if g.start_date else None,
			"close_date": g.end_date.isoformat() if g.end_date else None,
			"purpose": g.description,
			"conditions": g.theory_of_change,
			"program_manager_id": g.program_manager_id,
			"status": g.status,
			"notes": g.notes,
			"_widget_hints": GrantView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.nonprofit.models import Program
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "grant_number", "grantor", "amount_cents")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		grant_number = data["grant_number"]
		if not grant_number.startswith("GR-"):
			grant_number = f"GR-{grant_number}"

		grant = Program(
			tenant_id=data["tenant_id"],
			program_code=grant_number,
			program_name=data["grantor"],
			description=data.get("purpose"),
			theory_of_change=data.get("conditions"),
			program_manager_id=data.get("program_manager_id"),
			budget_cents=int(data["amount_cents"]),
			currency_code=data.get("currency_code", "USD"),
			start_date=data.get("award_date"),
			end_date=data.get("close_date"),
			status=data.get("status", "ACTIVE"),
		)
		session.add(grant)
		session.commit()
		return jsonify({"grant_id": grant.id, "grant_number": grant.program_code}), 201


# ---------------------------------------------------------------------------
# DonorProspectDashboardView
# ---------------------------------------------------------------------------

class DonorProspectDashboardView(BaseView):
	"""Major gift prospect dashboard.

	Shows scored donors with pipeline funnel chart (AdvancedChartsWidget).

	GET /nonprofit/prospects/             — scored prospect list
	GET /nonprofit/prospects/pipeline     — pipeline funnel chart data
	GET /nonprofit/prospects/lybunt/<year> — LYBUNT retention analysis
	"""

	route_base = "/nonprofit/prospects"
	default_view = "index"

	widgets = {
		"prospect_pipeline": {
			"widget": "AdvancedChartsWidget",
			"chart_type": "funnel",
			"label": "Major Gift Prospect Pipeline",
			"data_endpoint": "/nonprofit/prospects/pipeline",
		},
	}

	@expose("/")
	@has_access
	def index(self):
		"""Return all scored major gift prospects for the tenant."""
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		min_capacity = int(request.args.get("min_capacity_cents", 10_000_00))

		try:
			prospects = _svc().score_major_gift_prospects(
				tenant_id=tenant_id,
				min_capacity_cents=min_capacity,
				session=session,
			)
			return jsonify({
				"tenant_id": tenant_id,
				"min_capacity_cents": min_capacity,
				"prospect_count": len(prospects),
				"major_prospects": sum(1 for p in prospects if p["is_major_prospect"]),
				"prospects": prospects,
				"_widget_hints": DonorProspectDashboardView.widgets,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/pipeline")
	@has_access
	def pipeline(self):
		"""Prospect pipeline funnel data for AdvancedChartsWidget.

		Stages: Identified → Qualified → Cultivated → Solicited → Pledged
		Proxy: scored donors segmented by total_score ranges.
		"""
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		try:
			prospects = _svc().score_major_gift_prospects(
				tenant_id=tenant_id,
				session=session,
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

		stages = [
			{"label": "Identified (score 0–40)", "min": 0, "max": 40, "count": 0, "total_cents": 0},
			{"label": "Qualified (score 40–60)", "min": 40, "max": 60, "count": 0, "total_cents": 0},
			{"label": "Cultivated (score 60–75)", "min": 60, "max": 75, "count": 0, "total_cents": 0},
			{"label": "Solicited (score 75–90)", "min": 75, "max": 90, "count": 0, "total_cents": 0},
			{"label": "Pledged (score 90–100)", "min": 90, "max": 100.1, "count": 0, "total_cents": 0},
		]
		for p in prospects:
			score = p["total_score"]
			for stage in stages:
				if stage["min"] <= score < stage["max"]:
					stage["count"] += 1
					stage["total_cents"] += p["lifetime_giving_cents"]
					break

		return jsonify({
			"chart_type": "funnel",
			"title": "Major Gift Prospect Pipeline",
			"data": [
				{"stage": s["label"], "count": s["count"], "total_cents": s["total_cents"]}
				for s in stages
			],
		})

	@expose("/lybunt/<int:year>")
	@has_access
	def lybunt(self, year: int):
		"""LYBUNT retention analysis for the given year."""
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		try:
			donors = _svc().run_lybunt_analysis(
				tenant_id=tenant_id,
				year=year,
				session=session,
			)
			return jsonify({
				"year": year,
				"tenant_id": tenant_id,
				"lybunt_count": len(donors),
				"donors": donors,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


__all__ = [
	"DonorView",
	"DonationView",
	"ProgramView",
	"ImpactMeasurementView",
	"GrantView",
	"DonorProspectDashboardView",
]
