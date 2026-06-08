"""
pgappforge/plugins/erp/crm/appointments/__init__.py

AppointmentsPlugin — Appointments/Booking plugin.

End-to-end appointment booking: service catalogue, staff availability windows,
blocked slot management, slot calculation, booking with conflict re-validation,
confirmation/completion/cancellation lifecycle, reminder dispatch, and BPM
integration for workflow-driven bookings.

Depends on: foundation

Events emitted
--------------
  crm.appointments.booked
  crm.appointments.confirmed
  crm.appointments.cancelled
  crm.appointments.completed
  crm.appointments.reminder.sent

Events consumed
---------------
  hcm.employee.hired  (auto-create default availability on new hire)
"""
from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AppointmentsPlugin(BasePlugin):
	"""Appointments/Booking plugin.

	Covers the full booking lifecycle: service catalogue with duration/buffer/
	pricing, staff weekly availability windows with effective date ranges, ad-hoc
	blocked slots, available-slot calculation with conflict detection, booking
	with re-validation, PENDING→CONFIRMED→COMPLETED flow, cancellation, reminder
	dispatch, and BPM hooks.

	Listens to hcm.employee.hired to create a default empty availability schedule
	for new hires.
	"""

	name = "appointments"
	domain = "crm"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="appointments",
			version="1.0.0",
			description=(
				"Appointments/Booking — service catalogue, staff availability, "
				"slot calculation, booking lifecycle, and BPM integration."
			),
			author="PgAppForge Contributors",
			tags=["crm", "appointments", "booking", "scheduling"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_apt_service_read",
				"can_apt_service_write",
				"can_apt_availability_read",
				"can_apt_availability_write",
				"can_apt_blocked_slot_write",
				"can_apt_appointment_book",
				"can_apt_appointment_manage",
				"can_apt_reports",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"crm.appointments.booked",
			"crm.appointments.confirmed",
			"crm.appointments.cancelled",
			"crm.appointments.completed",
			"crm.appointments.reminder.sent",
		]

	def subscribe_to(self) -> list[str]:
		return ["hcm.employee.hired"]

	def activate(self) -> None:
		"""Alias for initialize() — satisfies plugin protocol variants."""
		self.initialize()

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"APT_MENU_CATEGORY": "Appointments",
			"APT_DEFAULT_CURRENCY": "KES",
			"APT_REMINDER_HOURS_BEFORE": 24,
			"APT_SLOT_GRANULARITY_MINUTES": 30,
		}
		self.config = {**defaults, **self.config}

		# Register the event handler for new employee hires
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe
			subscribe("hcm.employee.hired", self._on_employee_hired)
		except Exception as exc:
			log.debug("AppointmentsPlugin: could not subscribe to hcm.employee.hired: %s", exc)

		log.info("AppointmentsPlugin initialised")

	def _on_employee_hired(self, event: Any) -> None:
		"""Handle hcm.employee.hired — log intent to create default availability.

		Actual availability creation requires a database session that is not
		available in the in-process event bus handler.  The BPM layer or an
		async worker should call create_default_availability() with the session.
		"""
		employee_id = getattr(event, "employee_id", None) or (
			event.payload.get("employee_id") if hasattr(event, "payload") else None
		)
		log.info(
			"AppointmentsPlugin._on_employee_hired: employee=%s — "
			"default availability should be created via create_default_availability()",
			employee_id,
		)

	@staticmethod
	def create_default_availability(
		staff_id: str,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Create Mon–Fri 09:00–17:00 availability rows for a new staff member.

		Called from BPM/async workers after receiving hcm.employee.hired.
		Returns the created StaffAvailability rows.
		"""
		from datetime import time
		from pgappforge.plugins.erp.crm.appointments.models import StaffAvailability

		created: list[Any] = []
		for day in range(5):  # 0=Mon … 4=Fri
			existing = session.execute(
				sa.select(StaffAvailability).where(
					StaffAvailability.staff_id == staff_id,
					StaffAvailability.day_of_week == day,
					StaffAvailability.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if existing is not None:
				continue
			avail = StaffAvailability(
				tenant_id=tenant_id,
				staff_id=staff_id,
				day_of_week=day,
				start_time=time(9, 0),
				end_time=time(17, 0),
				is_active=True,
			)
			session.add(avail)
			created.append(avail)
		session.flush()

		log.info(
			"AppointmentsPlugin.create_default_availability: %d availability rows created for staff=%s",
			len(created), staff_id,
		)
		return created

	def register_models(self) -> list:
		from pgappforge.plugins.erp.crm.appointments.models import (
			AppointmentService,
			StaffAvailability,
			StaffBlockedSlot,
			Appointment,
		)
		return [
			AppointmentService,
			StaffAvailability,
			StaffBlockedSlot,
			Appointment,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.crm.appointments.views import (
			AppointmentServiceView,
			AppointmentView,
			AppointmentCalendarView,
		)
		cat = self.config.get("APT_MENU_CATEGORY", "Appointments")
		self.add_view(AppointmentCalendarView, "Booking Calendar", icon="fa-calendar", category=cat)
		self.add_view(AppointmentServiceView, "Services", icon="fa-list", category=cat)
		self.add_view(AppointmentView, "Appointments", icon="fa-clock-o", category=cat)
		log.info("AppointmentsPlugin: views registered under %r", cat)

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure Rules Engine rulesets for appointments business controls."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("AppointmentsPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "crm.appointments.no_past_bookings",
				"description": "Appointments cannot be booked with a start_at in the past",
				"model_name": "Appointment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_past_appointment",
						"trigger_event": "on_before_insert",
						"conditions_json": [
							{"field": "_start_at_is_past", "op": "eq", "value": True},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot book an appointment with a start time in the past",
							}
						],
					},
				],
			},
			{
				"name": "crm.appointments.no_reopen_completed",
				"description": "COMPLETED or CANCELLED appointments cannot be reopened",
				"model_name": "Appointment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_reopen_terminal",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{
								"field": "_status_old",
								"op": "in",
								"value": ["COMPLETED", "CANCELLED"],
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot modify a COMPLETED or CANCELLED appointment",
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
		log.info("AppointmentsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> AppointmentsPlugin:
	return AppointmentsPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.crm.appointments.models import (  # noqa: E402
	AppointmentService,
	StaffAvailability,
	StaffBlockedSlot,
	Appointment,
)
from pgappforge.plugins.erp.crm.appointments.events import (  # noqa: E402
	AppointmentBookedEvent,
	AppointmentConfirmedEvent,
	AppointmentCancelledEvent,
	AppointmentCompletedEvent,
	ReminderSentEvent,
)
from pgappforge.plugins.erp.crm.appointments.services import (  # noqa: E402
	AppointmentsService,
	AppointmentsServiceError,
	AppointmentNotFoundError,
	AppointmentStateError,
	SlotUnavailableError,
)

__all__ = [
	# Plugin
	"AppointmentsPlugin",
	"create_plugin",
	# Models
	"AppointmentService",
	"StaffAvailability",
	"StaffBlockedSlot",
	"Appointment",
	# Events
	"AppointmentBookedEvent",
	"AppointmentConfirmedEvent",
	"AppointmentCancelledEvent",
	"AppointmentCompletedEvent",
	"ReminderSentEvent",
	# Services / Exceptions
	"AppointmentsService",
	"AppointmentsServiceError",
	"AppointmentNotFoundError",
	"AppointmentStateError",
	"SlotUnavailableError",
]
