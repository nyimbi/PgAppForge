"""
pgappforge/plugins/erp/industry/real_estate/commercial/views.py

Flask views for the Commercial Real Estate sub-plugin.

Route summary
-------------
SpaceUnitView            /industry/commercial-re/spaces/
  ├─ GET  /spaces/                — list (filter by property_id, status, unit_type)
  ├─ GET  /spaces/<id>            — detail
  └─ POST /spaces/                — create space unit

CommercialLeaseView      /industry/commercial-re/leases/
  ├─ GET  /leases/                — list (filter by status, space_id)
  ├─ GET  /leases/<id>            — detail + rent schedule
  ├─ POST /leases/                — create lease
  └─ POST /leases/<id>/terminate  — terminate lease

CAMReconciliationView    /industry/commercial-re/cam/
  ├─ GET  /cam/                   — list reconciliations
  ├─ POST /cam/budget             — upsert CAM budget
  ├─ POST /cam/actual             — upsert CAM actual
  └─ POST /cam/reconcile          — run reconciliation

LOIView                  /industry/commercial-re/loi/
  ├─ GET  /loi/                   — list
  ├─ POST /loi/                   — submit LOI
  └─ POST /loi/<id>/accept        — accept LOI

LeaseAbstractView        /industry/commercial-re/abstracts/
  ├─ GET  /abstracts/<lease_id>   — get abstract by lease
  └─ POST /abstracts/             — create / update abstract

CommercialREDashboardView  /industry/commercial-re/
  └─ GET  /                       — dashboard with KPI counts
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView
from pgappforge import expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
)

from pgappforge.plugins.erp.industry.real_estate.commercial.models import (
	SpaceUnit,
	CommercialLease,
	CAMBudget,
	CAMActual,
	CAMReconciliation,
	LeaseAbstract,
	LOI,
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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


# ---------------------------------------------------------------------------
# SpaceUnitView
# ---------------------------------------------------------------------------

class SpaceUnitView(BaseERPView):
	"""Commercial space unit list and detail.

	Widget config:
	  - CurrencyWidget for asking_rent_cents
	  - DateWidget not needed here (no date fields)
	"""

	route_base = "/industry/commercial-re/spaces"
	default_view = "list"

	widget_config = {
		"asking_rent_cents": currency_widget("USD"),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		property_id = request.args.get("property_id")
		status = request.args.get("status")
		unit_type = request.args.get("unit_type")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(SpaceUnit)
			.order_by(SpaceUnit.suite_code)
			.limit(500)
		)
		if property_id:
			q = q.where(SpaceUnit.property_id == property_id)
		if status:
			q = q.where(SpaceUnit.status == status.upper())
		if unit_type:
			q = q.where(SpaceUnit.unit_type == unit_type.upper())
		if tenant_id:
			q = q.where(SpaceUnit.tenant_id == tenant_id)

		spaces = session.execute(q).scalars().all()
		return jsonify({
			"spaces": [
				{
					"id": s.id,
					"property_id": s.property_id,
					"suite_code": s.suite_code,
					"floor": s.floor,
					"sqft": s.sqft,
					"unit_type": s.unit_type,
					"status": s.status,
					"asking_rent_cents": s.asking_rent_cents,
					"asking_rent_display": _cents(s.asking_rent_cents),
				}
				for s in spaces
			]
		})

	@expose("/<string:space_id>")
	@has_access
	def detail(self, space_id: str):
		session = _get_session()
		space = session.get(SpaceUnit, space_id)
		if space is None:
			abort(404)
		return jsonify({
			"id": space.id,
			"tenant_id": space.tenant_id,
			"property_id": space.property_id,
			"suite_code": space.suite_code,
			"floor": space.floor,
			"sqft": space.sqft,
			"unit_type": space.unit_type,
			"status": space.status,
			"asking_rent_cents": space.asking_rent_cents,
			"asking_rent_display": _cents(space.asking_rent_cents),
			"created_at": space.created_at.isoformat() if space.created_at else None,
			"updated_at": space.updated_at.isoformat() if space.updated_at else None,
			"widget_config": self.widget_config,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "property_id", "suite_code", "unit_type") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			space = svc.create_space(
				property_id=data["property_id"],
				suite_code=data["suite_code"],
				sqft=data.get("sqft"),
				unit_type=data["unit_type"],
				tenant_id=data["tenant_id"],
				session=session,
				floor=data.get("floor"),
				asking_rent_cents=data.get("asking_rent_cents"),
				status=data.get("status", "VACANT"),
			)
			session.commit()
			return jsonify({"ok": True, "id": space.id, "suite_code": space.suite_code}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CommercialLeaseView
# ---------------------------------------------------------------------------

class CommercialLeaseView(BaseERPView):
	"""Commercial Lease CRUD + lifecycle.

	Widget config:
	  - CurrencyWidget for base_rent_cents, cam_estimate_cents,
	    insurance_estimate_cents, tax_estimate_cents
	  - DateWidget for lease_start, lease_end
	"""

	route_base = "/industry/commercial-re/leases"
	default_view = "list"

	widget_config = {
		"base_rent_cents": currency_widget("USD"),
		"cam_estimate_cents": currency_widget("USD"),
		"insurance_estimate_cents": currency_widget("USD"),
		"tax_estimate_cents": currency_widget("USD"),
		"lease_start": date_widget(),
		"lease_end": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		status = request.args.get("status")
		space_id = request.args.get("space_id")
		tenant_id = request.args.get("tenant_id")
		lease_type = request.args.get("lease_type")

		q = (
			sa.select(CommercialLease)
			.order_by(sa.desc(CommercialLease.created_at))
			.limit(500)
		)
		if status:
			q = q.where(CommercialLease.status == status.upper())
		if space_id:
			q = q.where(CommercialLease.space_id == space_id)
		if tenant_id:
			q = q.where(CommercialLease.tenant_id == tenant_id)
		if lease_type:
			q = q.where(CommercialLease.lease_type == lease_type.upper())

		leases = session.execute(q).scalars().all()
		return jsonify({
			"leases": [
				{
					"id": l.id,
					"space_id": l.space_id,
					"tenant_party_id": l.tenant_party_id,
					"landlord_id": l.landlord_id,
					"lease_type": l.lease_type,
					"base_rent_cents": l.base_rent_cents,
					"base_rent_display": _cents(l.base_rent_cents),
					"cam_estimate_cents": l.cam_estimate_cents,
					"insurance_estimate_cents": l.insurance_estimate_cents,
					"tax_estimate_cents": l.tax_estimate_cents,
					"lease_start": l.lease_start.isoformat() if l.lease_start else None,
					"lease_end": l.lease_end.isoformat() if l.lease_end else None,
					"status": l.status,
				}
				for l in leases
			]
		})

	@expose("/<string:lease_id>")
	@has_access
	def detail(self, lease_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			LeaseNotFoundError,
		)

		lease = session.get(CommercialLease, lease_id)
		if lease is None:
			abort(404)

		svc = CommercialLeaseService()
		try:
			schedule = svc.get_rent_schedule(lease_id, session)
		except LeaseNotFoundError:
			schedule = []

		return jsonify({
			"id": lease.id,
			"tenant_id": lease.tenant_id,
			"space_id": lease.space_id,
			"tenant_party_id": lease.tenant_party_id,
			"landlord_id": lease.landlord_id,
			"lease_type": lease.lease_type,
			"base_rent_cents": lease.base_rent_cents,
			"base_rent_display": _cents(lease.base_rent_cents),
			"cam_estimate_cents": lease.cam_estimate_cents,
			"insurance_estimate_cents": lease.insurance_estimate_cents,
			"tax_estimate_cents": lease.tax_estimate_cents,
			"lease_start": lease.lease_start.isoformat() if lease.lease_start else None,
			"lease_end": lease.lease_end.isoformat() if lease.lease_end else None,
			"status": lease.status,
			"rent_schedule": lease.rent_schedule,
			"options": lease.options,
			"rent_schedule_expanded": schedule,
			"widget_config": self.widget_config,
			"created_at": lease.created_at.isoformat() if lease.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "space_id", "tenant_party_id", "landlord_id",
					"lease_type", "base_rent_cents", "lease_start", "lease_end")
		missing = [f for f in required if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			lease = svc.create_commercial_lease(
				space_id=data["space_id"],
				tenant_party_id=data["tenant_party_id"],
				landlord_id=data["landlord_id"],
				lease_type=data["lease_type"],
				base_rent_cents=int(data["base_rent_cents"]),
				lease_start=data["lease_start"],
				lease_end=data["lease_end"],
				tenant_id=data["tenant_id"],
				session=session,
				cam_estimate_cents=int(data.get("cam_estimate_cents") or 0),
				insurance_estimate_cents=int(data.get("insurance_estimate_cents") or 0),
				tax_estimate_cents=int(data.get("tax_estimate_cents") or 0),
				rent_schedule=data.get("rent_schedule"),
				options=data.get("options"),
			)
			session.commit()
			return jsonify({"ok": True, "id": lease.id}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:lease_id>/terminate", methods=["POST"])
	@has_access
	def terminate(self, lease_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id", "")
		svc = CommercialLeaseService()
		try:
			lease = svc.terminate_commercial_lease(
				lease_id=lease_id,
				tenant_id=tenant_id,
				session=session,
				termination_date=data.get("termination_date"),
			)
			session.commit()
			return jsonify({"ok": True, "status": lease.status, "lease_end": lease.lease_end.isoformat()})
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CAMReconciliationView
# ---------------------------------------------------------------------------

class CAMReconciliationView(BaseERPView):
	"""CAM budget, actuals, and reconciliation management.

	Widget config:
	  - CurrencyWidget for total_budget_cents, total_actual_cents, variance_cents
	"""

	route_base = "/industry/commercial-re/cam"
	default_view = "list"

	widget_config = {
		"total_budget_cents": currency_widget("USD"),
		"total_actual_cents": currency_widget("USD"),
		"variance_cents": currency_widget("USD"),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		property_id = request.args.get("property_id")
		year = request.args.get("year")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(CAMReconciliation)
			.order_by(sa.desc(CAMReconciliation.year))
			.limit(200)
		)
		if property_id:
			q = q.where(CAMReconciliation.property_id == property_id)
		if year:
			q = q.where(CAMReconciliation.year == int(year))
		if tenant_id:
			q = q.where(CAMReconciliation.tenant_id == tenant_id)

		recons = session.execute(q).scalars().all()
		return jsonify({
			"reconciliations": [
				{
					"id": r.id,
					"property_id": r.property_id,
					"year": r.year,
					"total_budgeted_cents": r.total_budgeted_cents,
					"total_budgeted_display": _cents(r.total_budgeted_cents),
					"total_actual_cents": r.total_actual_cents,
					"total_actual_display": _cents(r.total_actual_cents),
					"variance_cents": r.variance_cents,
					"variance_display": _cents(r.variance_cents),
					"status": r.status,
					"reconciled_at": r.reconciled_at.isoformat() if r.reconciled_at else None,
					"allocation_count": len(r.tenant_allocations) if r.tenant_allocations else 0,
				}
				for r in recons
			]
		})

	@expose("/budget", methods=["POST"])
	@has_access
	def upsert_budget(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "property_id", "year", "total_budget_cents") if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			budget = svc.create_cam_budget(
				property_id=data["property_id"],
				year=int(data["year"]),
				total_budget_cents=int(data["total_budget_cents"]),
				categories=data.get("categories") or {},
				tenant_id=data["tenant_id"],
				session=session,
			)
			session.commit()
			return jsonify({"ok": True, "id": budget.id}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/actual", methods=["POST"])
	@has_access
	def upsert_actual(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "property_id", "year", "total_actual_cents") if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			actual = svc.record_cam_actual(
				property_id=data["property_id"],
				year=int(data["year"]),
				total_actual_cents=int(data["total_actual_cents"]),
				categories=data.get("categories") or {},
				tenant_id=data["tenant_id"],
				session=session,
			)
			session.commit()
			return jsonify({"ok": True, "id": actual.id}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/reconcile", methods=["POST"])
	@has_access
	def reconcile(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "property_id", "year") if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			recon = svc.reconcile_cam(
				property_id=data["property_id"],
				year=int(data["year"]),
				tenant_id=data["tenant_id"],
				session=session,
				finalize=bool(data.get("finalize", False)),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": recon.id,
				"variance_cents": recon.variance_cents,
				"variance_display": _cents(recon.variance_cents),
				"status": recon.status,
				"allocation_count": len(recon.tenant_allocations),
			})
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# LOIView
# ---------------------------------------------------------------------------

class LOIView(BaseERPView):
	"""Letter of Intent list and lifecycle.

	Widget config:
	  - CurrencyWidget for proposed_rent_cents, ti_requested_cents
	  - DateWidget for proposed_start_date, expires_at
	"""

	route_base = "/industry/commercial-re/loi"
	default_view = "list"

	widget_config = {
		"proposed_rent_cents": currency_widget("USD"),
		"ti_requested_cents": currency_widget("USD"),
		"proposed_start_date": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		property_id = request.args.get("property_id")
		status = request.args.get("status")
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(LOI)
			.order_by(sa.desc(LOI.created_at))
			.limit(500)
		)
		if property_id:
			q = q.where(LOI.property_id == property_id)
		if status:
			q = q.where(LOI.status == status.upper())
		if tenant_id:
			q = q.where(LOI.tenant_id == tenant_id)

		lois = session.execute(q).scalars().all()
		return jsonify({
			"lois": [
				{
					"id": l.id,
					"property_id": l.property_id,
					"space_id": l.space_id,
					"prospect_party_id": l.prospect_party_id,
					"proposed_term_months": l.proposed_term_months,
					"proposed_rent_cents": l.proposed_rent_cents,
					"proposed_rent_display": _cents(l.proposed_rent_cents),
					"ti_requested_cents": l.ti_requested_cents,
					"free_rent_months": l.free_rent_months,
					"status": l.status,
					"expires_at": l.expires_at.isoformat() if l.expires_at else None,
					"created_at": l.created_at.isoformat() if l.created_at else None,
				}
				for l in lois
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def submit(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "property_id", "prospect_party_id",
					"proposed_term_months", "proposed_rent_cents")
		missing = [f for f in required if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		svc = CommercialLeaseService()
		try:
			loi = svc.submit_loi(
				property_id=data["property_id"],
				prospect_party_id=data["prospect_party_id"],
				proposed_term_months=int(data["proposed_term_months"]),
				proposed_rent_cents=int(data["proposed_rent_cents"]),
				tenant_id=data["tenant_id"],
				session=session,
				space_id=data.get("space_id"),
				proposed_start_date=data.get("proposed_start_date"),
				ti_requested_cents=data.get("ti_requested_cents", 0),
				free_rent_months=data.get("free_rent_months", 0),
				notes=data.get("notes"),
				expires_at=data.get("expires_at"),
			)
			session.commit()
			return jsonify({"ok": True, "id": loi.id, "status": loi.status}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:loi_id>/accept", methods=["POST"])
	@has_access
	def accept(self, loi_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		tenant_id = data.get("tenant_id", "")
		svc = CommercialLeaseService()
		try:
			loi = svc.accept_loi(loi_id=loi_id, tenant_id=tenant_id, session=session)
			session.commit()
			return jsonify({
				"ok": True,
				"loi_id": loi.id,
				"status": loi.status,
				"property_id": loi.property_id,
				"prospect_party_id": str(loi.prospect_party_id),
			})
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# LeaseAbstractView
# ---------------------------------------------------------------------------

class LeaseAbstractView(BaseERPView):
	"""Lease abstract create and retrieve.

	Widget config:
	  - CurrencyWidget for tenant_improvement_cents
	  - DateWidget for commencement_date, expiry_date, rent_commencement_date
	"""

	route_base = "/industry/commercial-re/abstracts"
	default_view = "get_by_lease"

	widget_config = {
		"tenant_improvement_cents": currency_widget("USD"),
		"commencement_date": date_widget(),
		"expiry_date": date_widget(),
		"rent_commencement_date": date_widget(),
	}

	@expose("/<string:lease_id>")
	@has_access
	def get_by_lease(self, lease_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			LeaseNotFoundError,
		)

		svc = CommercialLeaseService()
		try:
			abstract = svc.get_lease_abstract(lease_id, session)
			return jsonify({"ok": True, "abstract": abstract, "widget_config": self.widget_config})
		except LeaseNotFoundError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 404

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.commercial.services import (
			CommercialLeaseService,
			CommercialREServiceError,
		)

		data = request.get_json(silent=True) or {}
		if not data.get("lease_id") or not data.get("tenant_id"):
			return jsonify({"ok": False, "error": "lease_id and tenant_id required"}), 400

		svc = CommercialLeaseService()
		try:
			abstract = svc.create_lease_abstract(
				lease_id=data.pop("lease_id"),
				tenant_id=data.pop("tenant_id"),
				session=session,
				**data,
			)
			session.commit()
			return jsonify({"ok": True, "id": abstract.id}), 201
		except CommercialREServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CommercialREDashboardView
# ---------------------------------------------------------------------------

class CommercialREDashboardView(BaseERPView):
	"""Commercial Real Estate dashboard — KPI counts and portfolio overview.

	GET /industry/commercial-re/   — HTML dashboard with live KPI cards.
	"""

	route_base = "/industry/commercial-re"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		session = _get_session()

		# Live KPI counts — all wrapped in try/except via self._count()
		active_leases = self._count(CommercialLease, status="ACTIVE")
		vacant_spaces = self._count(SpaceUnit, status="VACANT")
		pending_lois = self._count(LOI, status="SUBMITTED")
		negotiating_lois = self._count(LOI, status="NEGOTIATING")
		draft_recons = self._count(CAMReconciliation, status="DRAFT")
		total_spaces = self._count(SpaceUnit)

		kpi_html = self.kpi_cards([
			{
				"label": "Active Leases",
				"value": active_leases,
				"format": "integer",
				"color": "#057a55",
				"icon": "fa-file-contract",
			},
			{
				"label": "Vacant Spaces",
				"value": vacant_spaces,
				"format": "integer",
				"color": "#e3a008",
				"icon": "fa-building",
			},
			{
				"label": "Pending LOIs",
				"value": pending_lois,
				"format": "integer",
				"color": "#1a56db",
				"icon": "fa-handshake-o",
			},
			{
				"label": "Negotiating LOIs",
				"value": negotiating_lois,
				"format": "integer",
				"color": "#9061f9",
				"icon": "fa-comments",
			},
			{
				"label": "CAM Recons (Draft)",
				"value": draft_recons,
				"format": "integer",
				"color": "#c81e1e",
				"icon": "fa-calculator",
			},
			{
				"label": "Total Spaces",
				"value": total_spaces,
				"format": "integer",
				"color": "#0e9f6e",
				"icon": "fa-th",
			},
		])

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Commercial Real Estate Dashboard</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
<style>body{{padding:24px}}.well{{border-radius:4px}}</style>
</head><body>
<h3>Commercial Real Estate <small>Portfolio Overview</small></h3>
{kpi_html}
<div class="row" style="margin-top:20px">
  <div class="col-md-4">
    <div class="panel panel-default">
      <div class="panel-heading"><strong>Quick Links</strong></div>
      <div class="panel-body">
        <ul class="list-unstyled">
          <li><a href="/industry/commercial-re/spaces/">Space Units</a></li>
          <li><a href="/industry/commercial-re/leases/">Leases</a></li>
          <li><a href="/industry/commercial-re/loi/">Letters of Intent</a></li>
          <li><a href="/industry/commercial-re/cam/">CAM Reconciliation</a></li>
          <li><a href="/industry/commercial-re/abstracts/">Lease Abstracts</a></li>
        </ul>
      </div>
    </div>
  </div>
</div>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"SpaceUnitView",
	"CommercialLeaseView",
	"CAMReconciliationView",
	"LOIView",
	"LeaseAbstractView",
	"CommercialREDashboardView",
]
