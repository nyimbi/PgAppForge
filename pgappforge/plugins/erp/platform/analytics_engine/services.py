"""Analytics engine service."""
from __future__ import annotations
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube, AnalyticsReport, ReportCache


def _uuid() -> str:
	return str(uuid.uuid4())


class AnalyticsEngineService:
	def define_cube(
		self,
		tenant_id: str,
		name: str,
		base_query: str,
		dimensions: list[dict[str, Any]],
		measures: list[dict[str, Any]],
		session: Any,
	) -> AnalyticsCube:
		cube = AnalyticsCube(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			base_query=base_query,
			dimensions=dimensions,
			measures=measures,
		)
		session.add(cube)
		return cube

	def query_cube(
		self,
		cube_id: str,
		filters: dict[str, Any] | None,
		group_by: list[str] | None,
		session: Any,
	) -> list[dict[str, Any]]:
		cube = session.get(AnalyticsCube, cube_id)
		sql = cube.base_query
		params: dict[str, Any] = {}
		wheres = []
		if filters:
			allowed = {d["field"] for d in cube.dimensions} | {m["field"] for m in cube.measures}
			for field in filters:
				if field not in allowed:
					raise ValueError(f"Unknown filter field {field!r}; allowed: {sorted(allowed)}")
			for i, (field, value) in enumerate(filters.items()):
				param_key = f"f{i}"
				wheres.append(f"{field} = :{param_key}")
				params[param_key] = value
		if wheres:
			sql = f"SELECT * FROM ({sql}) _cube WHERE " + " AND ".join(wheres)
		if group_by:
			allowed_gb = {d["field"] for d in cube.dimensions}
			for field in group_by:
				if field not in allowed_gb:
					raise ValueError(f"Unknown group_by field {field!r}")
			cols = ", ".join(group_by)
			aggs = ", ".join(
				f"{m['agg']}({m['field']}) AS {m['name']}"
				for m in cube.measures
			)
			sql = f"SELECT {cols}, {aggs} FROM ({sql}) _cube GROUP BY {cols}"
		result = session.execute(sa.text(sql), params)
		return [dict(zip(result.keys(), row)) for row in result.fetchmany(1000)]

	def get_financial_dashboard(self, tenant_id: str, session: Any) -> dict[str, Any]:
		widgets: dict[str, Any] = {}
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			ar_total = session.execute(
				sa.select(sa.func.sum(ARInvoice.total_amount_cents)).where(ARInvoice.tenant_id == tenant_id)
			).scalar() or 0
			widgets["ar_outstanding_cents"] = ar_total
		except Exception:
			pass
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
			ap_total = session.execute(
				sa.select(sa.func.sum(APInvoice.total_amount_cents)).where(APInvoice.tenant_id == tenant_id)
			).scalar() or 0
			widgets["ap_outstanding_cents"] = ap_total
		except Exception:
			pass
		return widgets


__all__ = ["AnalyticsEngineService"]
