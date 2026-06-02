"""
pgappforge/plugins/erp/industry/health/__init__.py

HealthPlugin — Health Cloud ERP plugin.

Provides:
  - Patient        (MRN, blood type, allergies/medications as JSONB, insurance)
  - ClinicalEncounter  (INPATIENT / OUTPATIENT / EMERGENCY / TELEHEALTH)
  - DiagnosisRecord    (ICD-10; confirmed = append-only after clinician sign-off)
  - ProcedureRecord    (CPT)
  - Prescription       (NDC; refill tracking)
  - LabResult          (LOINC; critical value alerting)

Business rules enforced:
  - Only one PRIMARY diagnosis per encounter
  - Confirmed DiagnosisRecord rows are functionally immutable
  - refills_used must never exceed refills_allowed
  - Critical lab flags (HH/LL) emit LabCriticalValueEvent immediately
  - Encounter must be IN_PROGRESS to add clinical records

Events emitted:
  health.patient.registered
  health.patient.updated
  health.encounter.started
  health.encounter.completed
  health.diagnosis.confirmed
  health.prescription.issued
  health.prescription.discontinued
  health.lab.resulted
  health.lab.critical_value

Events consumed:
  party.created  (optionally create Patient shell on party registration)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.health",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class HealthPlugin(BasePlugin):
	"""Health Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "health"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "health"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="health",
			version="1.0.0",
			description=(
				"Health Cloud — clinical patient records, encounter management, "
				"ICD-10 / CPT / LOINC / NDC coding, prescription management with "
				"refill tracking, and critical lab value alerting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "health", "clinical", "ehr", "hipaa"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_health_patient_read",
				"can_health_patient_write",
				"can_health_encounter_read",
				"can_health_encounter_write",
				"can_health_encounter_discharge",
				"can_health_diagnosis_read",
				"can_health_diagnosis_write",
				"can_health_diagnosis_confirm",
				"can_health_prescription_read",
				"can_health_prescription_write",
				"can_health_lab_read",
				"can_health_lab_write",
				"can_health_lab_result",
				"can_health_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"health.patient.registered",
			"health.patient.updated",
			"health.encounter.started",
			"health.encounter.completed",
			"health.diagnosis.confirmed",
			"health.prescription.issued",
			"health.prescription.discontinued",
			"health.lab.resulted",
			"health.lab.critical_value",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"party.created",   # Optionally pre-register patient shell on party creation
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"HEALTH_MENU_CATEGORY": "Health Cloud",
			"HEALTH_SEED_RULES_ON_INIT": True,
			"HEALTH_CRITICAL_FLAGS": ["HH", "LL"],
		}
		self.config = {**defaults, **self.config}
		log.info("HealthPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("HEALTH_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Health views under the configured menu category."""
		from pgappforge.plugins.erp.industry.health.views import (
			ClinicalEncounterView,
			DiagnosisView,
			HealthReportView,
			LabResultView,
			PatientView,
			PrescriptionView,
		)

		cat = self.config.get("HEALTH_MENU_CATEGORY", "Health Cloud")

		self.add_view(
			PatientView,
			"Patients",
			icon="fa-user-md",
			category=cat,
		)
		self.add_view(
			ClinicalEncounterView,
			"Encounters",
			icon="fa-hospital-o",
			category=cat,
		)
		self.add_view(
			DiagnosisView,
			"Diagnoses",
			icon="fa-stethoscope",
			category=cat,
		)
		self.add_view(
			PrescriptionView,
			"Prescriptions",
			icon="fa-medkit",
			category=cat,
		)
		self.add_view(
			LabResultView,
			"Lab Results",
			icon="fa-flask",
			category=cat,
		)
		self.add_view(
			HealthReportView,
			"Health Reports",
			icon="fa-file-text-o",
			category=cat,
		)

		log.info("HealthPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.health.models import (
			ClinicalEncounter,
			DiagnosisRecord,
			LabResult,
			Patient,
			Prescription,
			ProcedureRecord,
		)
		return [
			Patient,
			ClinicalEncounter,
			DiagnosisRecord,
			ProcedureRecord,
			Prescription,
			LabResult,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 rulesets for Health Cloud domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("HealthPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "health.encounter.single_primary_diagnosis",
				"description": "Block adding a second PRIMARY diagnosis to the same encounter",
				"model_name": "DiagnosisRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_duplicate_primary",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "diagnosis_type", "op": "eq", "value": "PRIMARY"},
							{
								"field": "encounter.primary_diagnosis_count",
								"op": "gte",
								"value": 1,
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Encounter already has a PRIMARY diagnosis. "
									"Add additional diagnoses as SECONDARY or COMPLICATION."
								),
							}
						],
					},
				],
			},
			{
				"name": "health.diagnosis.immutable_after_confirm",
				"description": "Block updating a confirmed DiagnosisRecord",
				"model_name": "DiagnosisRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_update_confirmed",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_confirmed", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"DiagnosisRecord is confirmed — it cannot be modified. "
									"Add a correction note or a new diagnosis record instead."
								),
							}
						],
					},
				],
			},
			{
				"name": "health.prescription.refill_limit",
				"description": "Block refill if refills_used >= refills_allowed",
				"model_name": "Prescription",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_excess_refills",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_new_refills_used",
								"op": "gt",
								"value": "{{refills_allowed}}",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot issue refill: refills_used would exceed refills_allowed"
								),
							}
						],
					},
				],
			},
			{
				"name": "health.lab.no_result_update",
				"description": "Warn when a RESULTED lab result_value is being changed",
				"model_name": "LabResult",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_result_mutation",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "RESULTED"},
							{"field": "_changed_fields", "op": "contains", "value": "result_value"},
						],
						"actions_json": [
							{
								"type": "log",
								"level": "WARNING",
								"message": (
									"LabResult {{id}}: result_value modified after RESULTED status "
									"— consider adding a correction note"
								),
							}
						],
					},
				],
			},
			{
				"name": "health.encounter.no_records_after_complete",
				"description": "Block adding clinical records to a COMPLETED encounter",
				"model_name": "DiagnosisRecord",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_records_completed_encounter",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "encounter.encounter_status",
								"op": "eq",
								"value": "COMPLETED",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot add clinical records to a COMPLETED encounter. "
									"Open an amendment encounter instead."
								),
							}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("HealthPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("HealthPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> HealthPlugin:
	return HealthPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.health.models import (  # noqa: E402
	ClinicalEncounter,
	DiagnosisRecord,
	LabResult,
	Patient,
	Prescription,
	ProcedureRecord,
)
from pgappforge.plugins.erp.industry.health.events import (  # noqa: E402
	DiagnosisConfirmedEvent,
	EncounterCompletedEvent,
	EncounterStartedEvent,
	LabCriticalValueEvent,
	LabResultedEvent,
	PatientRegisteredEvent,
	PatientUpdatedEvent,
	PrescriptionDiscontinuedEvent,
	PrescriptionIssuedEvent,
	emit_event,
)
from pgappforge.plugins.erp.industry.health.services import (  # noqa: E402
	DiagnosisConfirmedError,
	DiagnosisNotFoundError,
	DuplicatePatientNumberError,
	DuplicatePrimaryDiagnosisError,
	EncounterNotActiveError,
	EncounterNotFoundError,
	HealthService,
	HealthServiceError,
	LabResultNotFoundError,
	PatientNotFoundError,
	PrescriptionNotFoundError,
	RefillLimitExceededError,
)

__all__ = [
	# plugin
	"HealthPlugin",
	"create_plugin",
	# models
	"Patient",
	"ClinicalEncounter",
	"DiagnosisRecord",
	"ProcedureRecord",
	"Prescription",
	"LabResult",
	# events
	"emit_event",
	"PatientRegisteredEvent",
	"PatientUpdatedEvent",
	"EncounterStartedEvent",
	"EncounterCompletedEvent",
	"DiagnosisConfirmedEvent",
	"PrescriptionIssuedEvent",
	"PrescriptionDiscontinuedEvent",
	"LabResultedEvent",
	"LabCriticalValueEvent",
	# services
	"HealthService",
	"HealthServiceError",
	"PatientNotFoundError",
	"EncounterNotFoundError",
	"DiagnosisNotFoundError",
	"PrescriptionNotFoundError",
	"LabResultNotFoundError",
	"EncounterNotActiveError",
	"DiagnosisConfirmedError",
	"DuplicatePrimaryDiagnosisError",
	"RefillLimitExceededError",
	"DuplicatePatientNumberError",
]
