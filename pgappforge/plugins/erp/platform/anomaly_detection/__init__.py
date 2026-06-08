from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	AnomalyBatchRunCompletedEvent,
	AnomalyResolvedEvent,
	APDuplicateDetectedEvent,
	GLAnomalyDetectedEvent,
	LargeTransactionFlaggedEvent,
	WeekendJournalFlaggedEvent,
)
from .models import Anomaly, AnomalyDetectionRun
from .services import AnomalyDetectionService

if TYPE_CHECKING:
	from sqlalchemy.orm import Session

__all__ = [
	"AnomalyDetectionPlugin",
	"AnomalyDetectionService",
	"AnomalyDetectionRun",
	"Anomaly",
	"GLAnomalyDetectedEvent",
	"APDuplicateDetectedEvent",
	"WeekendJournalFlaggedEvent",
	"LargeTransactionFlaggedEvent",
	"AnomalyResolvedEvent",
	"AnomalyBatchRunCompletedEvent",
]

log = logging.getLogger(__name__)

ANOMALY_MENU_CATEGORY = "Anomaly Detection"


class AnomalyDetectionPlugin(BasePlugin):
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="anomaly_detection",
		version="1.0.0",
		description=(
			"Statistical and rule-based anomaly detection for GL and AP modules. "
			"Detects outliers, duplicates, weekend postings, round numbers, and "
			"large transactions to support internal controls and fraud prevention."
		),
		author="PgAppForge Contributors",
		tags=[
			"platform",
			"anomaly-detection",
			"fraud",
			"audit",
			"internal-controls",
			"ai",
		],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[type]:
		return [
			GLAnomalyDetectedEvent,
			APDuplicateDetectedEvent,
			WeekendJournalFlaggedEvent,
			LargeTransactionFlaggedEvent,
			AnomalyResolvedEvent,
			AnomalyBatchRunCompletedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"finance.gl.journal.posted",
			"finance.ap.invoice.created",
		]

	def initialize(self, app=None) -> None:
		global ANOMALY_MENU_CATEGORY
		ANOMALY_MENU_CATEGORY = "Anomaly Detection"
		log.info("AnomalyDetectionPlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.anomaly_detection.views import (
			AnomalyDashboardView,
			AnomalyDetectionRunView,
			AnomalyView,
		)
		cat = self.config.get("ANOMALY_MENU_CATEGORY", "Anomaly Detection")
		self.add_view(AnomalyDashboardView, "Anomaly Dashboard", icon="fa-tachometer", category=cat)
		self.add_view(AnomalyDetectionRunView, "Detection Runs", icon="fa-refresh", category=cat)
		self.add_view(AnomalyView, "Anomalies", icon="fa-exclamation-circle", category=cat)
		log.info("AnomalyDetectionPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return [AnomalyDetectionRun, Anomaly]

	def setup_rules(self, session: Session) -> None:
		try:
			from pgappforge.plugins.rules.engine import RuleEngine
			from pgappforge.plugins.rules.models import Rule, RuleSet

			existing = session.execute(
				__import__("sqlalchemy", fromlist=["select"]).select(RuleSet).where(
					RuleSet.name == "anomaly.critical_must_be_reviewed"
				)
			).scalar_one_or_none()

			if existing:
				return

			ruleset = RuleSet(
				name="anomaly.critical_must_be_reviewed",
				description=(
					"Ensures all CRITICAL anomalies are reviewed and resolved "
					"within the required SLA."
				),
		author="PgAppForge Contributors",
				is_active=True,
			)
			session.add(ruleset)

			rule = Rule(
				ruleset=ruleset,
				name="critical_anomaly_must_be_acknowledged",
				description="Any CRITICAL anomaly must be acknowledged within 24 hours",
				condition='anomaly.severity == "CRITICAL" and anomaly.status == "OPEN"',
				action="notify_compliance_team",
				priority=1,
				is_active=True,
			)
			session.add(rule)
			session.flush()
			log.info("AnomalyDetectionPlugin: rules seeded")
		except Exception:
			log.debug("Rules setup skipped (rules engine unavailable)", exc_info=True)
