"""
pgappforge/plugins/erp/base_view.py

BaseERPView — convenience base class for all ERP module views.

Provides widget helper methods so views can generate KPI tiles, charts,
approval buttons, and data grids without importing each widget directly.
"""
from __future__ import annotations

from typing import Any

from pgappforge.baseviews import BaseView, expose
from pgappforge.security.decorators import has_access
from markupsafe import Markup


class BaseERPView(BaseView):
	"""Base class for all ERP module views with built-in widget support."""

	# ------------------------------------------------------------------
	# KPI tiles
	# ------------------------------------------------------------------

	def kpi_cards(self, kpis: list[dict]) -> Markup:
		"""Render a row of KPI stat cards.

		Args:
			kpis: List of dicts describing each card.  Each dict accepts:

				label   (str)           -- Display label shown below the value.
				value   (int|float|str) -- The KPI value to display.
				format  (str)           -- Formatting hint for the value renderer.
				                          One of: "integer" | "currency" | "percent" | "number".
				color   (str)           -- Accent hex color, e.g. "#1a56db".
				                          Must match ``#RRGGBB``; invalid values fall back to
				                          ``#1a56db``.
				icon    (str)           -- Font Awesome icon class, e.g. "fa-users".
				                          Must match ``fa-<slug>``; invalid values fall back to
				                          ``fa-chart-line``.
				trend   (str|None)      -- Optional trend label rendered below the value,
				                          e.g. "+5.2%".  Omit or set to ``None`` to hide.
				compare (str|None)      -- Optional comparison annotation, e.g. "vs last month".
				                          Omit or set to ``None`` to hide.

		Returns:
			Markup: An HTML fragment containing a CSS grid of StatCardWidget tiles.
			        Safe to emit directly with ``{{ kpi_html | safe }}``.

		Example::

			kpi_html = self.kpi_cards([
				{
					"label":   "Active Users",
					"value":   4_218,
					"format":  "integer",
					"color":   "#1a56db",
					"icon":    "fa-users",
					"trend":   "+12%",
					"compare": "vs last month",
				},
				{
					"label":  "Revenue",
					"value":  98_500.00,
					"format": "currency",
					"color":  "#057a55",
					"icon":   "fa-dollar-sign",
				},
			])
		"""
		import re as _re
		_COLOR_RE = _re.compile(r'^#[0-9a-fA-F]{6}$')
		_ICON_RE = _re.compile(r'^fa-[a-z0-9-]+$')

		from pgappforge.widgets.display_widgets import StatCardWidget
		parts: list[str] = [
			'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));'
			'gap:1rem;margin-bottom:1.5rem">'
		]
		for i, kpi in enumerate(kpis):
			color = kpi.get("color", "#1a56db")
			icon  = kpi.get("icon", "fa-chart-line")
			if not _COLOR_RE.match(str(color)): color = "#1a56db"
			if not _ICON_RE.match(str(icon)):   icon  = "fa-chart-line"
			widget = StatCardWidget(
				value_col="value",
				label=kpi.get("label", ""),
				format=kpi.get("format", "integer"),
				color=color,
				icon=icon,
				trend_col="trend" if kpi.get("trend") is not None else None,
			)
			row = {"value": kpi.get("value", 0), "trend": kpi.get("trend", "")}
			if kpi.get("compare") is not None:
				row["compare"] = kpi["compare"]
			cid = f"kpi_{i}"
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
		"""Render an EmbeddedChartWidget backed by Chart.js.

		Args:
			rows:       List of dicts representing the dataset.  Each dict must
			            contain at least the keys named by ``x_col`` and ``y_col``.
			            If ``group_col`` is set each dict must also contain that key.
			chart_type: Chart.js chart type.  One of:
			            ``"bar"`` | ``"line"`` | ``"pie"`` | ``"doughnut"``
			            | ``"radar"`` | ``"polarArea"``.
			            Defaults to ``"bar"``.
			x_col:      Key in each row dict used as the X-axis label (categories).
			            For pie/doughnut/polarArea this becomes the slice label.
			            Defaults to ``"label"``.
			y_col:      Key in each row dict containing the numeric Y-axis value.
			            Defaults to ``"value"``.
			title:      Optional chart title rendered above the canvas.
			height:     Canvas height in pixels.  Defaults to 280.
			group_col:  If provided, rows are grouped by this key and rendered as
			            separate series (multi-series / stacked chart).  Each
			            distinct value of ``group_col`` becomes one dataset.
			            Set to ``None`` (default) for a single-series chart.

		Returns:
			Markup: An HTML fragment containing the chart canvas wrapped in a
			        container ``<div>``.  Safe to emit with ``{{ chart_html | safe }}``.

		Example — single-series bar chart::

			chart_html = self.chart(
				rows=[
					{"month": "Jan", "revenue": 42000},
					{"month": "Feb", "revenue": 58000},
				],
				chart_type="bar",
				x_col="month",
				y_col="revenue",
				title="Monthly Revenue",
			)

		Example — multi-series line chart grouped by region::

			chart_html = self.chart(
				rows=[
					{"month": "Jan", "region": "North", "sales": 120},
					{"month": "Jan", "region": "South", "sales": 95},
					{"month": "Feb", "region": "North", "sales": 140},
					{"month": "Feb", "region": "South", "sales": 110},
				],
				chart_type="line",
				x_col="month",
				y_col="sales",
				group_col="region",
				title="Sales by Region",
			)
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
		cid = f"ch_{abs(hash(title + str(len(rows)))):08x}"
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
		"""Render an ApprovalButtonWidget for a workflow model instance.

		Emits an "Advance" and a "Reject" button that each POST JSON to their
		respective URLs.  The POST body is::

			{ "instance_id": <value>, "step": <value>, "action": "advance" | "reject" }

		Args:
			obj:             The model instance (or dict) being acted on.  Must
			                 expose ``instance_id_col`` and ``step_col`` as
			                 attributes or dict keys.
			advance_url:     URL that receives a POST when the user clicks "Advance".
			                 Expected payload: ``{"instance_id": str, "step": str,
			                 "action": "advance"}``.
			reject_url:      URL that receives a POST when the user clicks "Reject".
			                 Expected payload: ``{"instance_id": str, "step": str,
			                 "action": "reject"}``.
			instance_id_col: Attribute/key name on ``obj`` that holds the workflow
			                 process instance ID.  Defaults to
			                 ``"process_instance_id"``.
			step_col:        Attribute/key name on ``obj`` that holds the current
			                 workflow step name or identifier.  Defaults to
			                 ``"current_step"``.

		Returns:
			Markup: HTML containing the rendered button pair.
			        Safe to emit with ``{{ buttons_html | safe }}``.

		Example::

			buttons_html = self.approval_buttons(
				obj=leave_request,
				advance_url=url_for("LeaveModule.approve"),
				reject_url=url_for("LeaveModule.reject"),
			)
		"""
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
		"""Render a DataGridWidget for inline bulk editing of tabular data.

		Edited cells are batched and POSTed as JSON to ``save_url`` when the user
		clicks "Save".  The POST body is a list of modified row dicts.

		Args:
			rows:         List of dicts representing the current data.  Each dict
			              must contain a value for every ``key`` defined in
			              ``columns``.
			columns:      List of column descriptor dicts.  Each descriptor accepts:

			              key      (str)  -- Dict key in each row dict.  Required.
			              label    (str)  -- Column header text.  Required.
			              type     (str)  -- Cell data type.  One of:
			                               ``"text"`` | ``"number"`` | ``"date"``
			                               | ``"select"``.  Required.
			              editable (bool) -- Whether the cell is editable by the user.
			                               Non-editable cells render as read-only text.
			                               Required.
			              options  (list) -- For ``type="select"`` only: list of
			                               allowed string values shown in the dropdown.
			                               Omit for other types.

			save_url:     URL receiving a POST when the user saves edits.  The POST
			              body is ``application/json`` containing a list of the
			              modified row dicts.
			rows_per_page: Number of rows shown per page.  Defaults to 25.

		Returns:
			Markup: An HTML fragment containing the rendered editable grid.
			        Safe to emit with ``{{ grid_html | safe }}``.

		Example::

			grid_html = self.data_grid(
				rows=budget_line_items,
				columns=[
					{"key": "description", "label": "Description", "type": "text",   "editable": False},
					{"key": "qty",         "label": "Qty",         "type": "number", "editable": True},
					{"key": "unit_price",  "label": "Unit Price",  "type": "number", "editable": True},
					{"key": "category",    "label": "Category",    "type": "select", "editable": True,
					 "options": ["CAPEX", "OPEX", "PAYROLL"]},
				],
				save_url=url_for("BudgetModule.save_lines"),
			)
		"""
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
		"""Render a HeatmapCalendarWidget showing activity intensity over time.

		Produces a GitHub-style calendar heatmap where each day cell is shaded
		according to its count value.  Days absent from ``rows`` render as zero
		(no activity).

		Args:
			rows:      List of dicts providing per-day counts.  Each dict must
			           contain at least the keys named by ``date_col`` and
			           ``value_col``.  Expected row shape::

			               {"date": "YYYY-MM-DD", "count": int}

			           Dates must be ISO 8601 strings (``"YYYY-MM-DD"``).
			           Duplicate dates are not supported; last-one-wins if
			           duplicates are present.
			date_col:  Key in each row dict containing the ISO date string.
			           Defaults to ``"date"``.
			value_col: Key in each row dict containing the integer activity count.
			           Defaults to ``"count"``.
			title:     Optional heading rendered above the calendar.

		Returns:
			Markup: An HTML fragment containing the rendered calendar heatmap.
			        Safe to emit with ``{{ heatmap_html | safe }}``.

		Example::

			from datetime import date, timedelta
			import random

			# Generate 90 days of synthetic commit activity
			rows = [
				{
					"date":  (date.today() - timedelta(days=i)).isoformat(),
					"count": random.randint(0, 12),
				}
				for i in range(90)
			]

			heatmap_html = self.heatmap_calendar(
				rows=rows,
				title="Commit Activity (last 90 days)",
			)
		"""
		from pgappforge.widgets.display_widgets import HeatmapCalendarWidget

		widget = HeatmapCalendarWidget(
			date_col=date_col,
			value_col=value_col,
			title=title,
		)
		cid = f"hm_{abs(hash(title)):08x}"
		return widget.render(rows, container_id=cid)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _tenant_id(self) -> str:
		from flask import current_app
		return str(current_app.config.get("DEFAULT_TENANT_ID", ""))

	def _session(self):
		from flask import current_app
		return current_app.appbuilder.get_session()

	def _count(self, model: type, session=None, **filters) -> int:
		"""Safely count model rows matching keyword filters. Returns 0 on any error."""
		import sqlalchemy as sa
		from flask import current_app
		try:
			sess = session or current_app.appbuilder.get_session()
			q = sa.select(sa.func.count()).select_from(model)
			for col, val in filters.items():
				q = q.where(getattr(model, col) == val)
			return sess.execute(q).scalar_one() or 0
		except Exception:
			return 0


from pgappforge import ModelView as _ModelView

class BaseERPModelView(_ModelView):
	"""Base ModelView for ERP modules — excludes audit columns by default."""
	_AUDIT = ("id", "created_on", "changed_on", "created_at", "updated_at")
	add_exclude_columns  = list(_AUDIT)
	edit_exclude_columns = list(_AUDIT)
	page_size = 50

	@expose('/import/', methods=['GET', 'POST'])
	@has_access
	def bulk_import(self):
		import csv, io
		from flask import request, flash, redirect, url_for
		if request.method == 'GET':
			return self.render_template('appbuilder/general/model/import.html',
				title='Import ' + self.datamodel.obj.__name__)
		file = request.files.get('file')
		if not file:
			flash('No file uploaded', 'danger')
			return redirect(url_for('.' + self.__class__.__name__ + '.list'))
		stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
		reader = csv.DictReader(stream)
		imported = 0
		errors = []
		for i, row in enumerate(reader):
			try:
				obj = self.datamodel.obj()
				import_cols = getattr(self, 'import_columns', list(row.keys()))
				for col in import_cols:
					if col in row:
						setattr(obj, col, row[col] or None)
				self.datamodel.session.add(obj)
				imported += 1
			except Exception as e:
				errors.append(f'Row {i+2}: {e}')
		try:
			self.datamodel.session.commit()
		except Exception as e:
			self.datamodel.session.rollback()
			errors.append(f'Commit failed: {e}')
			imported = 0
		if errors:
			flash(f'Imported {imported} rows. Errors: {len(errors)}', 'warning')
		else:
			flash(f'Successfully imported {imported} rows', 'success')
		return redirect(url_for('.' + self.__class__.__name__ + '.list'))


__all__ = ["BaseERPView", "BaseERPModelView"]
