"""
PgForge Analytics Package

Advanced analytics and reporting system for wizard forms.
"""

from .wizard_analytics import (
    WizardAnalyticsEngine,
    WizardAnalyticsEvent,
    WizardCompletionStats,
    WizardFieldAnalytics,
    WizardUserJourney,
    wizard_analytics,
    track_wizard_event
)

__all__ = [
    'WizardAnalyticsEngine',
    'WizardAnalyticsEvent', 
    'WizardCompletionStats',
    'WizardFieldAnalytics',
    'WizardUserJourney',
    'wizard_analytics',
    'track_wizard_event'
]