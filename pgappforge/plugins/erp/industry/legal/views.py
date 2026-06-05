"""
pgappforge/plugins/erp/industry/legal/views.py

Flask views for the Legal Services plugin.

Views:
  MatterView          — matter CRUD with status workflow + profitability
  DocumentView        — document CRUD with versioning and execution
  TimeEntryView       — time entry CRUD with approval workflow
  DeadlineCalendarView — deadline list and status tracking
  LegalInvoiceView    — invoice generation and status management
  LegalReportView     — docket, profitability, deadline calendar reports
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	datetime_widget,
	rich_text_widget,
	select2_widget,
	select2_ajax_widget,
	select2_many_widget,
	file_widget,
	chart_widget,
	signature_widget,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Widget metadata — consumed by front-end widget renderer
# ---------------------------------------------------------------------------

MATTER_WIDGETS = {
	"matter_type": select2_widget(
		choices=["LITIGATION", "TRANSACTION", "ADVISORY", "COMPLIANCE", "IP"]
	),
	"status": select2_widget(
		choices=["INTAKE", "ACTIVE", "DISCOVERY", "TRIAL", "APPEAL", "SETTLED", "CLOSED"]
	),
	"description": rich_text_widget(height=250),
	"budget_cents": currency_widget("USD"),
	"billed_cents": currency_widget("USD"),
	"filed_date": date_widget(),
	"target_resolution_date": date_widget(),
	"client_id": select2_ajax_widget(),
	"lead_counsel_id": select2_ajax_widget(),
	"opposing_party_id": select2_ajax_widget(),
}

DOCUMENT_WIDGETS = {
	"document_type": select2_widget(
		choices=["CONTRACT", "PLEADING", "BRIEF", "ORDER", "JUDGMENT", "MEMO"]
	),
	"status": select2_widget(
		choices=["DRAFT", "REVIEW", "FINAL", "EXECUTED", "SUPERSEDED"]
	),
	"content_url": file_widget(types=["pdf", "docx", "txt"]),
	"executed_at": datetime_widget(),
	"expiry_date": date_widget(),
	# Signature widget renders on EXECUTED documents
	"_signature": signature_widget(),
}

TIME_ENTRY_WIDGETS = {
	"work_date": date_widget(),
	"amount_cents": currency_widget("USD"),
	"rate_cents_per_hour": currency_widget("USD"),
	"status": select2_widget(
		choices=["DRAFT", "SUBMITTED", "APPROVED", "BILLED"]
	),
}

DEADLINE_WIDGETS = {
	"deadline_type": select2_widget(
		choices=["STATUTE_OF_LIMITATIONS", "FILING", "HEARING", "DISCOVERY_CLOSE"]
	),
	"deadline_date": date_widget(),
	"status": select2_widget(choices=["PENDING", "MET", "MISSED", "EXTENDED"]),
	"responsible_id": select2_ajax_widget(),
}

INVOICE_WIDGETS = {
	"billing_period_start": date_widget(),
	"billing_period_end": date_widget(),
	"time_charges_cents": currency_widget("USD"),
	"disbursements_cents": currency_widget("USD"),
	"tax_cents": currency_widget("USD"),
	"total_cents": currency_widget("USD"),
	"status": select2_widget(choices=["DRAFT", "SENT", "PAID", "DISPUTED"]),
}


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
	from pgappforge.plugins.erp.industry.legal.services import LegalService
	return LegalService()


# ---------------------------------------------------------------------------
# MatterView
# ---------------------------------------------------------------------------

class MatterView(BaseView):
	"""Legal matter CRUD + workflow actions.

	GET  /legal/matters/                   — list (filterable by status/client)
	POST /legal/matters/                   — open new matter
	GET  /legal/matters/<id>               — detail
	POST /legal/matters/<id>/status        — transition status
	GET  /legal/matters/<id>/profitability — profitability report
	GET  /legal/matters/<id>/docket        — matter docket
	"""

	route_base = "/legal/matters"
	default_view = "list"
	_widgets = MATTER_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter
		session = _get_session()
		q = sa.select(LegalMatter).order_by(LegalMatter.matter_number)
		if request.args.get("tenant_id"):
			q = q.where(LegalMatter.tenant_id == request.args["tenant_id"])
		if request.args.get("status"):
			q = q.where(LegalMatter.status == request.args["status"])
		if request.args.get("client_id"):
			q = q.where(LegalMatter.client_id == request.args["client_id"])
		matters = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": m.id,
				"matter_number": m.matter_number,
				"matter_type": m.matter_type,
				"client_id": m.client_id,
				"lead_counsel_id": m.lead_counsel_id,
				"jurisdiction": m.jurisdiction,
				"status": m.status,
				"budget_cents": m.budget_cents,
				"billed_cents": m.billed_cents,
				"filed_date": m.filed_date.isoformat() if m.filed_date else None,
				"target_resolution_date": (
					m.target_resolution_date.isoformat()
					if m.target_resolution_date else None
				),
			}
			for m in matters
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "client_id", "matter_type", "lead_counsel_id", "jurisdiction")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			matter = _svc().open_matter(
				tenant_id=data["tenant_id"],
				client_id=data["client_id"],
				matter_type=data["matter_type"],
				lead_counsel_id=data["lead_counsel_id"],
				jurisdiction=data["jurisdiction"],
				details=data,
				session=session,
			)
			session.commit()
			return jsonify({"matter_id": matter.id, "matter_number": matter.matter_number}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:matter_id>")
	@has_access
	def detail(self, matter_id: str):
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter
		session = _get_session()
		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			abort(404)
		return jsonify({
			"id": matter.id,
			"matter_number": matter.matter_number,
			"matter_type": matter.matter_type,
			"client_id": matter.client_id,
			"lead_counsel_id": matter.lead_counsel_id,
			"opposing_party_id": matter.opposing_party_id,
			"jurisdiction": matter.jurisdiction,
			"court": matter.court,
			"status": matter.status,
			"description": matter.description,
			"filed_date": matter.filed_date.isoformat() if matter.filed_date else None,
			"target_resolution_date": (
				matter.target_resolution_date.isoformat()
				if matter.target_resolution_date else None
			),
			"budget_cents": matter.budget_cents,
			"billed_cents": matter.billed_cents,
		})

	@expose("/<string:matter_id>/status", methods=["POST"])
	@has_access
	def change_status(self, matter_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("status"):
			return jsonify({"error": "status required"}), 400
		try:
			result = _svc().change_matter_status(matter_id, data["status"], session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:matter_id>/profitability")
	@has_access
	def profitability(self, matter_id: str):
		session = _get_session()
		try:
			result = _svc().calculate_matter_profitability(matter_id, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:matter_id>/docket")
	@has_access
	def docket(self, matter_id: str):
		session = _get_session()
		try:
			result = _svc().get_docket(matter_id, session)
			return jsonify({"matter_id": matter_id, "docket": result})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# DocumentView
# ---------------------------------------------------------------------------

class DocumentView(BaseView):
	"""Legal document CRUD with versioning and execution workflow.

	GET  /legal/documents/              — list (filterable by matter_id/type)
	POST /legal/documents/              — create document
	GET  /legal/documents/<id>          — detail
	POST /legal/documents/<id>/execute  — mark as EXECUTED (triggers signature)
	"""

	route_base = "/legal/documents"
	default_view = "list"
	_widgets = DOCUMENT_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.legal.models import LegalDocument
		session = _get_session()
		q = sa.select(LegalDocument).order_by(LegalDocument.created_at.desc()).limit(200)
		if request.args.get("matter_id"):
			q = q.where(LegalDocument.matter_id == request.args["matter_id"])
		if request.args.get("document_type"):
			q = q.where(LegalDocument.document_type == request.args["document_type"])
		if request.args.get("status"):
			q = q.where(LegalDocument.status == request.args["status"])
		docs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"matter_id": d.matter_id,
				"document_type": d.document_type,
				"title": d.title,
				"version": d.version,
				"status": d.status,
				"author_id": d.author_id,
				"created_at": d.created_at.isoformat() if d.created_at else None,
				"executed_at": d.executed_at.isoformat() if d.executed_at else None,
				"expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
			}
			for d in docs
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.legal.models import LegalDocument
		from pgappforge.plugins.erp.industry.legal.events import (
			DocumentCreatedEvent, emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "matter_id", "document_type", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			doc = LegalDocument(
				tenant_id=data["tenant_id"],
				matter_id=data["matter_id"],
				document_type=data["document_type"],
				title=data["title"],
				version=data.get("version", "1.0"),
				status="DRAFT",
				author_id=data.get("author_id"),
				content_url=data.get("content_url"),
				checksum_sha256=data.get("checksum_sha256"),
				parties=data.get("parties", []),
				expiry_date=data.get("expiry_date"),
			)
			session.add(doc)
			session.flush()
			emit_event(
				DocumentCreatedEvent(
					aggregate_id=doc.id,
					aggregate_type="LegalDocument",
					tenant_id=doc.tenant_id,
					document_id=doc.id,
					matter_id=doc.matter_id,
					document_type=doc.document_type,
					title=doc.title,
				),
				session,
			)
			session.commit()
			return jsonify({"document_id": doc.id, "status": doc.status}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:document_id>")
	@has_access
	def detail(self, document_id: str):
		from pgappforge.plugins.erp.industry.legal.models import LegalDocument
		session = _get_session()
		doc = session.get(LegalDocument, document_id)
		if doc is None:
			abort(404)
		return jsonify({
			"id": doc.id,
			"matter_id": doc.matter_id,
			"document_type": doc.document_type,
			"title": doc.title,
			"version": doc.version,
			"status": doc.status,
			"author_id": doc.author_id,
			"content_url": doc.content_url,
			"checksum_sha256": doc.checksum_sha256,
			"parties": doc.parties,
			"expiry_date": doc.expiry_date.isoformat() if doc.expiry_date else None,
			"created_at": doc.created_at.isoformat() if doc.created_at else None,
			"executed_at": doc.executed_at.isoformat() if doc.executed_at else None,
			# Widget hint: render signature pad for EXECUTED status
			"_widget_hints": DOCUMENT_WIDGETS,
		})

	@expose("/<string:document_id>/execute", methods=["POST"])
	@has_access
	def execute(self, document_id: str):
		"""Mark a document as EXECUTED with timestamp."""
		from pgappforge.plugins.erp.industry.legal.models import LegalDocument
		from pgappforge.plugins.erp.industry.legal.events import (
			DocumentExecutedEvent, emit_event,
		)
		from datetime import datetime, timezone
		session = _get_session()
		doc = session.get(LegalDocument, document_id)
		if doc is None:
			abort(404)
		if doc.status in ("EXECUTED", "SUPERSEDED"):
			return jsonify({"error": f"Document is already {doc.status!r}"}), 422
		now = datetime.now(timezone.utc)
		doc.status = "EXECUTED"
		doc.executed_at = now
		emit_event(
			DocumentExecutedEvent(
				aggregate_id=document_id,
				aggregate_type="LegalDocument",
				tenant_id=doc.tenant_id,
				document_id=document_id,
				matter_id=doc.matter_id,
				document_type=doc.document_type,
				executed_at=now.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({
			"document_id": document_id,
			"status": "EXECUTED",
			"executed_at": now.isoformat(),
		})


# ---------------------------------------------------------------------------
# TimeEntryView
# ---------------------------------------------------------------------------

class TimeEntryView(BaseView):
	"""Time entry recording and approval.

	GET  /legal/time-entries/              — list (filterable by matter/status)
	POST /legal/time-entries/              — record time entry
	POST /legal/time-entries/<id>/approve  — approve entry
	POST /legal/time-entries/<id>/submit   — submit for approval
	"""

	route_base = "/legal/time-entries"
	default_view = "list"
	_widgets = TIME_ENTRY_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.legal.models import TimeEntry
		session = _get_session()
		q = sa.select(TimeEntry).order_by(TimeEntry.work_date.desc()).limit(500)
		if request.args.get("matter_id"):
			q = q.where(TimeEntry.matter_id == request.args["matter_id"])
		if request.args.get("timekeeper_id"):
			q = q.where(TimeEntry.timekeeper_id == request.args["timekeeper_id"])
		if request.args.get("status"):
			q = q.where(TimeEntry.status == request.args["status"])
		entries = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": e.id,
				"matter_id": e.matter_id,
				"timekeeper_id": e.timekeeper_id,
				"work_date": e.work_date.isoformat() if e.work_date else None,
				"hours": float(e.hours),
				"rate_cents_per_hour": e.rate_cents_per_hour,
				"amount_cents": e.amount_cents,
				"activity_code": e.activity_code,
				"description": e.description,
				"status": e.status,
				"is_billable": e.is_billable,
			}
			for e in entries
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "matter_id", "timekeeper_id",
			"hours", "description", "activity_code", "rate_cents_per_hour",
		)
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			from datetime import date as _date
			work_date_raw = data.get("work_date")
			work_date = (
				_date.fromisoformat(work_date_raw)
				if work_date_raw else None
			)
			entry = _svc().record_time(
				tenant_id=data["tenant_id"],
				matter_id=data["matter_id"],
				timekeeper_id=data["timekeeper_id"],
				hours=float(data["hours"]),
				description=data["description"],
				activity_code=data["activity_code"],
				rate_cents_per_hour=int(data["rate_cents_per_hour"]),
				work_date=work_date,
				is_billable=data.get("is_billable", True),
				session=session,
			)
			session.commit()
			return jsonify({
				"time_entry_id": entry.id,
				"amount_cents": entry.amount_cents,
				"status": entry.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:entry_id>/submit", methods=["POST"])
	@has_access
	def submit(self, entry_id: str):
		from pgappforge.plugins.erp.industry.legal.models import TimeEntry
		session = _get_session()
		entry = session.get(TimeEntry, entry_id)
		if entry is None:
			abort(404)
		if entry.status != "DRAFT":
			return jsonify({"error": f"Entry is {entry.status!r}, not DRAFT"}), 422
		entry.status = "SUBMITTED"
		session.commit()
		return jsonify({"time_entry_id": entry_id, "status": "SUBMITTED"})

	@expose("/<string:entry_id>/approve", methods=["POST"])
	@has_access
	def approve(self, entry_id: str):
		from pgappforge.plugins.erp.industry.legal.models import TimeEntry
		session = _get_session()
		entry = session.get(TimeEntry, entry_id)
		if entry is None:
			abort(404)
		if entry.status != "SUBMITTED":
			return jsonify({"error": f"Entry is {entry.status!r}, not SUBMITTED"}), 422
		entry.status = "APPROVED"
		session.commit()
		return jsonify({"time_entry_id": entry_id, "status": "APPROVED"})


# ---------------------------------------------------------------------------
# DeadlineCalendarView
# ---------------------------------------------------------------------------

class DeadlineCalendarView(BaseView):
	"""Deadline tracking with calendar-style output.

	GET  /legal/deadlines/              — list / calendar (filterable by matter)
	POST /legal/deadlines/              — track new deadline
	POST /legal/deadlines/<id>/status   — update deadline status
	GET  /legal/deadlines/upcoming      — deadlines in next N days
	"""

	route_base = "/legal/deadlines"
	default_view = "list"
	_widgets = DEADLINE_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.legal.models import Deadline
		session = _get_session()
		q = sa.select(Deadline).order_by(Deadline.deadline_date)
		if request.args.get("matter_id"):
			q = q.where(Deadline.matter_id == request.args["matter_id"])
		if request.args.get("status"):
			q = q.where(Deadline.status == request.args["status"])
		if request.args.get("tenant_id"):
			q = q.where(Deadline.tenant_id == request.args["tenant_id"])
		deadlines = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"matter_id": d.matter_id,
				"deadline_type": d.deadline_type,
				"deadline_date": d.deadline_date.isoformat() if d.deadline_date else None,
				"description": d.description,
				"is_hard_deadline": d.is_hard_deadline,
				"status": d.status,
				"responsible_id": d.responsible_id,
			}
			for d in deadlines
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "matter_id", "deadline_type", "deadline_date", "description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			from datetime import date as _date
			dl = _svc().track_deadline(
				tenant_id=data["tenant_id"],
				matter_id=data["matter_id"],
				deadline_type=data["deadline_type"],
				deadline_date=_date.fromisoformat(data["deadline_date"]),
				description=data["description"],
				is_hard_deadline=data.get("is_hard_deadline", True),
				responsible_id=data.get("responsible_id"),
				session=session,
			)
			session.commit()
			return jsonify({
				"deadline_id": dl.id,
				"deadline_date": dl.deadline_date.isoformat(),
				"status": dl.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:deadline_id>/status", methods=["POST"])
	@has_access
	def update_status(self, deadline_id: str):
		from pgappforge.plugins.erp.industry.legal.models import Deadline
		from pgappforge.plugins.erp.industry.legal.events import (
			DeadlineMissedEvent, emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("status"):
			return jsonify({"error": "status required"}), 400
		dl = session.get(Deadline, deadline_id)
		if dl is None:
			abort(404)
		dl.status = data["status"]
		if data["status"] == "MISSED" and dl.is_hard_deadline:
			emit_event(
				DeadlineMissedEvent(
					aggregate_id=deadline_id,
					aggregate_type="Deadline",
					tenant_id=dl.tenant_id,
					deadline_id=deadline_id,
					matter_id=dl.matter_id,
					deadline_type=dl.deadline_type,
					deadline_date=dl.deadline_date.isoformat() if dl.deadline_date else "",
					responsible_id=dl.responsible_id or "",
				),
				session,
			)
		session.commit()
		return jsonify({"deadline_id": deadline_id, "status": data["status"]})

	@expose("/upcoming")
	@has_access
	def upcoming(self):
		"""Deadlines in the next N days (default 14)."""
		from pgappforge.plugins.erp.industry.legal.models import Deadline
		from datetime import date, timedelta
		session = _get_session()
		days = int(request.args.get("days", 14))
		tenant_id = request.args.get("tenant_id")
		today = date.today()
		cutoff = today + timedelta(days=days)
		q = (
			sa.select(Deadline)
			.where(
				Deadline.status == "PENDING",
				Deadline.deadline_date >= today,
				Deadline.deadline_date <= cutoff,
			)
			.order_by(Deadline.deadline_date)
		)
		if tenant_id:
			q = q.where(Deadline.tenant_id == tenant_id)
		deadlines = session.execute(q).scalars().all()
		return jsonify({
			"period_days": days,
			"count": len(deadlines),
			"deadlines": [
				{
					"id": d.id,
					"matter_id": d.matter_id,
					"deadline_type": d.deadline_type,
					"deadline_date": d.deadline_date.isoformat(),
					"description": d.description,
					"is_hard_deadline": d.is_hard_deadline,
					"responsible_id": d.responsible_id,
				}
				for d in deadlines
			],
		})


# ---------------------------------------------------------------------------
# LegalInvoiceView
# ---------------------------------------------------------------------------

class LegalInvoiceView(BaseView):
	"""Invoice generation and lifecycle.

	GET  /legal/invoices/              — list invoices
	POST /legal/invoices/generate      — generate invoice from time entries
	GET  /legal/invoices/<id>          — detail
	POST /legal/invoices/<id>/send     — transition to SENT
	POST /legal/invoices/<id>/pay      — mark as PAID
	"""

	route_base = "/legal/invoices"
	default_view = "list"
	_widgets = INVOICE_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.legal.models import LegalInvoice
		session = _get_session()
		q = sa.select(LegalInvoice).order_by(LegalInvoice.created_at.desc()).limit(200)
		if request.args.get("matter_id"):
			q = q.where(LegalInvoice.matter_id == request.args["matter_id"])
		if request.args.get("status"):
			q = q.where(LegalInvoice.status == request.args["status"])
		if request.args.get("tenant_id"):
			q = q.where(LegalInvoice.tenant_id == request.args["tenant_id"])
		invoices = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": inv.id,
				"matter_id": inv.matter_id,
				"invoice_number": inv.invoice_number,
				"billing_period_start": inv.billing_period_start.isoformat(),
				"billing_period_end": inv.billing_period_end.isoformat(),
				"time_charges_cents": inv.time_charges_cents,
				"disbursements_cents": inv.disbursements_cents,
				"tax_cents": inv.tax_cents,
				"total_cents": inv.total_cents,
				"status": inv.status,
			}
			for inv in invoices
		])

	@expose("/generate", methods=["POST"])
	@has_access
	def generate(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "matter_id", "billing_period_start", "billing_period_end")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			from datetime import date as _date
			invoice = _svc().generate_invoice(
				tenant_id=data["tenant_id"],
				matter_id=data["matter_id"],
				billing_period_start=_date.fromisoformat(data["billing_period_start"]),
				billing_period_end=_date.fromisoformat(data["billing_period_end"]),
				disbursements_cents=int(data.get("disbursements_cents", 0)),
				tax_cents=int(data.get("tax_cents", 0)),
				session=session,
			)
			session.commit()
			return jsonify({
				"invoice_id": invoice.id,
				"invoice_number": invoice.invoice_number,
				"total_cents": invoice.total_cents,
				"status": invoice.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:invoice_id>")
	@has_access
	def detail(self, invoice_id: str):
		from pgappforge.plugins.erp.industry.legal.models import LegalInvoice
		session = _get_session()
		inv = session.get(LegalInvoice, invoice_id)
		if inv is None:
			abort(404)
		return jsonify({
			"id": inv.id,
			"matter_id": inv.matter_id,
			"invoice_number": inv.invoice_number,
			"billing_period_start": inv.billing_period_start.isoformat(),
			"billing_period_end": inv.billing_period_end.isoformat(),
			"time_charges_cents": inv.time_charges_cents,
			"disbursements_cents": inv.disbursements_cents,
			"tax_cents": inv.tax_cents,
			"total_cents": inv.total_cents,
			"status": inv.status,
		})

	def _transition_invoice(self, invoice_id: str, new_status: str):
		from pgappforge.plugins.erp.industry.legal.models import LegalInvoice
		from pgappforge.plugins.erp.industry.legal.events import (
			InvoicePaidEvent, emit_event,
		)
		session = _get_session()
		inv = session.get(LegalInvoice, invoice_id)
		if inv is None:
			abort(404)
		inv.status = new_status
		if new_status == "PAID":
			emit_event(
				InvoicePaidEvent(
					aggregate_id=invoice_id,
					aggregate_type="LegalInvoice",
					tenant_id=inv.tenant_id,
					invoice_id=invoice_id,
					matter_id=inv.matter_id,
					invoice_number=inv.invoice_number,
					total_cents=inv.total_cents,
				),
				session,
			)
		session.commit()
		return jsonify({"invoice_id": invoice_id, "status": new_status})

	@expose("/<string:invoice_id>/send", methods=["POST"])
	@has_access
	def send(self, invoice_id: str):
		return self._transition_invoice(invoice_id, "SENT")

	@expose("/<string:invoice_id>/pay", methods=["POST"])
	@has_access
	def pay(self, invoice_id: str):
		return self._transition_invoice(invoice_id, "PAID")


# ---------------------------------------------------------------------------
# LegalReportView
# ---------------------------------------------------------------------------

class LegalReportView(BaseView):
	"""Legal services reports and dashboards.

	GET /legal/reports/                                — index
	GET /legal/reports/docket/<matter_id>              — matter docket
	GET /legal/reports/profitability/<matter_id>       — profitability
	GET /legal/reports/deadline-calendar               — upcoming deadlines
	GET /legal/reports/precedents                      — precedent search
	"""

	route_base = "/legal/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{"name": "Matter Docket", "endpoint": "/legal/reports/docket/<matter_id>"},
				{"name": "Matter Profitability", "endpoint": "/legal/reports/profitability/<matter_id>"},
				{"name": "Deadline Calendar", "endpoint": "/legal/reports/deadline-calendar"},
				{"name": "Precedent Search", "endpoint": "/legal/reports/precedents"},
			]
		})

	@expose("/docket/<string:matter_id>")
	@has_access
	def docket(self, matter_id: str):
		session = _get_session()
		try:
			result = _svc().get_docket(matter_id, session)
			return jsonify({"matter_id": matter_id, "docket": result, "count": len(result)})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/profitability/<string:matter_id>")
	@has_access
	def profitability(self, matter_id: str):
		session = _get_session()
		try:
			return jsonify(_svc().calculate_matter_profitability(matter_id, session))
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/deadline-calendar")
	@has_access
	def deadline_calendar(self):
		from pgappforge.plugins.erp.industry.legal.models import Deadline
		from datetime import date, timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		days = int(request.args.get("days", 30))
		today = date.today()
		cutoff = today + timedelta(days=days)
		q = (
			sa.select(Deadline)
			.where(
				Deadline.deadline_date >= today,
				Deadline.deadline_date <= cutoff,
			)
			.order_by(Deadline.deadline_date)
		)
		if tenant_id:
			q = q.where(Deadline.tenant_id == tenant_id)
		deadlines = session.execute(q).scalars().all()
		return jsonify({
			"period_days": days,
			"hard_deadline_count": sum(1 for d in deadlines if d.is_hard_deadline),
			"total_count": len(deadlines),
			"deadlines": [
				{
					"id": d.id,
					"matter_id": d.matter_id,
					"deadline_type": d.deadline_type,
					"deadline_date": d.deadline_date.isoformat(),
					"description": d.description,
					"is_hard_deadline": d.is_hard_deadline,
					"status": d.status,
				}
				for d in deadlines
			],
		})

	@expose("/precedents")
	@has_access
	def precedents(self):
		"""Search precedents by legal_issues and jurisdiction."""
		session = _get_session()
		issues_raw = request.args.get("issues", "")
		jurisdiction = request.args.get("jurisdiction", "")
		if not issues_raw or not jurisdiction:
			return jsonify({"error": "issues and jurisdiction required"}), 400
		issues = [i.strip() for i in issues_raw.split(",") if i.strip()]
		limit = int(request.args.get("limit", 20))
		results = _svc().search_precedents(issues, jurisdiction, session, limit=limit)
		return jsonify({
			"jurisdiction": jurisdiction,
			"issues": issues,
			"count": len(results),
			"precedents": [
				{
					"id": p.id,
					"case_name": p.case_name,
					"citation": p.citation,
					"court": p.court,
					"decided_date": p.decided_date.isoformat() if p.decided_date else None,
					"outcome": p.outcome,
					"legal_issues": p.legal_issues,
					"summary": p.summary,
					"full_text_url": p.full_text_url,
					"relevance_tags": p.relevance_tags,
				}
				for p in results
			],
		})


__all__ = [
	"MatterView",
	"DocumentView",
	"TimeEntryView",
	"DeadlineCalendarView",
	"LegalInvoiceView",
	"LegalReportView",
]
