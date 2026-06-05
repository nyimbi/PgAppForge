"""
pgappforge/plugins/erp/industry/energy/views.py

Flask views for the Energy & Utilities plugin.

Views:
  MeterView              — CRUD + Read Meter / Generate Bill / Detect Anomalies actions
  MeterReadingView       — CRUD + consumption trend chart
  EnergyBillView         — CRUD + Generate PDF / Post to AR actions
  RenewableAttributeView — CRUD + QR code certificate verification
  CarbonDashboardView    — BaseView at /energy/carbon/ — Scope 1/2/3 breakdown
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

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
	from pgappforge.plugins.erp.industry.energy.services import EnergyService
	return EnergyService()


def _parse_date(s: str | None, default: date | None = None) -> date | None:
	if not s:
		return default
	return date.fromisoformat(s)


# ---------------------------------------------------------------------------
# MeterView
# ---------------------------------------------------------------------------

class MeterView(BaseView):
	"""Meter CRUD + business actions.

	Widget hints (rendered by template layer):
	  - MapWidget:           meter location from service_address + geo_location
	  - ToggleButtonWidget:  smart_meter flag

	GET  /energy/meters/                         — list
	GET  /energy/meters/<id>                     — detail (with map widget hint)
	POST /energy/meters/                         — create
	POST /energy/meters/<id>/read               — ingest a meter reading
	POST /energy/meters/<id>/generate-bill      — generate a bill for a period
	GET  /energy/meters/<id>/anomalies          — detect anomalies
	GET  /energy/meters/<id>/forecast           — demand forecast
	"""

	route_base = "/energy/meters"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.energy.models import Meter
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		meter_type = request.args.get("meter_type")
		q = sa.select(Meter).order_by(Meter.meter_number)
		if tenant_id:
			q = q.where(Meter.tenant_id == tenant_id)
		if meter_type:
			q = q.where(Meter.meter_type == meter_type)
		meters = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": m.id,
				"meter_number": m.meter_number,
				"meter_type": m.meter_type,
				"smart_meter": m.smart_meter,
				"tariff_code": m.tariff_code,
				"customer_id": m.customer_id,
				"customer_account_number": m.customer_account_number,
				"service_address": m.service_address,
				"geo_location": m.geo_location,
				"status": m.status,
				"unit": m.unit,
				# widget hints for the template layer
				"_widget_hints": {
					"smart_meter": "ToggleButtonWidget",
					"geo_location": "MapWidget",
				},
			}
			for m in meters
		])

	@expose("/<string:meter_id>")
	@has_access
	def detail(self, meter_id: str):
		from pgappforge.plugins.erp.industry.energy.models import Meter
		session = _get_session()
		m = session.get(Meter, meter_id)
		if m is None:
			abort(404, f"Meter {meter_id!r} not found")
		return jsonify({
			"id": m.id,
			"tenant_id": m.tenant_id,
			"meter_number": m.meter_number,
			"meter_type": m.meter_type,
			"smart_meter": m.smart_meter,
			"tariff_code": m.tariff_code,
			"customer_id": m.customer_id,
			"customer_account_number": m.customer_account_number,
			"service_address": m.service_address,
			"geo_location": m.geo_location,
			"installation_date": m.installation_date.isoformat() if m.installation_date else None,
			"last_calibration_date": m.last_calibration_date.isoformat() if m.last_calibration_date else None,
			"multiplier": str(m.multiplier),
			"unit": m.unit,
			"status": m.status,
			"notes": m.notes,
			"_widget_hints": {
				"smart_meter": "ToggleButtonWidget",
				"geo_location": "MapWidget",
				"readings_trend": "AdvancedChartsWidget",
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.energy.models import Meter
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "meter_number", "meter_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		meter = Meter(
			tenant_id=data["tenant_id"],
			meter_number=data["meter_number"],
			meter_type=data["meter_type"],
			smart_meter=bool(data.get("smart_meter", False)),
			tariff_code=data.get("tariff_code"),
			customer_id=data.get("customer_id"),
			customer_account_number=data.get("customer_account_number"),
			service_address=data.get("service_address", {}),
			geo_location=data.get("geo_location"),
			multiplier=Decimal(str(data.get("multiplier", "1"))),
			unit=data.get("unit", "kWh"),
			status=data.get("status", "ACTIVE"),
			notes=data.get("notes"),
		)
		session.add(meter)
		session.commit()
		return jsonify({"meter_id": meter.id, "meter_number": meter.meter_number}), 201

	@expose("/<string:meter_id>/read", methods=["POST"])
	@has_access
	def read_meter(self, meter_id: str):
		"""Action: ingest a meter reading."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("read_value", "read_date", "read_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			reading = _svc().ingest_meter_reading(
				meter_id=meter_id,
				read_value=Decimal(str(data["read_value"])),
				read_date=date.fromisoformat(data["read_date"]),
				read_type=data["read_type"],
				session=session,
				read_at=datetime.fromisoformat(data["read_at"]) if data.get("read_at") else None,
				read_by=data.get("read_by"),
				photo_url=data.get("photo_url"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify({
				"reading_id": reading.id,
				"meter_id": meter_id,
				"read_date": reading.read_date.isoformat(),
				"read_value": str(reading.read_value),
				"consumption_kwh": str(reading.consumption_kwh) if reading.consumption_kwh is not None else None,
				"status": reading.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:meter_id>/generate-bill", methods=["POST"])
	@has_access
	def generate_bill(self, meter_id: str):
		"""Action: generate an energy bill for a billing period."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("billing_period_start", "billing_period_end")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			bill = _svc().generate_bill(
				meter_id=meter_id,
				billing_period_start=date.fromisoformat(data["billing_period_start"]),
				billing_period_end=date.fromisoformat(data["billing_period_end"]),
				session=session,
				bill_number=data.get("bill_number"),
				tariff_rates=data.get("tariff_rates"),
				currency_code=data.get("currency_code", "USD"),
				notes=data.get("notes"),
			)
			session.commit()
			return jsonify({
				"bill_id": bill.id,
				"bill_number": bill.bill_number,
				"meter_id": meter_id,
				"consumption_kwh": str(bill.consumption_kwh),
				"amount_cents": bill.amount_cents,
				"currency_code": bill.currency_code,
				"status": bill.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:meter_id>/anomalies")
	@has_access
	def detect_anomalies(self, meter_id: str):
		"""Action: detect anomalous readings for a meter."""
		session = _get_session()
		lookback_days = int(request.args.get("lookback_days", 90))
		std_threshold = float(request.args.get("std_dev_threshold", 2.0))
		try:
			anomalies = _svc().detect_anomalies(
				meter_id, session,
				lookback_days=lookback_days,
				std_dev_threshold=std_threshold,
			)
			return jsonify({
				"meter_id": meter_id,
				"lookback_days": lookback_days,
				"std_dev_threshold": std_threshold,
				"anomaly_count": len(anomalies),
				"anomalies": anomalies,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:meter_id>/forecast")
	@has_access
	def forecast_demand(self, meter_id: str):
		"""Action: forecast demand for a meter."""
		session = _get_session()
		days_ahead = int(request.args.get("days_ahead", 30))
		lookback_days = int(request.args.get("lookback_days", 90))
		try:
			forecasts = _svc().forecast_demand(
				meter_id, session,
				days_ahead=days_ahead,
				lookback_days=lookback_days,
			)
			return jsonify({
				"meter_id": meter_id,
				"days_ahead": days_ahead,
				"forecast_count": len(forecasts),
				"forecasts": forecasts,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# MeterReadingView
# ---------------------------------------------------------------------------

class MeterReadingView(BaseView):
	"""Meter reading list/detail.

	Widget hints:
	  - DatePickerWidget:    read_date
	  - RangeSliderWidget:   anomaly_score (0–5 range)
	  - AdvancedChartsWidget: consumption trend in detail view

	GET  /energy/readings/               — list (filterable by meter_id, date range)
	GET  /energy/readings/<id>           — detail with trend chart hint
	"""

	route_base = "/energy/readings"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.energy.models import MeterReading
		session = _get_session()
		meter_id = request.args.get("meter_id")
		date_from = _parse_date(request.args.get("date_from"))
		date_to = _parse_date(request.args.get("date_to"))
		status = request.args.get("status")
		limit = min(int(request.args.get("limit", 200)), 1000)

		q = (
			sa.select(MeterReading)
			.order_by(MeterReading.read_date.desc(), MeterReading.created_at.desc())
			.limit(limit)
		)
		if meter_id:
			q = q.where(MeterReading.meter_id == meter_id)
		if date_from:
			q = q.where(MeterReading.read_date >= date_from)
		if date_to:
			q = q.where(MeterReading.read_date <= date_to)
		if status:
			q = q.where(MeterReading.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"meter_id": r.meter_id,
				"read_date": r.read_date.isoformat(),
				"read_value": str(r.read_value),
				"previous_read_value": str(r.previous_read_value) if r.previous_read_value is not None else None,
				"consumption_kwh": str(r.consumption_kwh) if r.consumption_kwh is not None else None,
				"read_type": r.read_type,
				"status": r.status,
				"_widget_hints": {
					"read_date": "DatePickerWidget",
					"consumption_trend": "AdvancedChartsWidget",
				},
			}
			for r in rows
		])

	@expose("/<string:reading_id>")
	@has_access
	def detail(self, reading_id: str):
		from pgappforge.plugins.erp.industry.energy.models import MeterReading
		session = _get_session()
		r = session.get(MeterReading, reading_id)
		if r is None:
			abort(404, f"MeterReading {reading_id!r} not found")
		return jsonify({
			"id": r.id,
			"tenant_id": r.tenant_id,
			"meter_id": r.meter_id,
			"read_date": r.read_date.isoformat(),
			"read_at": r.read_at.isoformat() if r.read_at else None,
			"read_value": str(r.read_value),
			"previous_read_value": str(r.previous_read_value) if r.previous_read_value is not None else None,
			"consumption_kwh": str(r.consumption_kwh) if r.consumption_kwh is not None else None,
			"read_type": r.read_type,
			"read_by": r.read_by,
			"photo_url": r.photo_url,
			"status": r.status,
			"notes": r.notes,
			"created_at": r.created_at.isoformat() if r.created_at else None,
			"_widget_hints": {
				"consumption_kwh": "RangeSliderWidget",
				"read_date": "DatePickerWidget",
				"consumption_trend": "AdvancedChartsWidget",
			},
		})


# ---------------------------------------------------------------------------
# EnergyBillView
# ---------------------------------------------------------------------------

class EnergyBillView(BaseView):
	"""Energy bill list/detail + actions.

	Widget hints:
	  - CurrencyWidget:    amount_cents, energy_charge_cents, etc.
	  - DateRangeWidget:   billing_period_start / billing_period_end

	GET  /energy/bills/                      — list
	GET  /energy/bills/<id>                  — detail
	POST /energy/bills/<id>/issue           — issue (DRAFT → ISSUED)
	POST /energy/bills/<id>/pay            — record payment
	GET  /energy/bills/<id>/pdf-stub        — generate PDF stub (placeholder)
	POST /energy/bills/<id>/post-to-ar     — post to AR (stub)
	"""

	route_base = "/energy/bills"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		session = _get_session()
		meter_id = request.args.get("meter_id")
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(EnergyBill)
			.order_by(EnergyBill.billing_period_start.desc())
			.limit(limit)
		)
		if meter_id:
			q = q.where(EnergyBill.meter_id == meter_id)
		if tenant_id:
			q = q.where(EnergyBill.tenant_id == tenant_id)
		if status:
			q = q.where(EnergyBill.status == status)

		bills = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": b.id,
				"bill_number": b.bill_number,
				"meter_id": b.meter_id,
				"customer_id": b.customer_id,
				"billing_period_start": b.billing_period_start.isoformat(),
				"billing_period_end": b.billing_period_end.isoformat(),
				"consumption_kwh": str(b.consumption_kwh),
				"amount_cents": b.amount_cents,
				"paid_cents": b.paid_cents,
				"currency_code": b.currency_code,
				"status": b.status,
				"_widget_hints": {
					"amount_cents": "CurrencyWidget",
					"paid_cents": "CurrencyWidget",
					"billing_period": "DateRangeWidget",
				},
			}
			for b in bills
		])

	@expose("/<string:bill_id>")
	@has_access
	def detail(self, bill_id: str):
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		session = _get_session()
		b = session.get(EnergyBill, bill_id)
		if b is None:
			abort(404, f"EnergyBill {bill_id!r} not found")
		return jsonify({
			"id": b.id,
			"tenant_id": b.tenant_id,
			"bill_number": b.bill_number,
			"meter_id": b.meter_id,
			"customer_id": b.customer_id,
			"billing_period_start": b.billing_period_start.isoformat(),
			"billing_period_end": b.billing_period_end.isoformat(),
			"issue_date": b.issue_date.isoformat() if b.issue_date else None,
			"due_date": b.due_date.isoformat() if b.due_date else None,
			"consumption_kwh": str(b.consumption_kwh),
			"opening_read": str(b.opening_read) if b.opening_read is not None else None,
			"closing_read": str(b.closing_read) if b.closing_read is not None else None,
			"energy_charge_cents": b.energy_charge_cents,
			"network_charge_cents": b.network_charge_cents,
			"standing_charge_cents": b.standing_charge_cents,
			"tax_cents": b.tax_cents,
			"amount_cents": b.amount_cents,
			"paid_cents": b.paid_cents,
			"currency_code": b.currency_code,
			"tariff_code": b.tariff_code,
			"bill_breakdown": b.bill_breakdown,
			"status": b.status,
			"notes": b.notes,
			"_widget_hints": {
				"amount_cents": "CurrencyWidget",
				"paid_cents": "CurrencyWidget",
				"energy_charge_cents": "CurrencyWidget",
				"billing_period": "DateRangeWidget",
			},
		})

	@expose("/<string:bill_id>/issue", methods=["POST"])
	@has_access
	def issue(self, bill_id: str):
		"""Transition bill from DRAFT → ISSUED."""
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		from pgappforge.plugins.erp.industry.energy.events import EnergyBillIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		b = session.get(EnergyBill, bill_id)
		if b is None:
			abort(404)
		if b.status != "DRAFT":
			return jsonify({"error": f"Bill status is {b.status!r}; only DRAFT bills can be issued"}), 422

		data = request.get_json(force=True) or {}
		b.status = "ISSUED"
		b.issue_date = date.today()
		if data.get("due_date"):
			b.due_date = date.fromisoformat(data["due_date"])
		elif b.due_date is None:
			b.due_date = date.today() + timedelta(days=30)

		emit_event(
			EnergyBillIssuedEvent(
				aggregate_id=bill_id,
				aggregate_type="EnergyBill",
				tenant_id=b.tenant_id,
				bill_id=bill_id,
				bill_number=b.bill_number,
				meter_id=b.meter_id,
				customer_id=b.customer_id or "",
				billing_period_start=b.billing_period_start.isoformat(),
				billing_period_end=b.billing_period_end.isoformat(),
				amount_cents=b.amount_cents,
				currency=b.currency_code,
				due_date=b.due_date.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({
			"bill_id": bill_id,
			"bill_number": b.bill_number,
			"status": "ISSUED",
			"issue_date": b.issue_date.isoformat(),
			"due_date": b.due_date.isoformat(),
			"amount_cents": b.amount_cents,
		})

	@expose("/<string:bill_id>/pay", methods=["POST"])
	@has_access
	def record_payment(self, bill_id: str):
		"""Record a payment against an issued bill."""
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		from pgappforge.plugins.erp.industry.energy.events import EnergyBillPaidEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		b = session.get(EnergyBill, bill_id)
		if b is None:
			abort(404)
		if b.status not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
			return jsonify({"error": f"Bill status {b.status!r} cannot accept payment"}), 422

		data = request.get_json(force=True) or {}
		payment_cents = int(data.get("payment_cents", 0))
		if payment_cents <= 0:
			return jsonify({"error": "payment_cents must be a positive integer"}), 400

		b.paid_cents += payment_cents
		if b.paid_cents >= b.amount_cents:
			b.paid_cents = b.amount_cents
			b.status = "PAID"
			emit_event(
				EnergyBillPaidEvent(
					aggregate_id=bill_id,
					aggregate_type="EnergyBill",
					tenant_id=b.tenant_id,
					bill_id=bill_id,
					bill_number=b.bill_number,
					meter_id=b.meter_id,
					customer_id=b.customer_id or "",
					amount_cents=b.amount_cents,
					currency=b.currency_code,
				),
				session,
			)
		else:
			b.status = "PARTIALLY_PAID"

		session.commit()
		return jsonify({
			"bill_id": bill_id,
			"paid_cents": b.paid_cents,
			"amount_cents": b.amount_cents,
			"status": b.status,
		})

	@expose("/<string:bill_id>/pdf-stub")
	@has_access
	def pdf_stub(self, bill_id: str):
		"""Action: Generate PDF — returns metadata stub.

		Full PDF generation requires a PDF renderer (WeasyPrint / ReportLab).
		"""
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		session = _get_session()
		b = session.get(EnergyBill, bill_id)
		if b is None:
			abort(404)
		return jsonify({
			"bill_id": bill_id,
			"bill_number": b.bill_number,
			"pdf_status": "stub",
			"message": "PDF generation requires a configured renderer (WeasyPrint/ReportLab).",
			"bill_data": {
				"amount_cents": b.amount_cents,
				"currency_code": b.currency_code,
				"billing_period_start": b.billing_period_start.isoformat(),
				"billing_period_end": b.billing_period_end.isoformat(),
				"consumption_kwh": str(b.consumption_kwh),
				"status": b.status,
			},
		})

	@expose("/<string:bill_id>/post-to-ar", methods=["POST"])
	@has_access
	def post_to_ar(self, bill_id: str):
		"""Action: Post to AR — emits integration event for AR module.

		Full AR posting requires the finance.ar plugin to be loaded.
		"""
		from pgappforge.plugins.erp.industry.energy.models import EnergyBill
		session = _get_session()
		b = session.get(EnergyBill, bill_id)
		if b is None:
			abort(404)
		if b.status not in ("ISSUED", "OVERDUE"):
			return jsonify({"error": f"Only ISSUED or OVERDUE bills can be posted to AR"}), 422

		# Attempt to call AR plugin integration if available
		ar_invoice_id = None
		try:
			from flask import current_app
			ar = current_app.extensions.get("pgaf_ar")
			if ar is not None:
				ar_invoice_id = ar.create_invoice_from_energy_bill(bill_id, session)
		except Exception as exc:
			log.warning("post_to_ar: AR integration not available (%s)", exc)

		return jsonify({
			"bill_id": bill_id,
			"bill_number": b.bill_number,
			"ar_invoice_id": ar_invoice_id,
			"status": "queued" if ar_invoice_id is None else "posted",
			"message": (
				"AR invoice created." if ar_invoice_id
				else "AR plugin not loaded; bill queued for manual AR posting."
			),
		})


# ---------------------------------------------------------------------------
# RenewableAttributeView
# ---------------------------------------------------------------------------

class RenewableAttributeView(BaseView):
	"""Renewable Energy Certificate (REC/REGO/GO) list/detail + retire action.

	Widget hints:
	  - QrCodeWidget:        certificate_id QR for verification (detail view)
	  - ToggleButtonWidget:  retired flag

	GET  /energy/certificates/                  — list
	GET  /energy/certificates/<id>              — detail
	POST /energy/certificates/                  — issue certificate
	POST /energy/certificates/<id>/retire       — retire certificate
	"""

	route_base = "/energy/certificates"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.energy.models import RenewableAttribute
		session = _get_session()
		energy_type = request.args.get("energy_type")
		retired = request.args.get("retired")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(RenewableAttribute)
			.order_by(RenewableAttribute.generation_date.desc())
			.limit(limit)
		)
		if energy_type:
			q = q.where(RenewableAttribute.energy_type == energy_type)
		if tenant_id:
			q = q.where(RenewableAttribute.tenant_id == tenant_id)
		if retired is not None:
			q = q.where(RenewableAttribute.retired == (retired.lower() == "true"))

		certs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"certificate_id": c.certificate_id,
				"energy_type": c.energy_type,
				"generation_mwh": str(c.generation_mwh),
				"generation_date": c.generation_date.isoformat(),
				"registry_name": c.registry_name,
				"generation_facility_name": c.generation_facility_name,
				"generation_country": c.generation_country,
				"retired": c.retired,
				"issued_date": c.issued_date.isoformat() if c.issued_date else None,
				"_widget_hints": {
					"retired": "ToggleButtonWidget",
					"certificate_id": "QrCodeWidget",
				},
			}
			for c in certs
		])

	@expose("/<string:cert_id>")
	@has_access
	def detail(self, cert_id: str):
		from pgappforge.plugins.erp.industry.energy.models import RenewableAttribute
		session = _get_session()
		c = session.get(RenewableAttribute, cert_id)
		if c is None:
			abort(404, f"RenewableAttribute {cert_id!r} not found")

		# Build QR verification URL hint
		qr_data = f"REC:{c.certificate_id}:{c.registry_name or 'UNREGISTERED'}:{c.generation_mwh}"

		return jsonify({
			"id": c.id,
			"tenant_id": c.tenant_id,
			"certificate_id": c.certificate_id,
			"energy_type": c.energy_type,
			"generation_mwh": str(c.generation_mwh),
			"generation_date": c.generation_date.isoformat(),
			"generation_facility_id": c.generation_facility_id,
			"generation_facility_name": c.generation_facility_name,
			"generation_country": c.generation_country,
			"registry_id": c.registry_id,
			"registry_name": c.registry_name,
			"issued_date": c.issued_date.isoformat() if c.issued_date else None,
			"expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
			"retired": c.retired,
			"retired_at": c.retired_at.isoformat() if c.retired_at else None,
			"retired_by_id": c.retired_by_id,
			"retirement_purpose": c.retirement_purpose,
			"holder_id": c.holder_id,
			"metadata": c.metadata_,
			"_qr_data": qr_data,
			"_widget_hints": {
				"retired": "ToggleButtonWidget",
				"certificate_id": "QrCodeWidget",
				"_qr_data": "QrCodeWidget",
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Issue a new renewable energy certificate."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "generation_mwh", "energy_type", "generation_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			cert = _svc().issue_renewable_certificate(
				tenant_id=data["tenant_id"],
				generation_mwh=Decimal(str(data["generation_mwh"])),
				energy_type=data["energy_type"],
				generation_date=date.fromisoformat(data["generation_date"]),
				session=session,
				certificate_id=data.get("certificate_id"),
				generation_facility_name=data.get("generation_facility_name"),
				generation_country=data.get("generation_country"),
				registry_name=data.get("registry_name"),
				holder_id=data.get("holder_id"),
				metadata=data.get("metadata"),
			)
			session.commit()
			return jsonify({
				"certificate_record_id": cert.id,
				"certificate_id": cert.certificate_id,
				"energy_type": cert.energy_type,
				"generation_mwh": str(cert.generation_mwh),
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:cert_id>/retire", methods=["POST"])
	@has_access
	def retire(self, cert_id: str):
		"""Retire a certificate — IMMUTABLE once retired."""
		from pgappforge.plugins.erp.industry.energy.models import RenewableAttribute
		from pgappforge.plugins.erp.industry.energy.events import RenewableCertificateRetiredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		session = _get_session()
		c = session.get(RenewableAttribute, cert_id)
		if c is None:
			abort(404)
		if c.retired:
			return jsonify({"error": "Certificate is already retired"}), 422

		data = request.get_json(force=True) or {}
		c.retired = True
		c.retired_at = datetime.now(datetime.timezone.utc) if hasattr(datetime, "timezone") else datetime.utcnow().replace(tzinfo=None)
		try:
			from datetime import timezone as _tz
			c.retired_at = datetime.now(_tz.utc)
		except Exception:
			pass
		c.retired_by_id = data.get("retired_by_id")
		c.retirement_purpose = data.get("retirement_purpose", "VOLUNTARY")

		emit_event(
			RenewableCertificateRetiredEvent(
				aggregate_id=cert_id,
				aggregate_type="RenewableAttribute",
				tenant_id=c.tenant_id,
				certificate_record_id=cert_id,
				certificate_id=c.certificate_id,
				energy_type=c.energy_type,
				generation_mwh=str(c.generation_mwh),
				registry_name=c.registry_name or "",
				retirement_purpose=c.retirement_purpose or "VOLUNTARY",
				retired_by_id=str(c.retired_by_id) if c.retired_by_id else "",
			),
			session,
		)
		session.commit()
		return jsonify({
			"certificate_id": c.certificate_id,
			"retired": True,
			"retirement_purpose": c.retirement_purpose,
		})


# ---------------------------------------------------------------------------
# CarbonDashboardView
# ---------------------------------------------------------------------------

class CarbonDashboardView(BaseView):
	"""Carbon footprint dashboard at /energy/carbon/.

	Widget hints:
	  - AdvancedChartsWidget: bar chart by meter + trend over time
	  - Shows Scope 1 / Scope 2 / Scope 3 breakdown (Scope 1 & 3 are stubs)

	GET /energy/carbon/                          — index / summary
	GET /energy/carbon/meter/<meter_id>          — per-meter carbon detail
	GET /energy/carbon/summary                   — tenant-level summary
	"""

	route_base = "/energy/carbon"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"title": "Carbon Footprint Dashboard",
			"description": "Scope 2 market-based CO2e from metered electricity consumption.",
			"endpoints": {
				"per_meter": "/energy/carbon/meter/<meter_id>?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD",
				"summary": "/energy/carbon/summary?tenant_id=<id>&period_start=YYYY-MM-DD&period_end=YYYY-MM-DD",
			},
			"scopes": {
				"SCOPE_1": "Direct combustion — not yet implemented (requires fuel consumption module)",
				"SCOPE_2": "Grid electricity consumption — calculated from meter readings",
				"SCOPE_3": "Value-chain emissions — not yet implemented",
			},
			"_widget_hints": {
				"charts": "AdvancedChartsWidget",
				"type": "bar+trend",
			},
		})

	@expose("/meter/<string:meter_id>")
	@has_access
	def meter_carbon(self, meter_id: str):
		"""Return carbon footprint for a specific meter over a period."""
		session = _get_session()
		period_start = _parse_date(request.args.get("period_start"), date.today().replace(day=1))
		period_end = _parse_date(request.args.get("period_end"), date.today())
		emission_factor = request.args.get("emission_factor")

		try:
			result = _svc().calculate_carbon_footprint(
				meter_id=meter_id,
				period_start=period_start,
				period_end=period_end,
				session=session,
				emission_factor_tco2e_per_kwh=Decimal(emission_factor) if emission_factor else None,
			)
			result["_widget_hints"] = {
				"total_tco2e": "AdvancedChartsWidget",
				"chart_type": "bar",
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/summary")
	@has_access
	def summary(self):
		"""Return carbon footprint summary across all meters for a tenant."""
		from pgappforge.plugins.erp.industry.energy.models import Meter
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		period_start = _parse_date(request.args.get("period_start"), date.today().replace(day=1))
		period_end = _parse_date(request.args.get("period_end"), date.today())

		meters = session.execute(
			sa.select(Meter).where(
				Meter.tenant_id == tenant_id,
				Meter.status == "ACTIVE",
			)
		).scalars().all()

		meter_results = []
		total_kwh = Decimal("0")
		total_tco2e = Decimal("0")

		for m in meters:
			try:
				r = _svc().calculate_carbon_footprint(
					meter_id=m.id,
					period_start=period_start,
					period_end=period_end,
					session=session,
				)
				meter_results.append({
					"meter_id": m.id,
					"meter_number": m.meter_number,
					"meter_type": m.meter_type,
					"consumption_kwh": r["consumption_kwh"],
					"total_tco2e": r["total_tco2e"],
				})
				total_kwh += Decimal(r["consumption_kwh"])
				total_tco2e += Decimal(r["total_tco2e"])
			except Exception as exc:
				log.warning("summary: skipping meter %r: %s", m.id, exc)

		return jsonify({
			"tenant_id": tenant_id,
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"total_consumption_kwh": str(total_kwh),
			"total_tco2e": str(total_tco2e),
			"scope": "SCOPE_2",
			"meter_count": len(meter_results),
			"meters": meter_results,
			"scope_breakdown": {
				"SCOPE_1": {"total_tco2e": "0", "status": "not_implemented"},
				"SCOPE_2": {"total_tco2e": str(total_tco2e), "status": "calculated"},
				"SCOPE_3": {"total_tco2e": "0", "status": "not_implemented"},
			},
			"_widget_hints": {
				"charts": "AdvancedChartsWidget",
				"type": "bar+trend",
			},
		})


__all__ = [
	"MeterView",
	"MeterReadingView",
	"EnergyBillView",
	"RenewableAttributeView",
	"CarbonDashboardView",
]
