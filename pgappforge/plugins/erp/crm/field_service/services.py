"""
pgappforge/plugins/erp/crm/field_service/services.py

FieldServiceService — stateless business logic for the Field Service plugin.

Key methods
-----------
  create_work_order(data, session) -> WorkOrder
  schedule_work_order(work_order_id, resource_id, start, end, session) -> WorkOrder
  complete_work_order(work_order_id, data, session) -> WorkOrder
  propose_appointment(work_order_id, slots, contact_id, session) -> ServiceAppointment
  confirm_appointment(appointment_id, slot_index, session) -> ServiceAppointment
  cancel_appointment(appointment_id, session) -> ServiceAppointment
  resource_schedule(resource_id, date_from, date_to, session) -> list[WorkOrder]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FieldServiceError(Exception):
	"""Base exception for Field Service service layer."""


class WorkOrderNotFoundError(FieldServiceError):
	pass


class AppointmentNotFoundError(FieldServiceError):
	pass


class ResourceNotFoundError(FieldServiceError):
	pass


class FieldServiceValidationError(FieldServiceError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# FieldServiceService
# ---------------------------------------------------------------------------

class FieldServiceService:
	"""Stateless business logic for Field Service."""

	@staticmethod
	def create_work_order(data: dict[str, Any], session: Any) -> Any:
		"""Create a DRAFT work order, optionally linked to a service case."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder
		from pgappforge.plugins.erp.crm.field_service.events import WorkOrderCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		wo = WorkOrder(
			tenant_id=data["tenant_id"],
			work_order_number=data["work_order_number"],
			case_id=data.get("case_id"),
			account_id=data.get("account_id"),
			contact_id=data.get("contact_id"),
			work_type=data["work_type"],
			status="DRAFT",
			address=data.get("address", {}),
			parts_used=[],
		)
		session.add(wo)
		session.flush()

		emit_event(WorkOrderCreatedEvent(
			aggregate_id=wo.id,
			aggregate_type="WorkOrder",
			tenant_id=wo.tenant_id,
			work_order_id=wo.id,
			work_order_number=wo.work_order_number,
			work_type=wo.work_type,
			account_id=data.get("account_id", ""),
			case_id=data.get("case_id", ""),
		), session)

		log.info("FieldServiceService.create_work_order: %s created", wo.work_order_number)
		return wo

	@staticmethod
	def schedule_work_order(
		work_order_id: str,
		resource_id: str,
		scheduled_start: datetime,
		scheduled_end: datetime,
		session: Any,
	) -> Any:
		"""Assign a resource and schedule start/end times; move to SCHEDULED."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, ServiceResource
		from pgappforge.plugins.erp.crm.field_service.events import WorkOrderScheduledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		wo = session.execute(
			sa.select(WorkOrder).where(WorkOrder.id == work_order_id)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")
		if wo.status not in ("DRAFT", "SCHEDULED"):
			raise FieldServiceValidationError(f"Cannot schedule a {wo.status} work order")

		resource = session.execute(
			sa.select(ServiceResource).where(ServiceResource.id == resource_id)
		).scalar_one_or_none()
		if resource is None:
			raise ResourceNotFoundError(f"ServiceResource {resource_id} not found")

		wo.assigned_to = resource_id
		wo.scheduled_start = scheduled_start
		wo.scheduled_end = scheduled_end
		wo.status = "SCHEDULED"
		session.flush()

		emit_event(WorkOrderScheduledEvent(
			aggregate_id=wo.id,
			aggregate_type="WorkOrder",
			tenant_id=wo.tenant_id,
			work_order_id=wo.id,
			work_order_number=wo.work_order_number,
			assigned_to=resource_id,
			scheduled_start=scheduled_start.isoformat(),
			scheduled_end=scheduled_end.isoformat(),
		), session)

		log.info(
			"FieldServiceService.schedule_work_order: %s scheduled to resource %s",
			wo.work_order_number, resource_id,
		)
		return wo

	@staticmethod
	def complete_work_order(work_order_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Record completion details and move work order to COMPLETED."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder
		from pgappforge.plugins.erp.crm.field_service.events import WorkOrderCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		wo = session.execute(
			sa.select(WorkOrder).where(WorkOrder.id == work_order_id)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")
		if wo.status not in ("SCHEDULED", "IN_PROGRESS"):
			raise FieldServiceValidationError(f"Cannot complete a {wo.status} work order")

		wo.status = "COMPLETED"
		wo.labor_minutes = data.get("labor_minutes")
		wo.parts_used = data.get("parts_used", [])
		wo.completion_notes = data.get("completion_notes")
		session.flush()

		emit_event(WorkOrderCompletedEvent(
			aggregate_id=wo.id,
			aggregate_type="WorkOrder",
			tenant_id=wo.tenant_id,
			work_order_id=wo.id,
			work_order_number=wo.work_order_number,
			assigned_to=wo.assigned_to or "",
			labor_minutes=wo.labor_minutes or 0,
			parts_used=wo.parts_used or [],
		), session)

		log.info("FieldServiceService.complete_work_order: %s completed", wo.work_order_number)
		return wo

	@staticmethod
	def propose_appointment(
		work_order_id: str,
		slots: list[dict[str, str]],
		contact_id: str | None,
		session: Any,
	) -> Any:
		"""Create a ServiceAppointment with proposed time slots for customer selection."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, ServiceAppointment

		wo = session.execute(
			sa.select(WorkOrder).where(WorkOrder.id == work_order_id)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")

		appt = ServiceAppointment(
			tenant_id=wo.tenant_id,
			work_order_id=work_order_id,
			contact_id=contact_id,
			proposed_slots=slots,
			status="PENDING",
		)
		session.add(appt)
		session.flush()
		log.debug("FieldServiceService.propose_appointment: created for wo %s", work_order_id)
		return appt

	@staticmethod
	def confirm_appointment(appointment_id: str, slot_index: int, session: Any) -> Any:
		"""Customer confirms a slot; move appointment to CONFIRMED."""
		from pgappforge.plugins.erp.crm.field_service.models import ServiceAppointment
		from pgappforge.plugins.erp.crm.field_service.events import AppointmentConfirmedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		appt = session.execute(
			sa.select(ServiceAppointment).where(ServiceAppointment.id == appointment_id)
		).scalar_one_or_none()
		if appt is None:
			raise AppointmentNotFoundError(f"ServiceAppointment {appointment_id} not found")
		if appt.status != "PENDING":
			raise FieldServiceValidationError(f"Appointment already {appt.status}")

		slots = appt.proposed_slots or []
		if slot_index >= len(slots):
			raise FieldServiceValidationError(
				f"slot_index {slot_index} out of range (have {len(slots)} slots)"
			)

		chosen = slots[slot_index]
		appt.confirmed_slot = chosen
		appt.status = "CONFIRMED"
		appt.confirmation_sent_at = datetime.now(timezone.utc)
		session.flush()

		emit_event(AppointmentConfirmedEvent(
			aggregate_id=appt.id,
			aggregate_type="ServiceAppointment",
			tenant_id=appt.tenant_id,
			appointment_id=appt.id,
			work_order_id=appt.work_order_id,
			contact_id=appt.contact_id or "",
			confirmed_start=chosen.get("start", ""),
			confirmed_end=chosen.get("end", ""),
		), session)

		log.info("FieldServiceService.confirm_appointment: %s confirmed slot %d", appointment_id, slot_index)
		return appt

	@staticmethod
	def cancel_appointment(appointment_id: str, session: Any) -> Any:
		"""Cancel a pending or confirmed appointment."""
		from pgappforge.plugins.erp.crm.field_service.models import ServiceAppointment
		from pgappforge.plugins.erp.crm.field_service.events import AppointmentCancelledEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		appt = session.execute(
			sa.select(ServiceAppointment).where(ServiceAppointment.id == appointment_id)
		).scalar_one_or_none()
		if appt is None:
			raise AppointmentNotFoundError(f"ServiceAppointment {appointment_id} not found")
		if appt.status in ("COMPLETED", "CANCELLED"):
			raise FieldServiceValidationError(f"Appointment already {appt.status}")

		appt.status = "CANCELLED"
		session.flush()

		emit_event(AppointmentCancelledEvent(
			aggregate_id=appt.id,
			aggregate_type="ServiceAppointment",
			tenant_id=appt.tenant_id,
			appointment_id=appt.id,
			work_order_id=appt.work_order_id,
			contact_id=appt.contact_id or "",
		), session)

		log.info("FieldServiceService.cancel_appointment: %s cancelled", appointment_id)
		return appt

	@staticmethod
	def resource_schedule(
		resource_id: str,
		date_from: Any,
		date_to: Any,
		session: Any,
	) -> list[Any]:
		"""Return scheduled work orders for a resource within a date range."""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder

		rows = session.execute(
			sa.select(WorkOrder).where(
				WorkOrder.assigned_to == resource_id,
				WorkOrder.status.in_(("SCHEDULED", "IN_PROGRESS")),
				WorkOrder.scheduled_start >= date_from,
				WorkOrder.scheduled_start <= date_to,
			).order_by(WorkOrder.scheduled_start)
		).scalars().all()
		return list(rows)


__all__ = [
	"FieldServiceService",
	"FieldServiceError",
	"WorkOrderNotFoundError",
	"AppointmentNotFoundError",
	"ResourceNotFoundError",
	"FieldServiceValidationError",
]
