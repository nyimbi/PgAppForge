from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from .events import (
	EmissionFactorUpdatedEvent,
	EmissionRecordedEvent,
	EmissionReportGeneratedEvent,
	OffsetAppliedEvent,
	ReductionTargetSetEvent,
)
from .models import CarbonOffset, EmissionFactor, EmissionRecord, GHGReport
from .services import CarbonTrackingService, CarbonValidationError

if TYPE_CHECKING:
	from sqlalchemy.orm import Session

__all__ = [
	"CarbonPlugin",
	"CarbonTrackingService",
	"CarbonValidationError",
	"EmissionFactor",
	"EmissionRecord",
	"GHGReport",
	"CarbonOffset",
	"EmissionRecordedEvent",
	"EmissionReportGeneratedEvent",
	"EmissionFactorUpdatedEvent",
	"ReductionTargetSetEvent",
	"OffsetAppliedEvent",
]

log = logging.getLogger(__name__)

CARBON_MENU_CATEGORY = "Sustainability"
CARBON_DEFAULT_COUNTRY = "KEN"


class CarbonPlugin(BasePlugin):
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	metadata = PluginMetadata(
		name="carbon",
		version="1.0.0",
		description=(
			"GHG emission tracking, reporting, and carbon offset management. "
			"Supports Scope 1/2/3 emissions per GHG Protocol, Kenya-specific "
			"default emission factors, and CSRD-aligned GHG reporting."
		),
		author="PgAppForge Contributors",
		tags=[
			"platform",
			"carbon",
			"ghg",
			"sustainability",
			"esg",
			"csrd",
			"scope1",
			"scope2",
			"scope3",
		],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[type]:
		return [
			EmissionRecordedEvent,
			EmissionReportGeneratedEvent,
			EmissionFactorUpdatedEvent,
			ReductionTargetSetEvent,
			OffsetAppliedEvent,
		]

	def subscribe_to(self) -> list[str]:
		return [
			"ops.fleet.trip.completed",
			"ops.transport.shipment.delivered",
		]

	def initialize(self, app=None) -> None:
		global CARBON_MENU_CATEGORY, CARBON_DEFAULT_COUNTRY
		CARBON_MENU_CATEGORY = "Sustainability"
		CARBON_DEFAULT_COUNTRY = "KEN"
		log.info("CarbonPlugin initialized")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.carbon.views import (
			CarbonDashboardView,
			EmissionFactorView,
			EmissionRecordView,
			GHGReportView,
		)
		cat = self.config.get("CARBON_MENU_CATEGORY", "Sustainability")
		self.add_view(CarbonDashboardView, "Carbon Dashboard", icon="fa-leaf", category=cat)
		self.add_view(EmissionFactorView, "Emission Factors", icon="fa-database", category=cat)
		self.add_view(EmissionRecordView, "Emission Records", icon="fa-list", category=cat)
		self.add_view(GHGReportView, "GHG Reports", icon="fa-file-text-o", category=cat)
		log.info("CarbonPlugin: views registered under %r", cat)

	def register_models(self) -> list[type]:
		return [EmissionFactor, EmissionRecord, GHGReport, CarbonOffset]

	def setup_rules(self, session: Session) -> None:
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet

			existing = session.execute(
				__import__("sqlalchemy", fromlist=["select"]).select(RuleSet).where(
					RuleSet.name == "carbon.record.activity_positive"
				)
			).scalar_one_or_none()

			if existing:
				return

			ruleset = RuleSet(
				name="carbon.record.activity_positive",
				description=(
					"Validates that all recorded emission activity data values are "
					"strictly positive before persisting."
				),
		author="PgAppForge Contributors",
				is_active=True,
			)
			session.add(ruleset)

			rule = Rule(
				ruleset=ruleset,
				name="activity_data_must_be_positive",
				description="Emission activity_data must be greater than zero",
				condition="emission.activity_data <= 0",
				action="raise_validation_error",
				priority=1,
				is_active=True,
			)
			session.add(rule)
			session.flush()
			log.info("CarbonPlugin: rules seeded")
		except Exception:
			log.debug("Rules setup skipped (rules engine unavailable)", exc_info=True)
