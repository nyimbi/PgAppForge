"""
pgappforge/plugins/erp/crm/events/__init__.py

EventsPlugin — event publishing, ticketing, attendee check-in, and
sponsorship management for the CRM domain.

Events emitted
--------------
  crm.events.published              — event transitions DRAFT → PUBLISHED
  crm.events.ticket.purchased       — ticket confirmed for an attendee
  crm.events.attendee.checked_in    — attendee scanned in at the venue
  crm.events.completed              — event marked COMPLETED with final tallies
  crm.events.sponsor.added          — sponsor attached to an event

Events consumed
---------------
  crm.marketing.campaign.activated  — optionally pre-populate event registration campaign
  crm.contacts.created              — auto-enrol new contacts in upcoming events

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.crm.events",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EventsPlugin(BasePlugin):
	"""Events Management ERP plugin.

	Manages the full event lifecycle: creation, publication, multi-tier
	ticketing with capacity control, QR-code-enabled check-in, and
	sponsorship tracking.  Exposes a BPM action for ticket purchase from
	workflow steps.

	Class-level attributes for dependency resolution:
	    name       = "events"
	    domain     = "crm"
	    depends_on = ["foundation"]
	"""

	name = "events"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="events",
			version="1.0.0",
			description=(
				"Events Management — full lifecycle: creation, ticketing, "
				"capacity control, attendee check-in, and sponsorship tracking."
			),
			author="PgAppForge Contributors",
			tags=["crm", "events", "ticketing", "conferences"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_evt_event_list",
				"can_evt_event_write",
				"can_evt_event_publish",
				"can_evt_ticket_type_write",
				"can_evt_ticket_list",
				"can_evt_ticket_purchase",
				"can_evt_attendance_checkin",
				"can_evt_sponsor_write",
				"can_evt_dashboard",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.events.published",
			"crm.events.ticket.purchased",
			"crm.events.attendee.checked_in",
			"crm.events.completed",
			"crm.events.sponsor.added",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"crm.marketing.campaign.activated",  # optional: link event to campaign
			"crm.contacts.created",              # optional: auto-register contact
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"EVENTS_MENU_CATEGORY": "Events",
			"EVENTS_DEFAULT_CURRENCY": "KES",
			"EVENTS_TICKET_REF_PREFIX": "EVT",
		}
		self.config = {**defaults, **self.config}
		log.info("EventsPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		self._subscribe_to_events()

	def register_views(self) -> None:
		try:
			from pgappforge.plugins.erp.crm.events.views import (
				EventView,
				EventTicketTypeView,
				EventTicketView,
				EventAttendanceView,
				EventSponsorView,
			)
			cat = self.config.get("EVENTS_MENU_CATEGORY", "Events")
			self.add_view(EventView, "Events", icon="fa-calendar", category=cat)
			self.add_view(EventTicketTypeView, "Ticket Types", icon="fa-ticket", category=cat)
			self.add_view(EventTicketView, "Tickets", icon="fa-barcode", category=cat)
			self.add_view(EventAttendanceView, "Check-In", icon="fa-check-square-o", category=cat)
			self.add_view(EventSponsorView, "Sponsors", icon="fa-handshake-o", category=cat)
			log.info("EventsPlugin: views registered under category %r", cat)
		except ImportError as exc:
			log.debug("EventsPlugin.register_views: views not available — %s", exc)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.events.models import (
			Event,
			EventAttendance,
			EventSponsor,
			EventTicket,
			EventTicketType,
		)
		return [
			Event,
			EventTicketType,
			EventTicket,
			EventAttendance,
			EventSponsor,
		]

	def _subscribe_to_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("crm.marketing.campaign.activated", self._on_campaign_activated)
			subscribe("crm.contacts.created", self._on_contact_created)
			log.debug(
				"EventsPlugin: subscribed to crm.marketing.campaign.activated and crm.contacts.created"
			)
		except Exception as exc:
			log.warning("EventsPlugin._subscribe_to_events failed: %s", exc)

	def _on_campaign_activated(self, event: Any) -> None:
		"""Optional: link a newly activated campaign to an event registration flow."""
		log.debug(
			"EventsPlugin._on_campaign_activated: campaign=%s",
			getattr(event, "campaign_id", "?"),
		)

	def _on_contact_created(self, event: Any) -> None:
		"""Optional: auto-register a new contact in upcoming public events."""
		log.debug(
			"EventsPlugin._on_contact_created: contact=%s",
			getattr(event, "party_id", "?"),
		)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EventsPlugin:
	"""Construct and return an EventsPlugin bound to *appbuilder*."""
	return EventsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.events.models import (  # noqa: E402
	Event,
	EventAttendance,
	EventSponsor,
	EventTicket,
	EventTicketType,
)
from pgappforge.plugins.erp.crm.events.events import (  # noqa: E402
	AttendeeCheckedInEvent,
	EventCompletedEvent,
	EventPublishedEvent,
	SponsorAddedEvent,
	TicketPurchasedEvent,
)
from pgappforge.plugins.erp.crm.events.services import (  # noqa: E402
	EventsNotFoundError,
	EventsService,
	EventsServiceError,
	EventsStateError,
)

__all__ = [
	# plugin
	"EventsPlugin",
	"create_plugin",
	# models
	"Event",
	"EventTicketType",
	"EventTicket",
	"EventAttendance",
	"EventSponsor",
	# events
	"EventPublishedEvent",
	"TicketPurchasedEvent",
	"AttendeeCheckedInEvent",
	"EventCompletedEvent",
	"SponsorAddedEvent",
	# services
	"EventsService",
	"EventsServiceError",
	"EventsNotFoundError",
	"EventsStateError",
]
