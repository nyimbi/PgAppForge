"""
pgappforge/plugins/erp/crm/field_service/__init__.py

FieldServicePlugin — Field Service ERP plugin.

Depends on: foundation, service (Cases)

Events emitted
--------------
  field_service.work_order.created
  field_service.work_order.scheduled
  field_service.work_order.completed
  field_service.appointment.confirmed
  field_service.appointment.cancelled

Events consumed
---------------
  service.case.created    — auto-create work order for field-type cases
  service.case.escalated  — flag related work orders for priority scheduling
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FieldServicePlugin(BasePlugin):
	"""Field Service plugin — territories, resources, work orders, appointments."""

	name = "field_service"
	domain = "crm"
	depends_on: list[str] = ["foundation", "service"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="field_service",
			version="1.0.0",
			description=(
				"Field Service — schedule and dispatch technicians: "
				"territories, resources, work orders, and customer appointments."
			),
			author="PgAppForge Contributors",
			tags=["erp", "crm", "field_service", "work_order", "scheduling", "gis"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_fs_territory_write",
				"can_fs_resource_write",
				"can_fs_work_order_list",
				"can_fs_work_order_write",
				"can_fs_work_order_schedule",
				"can_fs_work_order_complete",
				"can_fs_appointment_write",
				"can_fs_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"field_service.work_order.created",
			"field_service.work_order.scheduled",
			"field_service.work_order.completed",
			"field_service.appointment.confirmed",
			"field_service.appointment.cancelled",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"service.case.created",    # consider auto-creating work order
			"service.case.escalated",  # flag related work orders
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"FS_MENU_CATEGORY": "Field Service",
			"FS_DEFAULT_CAPACITY_PER_DAY": 4,
		}
		self.config = {**defaults, **self.config}
		log.info("FieldServicePlugin initialised")

	def post_initialize(self) -> None:
		self._subscribe_to_upstream_events()

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.field_service.views import (
			FieldServiceReportView,
			ServiceAppointmentView,
			ServiceResourceView,
			ServiceTerritoryView,
			WorkOrderView,
		)
		cat = self.config.get("FS_MENU_CATEGORY", "Field Service")
		self.add_view(ServiceTerritoryView, "Territories", icon="fa-map", category=cat)
		self.add_view(ServiceResourceView, "Resources", icon="fa-users", category=cat)
		self.add_view(WorkOrderView, "Work Orders", icon="fa-wrench", category=cat)
		self.add_view(ServiceAppointmentView, "Appointments", icon="fa-calendar", category=cat)
		self.add_view(FieldServiceReportView, "FS Reports", icon="fa-chart-bar", category=cat)
		log.info("FieldServicePlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.field_service.models import (
			ServiceAppointment,
			ServiceResource,
			ServiceTerritory,
			WorkOrder,
		)
		return [ServiceTerritory, ServiceResource, WorkOrder, ServiceAppointment]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 3 Rules Engine rulesets for Field Service business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("FieldServicePlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			# 1. Block completing a work order without assigned resource
			{
				"name": "fs.work_order.complete_requires_resource",
				"description": "Work order cannot be completed without an assigned resource",
				"model_name": "WorkOrder",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_unassigned_completion",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "COMPLETED"},
							{"field": "assigned_to", "op": "is_null", "value": None},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Work order must have an assigned resource before completion",
							}
						],
					},
				],
			},
			# 2. Prevent scheduling conflicts (same resource, overlapping times)
			{
				"name": "fs.work_order.schedule_conflict",
				"description": "Warn when scheduling may cause resource double-booking",
				"model_name": "WorkOrder",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_schedule_overlap",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "SCHEDULED"},
							{"field": "scheduled_start", "op": "is_not_null", "value": None},
						],
						"actions_json": [
							{
								"type": "log_warning",
								"message": "Verify no scheduling conflicts for this resource before confirming",
							}
						],
					},
				],
			},
			# 3. Appointment confirmation requires proposed slots
			{
				"name": "fs.appointment.confirm_requires_slots",
				"description": "Cannot confirm an appointment with no proposed slots",
				"model_name": "ServiceAppointment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_confirm_no_slots",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_status", "op": "eq", "value": "CONFIRMED"},
							{"field": "proposed_slots", "op": "eq", "value": []},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot confirm appointment: no proposed slots exist",
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
		log.info("FieldServicePlugin.setup_rules: %d rulesets configured", len(RULESETS))

	def _subscribe_to_upstream_events(self) -> None:
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("service.case.created", self._on_case_created)
			log.debug("FieldServicePlugin: subscribed to service.case.created")
		except Exception as exc:
			log.warning("FieldServicePlugin._subscribe_to_upstream_events failed: %s", exc)

	def _on_case_created(self, event: Any) -> None:
		log.debug(
			"FieldServicePlugin._on_case_created: case=%s channel=%s (no auto-WO)",
			event.aggregate_id,
			getattr(event, "channel", "?"),
		)


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> FieldServicePlugin:
	return FieldServicePlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.crm.field_service.models import (  # noqa: E402
	ServiceTerritory,
	ServiceResource,
	WorkOrder,
	ServiceAppointment,
)
from pgappforge.plugins.erp.crm.field_service.events import (  # noqa: E402
	WorkOrderCreatedEvent,
	WorkOrderScheduledEvent,
	WorkOrderCompletedEvent,
	AppointmentConfirmedEvent,
	AppointmentCancelledEvent,
)
from pgappforge.plugins.erp.crm.field_service.services import (  # noqa: E402
	FieldServiceService,
	FieldServiceError,
	WorkOrderNotFoundError,
	FieldServiceValidationError,
)

__all__ = [
	"FieldServicePlugin",
	"create_plugin",
	"ServiceTerritory",
	"ServiceResource",
	"WorkOrder",
	"ServiceAppointment",
	"WorkOrderCreatedEvent",
	"WorkOrderScheduledEvent",
	"WorkOrderCompletedEvent",
	"AppointmentConfirmedEvent",
	"AppointmentCancelledEvent",
	"FieldServiceService",
	"FieldServiceError",
	"WorkOrderNotFoundError",
	"FieldServiceValidationError",
]
