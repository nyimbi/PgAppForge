"""
pgappforge/plugins/erp/crm/events/views.py

Flask-AppBuilder views for the Events Management plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.crm.events.models import (
	Event,
	EventAttendance,
	EventSponsor,
	EventTicket,
	EventTicketType,
)

log = logging.getLogger(__name__)


class EventView(ModelView):
	datamodel = SQLAInterface(Event)
	list_columns = ['title', 'event_type', 'status', 'start_datetime', 'end_datetime', 'venue']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketTypeView(ModelView):
	datamodel = SQLAInterface(EventTicketType)
	list_columns = ['event_id', 'name', 'price_cents', 'quantity', 'sold_count']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketView(ModelView):
	datamodel = SQLAInterface(EventTicket)
	list_columns = ['ticket_ref', 'attendee_name', 'attendee_email', 'status', 'amount_paid_cents', 'purchased_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventAttendanceView(ModelView):
	datamodel = SQLAInterface(EventAttendance)
	list_columns = ['event_id', 'attendee_id', 'checked_in_at', 'checked_out_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventSponsorView(ModelView):
	datamodel = SQLAInterface(EventSponsor)
	list_columns = ['event_id', 'sponsor_name', 'sponsor_tier', 'amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventsDashboardView(BaseERPView):
	route_base = "/crm/events"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.crm.events.models import Event, EventTicket, EventAttendance
			sess = self._session()
			published = self._count(Event, session=sess, status="PUBLISHED")
			tickets_sold = self._count(EventTicket, session=sess, status="CONFIRMED")
			checked_in = self._count(EventAttendance, session=sess)
		except Exception:
			published = tickets_sold = checked_in = 0
		kpi_html = self.kpi_cards([
			{"label": "Published Events", "value": published, "icon": "fa-calendar", "color": "#1a56db"},
			{"label": "Tickets Sold", "value": tickets_sold, "icon": "fa-ticket", "color": "#0e9f6e"},
			{"label": "Checked In", "value": checked_in, "icon": "fa-check-square-o", "color": "#ff5a1f"},
		])
		return render_template(
			"crm_events/events_manager.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"EventView",
	"EventTicketTypeView",
	"EventTicketView",
	"EventAttendanceView",
	"EventSponsorView",
	"EventsDashboardView",
]
