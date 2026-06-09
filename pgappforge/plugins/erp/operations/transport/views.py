"""
pgappforge/plugins/erp/operations/transport/views.py

Flask-AppBuilder views for the Transport plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.operations.transport.models import (
	Carrier,
	FreightRate,
	Shipment,
)

log = logging.getLogger(__name__)


class CarrierView(ModelView):
	datamodel = SQLAInterface(Carrier)
	list_columns = ['name', 'code', 'carrier_type', 'contact_email', 'is_active', 'on_time_delivery_rate_pct']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class FreightRateView(ModelView):
	datamodel = SQLAInterface(FreightRate)
	list_columns = ['carrier_id', 'origin_zone', 'destination_zone', 'rate_cents', 'currency_code']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ShipmentView(ModelView):
	datamodel = SQLAInterface(Shipment)
	list_columns = ['shipment_ref', 'carrier_id', 'status', 'origin', 'destination', 'scheduled_pickup', 'estimated_delivery']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TransportDashboardView(BaseERPView):
	route_base = "/operations/transport"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.transport.models import Shipment
		import sqlalchemy as _sa

		in_transit = self._count(Shipment, status="IN_TRANSIT")
		delivered_today: int = 0
		delayed: int = 0
		try:
			from flask import current_app
			from datetime import date as _date
			session = current_app.appbuilder.get_session()
			today = _date.today()
			delivered_today = session.execute(
				_sa.select(_sa.func.count()).select_from(Shipment).where(
					Shipment.status == "DELIVERED",
					_sa.func.date(Shipment.actual_delivery_at) == today,
				)
			).scalar_one() or 0
			delayed = session.execute(
				_sa.select(_sa.func.count()).select_from(Shipment).where(
					Shipment.status == "IN_TRANSIT",
					Shipment.planned_delivery_date < today,
				)
			).scalar_one() or 0
		except Exception:
			pass

		kpi_html = self.kpi_cards([
			{"label": "In Transit", "value": in_transit, "icon": "fa-truck", "color": "#1a56db"},
			{"label": "Delivered Today", "value": delivered_today, "icon": "fa-check-circle", "color": "#0e9f6e"},
			{"label": "Delayed", "value": delayed, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
		])
		return render_template(
			"operations_ui/transport_dashboard.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"CarrierView",
	"FreightRateView",
	"ShipmentView",
	"TransportDashboardView",
]
