"""
pgappforge/plugins/erp/crm/appointments/views.py

Flask-AppBuilder views for the Appointments/Booking plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.crm.appointments.models import Appointment, AppointmentService

log = logging.getLogger(__name__)


class AppointmentServiceView(ModelView):
	datamodel = SQLAInterface(AppointmentService)
	list_columns = ['name', 'category', 'duration_minutes', 'price_cents', 'currency_code', 'is_active']
	label_columns = {
		'name': 'Name',
		'category': 'Category',
		'duration_minutes': 'Duration Minutes',
		'price_cents': 'Price Cents',
		'currency_code': 'Currency Code',
		'is_active': 'Active',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']


class AppointmentView(ModelView):
	datamodel = SQLAInterface(Appointment)
	list_columns = ['booking_ref', 'customer_name', 'staff_id', 'start_at', 'end_at', 'status', 'amount_cents']
	label_columns = {
		'booking_ref': 'Booking Ref',
		'customer_name': 'Customer Name',
		'staff_id': 'Staff',
		'start_at': 'Start At',
		'end_at': 'End At',
		'status': 'Status',
		'amount_cents': 'Amount Cents',
	}
	add_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']
	edit_exclude_columns = ['id', 'created_on', 'changed_on', 'created_at', 'updated_at']


class AppointmentCalendarView(BaseERPView):
	route_base = "/crm/appointments"

	@expose("/")
	@has_access
	def index(self):
		try:
			from pgappforge.plugins.erp.crm.appointments.models import Appointment
			sess = self._session()
			confirmed = self._count(Appointment, session=sess, status="CONFIRMED")
			pending = self._count(Appointment, session=sess, status="PENDING")
			completed = self._count(Appointment, session=sess, status="COMPLETED")
		except Exception:
			confirmed = pending = completed = 0
		kpi_html = self.kpi_cards([
			{"label": "Today's Bookings", "value": confirmed, "icon": "fa-calendar-check-o", "color": "#1a56db"},
			{"label": "Pending", "value": pending, "icon": "fa-clock-o", "color": "#ff5a1f"},
			{"label": "Completed Today", "value": completed, "icon": "fa-check", "color": "#0e9f6e"},
		])
		return render_template(
			"crm_appointments/booking_calendar.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"AppointmentServiceView",
	"AppointmentView",
	"AppointmentCalendarView",
]
