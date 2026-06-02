"""
pgappforge/plugins/erp/hcm/personnel/__init__.py

PersonnelPlugin — HCM Personnel Administration ERP plugin.

Entities managed:
  Employee → EmployeeCompensation (immutable ledger)
           → EmployeeDocument

Domain: hcm
Depends on: foundation, hcm.org

Events emitted:
  hcm.personnel.employee.hired
  hcm.personnel.employee.assigned
  hcm.personnel.employee.transferred
  hcm.personnel.employee.terminated
  hcm.personnel.employee.rehired
  hcm.personnel.compensation.changed
  hcm.personnel.document.verified
  hcm.personnel.document.expiring

Events consumed:
  hcm.org.position.created    — can pre-validate position reference
  hcm.time.timesheet.approved — downstream (payroll computes hourly from approved hours)

Usage::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.hcm.org",
        "pgappforge.plugins.erp.hcm.personnel",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PersonnelPlugin(BasePlugin):
	"""HCM Personnel Administration plugin.

	Registers 4 view groups (Employee, Compensation, Documents, Reports).
	Pre-configures 4 Rules Engine rulesets on first run.
	"""

	name = "hcm.personnel"
	domain = "hcm"
	depends_on: list[str] = ["foundation", "hcm.org"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="hcm.personnel",
			version="1.0.0",
			description=(
				"HCM Personnel Administration — employee master data, "
				"effective-dated compensation history (immutable ledger), "
				"and document management with expiry alerting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "hcm", "personnel", "employees", "compensation", "hr"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_hcm_per_employee_list",
				"can_hcm_per_employee_write",
				"can_hcm_per_employee_terminate",
				"can_hcm_per_employee_transfer",
				"can_hcm_per_compensation_list",
				"can_hcm_per_compensation_write",
				"can_hcm_per_document_list",
				"can_hcm_per_document_write",
				"can_hcm_per_document_verify",
				"can_hcm_per_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"hcm.personnel.employee.hired",
			"hcm.personnel.employee.assigned",
			"hcm.personnel.employee.transferred",
			"hcm.personnel.employee.terminated",
			"hcm.personnel.employee.rehired",
			"hcm.personnel.compensation.changed",
			"hcm.personnel.document.verified",
			"hcm.personnel.document.expiring",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.org.position.created",
			"hcm.time.timesheet.approved",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"HCM_PER_MENU_CATEGORY": "HCM — Personnel",
			"HCM_PER_DOC_EXPIRY_ALERT_DAYS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("PersonnelPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.personnel.views import (
			EmployeeView,
			EmployeeCompensationView,
			EmployeeDocumentView,
			PersonnelReportView,
		)

		cat = self.config.get("HCM_PER_MENU_CATEGORY", "HCM — Personnel")

		self.add_view(EmployeeView, "Employees", icon="fa-users", category=cat)
		self.add_view(EmployeeCompensationView, "Compensation", icon="fa-money", category=cat)
		self.add_view(EmployeeDocumentView, "Documents", icon="fa-file", category=cat)
		self.add_view(PersonnelReportView, "Personnel Reports", icon="fa-bar-chart", category=cat)

		log.info("PersonnelPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.hcm.personnel.models import (
			Employee,
			EmployeeCompensation,
			EmployeeDocument,
		)
		return [Employee, EmployeeCompensation, EmployeeDocument]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for HCM Personnel domain.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("PersonnelPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "hcm.personnel.employee.require_start_date",
				"description": "Employee start_date must be set on hire",
				"model_name": "Employee",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_start_date",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "start_date", "op": "eq", "value": None},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Employee.start_date is required on hire"}
						],
					},
				],
			},
			{
				"name": "hcm.personnel.compensation.positive_amount",
				"description": "Compensation amount_cents must be positive",
				"model_name": "EmployeeCompensation",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_positive_compensation",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "amount_cents", "op": "lte", "value": 0},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "EmployeeCompensation.amount_cents must be > 0"}
						],
					},
				],
			},
			{
				"name": "hcm.personnel.employee.termination_type_required",
				"description": "termination_type must be set when termination_date is set",
				"model_name": "Employee",
				"stop_on_match": True,
				"rules": [
					{
						"name": "require_termination_type",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "termination_date", "op": "neq", "value": None},
							{"field": "termination_type", "op": "eq", "value": None},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Employee.termination_type is required when termination_date is set"}
						],
					},
				],
			},
			{
				"name": "hcm.personnel.employee.no_rehire_if_ineligible",
				"description": "Cannot rehire an employee marked rehire_eligible=False",
				"model_name": "Employee",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_ineligible_rehire",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "employment_status", "op": "eq", "value": "ACTIVE"},
							{"field": "rehire_eligible", "op": "eq", "value": False},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "This employee is not eligible for rehire"}
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
		log.info("PersonnelPlugin.setup_rules: %d rulesets configured", len(RULESETS))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PersonnelPlugin:
	"""Construct a PersonnelPlugin without activating it."""
	return PersonnelPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.hcm.personnel.models import (  # noqa: E402
	Employee,
	EmployeeCompensation,
	EmployeeDocument,
)
from pgappforge.plugins.erp.hcm.personnel.events import (  # noqa: E402
	EmployeeHiredEvent,
	EmployeeAssignedEvent,
	EmployeeTransferredEvent,
	EmployeeTerminatedEvent,
	EmployeeRehiredEvent,
	CompensationChangedEvent,
	DocumentVerifiedEvent,
	DocumentExpiringEvent,
)
from pgappforge.plugins.erp.hcm.personnel.services import (  # noqa: E402
	PersonnelService,
	PersonnelServiceError,
	EmployeeNotFoundError,
	CompensationError,
	DocumentError,
)

__all__ = [
	# plugin
	"PersonnelPlugin",
	"create_plugin",
	# models
	"Employee",
	"EmployeeCompensation",
	"EmployeeDocument",
	# events
	"EmployeeHiredEvent",
	"EmployeeAssignedEvent",
	"EmployeeTransferredEvent",
	"EmployeeTerminatedEvent",
	"EmployeeRehiredEvent",
	"CompensationChangedEvent",
	"DocumentVerifiedEvent",
	"DocumentExpiringEvent",
	# services
	"PersonnelService",
	"PersonnelServiceError",
	"EmployeeNotFoundError",
	"CompensationError",
	"DocumentError",
]
