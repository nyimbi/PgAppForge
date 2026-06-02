"""
pgappforge/plugins/erp/foundation/views.py

Flask views for the ERP Foundation plugin.

Registered views:
  PartyView         — CRUD for Party + PartyRole management
  CurrencyView      — CRUD for Currency master
  CountryView       — CRUD for Country master (read-heavy)
  ExchangeRateView  — CRUD + rate conversion API
  CodeTableView     — CRUD for configurable lookup codes
  DomainEventLogView — Read-only event log browser
  FoundationReportView — 3 canned reports: Party Directory, FX Rate Sheet,
                         Code Table Listing

All mutating endpoints POST JSON and return JSON.  List/detail endpoints
return HTML for standard FAB list rendering.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared session helper
# ---------------------------------------------------------------------------

def _get_session():
	if True:
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


def _he(s: str) -> str:
	"""Minimal HTML-escape for inline HTML generation."""
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


# ---------------------------------------------------------------------------
# PartyView
# ---------------------------------------------------------------------------

class PartyView(BaseView):
	"""Party CRUD + PartyRole management.

	GET  /foundation/parties/             — paginated list (HTML)
	GET  /foundation/parties/<id>         — detail (JSON)
	POST /foundation/parties/             — create  (JSON in, JSON out)
	PUT  /foundation/parties/<id>         — update  (JSON in, JSON out)
	POST /foundation/parties/<id>/roles   — add role (JSON in, JSON out)
	POST /foundation/parties/merge        — merge duplicate into primary
	"""

	route_base = "/foundation/parties"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party
		q = (
			sa.select(Party)
			.where(Party.is_active.is_(True))
			.order_by(Party.name)
			.limit(200)
		)
		tenant_id = request.args.get("tenant_id")
		if tenant_id:
			q = q.where(Party.tenant_id == tenant_id)
		parties = session.execute(q).scalars().all()
		rows = "".join(
			f"<tr>"
			f"<td>{_he(str(p.id))[:8]}…</td>"
			f"<td>{_he(p.party_type)}</td>"
			f"<td>{_he(p.name)}</td>"
			f"<td>{_he(p.tax_id or '')}</td>"
			f"<td>{_he(p.website or '')}</td>"
			f"<td><a href='/foundation/parties/{_he(str(p.id))}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in parties
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Parties</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Party Directory</h3>
<table class="table table-bordered table-hover table-condensed">
<thead><tr><th>ID</th><th>Type</th><th>Name</th><th>Tax ID</th><th>Website</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""
		return make_response(html, 200)

	@expose("/<string:party_id>")
	@has_access
	def detail(self, party_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party
		party = session.get(Party, party_id)
		if party is None:
			abort(404)
		return jsonify({
			"id": party.id,
			"party_type": party.party_type,
			"name": party.name,
			"short_name": party.short_name,
			"legal_name": party.legal_name,
			"tax_id": party.tax_id,
			"vat_number": party.vat_number,
			"registration_number": party.registration_number,
			"lei": party.lei,
			"website": party.website,
			"is_active": party.is_active,
			"parent_id": party.parent_id,
			"tenant_id": party.tenant_id,
			"created_at": party.created_at.isoformat() if party.created_at else None,
			"updated_at": party.updated_at.isoformat() if party.updated_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party
		from pgappforge.plugins.erp.foundation.events import PartyCreatedEvent, emit_event
		data = request.get_json(silent=True) or {}
		if not data.get("name") or not data.get("party_type") or not data.get("tenant_id"):
			return jsonify({"ok": False, "error": "name, party_type, tenant_id required"}), 400
		party = Party(
			name=data["name"],
			party_type=data["party_type"].upper(),
			tenant_id=data["tenant_id"],
			short_name=data.get("short_name"),
			legal_name=data.get("legal_name"),
			tax_id=data.get("tax_id"),
			vat_number=data.get("vat_number"),
			registration_number=data.get("registration_number"),
			lei=data.get("lei"),
			website=data.get("website"),
			parent_id=data.get("parent_id"),
		)
		session.add(party)
		session.flush()  # populate id
		emit_event(
			PartyCreatedEvent(
				aggregate_id=party.id,
				aggregate_type="Party",
				tenant_id=party.tenant_id,
				party_id=party.id,
				party_type=party.party_type,
				name=party.name,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": party.id}), 201

	@expose("/<string:party_id>", methods=["PUT"])
	@has_access
	def update(self, party_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party
		from pgappforge.plugins.erp.foundation.events import PartyUpdatedEvent, emit_event
		party = session.get(Party, party_id)
		if party is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = [
			"name", "short_name", "legal_name", "tax_id", "vat_number",
			"registration_number", "lei", "website", "is_active", "parent_id",
		]
		changed = []
		for field in updatable:
			if field in data:
				setattr(party, field, data[field])
				changed.append(field)
		party.updated_at = datetime.now(timezone.utc)
		emit_event(
			PartyUpdatedEvent(
				aggregate_id=party_id,
				aggregate_type="Party",
				tenant_id=party.tenant_id,
				party_id=party_id,
				changed_fields=changed,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "changed": changed})

	@expose("/<string:party_id>/roles", methods=["POST"])
	@has_access
	def add_role(self, party_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party, PartyRole
		party = session.get(Party, party_id)
		if party is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		role_type = (data.get("role_type") or "").upper()
		if role_type not in ("CUSTOMER", "SUPPLIER", "EMPLOYEE", "PARTNER", "OTHER"):
			return jsonify({"ok": False, "error": "invalid role_type"}), 400
		role = PartyRole(
			party_id=party_id,
			tenant_id=party.tenant_id,
			role_type=role_type,
			attributes=data.get("attributes") or {},
		)
		session.add(role)
		session.commit()
		return jsonify({"ok": True, "id": role.id}), 201

	@expose("/merge", methods=["POST"])
	@has_access
	def merge(self):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, FoundationServiceError,
		)
		data = request.get_json(silent=True) or {}
		primary_id = data.get("primary_id")
		duplicate_id = data.get("duplicate_id")
		if not primary_id or not duplicate_id:
			return jsonify({"ok": False, "error": "primary_id and duplicate_id required"}), 400
		try:
			from flask_login import current_user
			merged_by = getattr(current_user, "id", None)
		except Exception:
			merged_by = None
		svc = FoundationService()
		try:
			party = svc.merge_parties(primary_id, duplicate_id, session, merged_by=merged_by)
			session.commit()
			return jsonify({"ok": True, "primary_id": party.id})
		except FoundationServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# ExchangeRateView
# ---------------------------------------------------------------------------

class ExchangeRateView(BaseView):
	"""Exchange rate CRUD + live conversion API.

	GET  /foundation/fx/rates           — list recent rates (JSON)
	POST /foundation/fx/rates           — create rate (JSON in/out)
	GET  /foundation/fx/convert         — ?from=USD&to=NGN&amount=1000&date=2026-01-01
	GET  /foundation/fx/sheet           — HTML rate sheet report
	"""

	route_base = "/foundation/fx"
	default_view = "list"

	@expose("/rates")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		rows = session.execute(
			sa.select(ExchangeRate)
			.order_by(sa.desc(ExchangeRate.rate_date))
			.limit(100)
		).scalars().all()
		return jsonify({
			"rates": [
				{
					"id": r.id,
					"from_currency": r.from_currency,
					"to_currency": r.to_currency,
					"rate": str(r.rate),
					"rate_date": r.rate_date.isoformat() if r.rate_date else None,
					"source": r.source,
					"expires_at": r.expires_at.isoformat() if r.expires_at else None,
				}
				for r in rows
			]
		})

	@expose("/rates", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		from pgappforge.plugins.erp.foundation.events import ExchangeRateUpdatedEvent, emit_event
		data = request.get_json(silent=True) or {}
		required = ("from_currency", "to_currency", "rate", "rate_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			rate_val = Decimal(str(data["rate"]))
		except Exception:
			return jsonify({"ok": False, "error": "rate must be numeric"}), 400
		rate_date_raw = data["rate_date"]
		if isinstance(rate_date_raw, str):
			rate_date = datetime.fromisoformat(rate_date_raw).replace(tzinfo=timezone.utc)
		else:
			rate_date = rate_date_raw
		row = ExchangeRate(
			from_currency=data["from_currency"].upper(),
			to_currency=data["to_currency"].upper(),
			rate=rate_val,
			rate_date=rate_date,
			source=(data.get("source") or "MANUAL").upper(),
		)
		session.add(row)
		session.flush()
		emit_event(
			ExchangeRateUpdatedEvent(
				aggregate_id=row.id,
				aggregate_type="ExchangeRate",
				tenant_id="",
				from_currency=row.from_currency,
				to_currency=row.to_currency,
				rate=str(rate_val),
				rate_date=rate_date.isoformat(),
				source=row.source,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": row.id}), 201

	@expose("/convert")
	@has_access
	def convert(self):
		"""GET /foundation/fx/convert?from=USD&to=NGN&amount=1000&date=2026-01-01"""
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, ExchangeRateNotFoundError,
		)
		from_ccy = request.args.get("from", "").upper()
		to_ccy = request.args.get("to", "").upper()
		amount_str = request.args.get("amount", "0")
		date_str = request.args.get("date")
		if not from_ccy or not to_ccy:
			return jsonify({"ok": False, "error": "from and to required"}), 400
		try:
			amount = int(amount_str)
		except ValueError:
			return jsonify({"ok": False, "error": "amount must be integer cents"}), 400
		if date_str:
			try:
				rate_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
			except ValueError:
				return jsonify({"ok": False, "error": "invalid date"}), 400
		else:
			rate_date = datetime.now(timezone.utc)
		session = _get_session()
		svc = FoundationService()
		try:
			result = svc.convert_amount(amount, from_ccy, to_ccy, rate_date, session)
			rate = svc.get_exchange_rate(from_ccy, to_ccy, rate_date, session)
			return jsonify({
				"ok": True,
				"from_currency": from_ccy,
				"to_currency": to_ccy,
				"input_amount_cents": amount,
				"output_amount_cents": result,
				"rate": str(rate),
			})
		except ExchangeRateNotFoundError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 404

	@expose("/sheet")
	@has_access
	def rate_sheet(self):
		"""HTML report: current exchange rate sheet grouped by from_currency."""
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		# Most recent rate per (from, to) pair
		subq = (
			sa.select(
				ExchangeRate.from_currency,
				ExchangeRate.to_currency,
				sa.func.max(ExchangeRate.rate_date).label("max_date"),
			)
			.group_by(ExchangeRate.from_currency, ExchangeRate.to_currency)
			.subquery()
		)
		rows = session.execute(
			sa.select(ExchangeRate)
			.join(
				subq,
				sa.and_(
					ExchangeRate.from_currency == subq.c.from_currency,
					ExchangeRate.to_currency == subq.c.to_currency,
					ExchangeRate.rate_date == subq.c.max_date,
				),
			)
			.order_by(ExchangeRate.from_currency, ExchangeRate.to_currency)
		).scalars().all()

		table_rows = "".join(
			f"<tr><td>{_he(r.from_currency)}</td><td>{_he(r.to_currency)}</td>"
			f"<td style='text-align:right'>{_he(str(r.rate))}</td>"
			f"<td>{_he(r.rate_date.strftime('%Y-%m-%d') if r.rate_date else '')}</td>"
			f"<td>{_he(r.source)}</td></tr>"
			for r in rows
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>FX Rate Sheet</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
</head><body style="padding:24px">
<h3>Exchange Rate Sheet — current rates as of {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</h3>
<table class="table table-bordered table-condensed table-hover">
<thead><tr><th>From</th><th>To</th><th>Rate</th><th>Date</th><th>Source</th></tr></thead>
<tbody>{table_rows}</tbody></table></body></html>"""
		return make_response(html, 200)


# ---------------------------------------------------------------------------
# CodeTableView
# ---------------------------------------------------------------------------

class CodeTableView(BaseView):
	"""Configurable lookup code CRUD.

	GET  /foundation/codes/<domain>   — list codes for domain (JSON)
	POST /foundation/codes/           — create code (JSON)
	PUT  /foundation/codes/<id>       — update code (JSON)
	"""

	route_base = "/foundation/codes"
	default_view = "list_domain"

	@expose("/<string:domain>")
	@has_access
	def list_domain(self, domain: str):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		session = _get_session()
		codes = FoundationService().get_codes(domain, session)
		return jsonify({
			"domain": domain,
			"codes": [
				{
					"id": c.id,
					"code": c.code,
					"label": c.label,
					"sort_order": c.sort_order,
					"is_active": c.is_active,
					"metadata": c.metadata_,
				}
				for c in codes
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.foundation.models import CodeTable
		session = _get_session()
		data = request.get_json(silent=True) or {}
		if not data.get("domain") or not data.get("code") or not data.get("label"):
			return jsonify({"ok": False, "error": "domain, code, label required"}), 400
		entry = CodeTable(
			domain=data["domain"],
			code=data["code"],
			label=data["label"],
			sort_order=int(data.get("sort_order") or 0),
			is_active=bool(data.get("is_active", True)),
			metadata_=data.get("metadata") or {},
		)
		session.add(entry)
		session.commit()
		return jsonify({"ok": True, "id": entry.id}), 201

	@expose("/<string:entry_id>", methods=["PUT"])
	@has_access
	def update(self, entry_id: str):
		from pgappforge.plugins.erp.foundation.models import CodeTable
		session = _get_session()
		entry = session.get(CodeTable, entry_id)
		if entry is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("label", "sort_order", "is_active"):
			if field in data:
				setattr(entry, field, data[field])
		if "metadata" in data:
			entry.metadata_ = data["metadata"]
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# DomainEventLogView
# ---------------------------------------------------------------------------

class DomainEventLogView(BaseView):
	"""Read-only browser for DomainEventLog.

	GET /foundation/events/           — paginated JSON list
	GET /foundation/events/<event_id> — single event detail
	"""

	route_base = "/foundation/events"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		session = _get_session()
		page = max(1, int(request.args.get("page", 1)))
		per_page = min(int(request.args.get("per_page", 50)), 200)
		event_type = request.args.get("event_type", "").strip()
		tenant_id = request.args.get("tenant_id", "").strip()
		aggregate_type = request.args.get("aggregate_type", "").strip()

		q = sa.select(DomainEventLog).order_by(sa.desc(DomainEventLog.published_at))
		if event_type:
			q = q.where(DomainEventLog.event_type == event_type)
		if tenant_id:
			q = q.where(DomainEventLog.tenant_id == tenant_id)
		if aggregate_type:
			q = q.where(DomainEventLog.aggregate_type == aggregate_type)

		q = q.offset((page - 1) * per_page).limit(per_page)
		rows = session.execute(q).scalars().all()
		return jsonify({
			"events": [
				{
					"id": r.id,
					"event_id": r.event_id,
					"event_type": r.event_type,
					"aggregate_type": r.aggregate_type,
					"aggregate_id": r.aggregate_id,
					"tenant_id": r.tenant_id,
					"published_at": r.published_at.isoformat() if r.published_at else None,
					"correlation_id": r.correlation_id,
					"payload": r.payload,
				}
				for r in rows
			],
			"page": page,
			"per_page": per_page,
		})

	@expose("/<string:event_id>")
	@has_access
	def detail(self, event_id: str):
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		session = _get_session()
		row = session.execute(
			sa.select(DomainEventLog).where(DomainEventLog.event_id == event_id)
		).scalar_one_or_none()
		if row is None:
			abort(404)
		return jsonify({
			"id": row.id,
			"event_id": row.event_id,
			"event_type": row.event_type,
			"aggregate_type": row.aggregate_type,
			"aggregate_id": row.aggregate_id,
			"tenant_id": row.tenant_id,
			"published_at": row.published_at.isoformat() if row.published_at else None,
			"correlation_id": row.correlation_id,
			"causation_id": row.causation_id,
			"payload": row.payload,
		})


# ---------------------------------------------------------------------------
# FoundationReportView
# ---------------------------------------------------------------------------

class FoundationReportView(BaseView):
	"""Three canned reports for the Foundation domain.

	GET /foundation/reports/party-directory  — paginated party directory (HTML)
	GET /foundation/reports/fx-rate-sheet    — alias to ExchangeRateView.rate_sheet
	GET /foundation/reports/code-listing     — full code table listing (HTML)
	"""

	route_base = "/foundation/reports"
	default_view = "party_directory"

	@expose("/party-directory")
	@has_access
	def party_directory(self):
		"""Party Directory report — filterable by type, active status, tenant."""
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import Party, Contact
		tenant_id = request.args.get("tenant_id")
		party_type = request.args.get("party_type")

		q = sa.select(Party).where(Party.is_active.is_(True)).order_by(Party.name)
		if tenant_id:
			q = q.where(Party.tenant_id == tenant_id)
		if party_type:
			q = q.where(Party.party_type == party_type.upper())

		parties = session.execute(q).scalars().all()

		# Fetch primary emails in one query
		party_ids = [p.id for p in parties]
		email_map: dict[str, str] = {}
		if party_ids:
			contacts = session.execute(
				sa.select(Contact)
				.where(Contact.party_id.in_(party_ids))
				.where(Contact.contact_type == "EMAIL")
				.where(Contact.is_primary.is_(True))
			).scalars().all()
			email_map = {c.party_id: c.value for c in contacts}

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.party_type)}</td>"
			f"<td>{_he(p.name)}</td>"
			f"<td>{_he(p.legal_name or '')}</td>"
			f"<td>{_he(p.tax_id or '')}</td>"
			f"<td>{_he(p.vat_number or '')}</td>"
			f"<td>{_he(email_map.get(p.id, ''))}</td>"
			f"<td>{_he(p.website or '')}</td>"
			f"</tr>"
			for p in parties
		)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Party Directory</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<div class="noprint" style="margin-bottom:12px">
  <h3>Party Directory</h3>
  <a href="?party_type=CUSTOMER" class="btn btn-xs btn-default">Customers</a>
  <a href="?party_type=SUPPLIER" class="btn btn-xs btn-default">Suppliers</a>
  <a href="?party_type=EMPLOYEE" class="btn btn-xs btn-default">Employees</a>
  <a href="?" class="btn btn-xs btn-default">All</a>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print / PDF</button>
</div>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Type</th><th>Name</th><th>Legal Name</th><th>Tax ID</th>
<th>VAT No.</th><th>Email</th><th>Website</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — {len(parties)} parties</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/fx-rate-sheet")
	@has_access
	def fx_rate_sheet(self):
		"""Redirect alias to ExchangeRateView.rate_sheet."""
		from flask import redirect
		return redirect("/foundation/fx/sheet")

	@expose("/code-listing")
	@has_access
	def code_listing(self):
		"""Full code table listing — all domains, grouped, printable."""
		session = _get_session()
		from pgappforge.plugins.erp.foundation.models import CodeTable
		rows = session.execute(
			sa.select(CodeTable)
			.where(CodeTable.is_active.is_(True))
			.order_by(CodeTable.domain, CodeTable.sort_order, CodeTable.code)
		).scalars().all()

		# Group by domain
		by_domain: dict[str, list] = {}
		for r in rows:
			by_domain.setdefault(r.domain, []).append(r)

		sections = ""
		for domain, codes in by_domain.items():
			table_rows = "".join(
				f"<tr><td>{_he(c.code)}</td><td>{_he(c.label)}</td>"
				f"<td>{c.sort_order}</td></tr>"
				for c in codes
			)
			sections += (
				f"<h5 style='margin-top:16px'>{_he(domain)}</h5>"
				f"<table class='table table-condensed table-bordered' style='font-size:0.82em'>"
				f"<thead><tr><th>Code</th><th>Label</th><th>Order</th></tr></thead>"
				f"<tbody>{table_rows}</tbody></table>"
			)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Code Table Listing</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<h3>Code Table Listing</h3>
<button class="btn btn-xs btn-primary noprint" onclick="window.print()">Print</button>
{sections or '<p>No codes defined yet.</p>'}
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"PartyView",
	"ExchangeRateView",
	"CodeTableView",
	"DomainEventLogView",
	"FoundationReportView",
]
