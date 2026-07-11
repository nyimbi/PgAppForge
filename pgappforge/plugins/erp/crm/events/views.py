"""
pgappforge/plugins/erp/crm/events/views.py

Flask-AppBuilder views for the Events Management plugin.
"""
from __future__ import annotations
from flask_babel import lazy_gettext as _

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
	label_columns = {
		'title': _('Title'),
		'event_type': _('Event Type'),
		'status': _('Status'),
		'start_datetime': _('Start Datetime'),
		'end_datetime': _('End Datetime'),
		'venue': _('Venue'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketTypeView(ModelView):
	datamodel = SQLAInterface(EventTicketType)
	list_columns = ['event_id', 'name', 'price_cents', 'quantity', 'sold_count']
	label_columns = {
		'event_id': _('Event'),
		'name': _('Name'),
		'price_cents': _('Price Cents'),
		'quantity': _('Quantity'),
		'sold_count': _('Sold Count'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventTicketView(ModelView):
	datamodel = SQLAInterface(EventTicket)
	list_columns = ['ticket_ref', 'attendee_name', 'attendee_email', 'status', 'amount_paid_cents', 'purchased_at']
	label_columns = {
		'ticket_ref': _('Ticket Ref'),
		'attendee_name': _('Attendee Name'),
		'attendee_email': _('Attendee Email'),
		'status': _('Status'),
		'amount_paid_cents': _('Amount Paid Cents'),
		'purchased_at': _('Purchased At'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventAttendanceView(ModelView):
	datamodel = SQLAInterface(EventAttendance)
	list_columns = ['event_id', 'attendee_id', 'checked_in_at', 'checked_out_at']
	label_columns = {
		'event_id': _('Event'),
		'attendee_id': _('Attendee'),
		'checked_in_at': _('Checked In At'),
		'checked_out_at': _('Checked Out At'),
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class EventSponsorView(ModelView):
	datamodel = SQLAInterface(EventSponsor)
	list_columns = ['event_id', 'sponsor_name', 'sponsor_tier', 'amount_cents']
	label_columns = {
		'event_id': _('Event'),
		'sponsor_name': _('Sponsor Name'),
		'sponsor_tier': _('Sponsor Tier'),
		'amount_cents': _('Amount Cents'),
	}
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
