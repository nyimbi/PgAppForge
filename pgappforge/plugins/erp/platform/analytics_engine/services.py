"""
pgappforge/plugins/erp/platform/analytics_engine/services.py

AnalyticsEngineService — cube definition, refresh, querying, financial dashboards.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("Analytics event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("analytics.define_cube")
	def _bpm_define_cube(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "analytics.define_cube", "params": ctx}

	@_BPMReg.register("analytics.refresh_cube")
	def _bpm_refresh_cube(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "analytics.refresh_cube", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — Analytics BPM actions not registered")


# ---------------------------------------------------------------------------
# AnalyticsEngineService
# ---------------------------------------------------------------------------

class AnalyticsEngineService:
	"""Service layer for the Analytics Engine."""

	# ------------------------------------------------------------------
	# Cube management
	# ------------------------------------------------------------------

	def define_cube(
		self,
		name: str,
		base_query: str,
		dimensions: list[str],
		measures: list[str],
		tenant_id: str,
		session: Any,
		*,
		refresh_schedule: str = "DAILY",
	) -> Any:
		"""Define a new analytics cube backed by a PostgreSQL materialized view.

		Creates the materialized view if DDL succeeds; falls back gracefully
		if the database user lacks CREATE MATERIALIZED VIEW privileges.
		Emits CubeDefinedEvent.
		"""
		from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
		from pgappforge.plugins.erp.platform.analytics_engine.events import CubeDefinedEvent

		safe_name = name.lower().replace(" ", "_")[:40]
		view_name = f"anl_cube_{safe_name}"

		# Attempt to create materialized view
		try:
			session.execute(
				sa.text(
					f"CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name} AS {base_query}"
				)
			)
			log.info("Analytics: created materialized view %r", view_name)
		except Exception as exc:
			log.warning(
				"Analytics: could not create materialized view %r — cube defined without view: %s",
				view_name, exc,
			)

		cube = AnalyticsCube(
			id=_uuid4(),
			tenant_id=tenant_id,
			name=name,
			base_query=base_query,
			refresh_schedule=refresh_schedule,
			last_refreshed=None,
			dimensions=dimensions,
			measures=measures,
			materialized_view_name=view_name,
			is_active=True,
		)
		session.add(cube)
		session.flush()

		_emit(
			CubeDefinedEvent(
				aggregate_id=cube.id,
				aggregate_type="AnalyticsCube",
				tenant_id=tenant_id,
				cube_id=cube.id,
				cube_name=name,
				view_name=view_name,
			),
			session,
		)
		log.info("Analytics: defined cube %r [view=%s]", name, view_name)
		return cube

	def refresh_cube(
		self,
		cube_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Refresh the materialized view backing an analytics cube.

		Uses REFRESH MATERIALIZED VIEW CONCURRENTLY to avoid exclusive locks.
		Updates cube.last_refreshed. Emits CubeRefreshedEvent.
		"""
		from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
		from pgappforge.plugins.erp.platform.analytics_engine.events import CubeRefreshedEvent

		cube = session.execute(
			sa.select(AnalyticsCube).where(AnalyticsCube.id == cube_id)
		).scalar_one_or_none()
		if cube is None:
			raise ValueError(f"AnalyticsCube {cube_id} not found")

		view_name = cube.materialized_view_name
		row_count = 0
		try:
			session.execute(
				sa.text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
			)
			row_count_result = session.execute(
				sa.text(f"SELECT COUNT(*) FROM {view_name}")
			).scalar()
			row_count = row_count_result or 0
		except Exception as exc:
			log.warning("Analytics: could not refresh view %r: %s", view_name, exc)

		cube.last_refreshed = _now()
		session.flush()

		_emit(
			CubeRefreshedEvent(
				aggregate_id=cube_id,
				aggregate_type="AnalyticsCube",
				tenant_id=cube.tenant_id,
				cube_id=cube_id,
				cube_name=cube.name,
				row_count=row_count,
			),
			session,
		)
		return {"cube_id": cube_id, "rows": row_count, "refreshed_at": str(cube.last_refreshed)}

	# ------------------------------------------------------------------
	# Query
	# ------------------------------------------------------------------

	def query_cube(
		self,
		cube_id: str,
		filters: list[dict[str, Any]],
		group_by: list[str],
		session: Any,
		*,
		limit: int = 1000,
	) -> list[dict[str, Any]]:
		"""Query an analytics cube with optional filters and group-by.

		Builds a parameterised SQL query against the cube's materialized view.
		Emits ReportRunEvent.
		"""
		from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
		from pgappforge.plugins.erp.platform.analytics_engine.events import ReportRunEvent

		cube = session.execute(
			sa.select(AnalyticsCube).where(AnalyticsCube.id == cube_id)
		).scalar_one_or_none()
		if cube is None:
			raise ValueError(f"AnalyticsCube {cube_id} not found")

		view_name = cube.materialized_view_name

		# Security: validate view_name is a safe materialized view identifier
		import re as _re
		if not _re.match(r'^anl_cube_[a-z0-9_]{1,60}$', view_name or ""):
			raise ValueError(f"Invalid materialized view name {view_name!r} — possible injection")

		# Build allowed field set from cube definition (whitelist approach)
		allowed_fields: set[str] = set()
		for dim in (cube.dimensions or {}).keys():
			allowed_fields.add(str(dim))
		for meas in (cube.measures or {}).keys():
			allowed_fields.add(str(meas))
		# Allow * only when no group_by and no filters (full-table read)

		def _safe_field(name: str) -> str:
			"""Raise if field name is not in the cube's allowed dimension/measure set."""
			if allowed_fields and name not in allowed_fields:
				raise ValueError(
					f"Field {name!r} not in cube dimensions/measures — possible injection. "
					f"Allowed: {sorted(allowed_fields)}"
				)
			# Additional safety: identifier-safe characters only
			if not _re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$', name):
				raise ValueError(f"Unsafe field name {name!r}")
			return name

		t0 = time.monotonic()

		# Cap limit to prevent unbounded result sets
		limit = min(int(limit), 10_000)

		# Build WHERE clause from filters [{field, op, value}]
		where_parts: list[str] = []
		bind_params: dict[str, Any] = {}
		_SAFE_OPS = {"eq": "=", "gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "in": "IN"}
		for i, f in enumerate(filters or []):
			raw_field = f.get("field", "")
			op = f.get("op", "eq")
			value = f.get("value")
			if op not in _SAFE_OPS:
				continue
			field = _safe_field(raw_field)
			param_key = f"p{i}"
			if op == "in":
				where_parts.append(f"{field} = ANY(:{param_key})")
			else:
				where_parts.append(f"{field} {_SAFE_OPS[op]} :{param_key}")
			bind_params[param_key] = value

		select_clause = "*"
		group_clause = ""
		if group_by:
			safe_cols = [_safe_field(c) for c in group_by]
			cols = ", ".join(safe_cols)
			select_clause = cols
			group_clause = f"GROUP BY {cols}"

		where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
		sql = f"SELECT {select_clause} FROM {view_name} {where_clause} {group_clause} LIMIT :lim"
		bind_params["lim"] = limit

		rows = []
		try:
			result = session.execute(sa.text(sql), bind_params)
			keys = list(result.keys())
			rows = [dict(zip(keys, row)) for row in result.fetchall()]
		except Exception as exc:
			log.warning("Analytics: query_cube failed for %r: %s", view_name, exc)

		duration_ms = int((time.monotonic() - t0) * 1000)
		_emit(
			ReportRunEvent(
				aggregate_id=cube_id,
				aggregate_type="AnalyticsCube",
				tenant_id=cube.tenant_id,
				report_id="",
				cube_id=cube_id,
				rows_returned=len(rows),
				duration_ms=duration_ms,
			),
			session,
		)
		return rows

	# ------------------------------------------------------------------
	# Financial dashboard
	# ------------------------------------------------------------------

	def get_financial_dashboard(
		self,
		tenant_id: str,
		period: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a high-level financial dashboard for a tenant.

		Attempts to pull data from RealtimeGLService when available.
		Falls back to zero-value stubs to avoid hard dependency.
		period format: "YYYY-MM" e.g. "2026-06"
		"""
		dashboard: dict[str, Any] = {
			"tenant_id": tenant_id,
			"period": period,
			"revenue_cents": 0,
			"expenses_cents": 0,
			"gross_profit_cents": 0,
			"ar_aging": {},
			"ap_aging": {},
			"cash_cents": 0,
		}

		try:
			from pgappforge.plugins.erp.finance.gl.services import RealtimeGLService
			gl = RealtimeGLService()
			trial_balance = gl.get_trial_balance(tenant_id, period, session)
			dashboard.update({
				"revenue_cents": trial_balance.get("revenue_cents", 0),
				"expenses_cents": trial_balance.get("expenses_cents", 0),
				"gross_profit_cents": (
					trial_balance.get("revenue_cents", 0)
					- trial_balance.get("expenses_cents", 0)
				),
			})
		except (ImportError, Exception) as exc:
			log.debug("Analytics: GL service not available for financial dashboard: %s", exc)

		try:
			from pgappforge.plugins.erp.finance.ar.services import ARService
			ar = ARService()
			dashboard["ar_aging"] = ar.get_aging(tenant_id, session)
		except (ImportError, Exception):
			pass

		try:
			from pgappforge.plugins.erp.finance.ap.services import APService
			ap = APService()
			dashboard["ap_aging"] = ap.get_aging(tenant_id, session)
		except (ImportError, Exception):
			pass

		return dashboard
