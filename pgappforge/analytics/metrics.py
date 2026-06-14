"""Semantic metric registry for PgAppForge.

Plugins declare named, typed metrics with explicit aggregation semantics.
Cross-plugin reports compose metrics by name without writing custom SQL.

Usage
-----
    from pgappforge.analytics.metrics import register_metric, Metric

    register_metric(Metric(
        name='finance.ar.revenue',
        label='AR Revenue',
        plugin='finance.ar',
        model_path='pgappforge.plugins.erp.finance.ar.models.ARInvoice',
        field='total_amount_cents',
        agg='sum',
        unit='cents',
        filters={'status': 'PAID'},
    ))

    results = query_metrics(
        metrics=['finance.ar.revenue', 'crm.deals_won'],
        group_by=['tenant_id'],
        filters={'tenant_id': 'tid'},
        session=session,
    )

Aggregation types
-----------------
- sum:        additive — safe to SUM across any grouping
- count:      additive — COUNT(*)
- avg:        non-additive — must re-average from raw rows; never sum of averages
- last_value: semi-additive — MAX(field); meaningful only within a partition
- distinct:   COUNT(DISTINCT field) — non-additive across groups
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlalchemy as sa

log = logging.getLogger(__name__)

AggType = Literal['sum', 'count', 'avg', 'last_value', 'distinct']


@dataclass
class Metric:
	"""Declaration of a named business metric.

	Attributes
	----------
	name:         Globally unique dotted name, e.g. 'finance.ar.revenue'
	label:        Human-readable label for UI
	plugin:       Plugin key that owns this metric, e.g. 'finance.ar'
	model_path:   Dotted import path to the SQLAlchemy model class
	field:        Column name on the model to aggregate
	agg:          Aggregation type — determines how values compose across groups
	unit:         Optional unit for display ('cents', 'hours', 'count')
	filters:      Static WHERE filters applied to every query (dict of col=val)
	tenant_field: Column name for tenant scoping (default 'tenant_id')
	description:  Free-text description
	"""
	name:         str
	label:        str
	plugin:       str
	model_path:   str
	field:        str
	agg:          AggType = 'sum'
	unit:         str = ''
	filters:      dict[str, Any] = field(default_factory=dict)
	tenant_field: str = 'tenant_id'
	description:  str = ''

	def is_additive(self) -> bool:
		"""Return True if values can be safely summed across arbitrary groupings."""
		return self.agg in ('sum', 'count')

	def _load_model(self) -> Any:
		module_path, class_name = self.model_path.rsplit('.', 1)
		mod = importlib.import_module(module_path)
		return getattr(mod, class_name)

	def build_query(
		self,
		group_by: list[str] | None,
		filters: dict[str, Any] | None,
		tenant_id: str | None,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Execute a SQLAlchemy query for this metric.

		Returns [{group_col: val, ..., metric_name: agg_val}, ...]
		"""
		try:
			model = self._load_model()
		except Exception as exc:
			log.warning("Metric %s: cannot load model %s — %s", self.name, self.model_path, exc)
			return []

		col = getattr(model, self.field, None)
		if col is None:
			log.warning("Metric %s: field %r not found on %s", self.name, self.field, model.__name__)
			return []

		if self.agg == 'sum':
			agg_expr = sa.func.sum(col).label(self.name)
		elif self.agg == 'count':
			agg_expr = sa.func.count(col).label(self.name)
		elif self.agg == 'avg':
			agg_expr = sa.func.avg(col).label(self.name)
		elif self.agg == 'last_value':
			agg_expr = sa.func.max(col).label(self.name)
		elif self.agg == 'distinct':
			agg_expr = sa.func.count(sa.distinct(col)).label(self.name)
		else:
			log.warning("Metric %s: unknown agg type %r", self.name, self.agg)
			return []

		select_cols = [agg_expr]
		group_by_cols = []
		for gb in (group_by or []):
			gc = getattr(model, gb, None)
			if gc is not None:
				select_cols.append(gc)
				group_by_cols.append(gc)

		q = sa.select(*select_cols)

		all_filters = {**self.filters, **(filters or {})}
		if tenant_id and hasattr(model, self.tenant_field):
			all_filters[self.tenant_field] = tenant_id

		for col_name, val in all_filters.items():
			model_col = getattr(model, col_name, None)
			if model_col is not None:
				q = q.where(model_col == val)

		if group_by_cols:
			q = q.group_by(*group_by_cols)

		try:
			rows = session.execute(q).fetchall()
			keys = [self.name] + [gb for gb in (group_by or []) if getattr(model, gb, None) is not None]
			return [dict(zip(keys, row)) for row in rows]
		except Exception as exc:
			log.warning("Metric %s: query failed — %s", self.name, exc)
			return []


class MetricRegistry:
	"""Central registry of named semantic metrics."""

	def __init__(self) -> None:
		self._metrics: dict[str, Metric] = {}

	def register(self, metric: Metric) -> None:
		if metric.name in self._metrics:
			log.warning("MetricRegistry: overwriting existing metric %r", metric.name)
		self._metrics[metric.name] = metric
		log.debug(
			"MetricRegistry: registered %s (%s.%s, agg=%s)",
			metric.name, metric.model_path, metric.field, metric.agg,
		)

	def get(self, name: str) -> Metric | None:
		return self._metrics.get(name)

	def list_all(self) -> list[Metric]:
		return list(self._metrics.values())

	def list_by_plugin(self, plugin_key: str) -> list[Metric]:
		return [m for m in self._metrics.values() if m.plugin == plugin_key]

	def query(
		self,
		metric_names: list[str],
		group_by: list[str] | None = None,
		filters: dict[str, Any] | None = None,
		tenant_id: str | None = None,
		session: Any = None,
	) -> dict[str, list[dict[str, Any]]]:
		"""Query one or more metrics.

		Returns {metric_name: [row_dict, ...]} — callers join on common group_by keys.
		Non-additive metrics are flagged in logs to prevent accidental cross-group sums.
		"""
		results: dict[str, list[dict[str, Any]]] = {}
		for name in metric_names:
			m = self._metrics.get(name)
			if m is None:
				log.warning("MetricRegistry.query: unknown metric %r — skipped", name)
				results[name] = []
				continue
			if not m.is_additive() and group_by:
				log.info(
					"MetricRegistry: metric %r (agg=%s) is non-additive — "
					"do not sum values across groups",
					name, m.agg,
				)
			results[name] = m.build_query(group_by, filters, tenant_id, session)
		return results


# Module singleton
_registry: MetricRegistry | None = None


def get_metric_registry() -> MetricRegistry:
	global _registry
	if _registry is None:
		_registry = MetricRegistry()
	return _registry


def register_metric(metric: Metric) -> None:
	"""Register a named metric in the global registry."""
	get_metric_registry().register(metric)


def query_metrics(
	metrics: list[str],
	group_by: list[str] | None = None,
	filters: dict[str, Any] | None = None,
	tenant_id: str | None = None,
	session: Any = None,
) -> dict[str, list[dict[str, Any]]]:
	"""Query metrics from the global registry."""
	return get_metric_registry().query(
		metrics, group_by=group_by, filters=filters, tenant_id=tenant_id, session=session,
	)


__all__ = ['Metric', 'MetricRegistry', 'register_metric', 'query_metrics', 'get_metric_registry', 'AggType']
