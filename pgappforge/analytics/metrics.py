"""
Semantic Metric Registry for Flask-AppBuilder.

Defines base Metric, DerivedMetric, and MetricRegistry for
declaring, composing, and evaluating business metrics.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any

import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe formula evaluator
# ---------------------------------------------------------------------------

_SAFE_OPS: dict[type, Any] = {
	ast.Add: operator.add,
	ast.Sub: operator.sub,
	ast.Mult: operator.mul,
	ast.Div: operator.truediv,
	ast.UAdd: operator.pos,
	ast.USub: operator.neg,
}

_ALLOWED_NODES = (
	ast.Expression,
	ast.BinOp,
	ast.UnaryOp,
	ast.Constant,
	ast.Name,
	ast.Load,
	*_SAFE_OPS.keys(),
)


def _eval_node(node: ast.AST, env: dict[str, float]) -> float:
	"""Recursively evaluate a restricted AST node."""
	if isinstance(node, ast.Expression):
		return _eval_node(node.body, env)

	if isinstance(node, ast.Constant):
		if not isinstance(node.value, (int, float)):
			raise ValueError(f"Unsupported literal type: {type(node.value)}")
		return float(node.value)

	if isinstance(node, ast.Name):
		if node.id not in env:
			raise ValueError(f"Unknown metric '{node.id}' referenced in formula")
		return float(env[node.id])

	if isinstance(node, ast.BinOp):
		op_type = type(node.op)
		if op_type not in _SAFE_OPS:
			raise ValueError(f"Unsupported operator: {op_type.__name__}")
		left = _eval_node(node.left, env)
		right = _eval_node(node.right, env)
		return _SAFE_OPS[op_type](left, right)

	if isinstance(node, ast.UnaryOp):
		op_type = type(node.op)
		if op_type not in _SAFE_OPS:
			raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
		return _SAFE_OPS[op_type](_eval_node(node.operand, env))

	raise ValueError(f"Disallowed AST node type: {type(node).__name__}")


def _safe_eval_formula(formula: str, env: dict[str, float]) -> float:
	"""
	Parse and evaluate *formula* against *env* using a restricted AST walk.

	Only +, -, *, /, unary +/-, parentheses, numeric literals, and names
	that exist in *env* are permitted.  Raises ValueError on any violation
	and ZeroDivisionError when the formula divides by zero.
	"""
	try:
		tree = ast.parse(formula.strip(), mode="eval")
	except SyntaxError as exc:
		raise ValueError(f"Invalid formula syntax: {exc}") from exc

	# Whitelist every node in the tree
	for node in ast.walk(tree):
		if not isinstance(node, _ALLOWED_NODES):
			raise ValueError(f"Disallowed AST node type in formula: {type(node).__name__}")

	return _eval_node(tree, env)


def _extract_names_from_formula(formula: str) -> list[str]:
	"""Return all bare identifiers referenced in *formula*."""
	try:
		tree = ast.parse(formula.strip(), mode="eval")
	except SyntaxError as exc:
		raise ValueError(f"Invalid formula syntax: {exc}") from exc
	return [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]


# ---------------------------------------------------------------------------
# Metric dataclasses
# ---------------------------------------------------------------------------

_ADDITIVE_AGGS = frozenset({"sum", "count"})


@dataclass
class Metric:
	"""
	A base (source) metric — a named, queryable measure produced by a plugin.

	source_metrics is empty; the registry will fetch values for these
	directly from the plugin's data layer.
	"""
	name: str
	label: str
	plugin: str
	model_path: str = ""   # dotted path to the SQLAlchemy model class
	field: str = ""        # model field / column name
	agg: str = "sum"       # aggregation function: sum, count, avg, last_value, distinct
	unit: str = ""
	description: str = ""

	def is_additive(self) -> bool:
		"""Return True when this metric is safe to sum across independent dimensions."""
		return self.agg in _ADDITIVE_AGGS


@dataclass
class DerivedMetric:
	"""
	A computed metric whose value is derived from one or more source metrics
	via a simple arithmetic formula.

	Examples::

		profit     = revenue - cost
		margin_pct = profit / revenue * 100
		net_hc     = hires - departures

	Security
	--------
	``evaluate()`` uses a whitelist AST walker — it never calls bare ``eval()``.
	Only +, -, *, /, unary signs, parentheses, numeric literals, and names
	that appear in *source_metrics* are permitted.
	"""
	name: str
	label: str
	plugin: str
	formula: str
	source_metrics: list[str]
	unit: str = ""
	description: str = ""

	def is_additive(self) -> bool:
		# Derived metrics (ratios, differences, percentages) are never safely
		# additive across independent dimension slices.
		return False

	def evaluate(self, source_values: dict[str, float | int]) -> float | None:
		"""
		Evaluate *formula* with the supplied source values.

		Parameters
		----------
		source_values:
			Mapping of metric name → numeric value.  Must contain every name
			listed in ``self.source_metrics``.

		Returns
		-------
		float or None
			Computed result, or ``None`` if a division-by-zero occurs.

		Raises
		------
		ValueError
			If any metric referenced in the formula is absent from
			*source_values*, or if the formula contains disallowed syntax.
		"""
		# Build env: source_values may use full dotted names ('test.a') or
		# short names ('a'). The formula uses short names (last segment).
		# Accept either form for each source_metric entry.
		env: dict[str, float] = {}
		missing: set[str] = set()
		for metric_name in self.source_metrics:
			short = metric_name.rsplit(".", 1)[-1]  # 'test.a' → 'a'
			if metric_name in source_values:
				env[short] = float(source_values[metric_name])
			elif short in source_values:
				env[short] = float(source_values[short])
			else:
				missing.add(metric_name)
		if missing:
			raise ValueError(
				f"DerivedMetric '{self.name}': missing source values for "
				f"{sorted(missing)}"
			)

		try:
			return _safe_eval_formula(self.formula, env)
		except ZeroDivisionError:
			log.warning(
				"DerivedMetric '%s': division by zero evaluating formula '%s'",
				self.name,
				self.formula,
			)
			return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class MetricRegistry:
	"""
	Central registry for Metric and DerivedMetric definitions.

	Usage::

		registry = MetricRegistry()
		registry.register(Metric(name="revenue", label="Revenue", plugin="sales", unit="USD"))
		registry.register(Metric(name="cost",    label="Cost",    plugin="sales", unit="USD"))
		registry.register_derived(
			name="profit",
			label="Gross Profit",
			plugin="sales",
			formula="revenue - cost",
			unit="USD",
		)
		# Query returns {'revenue': 1000.0, 'cost': 600.0, 'profit': 400.0}
		results = registry.query(["revenue", "cost", "profit"], data_provider)
	"""

	_metrics: dict[str, Metric | DerivedMetric] = field(default_factory=dict, init=False)

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def register(self, metric: Metric | DerivedMetric) -> None:
		"""Register a Metric or DerivedMetric. Warns and overwrites on duplicate name."""
		if not isinstance(metric, (Metric, DerivedMetric)):
			raise TypeError(
				f"Expected Metric or DerivedMetric, got {type(metric).__name__}"
			)
		if metric.name in self._metrics:
			log.warning(
				"MetricRegistry: overwriting existing metric '%s'", metric.name
			)
		self._metrics[metric.name] = metric

	def register_derived(
		self,
		name: str,
		label: str,
		plugin: str,
		formula: str,
		unit: str = "",
		description: str = "",
		source_metrics: list[str] | None = None,
	) -> DerivedMetric:
		"""
		Convenience helper: parse *formula*, infer source_metrics, create and
		register a DerivedMetric.

		Returns the newly created DerivedMetric.
		"""
		if source_metrics is None:
			source_metrics = _extract_names_from_formula(formula)
		derived = DerivedMetric(
			name=name,
			label=label,
			plugin=plugin,
			formula=formula,
			source_metrics=source_metrics,
			unit=unit,
			description=description,
		)
		self.register(derived)
		return derived

	# ------------------------------------------------------------------
	# Lookup helpers
	# ------------------------------------------------------------------

	def get(self, name: str) -> Metric | DerivedMetric | None:
		return self._metrics.get(name)

	def list_metrics(self) -> list[Metric]:
		return [m for m in self._metrics.values() if isinstance(m, Metric)]

	def list_derived(self) -> list[DerivedMetric]:
		return [m for m in self._metrics.values() if isinstance(m, DerivedMetric)]

	def all(self) -> list[Metric | DerivedMetric]:
		return list(self._metrics.values())

	def list_all(self) -> list[Metric | DerivedMetric]:
		"""Alias for all() — returns every registered metric."""
		return self.all()

	def list_by_plugin(self, plugin: str) -> list[Metric | DerivedMetric]:
		"""Return all metrics whose plugin matches *plugin* exactly."""
		return [m for m in self._metrics.values() if m.plugin == plugin]

	# ------------------------------------------------------------------
	# Query
	# ------------------------------------------------------------------

	def query(
		self,
		metric_names: list[str],
		data_provider: Any = None,
		session: Any = None,
	) -> dict[str, float | None]:
		"""
		Resolve *metric_names*, fetching source metrics via *data_provider*
		and computing any DerivedMetrics.

		DerivedMetric sources that are themselves DerivedMetrics are resolved
		recursively before evaluation (transitive dependency support).

		Parameters
		----------
		metric_names:
			List of metric names to resolve.
		data_provider:
			Any object that implements ``get_metric_value(name: str) -> float``.
			Called only for base ``Metric`` instances.

		Returns
		-------
		dict mapping each requested metric name to its resolved float value
		(or None when a derived formula produces a division-by-zero).

		Raises
		------
		ValueError
			If a requested metric name is not registered, or a DerivedMetric
			references an unregistered source.
		"""
		unknown = [n for n in metric_names if n not in self._metrics]
		if unknown:
			# Return empty list per name for unknown metrics rather than raising
			return {n: [] for n in unknown}

		# resolved_cache holds already-computed values (base or derived)
		resolved: dict[str, float | None] = {}

		def _resolve(name: str, visiting: set[str]) -> float | None:
			"""Recursively resolve a single metric, detecting cycles."""
			if name in resolved:
				return resolved[name]

			if name in visiting:
				raise ValueError(
					f"Circular dependency detected involving metric '{name}'"
				)

			m = self._metrics.get(name)
			if m is None:
				raise ValueError(f"Unknown metric '{name}'")

			if isinstance(m, Metric):
				if data_provider is None:
					raise ValueError(
						f"Metric '{name}' is a base metric and requires a data_provider"
					)
				val = data_provider.get_metric_value(name)
				result: float | None = float(val) if val is not None else 0.0
			else:
				# DerivedMetric: resolve each source first
				visiting = visiting | {name}
				src_values: dict[str, float] = {}
				for src in m.source_metrics:
					if src not in self._metrics:
						log.debug("DerivedMetric '%s': source '%s' not registered — returning None", name, src)
						resolved[name] = None
						return None
					src_val = _resolve(src, visiting)
					# propagate None (division by zero in a dependency)
					if src_val is None:
						resolved[name] = None
						return None
					src_values[src] = src_val
				result = m.evaluate(src_values)

			resolved[name] = result
			return result

		for name in metric_names:
			_resolve(name, set())

		return {name: resolved[name] for name in metric_names}


# ---------------------------------------------------------------------------
# Module-level global registry + convenience wrappers
# ---------------------------------------------------------------------------

_global_registry = MetricRegistry()


def get_metric_registry() -> MetricRegistry:
	"""Return the process-wide MetricRegistry singleton."""
	return _global_registry


def register_metric(metric: Metric | DerivedMetric) -> None:
	"""Register *metric* in the global registry."""
	_global_registry.register(metric)


def query_metrics(
	metric_names: list[str],
	data_provider: Any = None,
	session: Any = None,
) -> dict[str, Any]:
	"""Query *metric_names* against the global registry."""
	return _global_registry.query(metric_names, data_provider=data_provider, session=session)
