"""
pgappforge/plugins/erp/industry/public_sector/views.py

Flask views for the Public Sector plugin.

Views:
  ConstituentView          — CRUD + Open Case + View Benefits History + GDPR Anonymize
  GovernmentCaseView       — CRUD + Make Decision + Disburse Benefit + Generate Decision Letter
  PublicFundingGrantView   — CRUD + Record Disbursement + Generate Report
  ServiceRequestView       — CRUD + Assign + Resolve + Escalate
  CaseloadDashboardView    — SLA compliance chart, cases by status/program, geographic heatmap
  EligibilityCalculatorView — GET form / POST calculate result
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
	from pgappforge.plugins.erp.industry.public_sector.services import PublicSectorService
	return PublicSectorService()


def _mask_national_id(value: str | None) -> str:
	"""Mask all but the last 4 characters of a national ID for list display."""
	if not value:
		return ""
	visible = value[-4:] if len(value) >= 4 else value
	return "*" * max(0, len(value) - 4) + visible


# ---------------------------------------------------------------------------
# ConstituentView
# ---------------------------------------------------------------------------

class ConstituentView(BaseView):
	"""Constituent CRUD.

	list_columns : constituent_type, name (party_id denorm), national_id masked,
	               case_worker, status
	Widgets      : GeoPointWidget for location/address,
	               Select2 for constituent_type,
	               JSONEditorWidget(readonly) for benefits_enrolled
	Actions      : Open Case, View Benefits History, GDPR Anonymize

	GET  /public-sector/constituents/                    — list
	GET  /public-sector/constituents/<id>                — detail
	POST /public-sector/constituents/                    — create
	POST /public-sector/constituents/<id>/open-case      — open a new case
	GET  /public-sector/constituents/<id>/benefits       — benefits history
	POST /public-sector/constituents/<id>/anonymize      — GDPR anonymize
	"""

	route_base = "/public-sector/constituents"
	default_view = "list"

	list_columns = ["constituent_type", "constituent_number", "national_id_masked", "case_worker_id", "status"]

	widgets = {
		"constituent_type": {
			"widget": "Select2Widget",
			"label": "Constituent Type",
			"choices": ["CITIZEN", "BUSINESS", "NGO", "GOVERNMENT_ENTITY"],
			"placeholder": "Select type…",
		},
		"address": {
			"widget": "GeoPointWidget",
			"label": "Location",
			"lat_field": "address.lat",
			"lng_field": "address.lng",
			"address_field": "address",
		},
		"benefits_enrolled": {
			"widget": "JSONEditorWidget",
			"label": "Benefits Enrolled",
			"readonly": True,
			"schema": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"program_code": {"type": "string"},
						"enrolled_at": {"type": "string"},
						"status": {"type": "string"},
					},
				},
			},
		},
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		constituent_type = request.args.get("constituent_type")
		status = request.args.get("status", "ACTIVE")

		q = sa.select(Constituent).order_by(Constituent.constituent_number)
		if tenant_id:
			q = q.where(Constituent.tenant_id == tenant_id)
		if constituent_type:
			q = q.where(Constituent.constituent_type == constituent_type)
		if status:
			q = q.where(Constituent.status == status)

		rows = session.execute(q.limit(500)).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"constituent_number": c.constituent_number,
				"constituent_type": c.constituent_type,
				"national_id_masked": _mask_national_id(c.national_id_encrypted),
				"case_worker_id": c.case_worker_id,
				"status": c.status,
				"contact_email": c.contact_email,
				"preferred_language": c.preferred_language,
			}
			for c in rows
		])

	@expose("/<string:constituent_id>")
	@has_access
	def detail(self, constituent_id: str):
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent
		session = _get_session()
		c = session.get(Constituent, constituent_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"party_id": c.party_id,
			"constituent_number": c.constituent_number,
			"constituent_type": c.constituent_type,
			"national_id_masked": _mask_national_id(c.national_id_encrypted),
			"date_of_birth": c.date_of_birth.isoformat() if c.date_of_birth else None,
			"gender": c.gender,
			"benefits_enrolled": c.benefits_enrolled,
			"vulnerability_flags": c.vulnerability_flags,
			"case_worker_id": c.case_worker_id,
			"preferred_language": c.preferred_language,
			"contact_email": c.contact_email,
			"contact_phone": c.contact_phone,
			"address": c.address,
			"status": c.status,
			"notes": c.notes,
			"created_at": c.created_at.isoformat() if c.created_at else None,
			"updated_at": c.updated_at.isoformat() if c.updated_at else None,
			"_widget_hints": ConstituentView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "constituent_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			constituent = _svc().register_constituent(
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				constituent_type=data["constituent_type"],
				national_id=data.get("national_id"),
				case_worker_id=data.get("case_worker_id"),
				contact_email=data.get("contact_email"),
				contact_phone=data.get("contact_phone"),
				preferred_language=data.get("preferred_language"),
				address=data.get("address"),
				session=session,
			)
			session.commit()
			return jsonify({
				"constituent_id": constituent.id,
				"constituent_number": constituent.constituent_number,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:constituent_id>/open-case", methods=["POST"])
	@has_access
	def open_case(self, constituent_id: str):
		"""Action: Open a new government case for this constituent."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("program_type"):
			return jsonify({"error": "program_type is required"}), 400
		try:
			case = _svc().open_case(
				constituent_id=constituent_id,
				program_type=data["program_type"],
				application_details=data.get("application_details"),
				case_worker_id=data.get("case_worker_id"),
				session=session,
			)
			session.commit()
			return jsonify({
				"case_id": case.id,
				"case_number": case.case_number,
				"program_type": case.program_type,
				"eligibility_score": str(case.eligibility_score) if case.eligibility_score is not None else None,
				"status": case.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:constituent_id>/benefits")
	@has_access
	def benefits_history(self, constituent_id: str):
		"""Action: View benefits enrollment history for this constituent."""
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent, GovernmentCase
		session = _get_session()
		c = session.get(Constituent, constituent_id)
		if c is None:
			abort(404)

		cases = session.execute(
			sa.select(GovernmentCase).where(
				GovernmentCase.constituent_id == constituent_id,
				GovernmentCase.status.in_(["APPROVED", "ACTIVE", "SUSPENDED", "CLOSED"]),
			).order_by(GovernmentCase.created_at.desc())
		).scalars().all()

		return jsonify({
			"constituent_id": constituent_id,
			"constituent_number": c.constituent_number,
			"benefits_enrolled": c.benefits_enrolled,
			"historical_cases": [
				{
					"case_id": ca.id,
					"case_number": ca.case_number,
					"program_type": ca.program_type,
					"status": ca.status,
					"total_benefit_amount_cents": ca.total_benefit_amount_cents,
					"grant_start": ca.grant_start.isoformat() if ca.grant_start else None,
					"grant_end": ca.grant_end.isoformat() if ca.grant_end else None,
				}
				for ca in cases
			],
		})

	@expose("/<string:constituent_id>/anonymize", methods=["POST"])
	@has_access
	def gdpr_anonymize(self, constituent_id: str):
		"""Action: GDPR/POPIA anonymize — redact PII fields for this constituent."""
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent
		session = _get_session()
		c = session.get(Constituent, constituent_id)
		if c is None:
			abort(404)

		# Redact PII fields
		c.national_id_encrypted = "ANONYMIZED"
		c.date_of_birth = None
		c.gender = None
		c.contact_email = None
		c.contact_phone = None
		c.address = {}
		c.notes = (c.notes or "") + f"\n[ANONYMIZED at {datetime.now(timezone.utc).isoformat()} per DSR request]"
		c.status = "INACTIVE"

		session.commit()
		log.info("gdpr_anonymize: constituent %r anonymized", constituent_id)
		return jsonify({
			"constituent_id": constituent_id,
			"anonymized": True,
			"anonymized_at": datetime.now(timezone.utc).isoformat(),
		})


# ---------------------------------------------------------------------------
# GovernmentCaseView
# ---------------------------------------------------------------------------

class GovernmentCaseView(BaseView):
	"""GovernmentCase CRUD with decision workflow.

	list_columns : case_number, constituent, program_type, eligibility_score,
	               status, created_at
	Widgets      : StarRatingWidget for eligibility_score (0–1 mapped to 5 stars),
	               JSONEditorWidget for benefits_granted,
	               DatePickerWidget for grant_start / grant_end / next_review_date
	               Color badges for status (via _status_badge helper)
	Actions      : Make Decision, Disburse Benefit, Generate Decision Letter

	GET  /public-sector/cases/                         — list
	GET  /public-sector/cases/<id>                     — detail
	POST /public-sector/cases/                         — create
	POST /public-sector/cases/<id>/decision            — make decision
	POST /public-sector/cases/<id>/disburse            — disburse benefit
	GET  /public-sector/cases/<id>/decision-letter     — generate letter JSON
	"""

	route_base = "/public-sector/cases"
	default_view = "list"

	list_columns = ["case_number", "constituent_id", "program_type", "eligibility_score", "status", "created_at"]

	# Status → Bootstrap badge colour mapping
	STATUS_BADGES = {
		"OPEN": "info",
		"UNDER_REVIEW": "warning",
		"APPROVED": "success",
		"REJECTED": "danger",
		"ACTIVE": "primary",
		"SUSPENDED": "warning",
		"CLOSED": "default",
		"APPEALED": "secondary",
	}

	widgets = {
		"eligibility_score": {
			"widget": "StarRatingWidget",
			"label": "Eligibility Score",
			"max_stars": 5,
			"description": "0.0–1.0 score mapped to 1–5 stars (1 star = 0.2)",
		},
		"benefits_granted": {
			"widget": "JSONEditorWidget",
			"label": "Benefits Granted",
			"readonly": False,
			"schema": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"benefit_type": {"type": "string"},
						"amount_cents": {"type": "integer"},
						"frequency": {"type": "string"},
						"start_date": {"type": "string"},
					},
				},
			},
		},
		"grant_start": {
			"widget": "DatePickerWidget",
			"label": "Grant Start Date",
			"format": "YYYY-MM-DD",
		},
		"grant_end": {
			"widget": "DatePickerWidget",
			"label": "Grant End Date",
			"format": "YYYY-MM-DD",
			"allow_clear": True,
		},
		"next_review_date": {
			"widget": "DatePickerWidget",
			"label": "Next Review Date",
			"format": "YYYY-MM-DD",
			"allow_clear": True,
		},
	}

	@staticmethod
	def _score_to_stars(score) -> int:
		"""Map eligibility_score [0,1] to 1-5 star rating."""
		if score is None:
			return 0
		return max(1, min(5, round(float(score) * 5)))

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		constituent_id = request.args.get("constituent_id")
		program_type = request.args.get("program_type")
		status = request.args.get("status")

		q = sa.select(GovernmentCase).order_by(GovernmentCase.created_at.desc())
		if tenant_id:
			q = q.where(GovernmentCase.tenant_id == tenant_id)
		if constituent_id:
			q = q.where(GovernmentCase.constituent_id == constituent_id)
		if program_type:
			q = q.where(GovernmentCase.program_type == program_type)
		if status:
			q = q.where(GovernmentCase.status == status)

		cases = session.execute(q.limit(500)).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"case_number": c.case_number,
				"constituent_id": c.constituent_id,
				"program_type": c.program_type,
				"eligibility_score": str(c.eligibility_score) if c.eligibility_score is not None else None,
				"eligibility_stars": GovernmentCaseView._score_to_stars(c.eligibility_score),
				"status": c.status,
				"status_badge": GovernmentCaseView.STATUS_BADGES.get(c.status, "default"),
				"created_at": c.created_at.isoformat() if c.created_at else None,
			}
			for c in cases
		])

	@expose("/<string:case_id>")
	@has_access
	def detail(self, case_id: str):
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase
		session = _get_session()
		c = session.get(GovernmentCase, case_id)
		if c is None:
			abort(404)
		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"case_number": c.case_number,
			"constituent_id": c.constituent_id,
			"case_worker_id": c.case_worker_id,
			"verified_by": c.verified_by,
			"program_type": c.program_type,
			"eligibility_score": str(c.eligibility_score) if c.eligibility_score is not None else None,
			"eligibility_stars": GovernmentCaseView._score_to_stars(c.eligibility_score),
			"benefits_granted": c.benefits_granted,
			"total_benefit_amount_cents": c.total_benefit_amount_cents,
			"grant_start": c.grant_start.isoformat() if c.grant_start else None,
			"grant_end": c.grant_end.isoformat() if c.grant_end else None,
			"next_review_date": c.next_review_date.isoformat() if c.next_review_date else None,
			"status": c.status,
			"status_badge": GovernmentCaseView.STATUS_BADGES.get(c.status, "default"),
			"rejection_reason": c.rejection_reason,
			"supporting_documents": c.supporting_documents,
			"notes": c.notes,
			"created_at": c.created_at.isoformat() if c.created_at else None,
			"updated_at": c.updated_at.isoformat() if c.updated_at else None,
			"_widget_hints": GovernmentCaseView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("constituent_id", "program_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			case = _svc().open_case(
				constituent_id=data["constituent_id"],
				program_type=data["program_type"],
				application_details=data.get("application_details"),
				case_worker_id=data.get("case_worker_id"),
				session=session,
			)
			session.commit()
			return jsonify({
				"case_id": case.id,
				"case_number": case.case_number,
				"status": case.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/decision", methods=["POST"])
	@has_access
	def make_decision(self, case_id: str):
		"""Action: Record an APPROVED or REJECTED decision on this case."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("decision"):
			return jsonify({"error": "decision (APPROVED|REJECTED) is required"}), 400
		try:
			case = _svc().make_decision(
				case_id=case_id,
				decision=data["decision"],
				benefits_granted_dict=data.get("benefits_granted", {}),
				reviewer_id=data.get("reviewer_id"),
				rejection_reason=data.get("rejection_reason"),
				session=session,
			)
			session.commit()
			return jsonify({
				"case_id": case_id,
				"case_number": case.case_number,
				"decision": data["decision"],
				"status": case.status,
				"total_benefit_amount_cents": case.total_benefit_amount_cents,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/disburse", methods=["POST"])
	@has_access
	def disburse_benefit(self, case_id: str):
		"""Action: Record a benefit payment disbursement for this case."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("amount_cents") or not data.get("payment_method"):
			return jsonify({"error": "amount_cents and payment_method are required"}), 400
		try:
			result = _svc().disburse_benefit(
				case_id=case_id,
				amount_cents=int(data["amount_cents"]),
				payment_method=data["payment_method"],
				disbursed_by_id=data.get("disbursed_by_id"),
				session=session,
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:case_id>/decision-letter")
	@has_access
	def decision_letter(self, case_id: str):
		"""Action: Generate a structured decision letter payload."""
		from pgappforge.plugins.erp.industry.public_sector.models import Constituent, GovernmentCase
		session = _get_session()
		case = session.get(GovernmentCase, case_id)
		if case is None:
			abort(404)

		constituent = session.get(Constituent, case.constituent_id)

		letter = {
			"letter_type": "BENEFIT_DECISION",
			"reference": case.case_number,
			"date_issued": date.today().isoformat(),
			"recipient": {
				"constituent_number": constituent.constituent_number if constituent else None,
				"contact_email": constituent.contact_email if constituent else None,
				"address": constituent.address if constituent else {},
			},
			"program_type": case.program_type,
			"decision": case.status,
			"eligibility_score": str(case.eligibility_score) if case.eligibility_score is not None else None,
			"benefits_granted": case.benefits_granted,
			"total_benefit_amount_cents": case.total_benefit_amount_cents,
			"grant_start": case.grant_start.isoformat() if case.grant_start else None,
			"grant_end": case.grant_end.isoformat() if case.grant_end else None,
			"rejection_reason": case.rejection_reason,
			"appeal_instructions": (
				"If you disagree with this decision, you have 30 days to submit an appeal "
				"in writing to the relevant department."
				if case.status == "REJECTED" else None
			),
		}
		return jsonify(letter)


# ---------------------------------------------------------------------------
# PublicFundingGrantView
# ---------------------------------------------------------------------------

class PublicFundingGrantView(BaseView):
	"""PublicFundingGrant CRUD.

	list_columns : grant_number, grantor, amount (currency), disbursed_pct, status
	Widgets      : CurrencyWidget for amount_cents / disbursed_cents,
	               RangeSliderWidget for disbursement progress (0–100%)
	Actions      : Record Disbursement, Generate Report

	GET  /public-sector/grants/                       — list
	GET  /public-sector/grants/<id>                   — detail
	POST /public-sector/grants/                       — create
	POST /public-sector/grants/<id>/disburse          — record disbursement
	GET  /public-sector/grants/<id>/report            — generate report JSON
	"""

	route_base = "/public-sector/grants"
	default_view = "list"

	list_columns = ["grant_number", "grantor", "amount_cents", "disbursed_pct", "status"]

	widgets = {
		"amount_cents": {
			"widget": "CurrencyWidget",
			"label": "Total Grant Amount",
			"currency_field": "currency_code",
			"cents": True,
		},
		"disbursed_cents": {
			"widget": "CurrencyWidget",
			"label": "Disbursed Amount",
			"currency_field": "currency_code",
			"cents": True,
		},
		"disbursed_pct": {
			"widget": "RangeSliderWidget",
			"label": "Disbursement Progress",
			"min": 0,
			"max": 100,
			"step": 0.1,
			"unit": "%",
			"readonly": True,
		},
	}

	@staticmethod
	def _disbursed_pct(grant) -> float:
		if not grant.amount_cents:
			return 0.0
		return round(grant.disbursed_cents / grant.amount_cents * 100, 1)

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.public_sector.models import PublicFundingGrant
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = sa.select(PublicFundingGrant).order_by(PublicFundingGrant.award_date.desc())
		if tenant_id:
			q = q.where(PublicFundingGrant.tenant_id == tenant_id)
		if status:
			q = q.where(PublicFundingGrant.status == status)

		grants = session.execute(q.limit(500)).scalars().all()
		return jsonify([
			{
				"id": g.id,
				"grant_number": g.grant_number,
				"grantor": g.grantor,
				"amount_cents": g.amount_cents,
				"disbursed_cents": g.disbursed_cents,
				"disbursed_pct": PublicFundingGrantView._disbursed_pct(g),
				"currency_code": g.currency_code,
				"status": g.status,
				"award_date": g.award_date.isoformat() if g.award_date else None,
				"end_date": g.end_date.isoformat() if g.end_date else None,
			}
			for g in grants
		])

	@expose("/<string:grant_id>")
	@has_access
	def detail(self, grant_id: str):
		from pgappforge.plugins.erp.industry.public_sector.models import PublicFundingGrant
		session = _get_session()
		g = session.get(PublicFundingGrant, grant_id)
		if g is None:
			abort(404)
		return jsonify({
			"id": g.id,
			"tenant_id": g.tenant_id,
			"grant_number": g.grant_number,
			"grantor": g.grantor,
			"grantor_id": g.grantor_id,
			"amount_cents": g.amount_cents,
			"disbursed_cents": g.disbursed_cents,
			"disbursed_pct": PublicFundingGrantView._disbursed_pct(g),
			"currency_code": g.currency_code,
			"purpose": g.purpose,
			"conditions": g.conditions,
			"reporting_schedule": g.reporting_schedule,
			"award_date": g.award_date.isoformat() if g.award_date else None,
			"start_date": g.start_date.isoformat() if g.start_date else None,
			"end_date": g.end_date.isoformat() if g.end_date else None,
			"status": g.status,
			"programme_manager_id": g.programme_manager_id,
			"notes": g.notes,
			"created_at": g.created_at.isoformat() if g.created_at else None,
			"_widget_hints": PublicFundingGrantView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.public_sector.models import PublicFundingGrant
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "grant_number", "grantor", "amount_cents", "purpose")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		grant = PublicFundingGrant(
			tenant_id=data["tenant_id"],
			grant_number=data["grant_number"],
			grantor=data["grantor"],
			grantor_id=data.get("grantor_id"),
			amount_cents=int(data["amount_cents"]),
			disbursed_cents=0,
			currency_code=data.get("currency_code", "USD"),
			purpose=data["purpose"],
			conditions=data.get("conditions", []),
			reporting_schedule=data.get("reporting_schedule", []),
			award_date=data.get("award_date"),
			start_date=data.get("start_date"),
			end_date=data.get("end_date"),
			status=data.get("status", "AWARDED"),
			programme_manager_id=data.get("programme_manager_id"),
		)
		session.add(grant)
		session.commit()
		return jsonify({"grant_id": grant.id, "grant_number": grant.grant_number}), 201

	@expose("/<string:grant_id>/disburse", methods=["POST"])
	@has_access
	def record_disbursement(self, grant_id: str):
		"""Action: Record a funding tranche disbursement."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("tranche_amount_cents"):
			return jsonify({"error": "tranche_amount_cents is required"}), 400
		try:
			result = _svc().record_grant_disbursement(
				grant_id=grant_id,
				tranche_amount_cents=int(data["tranche_amount_cents"]),
				disbursed_by_id=data.get("disbursed_by_id"),
				session=session,
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:grant_id>/report")
	@has_access
	def generate_report(self, grant_id: str):
		"""Action: Generate a grant utilisation report."""
		from pgappforge.plugins.erp.industry.public_sector.models import PublicFundingGrant
		session = _get_session()
		g = session.get(PublicFundingGrant, grant_id)
		if g is None:
			abort(404)

		undisbursed = g.amount_cents - g.disbursed_cents
		return jsonify({
			"report_type": "GRANT_UTILISATION",
			"grant_number": g.grant_number,
			"grantor": g.grantor,
			"currency_code": g.currency_code,
			"total_awarded_cents": g.amount_cents,
			"total_disbursed_cents": g.disbursed_cents,
			"undisbursed_cents": undisbursed,
			"disbursed_pct": PublicFundingGrantView._disbursed_pct(g),
			"status": g.status,
			"conditions_met": sum(1 for c in (g.conditions or []) if c.get("met")),
			"conditions_total": len(g.conditions or []),
			"purpose": g.purpose,
			"award_date": g.award_date.isoformat() if g.award_date else None,
			"end_date": g.end_date.isoformat() if g.end_date else None,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		})


# ---------------------------------------------------------------------------
# ServiceRequestView
# ---------------------------------------------------------------------------

class ServiceRequestView(BaseView):
	"""ServiceRequest CRUD.

	list_columns : request_number, constituent, service_type, channel, priority, status
	Widgets      : Select2 for channel / service_type,
	               StarRatingWidget for priority (LOW=1, NORMAL=2, HIGH=3, URGENT=4),
	               RichTextEditorWidget for description,
	               FileUploadWidget(multiple=True) for attachments
	Actions      : Assign, Resolve, Escalate

	GET  /public-sector/service-requests/                     — list
	GET  /public-sector/service-requests/<id>                 — detail
	POST /public-sector/service-requests/                     — create
	POST /public-sector/service-requests/<id>/assign          — assign to user
	POST /public-sector/service-requests/<id>/resolve         — resolve
	POST /public-sector/service-requests/<id>/escalate        — escalate
	"""

	route_base = "/public-sector/service-requests"
	default_view = "list"

	list_columns = ["request_number", "constituent_id", "service_type", "channel", "priority", "status"]

	PRIORITY_STARS = {"LOW": 1, "NORMAL": 2, "HIGH": 3, "URGENT": 4}

	widgets = {
		"channel": {
			"widget": "Select2Widget",
			"label": "Channel",
			"choices": ["WEB", "PHONE", "WALK_IN", "EMAIL", "MOBILE_APP"],
			"placeholder": "Select channel…",
		},
		"service_type": {
			"widget": "Select2Widget",
			"label": "Service Type",
			"choices": ["INFO_REQUEST", "DOCUMENT_REQUEST", "COMPLAINT", "APPEAL", "GENERAL"],
			"placeholder": "Select service type…",
		},
		"priority": {
			"widget": "StarRatingWidget",
			"label": "Priority",
			"max_stars": 4,
			"description": "LOW=1 star, NORMAL=2, HIGH=3, URGENT=4",
		},
		"description": {
			"widget": "RichTextEditorWidget",
			"label": "Description",
			"toolbar": ["bold", "italic", "ul", "ol", "link"],
		},
		"attachments": {
			"widget": "FileUploadWidget",
			"label": "Attachments",
			"multiple": True,
			"allowed_extensions": ["pdf", "jpg", "jpeg", "png", "docx", "xlsx"],
		},
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		constituent_id = request.args.get("constituent_id")
		status = request.args.get("status")
		priority = request.args.get("priority")

		q = sa.select(ServiceRequest).order_by(ServiceRequest.created_at.desc())
		if tenant_id:
			q = q.where(ServiceRequest.tenant_id == tenant_id)
		if constituent_id:
			q = q.where(ServiceRequest.constituent_id == constituent_id)
		if status:
			q = q.where(ServiceRequest.status == status)
		if priority:
			q = q.where(ServiceRequest.priority == priority)

		rows = session.execute(q.limit(500)).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"request_number": r.request_number,
				"constituent_id": r.constituent_id,
				"service_type": r.service_type,
				"channel": r.channel,
				"priority": r.priority,
				"priority_stars": ServiceRequestView.PRIORITY_STARS.get(r.priority, 2),
				"subject": r.subject,
				"assigned_to_id": r.assigned_to_id,
				"status": r.status,
				"created_at": r.created_at.isoformat() if r.created_at else None,
			}
			for r in rows
		])

	@expose("/<string:request_id>")
	@has_access
	def detail(self, request_id: str):
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		session = _get_session()
		r = session.get(ServiceRequest, request_id)
		if r is None:
			abort(404)
		return jsonify({
			"id": r.id,
			"tenant_id": r.tenant_id,
			"request_number": r.request_number,
			"constituent_id": r.constituent_id,
			"service_type": r.service_type,
			"channel": r.channel,
			"priority": r.priority,
			"priority_stars": ServiceRequestView.PRIORITY_STARS.get(r.priority, 2),
			"subject": r.subject,
			"description": r.description,
			"attachments": r.attachments,
			"assigned_to_id": r.assigned_to_id,
			"resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
			"resolution_notes": r.resolution_notes,
			"status": r.status,
			"created_at": r.created_at.isoformat() if r.created_at else None,
			"updated_at": r.updated_at.isoformat() if r.updated_at else None,
			"_widget_hints": ServiceRequestView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		from sqlalchemy import func as sqlfunc, select as saselect
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "subject")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		count = session.execute(
			saselect(sqlfunc.count()).select_from(ServiceRequest).where(
				ServiceRequest.tenant_id == data["tenant_id"]
			)
		).scalar_one()
		request_number = f"SR-{data['tenant_id'][:8].upper()}-{count + 1:06d}"

		sr = ServiceRequest(
			tenant_id=data["tenant_id"],
			request_number=request_number,
			constituent_id=data.get("constituent_id"),
			service_type=data.get("service_type", "GENERAL"),
			channel=data.get("channel", "WEB"),
			priority=data.get("priority", "NORMAL"),
			subject=data["subject"],
			description=data.get("description"),
			attachments=data.get("attachments", []),
			status="OPEN",
		)
		session.add(sr)
		session.commit()
		return jsonify({"request_id": sr.id, "request_number": sr.request_number}), 201

	@expose("/<string:request_id>/assign", methods=["POST"])
	@has_access
	def assign(self, request_id: str):
		"""Action: Assign service request to a user."""
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("assigned_to_id"):
			return jsonify({"error": "assigned_to_id is required"}), 400
		r = session.get(ServiceRequest, request_id)
		if r is None:
			abort(404)
		r.assigned_to_id = data["assigned_to_id"]
		r.status = "IN_PROGRESS"
		session.commit()
		return jsonify({
			"request_id": request_id,
			"assigned_to_id": r.assigned_to_id,
			"status": r.status,
		})

	@expose("/<string:request_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, request_id: str):
		"""Action: Mark service request as resolved."""
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		session = _get_session()
		data = request.get_json(force=True) or {}
		r = session.get(ServiceRequest, request_id)
		if r is None:
			abort(404)
		if r.status in ("RESOLVED", "CLOSED"):
			return jsonify({"error": f"Request is already {r.status!r}"}), 422
		r.status = "RESOLVED"
		r.resolved_at = datetime.now(timezone.utc)
		r.resolution_notes = data.get("resolution_notes", "")
		session.commit()

		# Emit ps.service.request.fulfilled
		try:
			from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event

			class _SRFulfilledEvent(DomainEvent):
				event_type: str = "ps.service.request.fulfilled"
				request_id: str = ""
				request_number: str = ""
				constituent_id: str = ""

			emit_event(
				_SRFulfilledEvent(
					aggregate_id=request_id,
					aggregate_type="ServiceRequest",
					tenant_id=r.tenant_id,
					request_id=request_id,
					request_number=r.request_number,
					constituent_id=r.constituent_id or "",
				),
				session,
			)
			session.commit()
		except Exception as exc:
			log.debug("resolve: service.request.fulfilled emit failed (non-fatal): %s", exc)

		return jsonify({
			"request_id": request_id,
			"status": "RESOLVED",
			"resolved_at": r.resolved_at.isoformat(),
		})

	@expose("/<string:request_id>/escalate", methods=["POST"])
	@has_access
	def escalate(self, request_id: str):
		"""Action: Escalate service request."""
		from pgappforge.plugins.erp.industry.public_sector.service_request_model import ServiceRequest
		session = _get_session()
		data = request.get_json(force=True) or {}
		r = session.get(ServiceRequest, request_id)
		if r is None:
			abort(404)
		r.status = "ESCALATED"
		r.priority = "URGENT"
		if data.get("escalated_to_id"):
			r.assigned_to_id = data["escalated_to_id"]
		session.commit()
		return jsonify({
			"request_id": request_id,
			"status": "ESCALATED",
			"priority": "URGENT",
		})


# ---------------------------------------------------------------------------
# CaseloadDashboardView
# ---------------------------------------------------------------------------

class CaseloadDashboardView(BaseView):
	"""Caseload analytics dashboard for public sector case workers.

	Shows SLA compliance chart, cases by status, cases by program type,
	and a geographic heatmap of constituent locations.

	GET /public-sector/caseload/       — rendered HTML dashboard
	GET /public-sector/caseload/data   — JSON metrics payload
	"""

	route_base = "/public-sector/caseload"
	default_view = "index"

	widgets = {
		"sla_compliance": {
			"widget": "AdvancedChartsWidget",
			"chart_type": "bar",
			"label": "SLA Compliance",
			"x_label": "Case Worker",
			"y_label": "Cases",
			"data_endpoint": "/public-sector/caseload/data",
		},
		"geographic_heatmap": {
			"widget": "GeographicHeatmapWidget",
			"label": "Constituent Locations",
			"data_endpoint": "/public-sector/caseload/data",
			"lat_field": "address.lat",
			"lng_field": "address.lng",
			"intensity_field": "open_cases",
		},
	}

	@expose("/")
	@has_access
	def index(self):
		"""Render the caseload dashboard (returns JSON metrics for API mode)."""
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		case_worker_id = request.args.get("case_worker_id")

		if case_worker_id:
			try:
				summary = _svc().get_caseload_summary(
					case_worker_id=case_worker_id,
					session=session,
				)
				return jsonify({
					"dashboard_type": "INDIVIDUAL_CASELOAD",
					"summary": summary,
					"_widget_hints": CaseloadDashboardView.widgets,
				})
			except Exception as exc:
				return jsonify({"error": str(exc)}), 422

		# Team-level summary
		from pgappforge.plugins.erp.industry.public_sector.models import GovernmentCase
		q = sa.select(GovernmentCase)
		if tenant_id:
			q = q.where(GovernmentCase.tenant_id == tenant_id)

		cases = session.execute(
			q.where(GovernmentCase.status.in_(["OPEN", "UNDER_REVIEW"])).limit(1000)
		).scalars().all()

		now = datetime.now(timezone.utc)
		by_status: dict[str, int] = {}
		by_program: dict[str, int] = {}
		sla_breaches = 0

		for c in cases:
			by_status[c.status] = by_status.get(c.status, 0) + 1
			by_program[c.program_type] = by_program.get(c.program_type, 0) + 1
			if c.created_at:
				created = c.created_at
				if created.tzinfo is None:
					created = created.replace(tzinfo=timezone.utc)
				if (now - created).days > 30:
					sla_breaches += 1

		return jsonify({
			"dashboard_type": "TEAM_CASELOAD",
			"tenant_id": tenant_id,
			"total_open_cases": len(cases),
			"cases_by_status": by_status,
			"cases_by_program": by_program,
			"sla_breaches": sla_breaches,
			"sla_compliance_pct": (
				round((len(cases) - sla_breaches) / len(cases) * 100, 1)
				if cases else 100.0
			),
			"_widget_hints": CaseloadDashboardView.widgets,
		})

	@expose("/data")
	@has_access
	def data(self):
		"""JSON metrics endpoint for dashboard widgets."""
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		from pgappforge.plugins.erp.industry.public_sector.models import Constituent, GovernmentCase

		# Cases by status
		cases_q = sa.select(GovernmentCase)
		if tenant_id:
			cases_q = cases_q.where(GovernmentCase.tenant_id == tenant_id)
		all_cases = session.execute(cases_q.limit(5000)).scalars().all()

		by_status: dict[str, int] = {}
		by_program: dict[str, int] = {}
		now = datetime.now(timezone.utc)
		sla_breaches = 0

		for c in all_cases:
			by_status[c.status] = by_status.get(c.status, 0) + 1
			by_program[c.program_type] = by_program.get(c.program_type, 0) + 1
			if c.status in ("OPEN", "UNDER_REVIEW") and c.created_at:
				created = c.created_at
				if created.tzinfo is None:
					created = created.replace(tzinfo=timezone.utc)
				if (now - created).days > 30:
					sla_breaches += 1

		# Geographic heatmap data — constituent addresses with open cases
		constituent_q = sa.select(Constituent)
		if tenant_id:
			constituent_q = constituent_q.where(Constituent.tenant_id == tenant_id)
		constituents = session.execute(constituent_q.limit(2000)).scalars().all()

		heatmap_points = []
		for c in constituents:
			addr = c.address or {}
			if addr.get("lat") and addr.get("lng"):
				heatmap_points.append({
					"lat": addr["lat"],
					"lng": addr["lng"],
					"constituent_id": c.id,
					"constituent_number": c.constituent_number,
				})

		return jsonify({
			"cases_by_status": [{"status": k, "count": v} for k, v in by_status.items()],
			"cases_by_program": [{"program": k, "count": v} for k, v in by_program.items()],
			"sla_breaches": sla_breaches,
			"total_cases": len(all_cases),
			"heatmap_points": heatmap_points,
		})


# ---------------------------------------------------------------------------
# EligibilityCalculatorView
# ---------------------------------------------------------------------------

class EligibilityCalculatorView(BaseView):
	"""Interactive eligibility calculator for program assessment.

	GET  /public-sector/eligibility/         — form with Select2AJAX constituent + Select2 program
	POST /public-sector/eligibility/         — calculate and return result

	Response includes: eligible, score, disqualifying_factors, eligible_amount_cents,
	                   recommendation, and widget hints for rendering.
	"""

	route_base = "/public-sector/eligibility"
	default_view = "form"

	PROGRAM_TYPES = [
		"SOCIAL_GRANT",
		"HOUSING",
		"HEALTH",
		"EDUCATION",
		"BUSINESS_SUPPORT",
		"DISABILITY",
		"UNEMPLOYMENT",
	]

	widgets = {
		"constituent_id": {
			"widget": "Select2AJAXWidget",
			"label": "Constituent",
			"ajax_url": "/public-sector/constituents/",
			"value_field": "id",
			"label_field": "constituent_number",
			"placeholder": "Search constituent…",
			"min_input_length": 2,
		},
		"program_type": {
			"widget": "Select2Widget",
			"label": "Program Type",
			"choices": [
				"SOCIAL_GRANT",
				"HOUSING",
				"HEALTH",
				"EDUCATION",
				"BUSINESS_SUPPORT",
				"DISABILITY",
				"UNEMPLOYMENT",
			],
			"placeholder": "Select program…",
		},
	}

	@expose("/")
	@has_access
	def form(self):
		"""Return form schema with widget hints for GET."""
		return jsonify({
			"form_type": "ELIGIBILITY_CALCULATOR",
			"fields": [
				{
					"name": "constituent_id",
					"required": True,
					"widget": EligibilityCalculatorView.widgets["constituent_id"],
				},
				{
					"name": "program_type",
					"required": True,
					"widget": EligibilityCalculatorView.widgets["program_type"],
				},
			],
			"submit_url": "/public-sector/eligibility/",
			"submit_method": "POST",
		})

	@expose("/", methods=["POST"])
	@has_access
	def calculate(self):
		"""POST: calculate eligibility and return structured result."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("constituent_id", "program_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		if data["program_type"] not in self.PROGRAM_TYPES:
			return jsonify({
				"error": f"Invalid program_type. Valid values: {self.PROGRAM_TYPES}"
			}), 400

		try:
			result = _svc().calculate_eligibility(
				constituent_id=data["constituent_id"],
				program_type=data["program_type"],
				session=session,
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

		# Build recommendation message
		score = result["score"]
		if result["eligible"]:
			if score >= 0.8:
				recommendation = "STRONGLY_RECOMMENDED — constituent meets criteria with high confidence."
			elif score >= 0.6:
				recommendation = "RECOMMENDED — constituent meets eligibility criteria."
			else:
				recommendation = "BORDERLINE — eligible but recommend enhanced verification."
		else:
			recommendation = "NOT_ELIGIBLE — " + (
				result["disqualifying_factors"][0]
				if result["disqualifying_factors"]
				else "Score below program threshold."
			)

		return jsonify({
			"constituent_id": data["constituent_id"],
			"program_type": data["program_type"],
			"eligible": result["eligible"],
			"score": result["score"],
			"score_stars": max(1, min(5, round(score * 5))),
			"disqualifying_factors": result["disqualifying_factors"],
			"eligible_amount_cents": result["eligible_amount_cents"],
			"recommendation": recommendation,
			"_widget_hints": EligibilityCalculatorView.widgets,
		})


__all__ = [
	"ConstituentView",
	"GovernmentCaseView",
	"PublicFundingGrantView",
	"ServiceRequestView",
	"CaseloadDashboardView",
	"EligibilityCalculatorView",
]
