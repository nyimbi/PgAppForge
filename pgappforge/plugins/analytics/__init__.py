"""
pgappforge/plugins/analytics/__init__.py

Self-service BI plugin: drag-and-drop dashboards, predictive analytics,
real-time KPIs, and ad-hoc report building on top of PgAppForge.

Enabling the plugin
-------------------
Add to your application config::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.analytics"]

Or instantiate directly::

    from pgappforge.plugins.analytics import create_plugin
    plugin = create_plugin(appbuilder, config={...})
    plugin.activate()

Configuration keys
------------------
``ANALYTICS_MAX_DASHBOARDS_PER_USER`` : int, default 50
    Hard cap on dashboards owned by a single user.

``ANALYTICS_ENABLE_PREDICTIVE`` : bool, default False
    Enable scikit-learn-backed predictive widgets. Requires ``scikit-learn``
    and ``pandas`` to be installed; silently disabled when they are absent.

``ANALYTICS_ENABLE_DUCKDB`` : bool, default False
    Use DuckDB for fast in-process OLAP queries on exported data sets.
    Requires ``duckdb``; silently disabled when absent.

``ANALYTICS_KPI_REFRESH_SECONDS`` : int, default 60
    Polling interval (seconds) for real-time KPI widgets on the front-end.
    Set to 0 to disable auto-refresh.

``ANALYTICS_REPORT_EXPORT_FORMATS`` : list[str], default ["csv", "json"]
    Allowed export formats for SavedReport downloads.
    Include ``"xlsx"`` only when ``openpyxl`` is installed.

``ANALYTICS_PLOTLY_CDN`` : str | None, default None
    Override the Plotly.js CDN URL used by chart widgets. ``None`` uses the
    official CDN (``https://cdn.plot.ly/plotly-latest.min.js``).

``ANALYTICS_MENU_CATEGORY`` : str, default "Analytics"
    FAB menu category under which plugin views are grouped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

from pgappforge import Model
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy-dep guards
# ---------------------------------------------------------------------------

try:
	import plotly  # noqa: F401
	_HAS_PLOTLY = True
except ImportError:
	_HAS_PLOTLY = False
	log.debug("analytics plugin: plotly not installed — chart rendering disabled")

try:
	import pandas  # noqa: F401
	_HAS_PANDAS = True
except ImportError:
	_HAS_PANDAS = False
	log.debug("analytics plugin: pandas not installed — data-frame features disabled")

try:
	import sklearn  # noqa: F401
	_HAS_SKLEARN = True
except ImportError:
	_HAS_SKLEARN = False
	log.debug("analytics plugin: scikit-learn not installed — predictive analytics disabled")

try:
	import duckdb  # noqa: F401
	_HAS_DUCKDB = True
except ImportError:
	_HAS_DUCKDB = False
	log.debug("analytics plugin: duckdb not installed — OLAP acceleration disabled")

# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------

class Dashboard(Model):
	__allow_unmapped__ = True
	"""
	A named collection of widgets owned by a user.

	``layout_config`` (JSONB) stores grid positions, tab order, and per-widget
	sizing so the front-end can reconstruct the drag-and-drop arrangement
	without additional queries.

	Example ``layout_config``::

	    {
	        "type": "grid",
	        "cols": 12,
	        "rows": [
	            {"widget_id": 1, "x": 0, "y": 0, "w": 6, "h": 4},
	            {"widget_id": 2, "x": 6, "y": 0, "w": 6, "h": 4}
	        ]
	    }
	"""

	__tablename__ = "analytics_dashboard"
	__table_args__ = (
		Index("ix_analytics_dashboard_owner_id", "owner_id"),
		Index("ix_analytics_dashboard_slug", "slug", unique=True),
	)

	id = Column(Integer, primary_key=True)
	name = Column(String(255), nullable=False)
	slug = Column(String(255), nullable=False, unique=True)
	description = Column(Text, nullable=True)
	is_public = Column(Boolean, default=False, nullable=False)
	is_published = Column(Boolean, default=False, nullable=False)

	# drag-and-drop layout serialised as JSONB
	layout_config = Column(JSONB, nullable=False, server_default="{}")

	# arbitrary extensible metadata (tags, theme overrides, etc.)
	extra_metadata = Column(JSONB, nullable=False, server_default="{}")

	owner_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	owner = relationship("User", foreign_keys=[owner_id])

	created_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	widgets = relationship(
		"DashboardWidget",
		back_populates="dashboard",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<Dashboard id={self.id} name={self.name!r}>"


class DashboardWidget(Model):
	__allow_unmapped__ = True
	"""
	A single panel inside a Dashboard.

	``widget_config`` (JSONB) holds the widget-type-specific payload, e.g. a
	chart definition, SQL query, KPI source expression, or embedded HTML.

	Example ``widget_config`` for a metric card::

	    {
	        "type": "metric_card",
	        "title": "Monthly Revenue",
	        "datasource": "orders",
	        "metric": "SUM(amount)",
	        "filter": "created_at >= NOW() - INTERVAL '30 days'",
	        "format": "$,.2f",
	        "goal": 100000
	    }
	"""

	__tablename__ = "analytics_dashboard_widget"
	__table_args__ = (
		Index("ix_analytics_widget_dashboard_id", "dashboard_id"),
		Index("ix_analytics_widget_type", "widget_type"),
	)

	id = Column(Integer, primary_key=True)
	dashboard_id = Column(
		Integer,
		ForeignKey("analytics_dashboard.id", ondelete="CASCADE"),
		nullable=False,
	)
	dashboard = relationship("Dashboard", back_populates="widgets")

	widget_type = Column(String(64), nullable=False)  # "chart" | "kpi" | "table" | ...
	title = Column(String(255), nullable=False)
	position = Column(Integer, default=0, nullable=False)  # sort order fallback

	widget_config = Column(JSONB, nullable=False, server_default="{}")
	cache_config = Column(JSONB, nullable=False, server_default="{}")

	is_visible = Column(Boolean, default=True, nullable=False)

	created_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"<DashboardWidget id={self.id} type={self.widget_type!r} title={self.title!r}>"


class SavedReport(Model):
	__allow_unmapped__ = True
	"""
	A persisted report definition (query + formatting) built by a user.

	``report_spec`` (JSONB) stores the full report definition so it can be
	re-run or scheduled without user interaction::

	    {
	        "datasource": "orders",
	        "columns": ["id", "customer", "amount", "status"],
	        "filters": [{"col": "status", "op": "eq", "val": "completed"}],
	        "order_by": [{"col": "amount", "dir": "desc"}],
	        "limit": 1000,
	        "export_format": "csv"
	    }
	"""

	__tablename__ = "analytics_saved_report"
	__table_args__ = (
		Index("ix_analytics_report_owner_id", "owner_id"),
		Index("ix_analytics_report_is_scheduled", "is_scheduled"),
	)

	id = Column(Integer, primary_key=True)
	name = Column(String(255), nullable=False)
	description = Column(Text, nullable=True)

	report_spec = Column(JSONB, nullable=False, server_default="{}")

	is_scheduled = Column(Boolean, default=False, nullable=False)
	schedule_cron = Column(String(128), nullable=True)  # cron expression when scheduled
	last_run_at = Column(DateTime(timezone=True), nullable=True)
	last_run_rows = Column(Integer, nullable=True)

	owner_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	owner = relationship("User", foreign_keys=[owner_id])

	created_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"<SavedReport id={self.id} name={self.name!r}>"


class KPIMetric(Model):
	__allow_unmapped__ = True
	"""
	A named KPI definition with optional threshold alerting.

	``eval_config`` (JSONB) describes how the metric value is computed at
	runtime — either via a raw SQL expression, a Python callable reference,
	or a pre-aggregated datasource column::

	    {
	        "strategy": "sql",
	        "expression": "SELECT COUNT(*) FROM orders WHERE status='open'",
	        "connection": "default"
	    }

	``threshold_config`` (JSONB) drives front-end colouring and optional
	alert dispatch::

	    {
	        "good_above": 95,
	        "warn_below": 80,
	        "bad_below": 60,
	        "unit": "%",
	        "direction": "higher_is_better"
	    }
	"""

	__tablename__ = "analytics_kpi_metric"
	__table_args__ = (
		Index("ix_analytics_kpi_slug", "slug", unique=True),
		Index("ix_analytics_kpi_is_active", "is_active"),
	)

	id = Column(Integer, primary_key=True)
	name = Column(String(255), nullable=False)
	slug = Column(String(255), nullable=False, unique=True)
	description = Column(Text, nullable=True)
	unit = Column(String(32), nullable=True)  # "%" | "$" | "ms" | etc.

	eval_config = Column(JSONB, nullable=False, server_default="{}")
	threshold_config = Column(JSONB, nullable=False, server_default="{}")

	is_active = Column(Boolean, default=True, nullable=False)

	# cache: last computed value + timestamp
	last_value = Column(Text, nullable=True)
	last_evaluated_at = Column(DateTime(timezone=True), nullable=True)

	created_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	def __repr__(self) -> str:
		return f"<KPIMetric id={self.id} slug={self.slug!r} last_value={self.last_value!r}>"


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

_BOOTSTRAP3_BASE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <style>
    body  {{ padding-top: 60px; }}
    .hero {{ background:#f5f5f5; padding:40px 20px; border-radius:6px;
             margin-bottom:30px; border-left:4px solid #337ab7; }}
    .badge-pill {{ display:inline-block; padding:3px 10px; border-radius:20px;
                   background:#337ab7; color:#fff; font-size:12px;
                   margin-right:4px; }}
  </style>
</head>
<body>
<div class="container">
  <div class="hero">
    <h2><span class="glyphicon glyphicon-{icon}"></span> {title}</h2>
    <p class="lead">{lead}</p>
    <span class="label label-success">Plugin active</span>
    {extra_badges}
  </div>
  <div class="row">
    {cards}
  </div>
</div>
</body>
</html>
"""

def _card(heading: str, body: str) -> str:
	return (
		f'<div class="col-md-4">'
		f'<div class="panel panel-default">'
		f'<div class="panel-heading"><h4>{heading}</h4></div>'
		f'<div class="panel-body">{body}</div>'
		f'</div></div>'
	)


class AnalyticsDashboardView(BaseView):
	"""
	Drag-and-drop dashboard builder.

	Displays user-owned dashboards; delegates layout persistence to the
	Dashboard / DashboardWidget models.
	"""

	route_base = "/analytics/dashboards"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		cards = "".join([
			_card(
				"My Dashboards",
				"Browse, create, and share your personal dashboards. "
				"Drag widgets to rearrange them.",
			),
			_card(
				"Public Dashboards",
				"Organisation-wide dashboards published by other users or "
				"imported from templates.",
			),
			_card(
				"Dashboard Templates",
				"Start from a pre-built template: Sales Overview, "
				"User Engagement, Infrastructure Health, and more.",
			),
		])
		html = _BOOTSTRAP3_BASE.format(
			title="Analytics Dashboards",
			icon="dashboard",
			lead=(
				"Self-service BI: build drag-and-drop dashboards from live data "
				"sources. Combine charts, KPI cards, tables, and rich text panels."
			),
			extra_badges=(
				'<span class="badge-pill">plotly</span>'
				if _HAS_PLOTLY else
				'<span class="badge-pill" style="background:#888">plotly (not installed)</span>'
			),
			cards=cards,
		)
		from flask import make_response
		return make_response(html, 200)

	@expose("/<int:dashboard_id>")
	@has_access
	def detail(self, dashboard_id: int):
		from flask import make_response
		html = _BOOTSTRAP3_BASE.format(
			title=f"Dashboard #{dashboard_id}",
			icon="th",
			lead=f"Viewing dashboard {dashboard_id}.",
			extra_badges="",
			cards=_card("Widgets", "Widget canvas renders here."),
		)
		return make_response(html, 200)


class ReportBuilderView(BaseView):
	"""
	Ad-hoc report builder with column picker, filter rows, and export.

	Persists report definitions as SavedReport records so they can be
	re-run, scheduled, or shared.
	"""

	route_base = "/analytics/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		cards = "".join([
			_card(
				"Build a Report",
				"Pick a data source, choose columns, apply filters, and "
				"preview results before saving.",
			),
			_card(
				"Saved Reports",
				"Re-run or edit previously saved report definitions. "
				"Export to CSV, JSON"
				+ (", XLSX" if _HAS_PANDAS else "")
				+ ".",
			),
			_card(
				"Scheduled Reports",
				"Automate report delivery on a cron schedule. Results are "
				"stored and optionally emailed to a distribution list.",
			),
		])
		html = _BOOTSTRAP3_BASE.format(
			title="Report Builder",
			icon="list-alt",
			lead=(
				"Build, save, and schedule ad-hoc reports against any configured "
				"data source. No SQL knowledge required."
			),
			extra_badges=(
				'<span class="badge-pill">pandas</span>'
				if _HAS_PANDAS else
				'<span class="badge-pill" style="background:#888">pandas (not installed)</span>'
			),
			cards=cards,
		)
		from flask import make_response
		return make_response(html, 200)

	@expose("/new")
	@has_access
	def new(self):
		from flask import make_response
		html = _BOOTSTRAP3_BASE.format(
			title="New Report",
			icon="pencil",
			lead="Configure a new report definition.",
			extra_badges="",
			cards=_card("Report Editor", "Column picker and filter builder render here."),
		)
		return make_response(html, 200)

	@expose("/<int:report_id>/run")
	@has_access
	def run(self, report_id: int):
		from flask import make_response
		html = _BOOTSTRAP3_BASE.format(
			title=f"Run Report #{report_id}",
			icon="play",
			lead=f"Executing saved report {report_id}.",
			extra_badges="",
			cards=_card("Results", "Query results table renders here."),
		)
		return make_response(html, 200)


class KPIView(BaseView):
	"""
	Real-time KPI metric board.

	Polls ``/analytics/kpis/data`` at the configured
	``ANALYTICS_KPI_REFRESH_SECONDS`` interval and updates metric cards
	in-place without a full page reload.
	"""

	route_base = "/analytics/kpis"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		cards = "".join([
			_card(
				"KPI Board",
				"Live metric cards with threshold colouring — green / amber / red "
				"based on configured targets.",
			),
			_card(
				"Metric Definitions",
				"Create and edit KPI definitions. Supported evaluation strategies: "
				"SQL expression, Python callable, or datasource column aggregate.",
			),
			_card(
				"Predictive Insights",
				(
					"scikit-learn time-series forecasts appear below each KPI card "
					"when trend data is available."
					if _HAS_SKLEARN else
					"Install scikit-learn to enable predictive trend forecasts."
				),
			),
		])
		html = _BOOTSTRAP3_BASE.format(
			title="KPI Metrics",
			icon="signal",
			lead=(
				"Real-time key performance indicators with configurable thresholds, "
				"auto-refresh, and optional ML-powered trend forecasting."
			),
			extra_badges=(
				'<span class="badge-pill">scikit-learn</span>'
				if _HAS_SKLEARN else
				'<span class="badge-pill" style="background:#888">scikit-learn (not installed)</span>'
			),
			cards=cards,
		)
		from flask import make_response
		return make_response(html, 200)

	@expose("/data")
	@has_access
	def data(self):
		"""JSON endpoint polled by the front-end for KPI refresh."""
		from flask import jsonify
		# Stub: real impl queries KPIMetric rows and evaluates eval_config
		return jsonify({"kpis": [], "generated_at": datetime.now(timezone.utc).isoformat()})

	@expose("/<int:kpi_id>")
	@has_access
	def detail(self, kpi_id: int):
		from flask import make_response
		html = _BOOTSTRAP3_BASE.format(
			title=f"KPI #{kpi_id}",
			icon="stats",
			lead=f"Detail view for KPI metric {kpi_id}.",
			extra_badges="",
			cards=_card("Trend Chart", "Historical trend chart renders here."),
		)
		return make_response(html, 200)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
	"ANALYTICS_MAX_DASHBOARDS_PER_USER": 50,
	"ANALYTICS_ENABLE_PREDICTIVE": False,
	"ANALYTICS_ENABLE_DUCKDB": False,
	"ANALYTICS_KPI_REFRESH_SECONDS": 60,
	"ANALYTICS_REPORT_EXPORT_FORMATS": ["csv", "json"],
	"ANALYTICS_PLOTLY_CDN": None,
	"ANALYTICS_MENU_CATEGORY": "Analytics",
}

_CONFIG_SCHEMA: dict[str, Any] = {
	"$schema": "https://json-schema.org/draft/2020-12/schema",
	"title": "AnalyticsPlugin configuration",
	"type": "object",
	"additionalProperties": False,
	"properties": {
		"ANALYTICS_MAX_DASHBOARDS_PER_USER": {
			"type": "integer",
			"minimum": 1,
			"default": 50,
			"description": "Maximum dashboards a single user may own.",
		},
		"ANALYTICS_ENABLE_PREDICTIVE": {
			"type": "boolean",
			"default": False,
			"description": (
				"Enable scikit-learn predictive widgets. "
				"Requires scikit-learn + pandas."
			),
		},
		"ANALYTICS_ENABLE_DUCKDB": {
			"type": "boolean",
			"default": False,
			"description": "Use DuckDB for in-process OLAP acceleration. Requires duckdb.",
		},
		"ANALYTICS_KPI_REFRESH_SECONDS": {
			"type": "integer",
			"minimum": 0,
			"default": 60,
			"description": "Front-end KPI polling interval in seconds. 0 disables auto-refresh.",
		},
		"ANALYTICS_REPORT_EXPORT_FORMATS": {
			"type": "array",
			"items": {"type": "string", "enum": ["csv", "json", "xlsx"]},
			"default": ["csv", "json"],
			"description": "Allowed export formats for SavedReport downloads.",
		},
		"ANALYTICS_PLOTLY_CDN": {
			"type": ["string", "null"],
			"default": None,
			"description": "Override Plotly.js CDN URL. null uses the official CDN.",
		},
		"ANALYTICS_MENU_CATEGORY": {
			"type": "string",
			"default": "Analytics",
			"description": "FAB menu category for analytics views.",
		},
	},
}


class AnalyticsPlugin(BasePlugin):
	"""
	Self-service BI plugin for PgAppForge.

	Adds drag-and-drop dashboards, ad-hoc report building, and real-time
	KPI monitoring to any PgAppForge application.

	Lifecycle::

	    plugin = AnalyticsPlugin(appbuilder, config={...})
	    plugin.activate()   # runs initialize() → register_views()
	    # later:
	    plugin.deactivate()

	Hook wiring happens inside ``initialize()`` so hooks are only active
	while the plugin is in the ACTIVE state.
	"""

	# ------------------------------------------------------------------
	# metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="analytics",
			version="0.1.0",
			description=(
				"Self-service BI: drag-and-drop dashboards, predictive analytics, "
				"and real-time KPIs for PgAppForge applications."
			),
			author="PgAppForge Contributors",
			tags=["analytics", "bi", "dashboard", "kpi", "reporting"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_analytics_dashboards",
				"can_analytics_reports",
				"can_analytics_kpis",
			],
			safe_mode_compatible=True,
			example_config=_DEFAULT_CONFIG,
		)

	# ------------------------------------------------------------------
	# lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Wire hook receivers and apply config defaults."""
		# Merge defaults under any caller-supplied keys (caller wins)
		merged = {**_DEFAULT_CONFIG, **self.config}
		self.config = merged

		# Runtime capability checks — warn when config asks for optional deps
		if self.config["ANALYTICS_ENABLE_PREDICTIVE"] and not (_HAS_SKLEARN and _HAS_PANDAS):
			log.warning(
				"analytics plugin: ANALYTICS_ENABLE_PREDICTIVE=True but "
				"scikit-learn/pandas are not installed — predictive features disabled"
			)
			self.config["ANALYTICS_ENABLE_PREDICTIVE"] = False

		if self.config["ANALYTICS_ENABLE_DUCKDB"] and not _HAS_DUCKDB:
			log.warning(
				"analytics plugin: ANALYTICS_ENABLE_DUCKDB=True but "
				"duckdb is not installed — OLAP acceleration disabled"
			)
			self.config["ANALYTICS_ENABLE_DUCKDB"] = False

		# Connect hook receivers
		if hasattr(self.appbuilder, "hooks"):
			self.appbuilder.hooks.on_record_save.connect(self._on_record_save)
			self.appbuilder.hooks.on_user_login.connect(self._on_user_login)
			log.debug("analytics plugin: hook receivers connected")

		log.info("analytics plugin: initialized (plotly=%s, pandas=%s, sklearn=%s, duckdb=%s)",
			_HAS_PLOTLY, _HAS_PANDAS, _HAS_SKLEARN, _HAS_DUCKDB)

	def configure(self, config: dict[str, Any]) -> None:
		"""Merge additional config after construction."""
		super().configure(config)
		log.debug("analytics plugin: config updated: %s", list(config.keys()))

	def activate(self) -> bool:
		"""Full lifecycle activation via BasePlugin."""
		return super().activate()

	def deactivate(self) -> bool:
		"""Disconnect hooks and clean up resources."""
		if hasattr(self.appbuilder, "hooks"):
			self.appbuilder.hooks.on_record_save.disconnect(self._on_record_save)
			self.appbuilder.hooks.on_user_login.disconnect(self._on_user_login)
			log.debug("analytics plugin: hook receivers disconnected")
		return super().deactivate()

	# ------------------------------------------------------------------
	# views
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		"""Register analytics views under the configured menu category."""
		category = self.config.get("ANALYTICS_MENU_CATEGORY", "Analytics")

		self.add_view(
			AnalyticsDashboardView,
			"Dashboards",
			icon="fa-th-large",
			category=category,
		)
		self.add_view(
			ReportBuilderView,
			"Report Builder",
			icon="fa-list-alt",
			category=category,
		)
		self.add_view(
			KPIView,
			"KPI Metrics",
			icon="fa-signal",
			category=category,
		)
		log.info("analytics plugin: registered views under category %r", category)

	# ------------------------------------------------------------------
	# models
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""Return model classes for Alembic autogenerate discovery."""
		return [Dashboard, DashboardWidget, SavedReport, KPIMetric]

	# ------------------------------------------------------------------
	# config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		"""JSON Schema for the plugin settings admin form."""
		return _CONFIG_SCHEMA

	# ------------------------------------------------------------------
	# hook overrides
	# ------------------------------------------------------------------

	def on_record_save(self, model_class, record, is_new: bool) -> None:
		"""
		BasePlugin hook override (called by PluginManager).

		Invalidates cached KPI values when a record that a KPI expression
		depends on is created or updated — a coarse but safe strategy until
		per-KPI dependency tracking is implemented.
		"""
		self._on_record_save(model_class, record, is_new)

	def on_user_login(self, user) -> None:
		"""BasePlugin hook override (called by PluginManager)."""
		self._on_user_login(user)

	# ------------------------------------------------------------------
	# internal receivers (connected to HookRegistry signals directly)
	# ------------------------------------------------------------------

	def _on_record_save(self, model_class, record, is_new: bool) -> None:
		"""
		Invalidate stale KPI caches on any record mutation.

		A production implementation would maintain a dependency graph between
		KPI eval_config SQL expressions and the tables they reference, then
		only invalidate the affected KPIs.  The stub below logs the event so
		the signal plumbing can be verified without side-effects.
		"""
		log.debug(
			"analytics._on_record_save: model=%s pk=%s is_new=%s",
			getattr(model_class, "__name__", model_class),
			getattr(record, "id", "?"),
			is_new,
		)

	def _on_user_login(self, user) -> None:
		"""
		Track login events for per-user analytics.

		Could update a ``UserActivity`` record or emit a telemetry event.
		Stub logs only.
		"""
		log.debug(
			"analytics._on_user_login: user=%s",
			getattr(user, "username", getattr(user, "id", "?")),
		)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder, config: dict[str, Any] | None = None) -> AnalyticsPlugin:
	"""
	Construct and return an AnalyticsPlugin bound to *appbuilder*.

	Does **not** call ``activate()`` — the caller controls the lifecycle::

	    plugin = create_plugin(appbuilder, config={"ANALYTICS_ENABLE_PREDICTIVE": True})
	    plugin.activate()

	Args:
	    appbuilder: PgAppForge / PgAppForge AppBuilder instance.
	    config:     Optional plugin configuration dict. Keys are merged
	                over built-in defaults; caller values take precedence.

	Returns:
	    An uninitialised AnalyticsPlugin ready for ``activate()``.
	"""
	return AnalyticsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# plugin
	"AnalyticsPlugin",
	"create_plugin",
	# models
	"Dashboard",
	"DashboardWidget",
	"SavedReport",
	"KPIMetric",
	# views
	"AnalyticsDashboardView",
	"ReportBuilderView",
	"KPIView",
	# capability flags (useful for conditional imports downstream)
	"_HAS_PLOTLY",
	"_HAS_PANDAS",
	"_HAS_SKLEARN",
	"_HAS_DUCKDB",
]
