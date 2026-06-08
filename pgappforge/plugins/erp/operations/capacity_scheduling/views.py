"""
pgappforge/plugins/erp/operations/capacity_scheduling/views.py

Flask-AppBuilder views for the Capacity Scheduling plugin.
"""
from __future__ import annotations

import logging

from flask import render_template
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView

log = logging.getLogger(__name__)


class WorkCenterView(ModelView):
	from pgappforge.plugins.erp.operations.capacity_scheduling.models import WorkCenter
	datamodel = SQLAInterface(WorkCenter)
	list_columns = ['code', 'name', 'capacity_hours_per_day', 'efficiency_pct', 'setup_time_hours']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CapacityLoadView(ModelView):
	from pgappforge.plugins.erp.operations.capacity_scheduling.models import CapacityLoad
	datamodel = SQLAInterface(CapacityLoad)
	list_columns = ['work_center_id', 'load_date', 'planned_hours', 'actual_hours', 'utilisation_pct']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ProductionScheduleView(ModelView):
	from pgappforge.plugins.erp.operations.capacity_scheduling.models import ProductionSchedule
	datamodel = SQLAInterface(ProductionSchedule)
	list_columns = ['work_center_id', 'order_ref', 'scheduled_start', 'scheduled_end', 'status']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CapacityGanttView(BaseERPView):
	route_base = "/operations/capacity"

	@expose("/")
	@has_access
	def index(self):
		kpi_html = self.kpi_cards([
			{"label": "Work Centers", "value": 0, "icon": "fa-industry", "color": "#1a56db"},
			{"label": "Avg Utilisation (%)", "value": 0, "format": "percent", "icon": "fa-bar-chart", "color": "#0e9f6e"},
			{"label": "Overloaded Centers", "value": 0, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
		])
		return render_template(
			"operations/capacity_gantt.html",
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"WorkCenterView",
	"CapacityLoadView",
	"ProductionScheduleView",
	"CapacityGanttView",
]
