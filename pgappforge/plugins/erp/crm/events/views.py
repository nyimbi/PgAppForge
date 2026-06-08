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

log = logging.getLogger(__name__)


class EventView(ModelView):
	from pgappforge.plugins.erp.crm.events.models import Event
	datamodel = SQLAInterface(Event)
	list_columns = ['title', 'event_type', 'status', 'start_datetime', 'end_datetime', 'venue']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketTypeView(ModelView):
	from pgappforge.plugins.erp.crm.events.models import EventTicketType
	datamodel = SQLAInterface(EventTicketType)
	list_columns = ['event_id', 'name', 'price_cents', 'quantity', 'sold_count']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketView(ModelView):
	from pgappforge.plugins.erp.crm.events.models import EventTicket
	datamodel = SQLAInterface(EventTicket)
	list_columns = ['ticket_ref', 'attendee_name', 'attendee_email', 'status', 'amount_paid_cents', 'purchased_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventAttendanceView(ModelView):
	from pgappforge.plugins.erp.crm.events.models import EventAttendance
	datamodel = SQLAInterface(EventAttendance)
	list_columns = ['event_id', 'attendee_id', 'checked_in_at', 'checked_out_at']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventSponsorView(ModelView):
	from pgappforge.plugins.erp.crm.events.models import EventSponsor
	datamodel = SQLAInterface(EventSponsor)
	list_columns = ['event_id', 'sponsor_name', 'sponsor_tier', 'amount_cents']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventsDashboardView(BaseERPView):
	route_base = "/crm/events"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Published Events", "value": 0, "icon": "fa-calendar", "color": "#1a56db"},
			{"label": "Tickets Sold", "value": 0, "icon": "fa-ticket", "color": "#0e9f6e"},
			{"label": "Checked In", "value": 0, "icon": "fa-check-square-o", "color": "#ff5a1f"},
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
