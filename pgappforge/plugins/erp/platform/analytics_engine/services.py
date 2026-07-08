"""Analytics engine service."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.analytics_engine.models import AnalyticsCube
from pgappforge.plugins.erp.platform.query_guard import (
	validate_aggregate,
	validate_identifier_collection,
	validate_read_only_sql,
	validate_sql_identifier,
)


_DEFAULT_DIMENSION_TYPE = "string"
_DEFAULT_MEASURE_AGGREGATE = "SUM"
_MAX_FILTERS = 50
_MAX_GROUP_BY = 20
_MAX_ROWS = 5000


def _uuid() -> str:
	return str(uuid.uuid4())


class AnalyticsEngineService:
	def define_cube(
		self,
		tenant_id: str,
		name: str,
		base_query: str,
		dimensions: Any,
		measures: Any,
		session: Any,
		*,
		refresh_schedule: str | None = None,
	) -> AnalyticsCube:
		base_query = validate_read_only_sql(base_query)
		dimensions, measures = self._validate_cube_schema(dimensions, measures)
		cube = AnalyticsCube(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			base_query=base_query,
			refresh_schedule=refresh_schedule,
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
		tenant_id: str | None = None,
		limit_rows: int = 1000,
	) -> list[dict[str, Any]]:
		cube = session.get(AnalyticsCube, cube_id)
		if cube is None:
			raise ValueError(f"Analytics cube {cube_id!r} not found")
		if tenant_id is not None and cube.tenant_id != tenant_id:
			raise ValueError(f"Analytics cube {cube_id!r} not found for tenant {tenant_id!r}")
		dimensions, measures = self._validate_cube_schema(cube.dimensions or [], cube.measures or [])
		filters = self._normalize_filters(filters)
		group_by = self._normalize_group_by(group_by)
		row_limit = self._normalize_limit(limit_rows)
		sql = validate_read_only_sql(cube.base_query)
		params: dict[str, Any] = {}
		wheres = []
		if filters:
			allowed = {d["field"] for d in dimensions} | {m["field"] for m in measures}
			for field in filters:
				if field not in allowed:
					raise ValueError(f"Unknown filter field {field!r}; allowed: {sorted(allowed)}")
			for i, (field, value) in enumerate(filters.items()):
				field = validate_sql_identifier(field, label="filter field")
				param_key = f"f{i}"
				wheres.append(f"{field} = :{param_key}")
				params[param_key] = value
		if wheres:
			sql = f"SELECT * FROM ({sql}) _cube WHERE " + " AND ".join(wheres)
		if group_by:
			if not measures:
				raise ValueError("At least one measure is required when grouping analytics cubes")
			allowed_gb = {d["field"] for d in dimensions}
			for field in group_by:
				if field not in allowed_gb:
					raise ValueError(f"Unknown group_by field {field!r}")
			cols = ", ".join(validate_identifier_collection(group_by, label="group_by field"))
			aggs = ", ".join(
				f"{validate_aggregate(m['agg'])}({validate_sql_identifier(m['field'], label='measure field')}) "
				f"AS {validate_sql_identifier(m['name'], label='measure alias')}"
				for m in measures
			)
			sql = f"SELECT {cols}, {aggs} FROM ({sql}) _cube GROUP BY {cols}"
		result = session.execute(sa.text(sql), params)
		return [dict(zip(result.keys(), row)) for row in result.fetchmany(row_limit)]

	def _validate_cube_schema(
		self,
		dimensions: Any,
		measures: Any,
	) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
		dimensions = self._normalize_dimensions(dimensions)
		measures = self._normalize_measures(measures)
		for dimension in dimensions:
			validate_sql_identifier(dimension.get("field", ""), label="dimension field")
			if dimension.get("name"):
				validate_sql_identifier(dimension["name"], label="dimension alias")
		for measure in measures:
			validate_sql_identifier(measure.get("field", ""), label="measure field")
			validate_sql_identifier(measure.get("name", ""), label="measure alias")
			measure["agg"] = validate_aggregate(measure.get("agg", ""))
		return dimensions, measures

	@staticmethod
	def _normalize_dimensions(dimensions: Any) -> list[dict[str, Any]]:
		if dimensions is None:
			return []
		if isinstance(dimensions, Mapping):
			items = dimensions.items()
			return [
				{
					"name": str(field).strip(),
					"field": str(field).strip(),
					"type": str(dimension_type or _DEFAULT_DIMENSION_TYPE).strip().lower(),
				}
				for field, dimension_type in items
			]
		if isinstance(dimensions, (str, bytes)) or not isinstance(dimensions, Sequence):
			raise ValueError("dimensions must be a list or mapping")
		normalized: list[dict[str, Any]] = []
		for dimension in dimensions:
			if isinstance(dimension, str):
				field = dimension.strip()
				normalized.append({"name": field, "field": field, "type": _DEFAULT_DIMENSION_TYPE})
				continue
			if not isinstance(dimension, Mapping):
				raise ValueError("each dimension must be a field name or mapping")
			field = str(dimension.get("field") or dimension.get("name") or "").strip()
			name = str(dimension.get("name") or field).strip()
			dimension_type = str(dimension.get("type") or _DEFAULT_DIMENSION_TYPE).strip().lower()
			normalized.append({"name": name, "field": field, "type": dimension_type})
		return normalized

	@staticmethod
	def _normalize_measures(measures: Any) -> list[dict[str, Any]]:
		if measures is None:
			return []
		if isinstance(measures, Mapping):
			return [
				{
					"name": str(field).strip(),
					"field": str(field).strip(),
					"agg": str(aggregate or _DEFAULT_MEASURE_AGGREGATE).strip().upper(),
				}
				for field, aggregate in measures.items()
			]
		if isinstance(measures, (str, bytes)) or not isinstance(measures, Sequence):
			raise ValueError("measures must be a list or mapping")
		normalized: list[dict[str, Any]] = []
		for measure in measures:
			if isinstance(measure, str):
				field = measure.strip()
				normalized.append(
					{"name": field, "field": field, "agg": _DEFAULT_MEASURE_AGGREGATE}
				)
				continue
			if not isinstance(measure, Mapping):
				raise ValueError("each measure must be a field name or mapping")
			field = str(measure.get("field") or measure.get("name") or "").strip()
			name = str(measure.get("name") or field).strip()
			aggregate = str(measure.get("agg") or _DEFAULT_MEASURE_AGGREGATE).strip().upper()
			normalized.append({"name": name, "field": field, "agg": aggregate})
		return normalized

	@staticmethod
	def _normalize_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
		if filters is None:
			return {}
		if not isinstance(filters, dict):
			raise ValueError("filters must be a mapping of field names to values")
		if len(filters) > _MAX_FILTERS:
			raise ValueError(f"filters cannot contain more than {_MAX_FILTERS} fields")
		return filters

	@staticmethod
	def _normalize_group_by(group_by: list[str] | None) -> list[str]:
		if group_by is None:
			return []
		if isinstance(group_by, (str, bytes)) or not isinstance(group_by, Sequence):
			raise ValueError("group_by must be a list of field names")
		if len(group_by) > _MAX_GROUP_BY:
			raise ValueError(f"group_by cannot contain more than {_MAX_GROUP_BY} fields")
		normalized = validate_identifier_collection(group_by, label="group_by field")
		if len(set(normalized)) != len(normalized):
			raise ValueError("group_by cannot contain duplicate fields")
		return normalized

	@staticmethod
	def _normalize_limit(limit_rows: int) -> int:
		try:
			value = int(limit_rows)
		except (TypeError, ValueError) as exc:
			raise ValueError("limit_rows must be a positive integer") from exc
		if value < 1:
			raise ValueError("limit_rows must be a positive integer")
		return min(value, _MAX_ROWS)

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
