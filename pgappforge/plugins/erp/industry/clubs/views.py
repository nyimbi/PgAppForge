"""
pgappforge/plugins/erp/industry/clubs/views.py

Flask views for the Clubs & Membership plugin.

Route summary
-------------
ClubsDashboardView          /industry/clubs/
  └─ GET  /industry/clubs/  — dashboard with KPI tiles and tabbed sections
ClubMemberView              /clubs/members/
MembershipApplicationView   /clubs/applications/
FacilityView                /clubs/facilities/
FacilityBookingView         /clubs/bookings/
MemberAccountView           /clubs/accounts/
MemberChargeView            /clubs/charges/
GuestVisitView              /clubs/guests/
AccessEventView             /clubs/access/
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from flask import make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.industry.clubs.models import (
	ClubMembershipType,
	ClubMember,
	MembershipApplication,
	Facility,
	FacilityBooking,
	MemberAccount,
	MemberCharge,
	GuestVisit,
	AccessEvent,
	MemberStatement,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents(cents: int | None, symbol: str = "") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	prefix = f"{symbol} " if symbol else ""
	return f"{prefix}{sign}{major:,}.{minor:02d}"


# ---------------------------------------------------------------------------
# ModelViews
# ---------------------------------------------------------------------------

class ClubMemberView(BaseERPModelView):
	"""Member directory.

	No delete — members are a historical record; use status RESIGNED / DECEASED.
	"""

	datamodel = None  # set by FAB on registration against ClubMember model
	route_base = "/clubs/members"

	list_columns = [
		"membership_number",
		"full_name",
		"member_type_id",
		"status",
		"joined_date",
	]
	search_columns = ["membership_number", "full_name", "email"]
	base_permissions = ["can_list", "can_show", "can_edit"]

	label_columns = {
		"membership_number": "Number",
		"full_name": "Name",
		"member_type_id": "Type",
		"joined_date": "Joined",
	}
	description_columns = {
		"status": "PENDING / ACTIVE / SUSPENDED / LAPSED / RESIGNED",
		"suspension_reason": "Populated when status = SUSPENDED",
	}


class MembershipApplicationView(BaseERPModelView):
	"""Membership application queue — approve or reject from the show view."""

	datamodel = None
	route_base = "/clubs/applications"

	list_columns = [
		"applicant_name",
		"member_type_id",
		"status",
		"applied_at",
		"decided_at",
	]
	base_permissions = ["can_list", "can_show", "can_edit"]

	label_columns = {
		"applicant_name": "Applicant",
		"member_type_id": "Membership Type",
		"applied_at": "Applied",
		"decided_at": "Decided",
	}


class FacilityView(BaseERPModelView):
	"""Club facilities — courts, pools, gyms, etc."""

	datamodel = None
	route_base = "/clubs/facilities"

	list_columns = [
		"name",
		"facility_type",
		"capacity",
		"is_active",
		"hourly_rate_cents",
	]
	label_columns = {
		"facility_type": "Type",
		"hourly_rate_cents": "Hourly Rate (¢)",
		"is_active": "Active",
	}
	description_columns = {
		"hourly_rate_cents": "0 = included in membership (no charge on booking)",
		"booking_advance_hours": "How many hours ahead members can book (168 = 1 week)",
	}


class FacilityBookingView(BaseERPModelView):
	"""Facility bookings — read-only list and detail; mutations via service layer."""

	datamodel = None
	route_base = "/clubs/bookings"

	list_columns = [
		"booking_ref",
		"facility_id",
		"member_id",
		"booking_date",
		"start_time",
		"end_time",
		"status",
		"total_fee_cents",
	]
	base_permissions = ["can_list", "can_show"]

	label_columns = {
		"booking_ref": "Ref",
		"facility_id": "Facility",
		"member_id": "Member",
		"booking_date": "Date",
		"start_time": "From",
		"end_time": "To",
		"total_fee_cents": "Fee (¢)",
	}


class MemberAccountView(BaseERPModelView):
	"""Member charge accounts — read-only; charges posted via service layer."""

	datamodel = None
	route_base = "/clubs/accounts"

	list_columns = [
		"member_id",
		"current_balance_cents",
		"credit_limit_cents",
		"last_statement_date",
	]
	base_permissions = ["can_list", "can_show"]

	label_columns = {
		"member_id": "Member",
		"current_balance_cents": "Balance (¢)",
		"credit_limit_cents": "Credit Limit (¢)",
		"last_statement_date": "Last Statement",
	}
	description_columns = {
		"current_balance_cents": "Positive = member owes the club",
		"credit_limit_cents": "0 = no credit facility extended",
	}


class MemberChargeView(BaseERPModelView):
	"""Member charge ledger — immutable; no add/edit/delete."""

	datamodel = None
	route_base = "/clubs/charges"

	list_columns = [
		"charge_type",
		"description",
		"amount_cents",
		"charged_at",
	]
	base_permissions = ["can_list", "can_show"]

	label_columns = {
		"charge_type": "Type",
		"amount_cents": "Amount (¢)",
		"charged_at": "Charged At",
	}
	description_columns = {
		"amount_cents": "Positive = debit, negative = credit/reversal",
	}


class GuestVisitView(BaseERPModelView):
	"""Guest visit log."""

	datamodel = None
	route_base = "/clubs/guests"

	list_columns = [
		"member_id",
		"guest_name",
		"visit_date",
		"facility_id",
		"levy_cents",
	]
	label_columns = {
		"member_id": "Sponsor",
		"guest_name": "Guest",
		"visit_date": "Date",
		"facility_id": "Facility",
		"levy_cents": "Levy (¢)",
	}


class AccessEventView(BaseERPModelView):
	"""Access control audit log — immutable; no add/edit/delete."""

	datamodel = None
	route_base = "/clubs/access"

	list_columns = [
		"member_id",
		"door_name",
		"direction",
		"access_result",
		"occurred_at",
	]
	base_permissions = ["can_list", "can_show"]

	label_columns = {
		"member_id": "Member",
		"door_name": "Door",
		"access_result": "Result",
		"occurred_at": "When",
	}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class ClubsDashboardView(BaseERPView):
	"""Clubs management dashboard with live KPI tiles and tabbed sections."""

	route_base = "/industry/clubs"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		"""GET /industry/clubs/ — KPI overview with tabbed breakdown."""

		# Live counts — scoped to current tenant
		sess = self._session()
		tid = self._tenant_id()
		active_members = self._count(ClubMember, session=sess, tenant_id=tid, status="ACTIVE")
		pending_applications = self._count(MembershipApplication, session=sess, tenant_id=tid, status="PENDING")
		outstanding_accounts = self._count_positive_balance(sess, tid)
		todays_bookings = self._count_todays_bookings(sess, tid)

		kpi_html = self.kpi_cards([
			{
				"label": "Active Members",
				"value": active_members,
				"format": "integer",
				"color": "#1a56db",
				"icon": "fa-id-card",
			},
			{
				"label": "Pending Applications",
				"value": pending_applications,
				"format": "integer",
				"color": "#c27803",
				"icon": "fa-file-text",
			},
			{
				"label": "Today's Bookings",
				"value": todays_bookings,
				"format": "integer",
				"color": "#057a55",
				"icon": "fa-calendar",
			},
			{
				"label": "Outstanding Accounts",
				"value": outstanding_accounts,
				"format": "integer",
				"color": "#e02424",
				"icon": "fa-money",
			},
		])

		tabs_html = self._render_tabs([
			{
				"id": "tab-members",
				"label": "Recent Members",
				"content": self._recent_members_table(),
			},
			{
				"id": "tab-bookings",
				"label": "Today's Bookings",
				"content": self._todays_bookings_table(),
			},
			{
				"id": "tab-applications",
				"label": "Pending Applications",
				"content": self._pending_applications_table(),
			},
			{
				"id": "tab-access",
				"label": "Recent Access",
				"content": self._recent_access_table(),
			},
		])

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Club Management Dashboard</title>
<link rel="stylesheet" href="/static/appbuilder/css/bootstrap.min.css">
<style>
  body{{padding:24px}}
  .tab-content{{padding-top:16px}}
  .badge-success{{background:#057a55;color:#fff;padding:2px 8px;border-radius:3px}}
  .badge-warning{{background:#c27803;color:#fff;padding:2px 8px;border-radius:3px}}
  .badge-danger{{background:#e02424;color:#fff;padding:2px 8px;border-radius:3px}}
  .badge-default{{background:#6b7280;color:#fff;padding:2px 8px;border-radius:3px}}
</style>
</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <h3><i class="fa fa-users"></i> Club Management</h3>
  <span style="color:#6b7280;font-size:0.8em">
    {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
  </span>
</div>
{kpi_html}
{tabs_html}
</body></html>"""
		return make_response(html, 200)

	# ------------------------------------------------------------------
	# Private helpers
	# ------------------------------------------------------------------

	def _count_positive_balance(self, session: Any = None, tenant_id: str | None = None) -> int:
		"""Count MemberAccounts with current_balance_cents > 0 for the given tenant."""
		try:
			if session is None:
				from flask import current_app
				session = current_app.appbuilder.get_session()
			q = (
				sa.select(sa.func.count()).select_from(MemberAccount)
				.where(MemberAccount.current_balance_cents > 0)
			)
			if tenant_id is not None:
				q = q.where(MemberAccount.tenant_id == tenant_id)
			return session.execute(q).scalar_one() or 0
		except Exception:
			return 0

	def _count_todays_bookings(self, session: Any = None, tenant_id: str | None = None) -> int:
		"""Count FacilityBookings for today with status CONFIRMED for the given tenant."""
		try:
			if session is None:
				from flask import current_app
				session = current_app.appbuilder.get_session()
			q = (
				sa.select(sa.func.count()).select_from(FacilityBooking)
				.where(
					FacilityBooking.booking_date == date.today(),
					FacilityBooking.status == "CONFIRMED",
				)
			)
			if tenant_id is not None:
				q = q.where(FacilityBooking.tenant_id == tenant_id)
			return session.execute(q).scalar_one() or 0
		except Exception:
			return 0

	def _recent_members_table(self) -> str:
		"""HTML table of the 20 most recently joined active members."""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			rows = session.execute(
				sa.select(ClubMember)
				.order_by(sa.desc(ClubMember.created_at))
				.limit(20)
			).scalars().all()
		except Exception:
			return "<p class='text-muted'>Unable to load members.</p>"

		if not rows:
			return "<p class='text-muted'>No members found.</p>"

		status_class = {
			"ACTIVE": "badge-success",
			"SUSPENDED": "badge-danger",
			"PENDING": "badge-warning",
		}
		tbody = "".join(
			f"<tr>"
			f"<td>{_he(m.membership_number)}</td>"
			f"<td>{_he(m.full_name)}</td>"
			f"<td><span class='badge {status_class.get(m.status, 'badge-default')}'>"
			f"{_he(m.status)}</span></td>"
			f"<td>{_he(m.joined_date or '—')}</td>"
			f"</tr>"
			for m in rows
		)
		return (
			"<table class='table table-condensed table-hover'>"
			"<thead><tr><th>Number</th><th>Name</th><th>Status</th><th>Joined</th></tr></thead>"
			f"<tbody>{tbody}</tbody></table>"
		)

	def _todays_bookings_table(self) -> str:
		"""HTML table of today's CONFIRMED facility bookings."""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			rows = session.execute(
				sa.select(FacilityBooking)
				.where(
					FacilityBooking.booking_date == date.today(),
					FacilityBooking.status == "CONFIRMED",
				)
				.order_by(FacilityBooking.start_time)
				.limit(50)
			).scalars().all()
		except Exception:
			return "<p class='text-muted'>Unable to load bookings.</p>"

		if not rows:
			return "<p class='text-muted'>No confirmed bookings for today.</p>"

		tbody = "".join(
			f"<tr>"
			f"<td>{_he(b.booking_ref)}</td>"
			f"<td>{_he(b.start_time)} – {_he(b.end_time)}</td>"
			f"<td>{_he(b.facility_id)}</td>"
			f"<td>{_he(b.member_id)}</td>"
			f"<td>{_cents(b.total_fee_cents)}</td>"
			f"</tr>"
			for b in rows
		)
		return (
			"<table class='table table-condensed table-hover'>"
			"<thead><tr><th>Ref</th><th>Slot</th><th>Facility</th><th>Member</th><th>Fee (¢)</th></tr></thead>"
			f"<tbody>{tbody}</tbody></table>"
		)

	def _pending_applications_table(self) -> str:
		"""HTML table of PENDING membership applications."""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			rows = session.execute(
				sa.select(MembershipApplication)
				.where(MembershipApplication.status == "PENDING")
				.order_by(MembershipApplication.applied_at)
				.limit(50)
			).scalars().all()
		except Exception:
			return "<p class='text-muted'>Unable to load applications.</p>"

		if not rows:
			return "<p class='text-muted'>No pending applications.</p>"

		tbody = "".join(
			f"<tr>"
			f"<td>{_he(a.applicant_name)}</td>"
			f"<td>{_he(a.applicant_email or '—')}</td>"
			f"<td>{_he(a.applied_at.strftime('%Y-%m-%d') if a.applied_at else '—')}</td>"
			f"</tr>"
			for a in rows
		)
		return (
			"<table class='table table-condensed table-hover'>"
			"<thead><tr><th>Applicant</th><th>Email</th><th>Applied</th></tr></thead>"
			f"<tbody>{tbody}</tbody></table>"
		)

	def _recent_access_table(self) -> str:
		"""HTML table of the 30 most recent access events."""
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			rows = session.execute(
				sa.select(AccessEvent)
				.order_by(sa.desc(AccessEvent.occurred_at))
				.limit(30)
			).scalars().all()
		except Exception:
			return "<p class='text-muted'>Unable to load access events.</p>"

		if not rows:
			return "<p class='text-muted'>No access events recorded.</p>"

		result_class = {
			"GRANTED": "badge-success",
			"DENIED": "badge-danger",
		}
		tbody = "".join(
			f"<tr>"
			f"<td>{_he(e.door_name)}</td>"
			f"<td>{_he(e.direction)}</td>"
			f"<td><span class='badge {result_class.get(e.access_result, 'badge-default')}'>"
			f"{_he(e.access_result)}</span></td>"
			f"<td>{_he(e.member_id or '—')}</td>"
			f"<td>{_he(e.occurred_at.strftime('%H:%M:%S') if e.occurred_at else '—')}</td>"
			f"</tr>"
			for e in rows
		)
		return (
			"<table class='table table-condensed table-hover'>"
			"<thead><tr><th>Door</th><th>Dir</th><th>Result</th><th>Member</th><th>Time</th></tr></thead>"
			f"<tbody>{tbody}</tbody></table>"
		)

	@staticmethod
	def _render_tabs(tabs: list[dict]) -> str:
		"""Render a Bootstrap 3 tabbed panel from a list of {id, label, content} dicts."""
		nav_items = "".join(
			f'<li{"  class=\"active\"" if i == 0 else ""}>'
			f'<a href="#{t["id"]}" data-toggle="tab">{_he(t["label"])}</a></li>'
			for i, t in enumerate(tabs)
		)
		panes = "".join(
			f'<div class="tab-pane{"  active" if i == 0 else ""}" id="{_he(t["id"])}">'
			f'{t["content"]}</div>'
			for i, t in enumerate(tabs)
		)
		return (
			f'<ul class="nav nav-tabs">{nav_items}</ul>'
			f'<div class="tab-content">{panes}</div>'
			'<script>$(\'[data-toggle="tab"]\').on("click",function(e){{'
			'e.preventDefault();$(this).tab("show")}});</script>'
		)




__all__ = [
	"ClubsDashboardView",
	"ClubMemberView",
	"MembershipApplicationView",
	"FacilityView",
	"FacilityBookingView",
	"MemberAccountView",
	"MemberChargeView",
	"GuestVisitView",
	"AccessEventView",
]
