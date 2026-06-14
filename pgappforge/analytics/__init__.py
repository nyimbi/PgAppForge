"""PgAppForge analytics layer — named metrics, semantic composition."""
from pgappforge.analytics.metrics import Metric, MetricRegistry, register_metric, query_metrics, get_metric_registry

__all__ = ['Metric', 'MetricRegistry', 'register_metric', 'query_metrics', 'get_metric_registry']
