"""
pgappforge/plugins/erp/industry/clubs/__init__.py

ClubsPlugin — member registry, facility booking, member accounts, guest
management, and access control for sports clubs, leisure clubs, and similar
membership organisations.

Depends on: foundation, crm.subscriptions, crm.appointments, crm.loyalty,
            operations.rental

Events emitted
--------------
  club.application.submitted  — new MembershipApplication submitted
  club.member.approved        — application approved, ClubMember created
  club.member.suspended       — member status changed to SUSPENDED
  club.member.resigned        — member formally resigned
  club.facility.booked        — FacilityBooking confirmed
  club.booking.cancelled      — FacilityBooking cancelled
  club.member.charged         — MemberCharge posted to account
  club.guest.visited          — GuestVisit recorded
  club.access.granted         — AccessEvent with result=GRANTED
  club.access.denied          — AccessEvent with result=DENIED
  club.statement.generated    — monthly statement generated for member

Events consumed
---------------
  crm.subscriptions.cancelled — auto-suspend lapsed members

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.subscriptions",
        "pgappforge.plugins.erp.crm.appointments",
        "pgappforge.plugins.erp.crm.loyalty",
        "pgappforge.plugins.erp.operations.rental",
        "pgappforge.plugins.erp.industry.clubs",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ClubsPlugin(BasePlugin):
	"""Club management industry plugin.

	Registers member registry, facility booking, member accounts, guest
	management, and access-control views.  Wires into CRM subscriptions to
	auto-suspend members whose subscription lapses.

	Class-level attributes:
	    name       = "clubs"
	    domain     = "industry"
	    depends_on = ["foundation", "crm.subscriptions", "crm.appointments",
	                  "crm.loyalty", "operations.rental"]
	"""

	name = "clubs"
	domain = "industry"
	depends_on: list[str] = [
		"foundation",
		"crm.subscriptions",
		"crm.appointments",
		"crm.loyalty",
		"operations.rental",
	]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="clubs",
			version="1.0.0",
			description=(
				"Club management — member registry, facility booking, member accounts, "
				"guest management, access control"
			),
			author="PgAppForge Contributors",
			tags=["clubs", "membership", "facility-management", "sports-club", "leisure"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_manage_members",
				"can_view_members",
				"can_book_facility",
				"can_manage_facilities",
				"can_view_member_accounts",
				"can_post_charges",
				"can_manage_guest_visits",
				"can_view_access_log",
				"can_manage_access",
				"can_generate_statements",
				"can_approve_applications",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Return all club.* event type strings defined in events.py."""
		return [
			"club.application.submitted",
			"club.member.approved",
			"club.member.suspended",
			"club.member.resigned",
			"club.facility.booked",
			"club.booking.cancelled",
			"club.member.charged",
			"club.guest.visited",
			"club.access.granted",
			"club.access.denied",
			"club.statement.generated",
		]

	def subscribe_to(self) -> list[str]:
		"""Auto-suspend lapsed members when a CRM subscription is cancelled."""
		return ["crm.subscriptions.cancelled"]

	def _on_crm_subscriptions_cancelled(self, event: Any) -> None:
		"""Suspend a ClubMember when their CRM subscription is cancelled.

		Tries to match by customer_id column first; falls back to checking
		the JSON subscription_metadata... field in ClubMember (soft-FK pattern).
		"""
		try:
			from flask import current_app
			import sqlalchemy as sa
			from pgappforge.plugins.erp.industry.clubs.models import ClubMember
			from pgappforge.plugins.erp.industry.clubs.services import ClubMemberService

			customer_id = getattr(event, "customer_id", None) or (
				event.get("customer_id") if isinstance(event, dict) else None
			)
			if not customer_id:
				log.debug("_on_crm_subscriptions_cancelled: no customer_id on event, skipping")
				return

			session = current_app.appbuilder.get_session()

			# Primary lookup: hard column
			member = session.execute(
				sa.select(ClubMember).where(ClubMember.customer_id == customer_id)
			).scalar_one_or_none()

			if member is None:
				log.debug(
					"_on_crm_subscriptions_cancelled: no ClubMember found for customer_id=%s",
					customer_id,
				)
				return

			if member.status == "ACTIVE":
				svc = ClubMemberService()
				svc.suspend_member(
					member.id,
					reason="CRM subscription cancelled",
					session=session,
				)
				session.commit()
				log.info(
					"ClubsPlugin: auto-suspended member %s (customer_id=%s) — subscription cancelled",
					member.id,
					customer_id,
				)
		except Exception:
			log.exception("ClubsPlugin._on_crm_subscriptions_cancelled failed")

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"CLUBS_MENU_CATEGORY": "Club Management",
			"CLUBS_GUEST_LEVY_CENTS": 0,
			"CLUBS_DEFAULT_GUEST_LIMIT": 2,
			"CLUBS_STATEMENT_DAY": 1,
		}
		self.config = {**defaults, **self.config}
		log.info("ClubsPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Wire event subscriptions via BasePlugin auto-wiring."""
		super().post_initialize()

	def register_models(self) -> list:
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
		return [
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
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.industry.clubs.views import (
			ClubsDashboardView,
			ClubMemberView,
			MembershipApplicationView,
			FacilityView,
			FacilityBookingView,
			MemberAccountView,
			MemberChargeView,
			GuestVisitView,
			AccessEventView,
		)

		cat = self.config.get("CLUBS_MENU_CATEGORY", "Club Management")

		self.add_view(ClubsDashboardView, "Dashboard", icon="fa-users", category=cat)
		self.add_view(ClubMemberView, "Members", icon="fa-id-card", category=cat)
		self.add_view(MembershipApplicationView, "Applications", icon="fa-file-text", category=cat)
		self.add_view(FacilityView, "Facilities", icon="fa-building", category=cat)
		self.add_view(FacilityBookingView, "Bookings", icon="fa-calendar", category=cat)
		self.add_view(MemberAccountView, "Member Accounts", icon="fa-money", category=cat)
		self.add_view(MemberChargeView, "Member Charges", icon="fa-credit-card", category=cat)
		self.add_view(GuestVisitView, "Guest Visits", icon="fa-user-plus", category=cat)
		self.add_view(AccessEventView, "Access Log", icon="fa-shield", category=cat)

		log.info("ClubsPlugin: views registered under category %r", cat)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ClubsPlugin:
	"""Construct and return a ClubsPlugin bound to *appbuilder*."""
	return ClubsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.clubs.models import (  # noqa: E402
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
from pgappforge.plugins.erp.industry.clubs.services import (  # noqa: E402
	ClubMemberService,
	ClubError,
)

__all__ = [
	# plugin
	"ClubsPlugin",
	"create_plugin",
	# models
	"ClubMembershipType",
	"ClubMember",
	"MembershipApplication",
	"Facility",
	"FacilityBooking",
	"MemberAccount",
	"MemberCharge",
	"GuestVisit",
	"AccessEvent",
	"MemberStatement",
	# services
	"ClubMemberService",
	"ClubError",
]
