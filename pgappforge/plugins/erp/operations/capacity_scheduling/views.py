"""
pgappforge/plugins/erp/operations/capacity_scheduling/views.py

Flask-AppBuilder views for the Capacity Scheduling plugin.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta

from flask import render_template, request
from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
	CapacityLoad,
	ProductionSchedule,
	WorkCenter,
)

log = logging.getLogger(__name__)


class WorkCenterView(ModelView):
	datamodel = SQLAInterface(WorkCenter)
	list_columns = ['code', 'name', 'capacity_hours_per_day', 'efficiency_pct', 'setup_time_hours']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CapacityLoadView(ModelView):
	datamodel = SQLAInterface(CapacityLoad)
	list_columns = ['work_center_id', 'load_date', 'planned_hours', 'actual_hours', 'utilisation_pct']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class ProductionScheduleView(ModelView):
	datamodel = SQLAInterface(ProductionSchedule)
	list_columns = ['work_center_id', 'order_ref', 'scheduled_start', 'scheduled_end', 'status']
	add_exclude_columns = ['id', 'created_on', 'changed_on']
	edit_exclude_columns = ['id', 'created_on', 'changed_on']


class CapacityGanttView(BaseERPView):
	route_base = "/operations/capacity"

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.capacity_scheduling.models import (
			WorkCenter,
			CapacityLoad,
			ProductionSchedule,
		)
		import sqlalchemy as _sa

		def _parse_date_arg(name: str, default: date) -> date:
			value = request.args.get(name)
			if not value:
				return default
			try:
				return date.fromisoformat(value)
			except ValueError:
				return default

		def _status_class(status: str | None) -> str:
			status_map = {
				"PLANNED": "on-track",
				"CONFIRMED": "on-track",
				"COMPLETED": "done",
				"CANCELLED": "delayed",
			}
			return status_map.get(str(status or "").upper(), "on-track")

		today = date.today()
		default_from = today - timedelta(days=today.weekday())
		default_to = default_from + timedelta(days=6)
		from_date = _parse_date_arg("from_date", default_from)
		to_date = _parse_date_arg("to_date", default_to)
		if to_date < from_date:
			from_date, to_date = to_date, from_date

		work_centers = self._count(WorkCenter)
		overloaded: int = 0
		avg_utilisation: float = 0.0
		tasks: list[dict] = []
		try:
			from flask import current_app
			session = current_app.appbuilder.get_session()
			row = session.execute(
				_sa.select(
					_sa.func.avg(CapacityLoad.utilization_pct),
					_sa.func.count(_sa.case(
						(CapacityLoad.utilization_pct > 100, 1),
					)).label("overloaded"),
				).select_from(CapacityLoad)
			).one()
			avg_utilisation = float(row[0] or 0)
			overloaded = int(row[1] or 0)

			start_boundary = datetime.combine(from_date, time.min)
			end_boundary = datetime.combine(to_date, time.max)
			schedules = session.execute(
				_sa.select(ProductionSchedule)
				.where(ProductionSchedule.start_datetime <= end_boundary)
				.where(ProductionSchedule.end_datetime >= start_boundary)
				.order_by(
					ProductionSchedule.start_datetime.asc(),
					ProductionSchedule.work_center_id.asc(),
					ProductionSchedule.priority.asc(),
				)
			).scalars().all()

			for schedule in schedules:
				start_date = schedule.start_datetime.date()
				end_date = schedule.end_datetime.date()
				start_offset = max((start_date - from_date).days, 0)
				end_offset = min((end_date - from_date).days, (to_date - from_date).days)
				duration = max(end_offset - start_offset + 1, 1)
				tasks.append({
					"id": schedule.id,
					"title": schedule.production_order_id,
					"resource": schedule.work_center_id,
					"assignee": schedule.work_center_id,
					"start": str(schedule.start_datetime),
					"end": str(schedule.end_datetime),
					"start_date": schedule.start_datetime.isoformat(),
					"end_date": schedule.end_datetime.isoformat(),
					"start_offset": start_offset,
					"duration": duration,
					"status": _status_class(schedule.status),
					"raw_status": schedule.status,
					"pct_done": 100 if str(schedule.status).upper() == "COMPLETED" else 0,
				})
		except Exception:
			pass

		day_count = (to_date - from_date).days + 1
		dates_json = []
		for offset in range(day_count):
			current = from_date + timedelta(days=offset)
			dates_json.append({
				"iso": current.isoformat(),
				"label": str(current.day),
				"weekend": current.weekday() >= 5,
				"today": current == today,
				"month_start": current.day == 1,
				"month": current.strftime("%b"),
			})

		kpi_html = self.kpi_cards([
			{"label": "Work Centers", "value": work_centers, "icon": "fa-industry", "color": "#1a56db"},
			{"label": "Avg Utilisation (%)", "value": avg_utilisation, "format": "percent", "icon": "fa-bar-chart", "color": "#0e9f6e"},
			{"label": "Overloaded Centers", "value": overloaded, "icon": "fa-exclamation-triangle", "color": "#9e1c00"},
		])
		return render_template(
			"operations/capacity_gantt.html",
			kpi_html=kpi_html,
			tasks=tasks,
			tasks_json=json.dumps(tasks),
			dates_json=dates_json,
			dates_json_text=json.dumps([d["iso"] for d in dates_json]),
			day_count=day_count,
			from_date=from_date,
			to_date=to_date,
			appbuilder=self.appbuilder,
		)


__all__ = [
	"WorkCenterView",
	"CapacityLoadView",
	"ProductionScheduleView",
	"CapacityGanttView",
]
