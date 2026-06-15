"""
Flask-AppBuilder Analytics Package

Advanced analytics and reporting system for wizard forms, plus the
semantic metric registry for defining and composing business metrics.
"""

from .wizard_analytics import (
	WizardAnalyticsEngine,
	WizardAnalyticsEvent,
	WizardCompletionStats,
	WizardFieldAnalytics,
	WizardUserJourney,
	wizard_analytics,
	track_wizard_event,
)
from .metrics import (
	Metric,
	DerivedMetric,
	MetricRegistry,
	get_metric_registry,
	register_metric,
	query_metrics,
)

__all__ = [
	# Wizard analytics
	'WizardAnalyticsEngine',
	'WizardAnalyticsEvent',
	'WizardCompletionStats',
	'WizardFieldAnalytics',
	'WizardUserJourney',
	'wizard_analytics',
	'track_wizard_event',
	# Semantic metric registry
	'Metric',
	'DerivedMetric',
	'MetricRegistry',
	'get_metric_registry',
	'register_metric',
	'query_metrics',
]