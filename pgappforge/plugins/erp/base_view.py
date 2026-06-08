"""
pgappforge/plugins/erp/base_view.py

BaseERPView — convenience base class for all ERP module views.

Provides widget helper methods so views can generate KPI tiles, charts,
approval buttons, and data grids without importing each widget directly.
"""
from __future__ import annotations

import uuid
from typing import Any

from pgappforge.baseviews import BaseView
from markupsafe import Markup


class BaseERPView(BaseView):
	"""Base class for all ERP module views with built-in widget support."""

	# ------------------------------------------------------------------
	# KPI tiles
	# ------------------------------------------------------------------

	def kpi_cards(self, kpis: list[dict]) -> Markup:
		"""Render a row of KPI stat cards.

		kpis: list of {value, label, format, color, icon, trend?, compare?}
		format: "integer" | "currency" | "percent" | "number"

		Returns Markup ready for {{ kpi_html | safe }}
		"""
		from pgappforge.widgets.display_widgets import StatCardWidget

		parts: list[str] = [
			'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));'
			'gap:1rem;margin-bottom:1.5rem">'
		]
		for i, kpi in enumerate(kpis):
			widget = StatCardWidget(
				value_col="value",
				label=kpi.get("label", ""),
				format=kpi.get("format", "integer"),
				color=kpi.get("color", "#1a56db"),
				icon=kpi.get("icon", "fa-chart-line"),
				trend_col="period" if kpi.get("trend") else None,
			)
			row = {"value": kpi.get("value", 0), "period": kpi.get("period", "")}
			if kpi.get("compare"):
				row["compare"] = kpi["compare"]
			cid = f"kpi_{i}_{uuid.uuid4().hex[:6]}"
			parts.append(str(widget.render([row], container_id=cid)))
		parts.append("</div>")
		return Markup("".join(parts))

	# ------------------------------------------------------------------
	# Charts
	# ------------------------------------------------------------------

	def chart(
		self,
		rows: list[dict],
		chart_type: str = "bar",
		x_col: str = "label",
		y_col: str = "value",
		title: str = "",
		height: int = 280,
		group_col: str | None = None,
	) -> Markup:
		"""Render an EmbeddedChartWidget.

		Returns Markup for {{ chart_html | safe }}.
		"""
		from pgappforge.widgets.display_widgets import EmbeddedChartWidget

		widget = EmbeddedChartWidget(
			chart_type=chart_type,
			x_col=x_col,
			y_col=y_col,
			group_col=group_col,
			title=title,
			height=height,
		)
		cid = f"ch_{uuid.uuid4().hex[:8]}"
		return widget.render(rows, container_id=cid)

	# ------------------------------------------------------------------
	# Approval buttons
	# ------------------------------------------------------------------

	def approval_buttons(
		self,
		obj: Any,
		advance_url: str,
		reject_url: str,
		instance_id_col: str = "process_instance_id",
		step_col: str = "current_step",
	) -> Markup:
		"""Render ApprovalButtonWidget for a model instance."""
		from pgappforge.widgets.action_widgets import ApprovalButtonWidget

		widget = ApprovalButtonWidget(
			instance_id_col=instance_id_col,
			advance_url=advance_url,
			reject_url=reject_url,
			step_col=step_col,
		)
		return widget.render(obj)

	# ------------------------------------------------------------------
	# Data grid
	# ------------------------------------------------------------------

	def data_grid(
		self,
		rows: list[dict],
		columns: list[dict],
		save_url: str,
		rows_per_page: int = 25,
	) -> Markup:
		"""Render a DataGridWidget for inline bulk editing."""
		from pgappforge.widgets.data_widgets import DataGridWidget

		widget = DataGridWidget(
			columns=columns,
			save_url=save_url,
			rows_per_page=rows_per_page,
		)
		return widget.render(rows)

	# ------------------------------------------------------------------
	# Heatmap calendar
	# ------------------------------------------------------------------

	def heatmap_calendar(
		self,
		rows: list[dict],
		date_col: str = "date",
		value_col: str = "count",
		title: str = "",
	) -> Markup:
		"""Render a HeatmapCalendarWidget."""
		from pgappforge.widgets.display_widgets import HeatmapCalendarWidget

		widget = HeatmapCalendarWidget(
			date_col=date_col,
			value_col=value_col,
			title=title,
		)
		cid = f"hm_{uuid.uuid4().hex[:8]}"
		return widget.render(rows, container_id=cid)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _tenant_id(self) -> str:
		from flask import current_app
		return str(current_app.config.get("DEFAULT_TENANT_ID", ""))

	def _session(self):
		from flask import current_app
		return current_app.appbuilder.get_session


__all__ = ["BaseERPView"]
