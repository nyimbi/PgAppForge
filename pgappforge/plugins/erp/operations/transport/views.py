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

log = logging.getLogger(__name__)


class CarrierView(ModelView):
	from pgappforge.plugins.erp.operations.transport.models import Carrier
	datamodel = SQLAInterface(Carrier)
	list_columns = ['name', 'code', 'carrier_type', 'contact_email', 'is_active', 'on_time_delivery_rate_pct']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class FreightRateView(ModelView):
	from pgappforge.plugins.erp.operations.transport.models import FreightRate
	datamodel = SQLAInterface(FreightRate)
	list_columns = ['carrier_id', 'origin_zone', 'destination_zone', 'rate_cents', 'currency_code']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ShipmentView(ModelView):
	from pgappforge.plugins.erp.operations.transport.models import Shipment
	datamodel = SQLAInterface(Shipment)
	list_columns = ['shipment_ref', 'carrier_id', 'status', 'origin', 'destination', 'scheduled_pickup', 'estimated_delivery']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class TransportDashboardView(BaseERPView):
	route_base = "/operations/transport"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "In Transit", "value": 0, "icon": "fa-truck", "color": "#1a56db"},
			{"label": "Delivered Today", "value": 0, "icon": "fa-check-circle", "color": "#0e9f6e"},
			{"label": "Delayed", "value": 0, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
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
