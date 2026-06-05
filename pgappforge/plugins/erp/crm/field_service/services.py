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

	# -----------------------------------------------------------------------
	# SLA / Contract
	# -----------------------------------------------------------------------

	@staticmethod
	def check_sla_status(session: Any, work_order_id: str, tenant_id: str) -> dict[str, Any]:
		"""Return SLA elapsed percentages and breach flags for a work order.

		Looks up the WorkOrder → ServiceContract → ServiceLevel chain.
		Contract-level overrides take precedence over ServiceLevel defaults.

		Returns
		-------
		dict with keys:
		  work_order_id, sla_level_name,
		  response_hours_target, resolution_hours_target,
		  elapsed_hours,
		  response_elapsed_pct, resolution_elapsed_pct,
		  response_breached, resolution_breached,
		  escalate_now (bool — elapsed >= escalation_at_pct threshold),
		  penalty_cents (accrued cents if resolution breached)
		"""
		from pgappforge.plugins.erp.crm.field_service.models import (
			WorkOrder, ServiceContract, ServiceLevel,
		)

		wo: Any = session.execute(
			sa.select(WorkOrder).where(
				WorkOrder.id == work_order_id,
				WorkOrder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")

		now = datetime.now(timezone.utc)
		# Use actual_start if available, otherwise creation time
		reference_dt: datetime = wo.actual_start or wo.created_at
		if reference_dt.tzinfo is None:
			reference_dt = reference_dt.replace(tzinfo=timezone.utc)

		elapsed_hours: float = (now - reference_dt).total_seconds() / 3600.0

		# Resolve contract + SLA
		contract: Any = None
		sla: Any = None
		if wo.contract_id:
			contract = session.execute(
				sa.select(ServiceContract).where(ServiceContract.id == wo.contract_id)
			).scalar_one_or_none()
		if contract and contract.service_level_id:
			sla = session.execute(
				sa.select(ServiceLevel).where(ServiceLevel.id == contract.service_level_id)
			).scalar_one_or_none()

		# Effective targets — contract overrides win
		response_target: float | None = None
		resolution_target: float | None = None
		sla_name = "NONE"
		escalation_pct: float = 80.0
		penalty_rate: int = 0

		if contract:
			if contract.sla_response_hours is not None:
				response_target = float(contract.sla_response_hours)
			if contract.sla_resolution_hours is not None:
				resolution_target = float(contract.sla_resolution_hours)

		if sla:
			sla_name = sla.name
			escalation_pct = float(sla.escalation_at_pct)
			penalty_rate = int(sla.penalty_cents_per_hour)
			if response_target is None:
				response_target = float(sla.response_hours)
			if resolution_target is None:
				resolution_target = float(sla.resolution_hours)

		def _pct(elapsed: float, target: float | None) -> float | None:
			if target is None or target == 0:
				return None
			return round(elapsed / target * 100, 2)

		response_pct = _pct(elapsed_hours, response_target)
		resolution_pct = _pct(elapsed_hours, resolution_target)

		response_breached = bool(response_pct is not None and response_pct >= 100)
		resolution_breached = bool(resolution_pct is not None and resolution_pct >= 100)

		# Accrued penalty: hours beyond resolution target × rate
		penalty_cents = 0
		if resolution_breached and resolution_target is not None and penalty_rate > 0:
			overage_hours = max(0.0, elapsed_hours - resolution_target)
			penalty_cents = int(overage_hours * penalty_rate)

		escalate_now = bool(resolution_pct is not None and resolution_pct >= escalation_pct and not resolution_breached)

		result = {
			"work_order_id": work_order_id,
			"sla_level_name": sla_name,
			"contract_id": wo.contract_id,
			"response_hours_target": response_target,
			"resolution_hours_target": resolution_target,
			"elapsed_hours": round(elapsed_hours, 4),
			"response_elapsed_pct": response_pct,
			"resolution_elapsed_pct": resolution_pct,
			"response_breached": response_breached,
			"resolution_breached": resolution_breached,
			"escalate_now": escalate_now,
			"penalty_cents": penalty_cents,
		}

		# Persist denormalised breach flags back to the work order row
		if wo.response_breached != response_breached or wo.resolution_breached != resolution_breached:
			wo.response_breached = response_breached
			wo.resolution_breached = resolution_breached
			session.flush()

		log.debug("check_sla_status: wo=%s elapsed=%.2fh resolution_pct=%s", work_order_id, elapsed_hours, resolution_pct)
		return result

	# -----------------------------------------------------------------------
	# Smart dispatch
	# -----------------------------------------------------------------------

	@staticmethod
	def find_best_technician(
		session: Any,
		work_order_id: str,
		required_skills: list[str],
		preferred_territory_id: str | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Score and rank ServiceResources for a work order.

		Scoring (0.0 – 1.0 composite):
		  skills_match_pct   : required_skills ∩ resource skills / len(required_skills)  [weight 0.5]
		  territory_match    : 1 if resource.territory_id == preferred_territory_id       [weight 0.3]
		  workload_score     : 1 – (open_wos / capacity_per_day) clamped 0..1            [weight 0.2]

		Returns top 5 resources sorted by composite score descending.
		"""
		from pgappforge.plugins.erp.crm.field_service.models import (
			WorkOrder, ServiceResource, TechnicianSkill,
		)

		# Validate work order exists
		wo: Any = session.execute(
			sa.select(WorkOrder).where(WorkOrder.id == work_order_id)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")

		# Fetch all active resources for this tenant
		resources: list[Any] = session.execute(
			sa.select(ServiceResource).where(
				ServiceResource.tenant_id == tenant_id,
			)
		).scalars().all()

		if not resources:
			return []

		# Build skill sets from TechnicianSkill rows (non-expired)
		today_date = datetime.now(timezone.utc).date()
		resource_ids = [r.id for r in resources]

		skill_rows: list[Any] = session.execute(
			sa.select(TechnicianSkill).where(
				TechnicianSkill.resource_id.in_(resource_ids),
				sa.or_(
					TechnicianSkill.expires_at == None,  # noqa: E711
					TechnicianSkill.expires_at >= today_date,
				),
			)
		).scalars().all()

		# resource_id → set of skill_codes
		resource_skills: dict[str, set[str]] = {}
		for ts in skill_rows:
			resource_skills.setdefault(ts.resource_id, set()).add(ts.skill_code)

		# Also fold in JSONB skills dict keys as a fallback
		for r in resources:
			jsonb_skills: dict[str, Any] = r.skills or {}
			resource_skills.setdefault(r.id, set()).update(jsonb_skills.keys())

		# Open WO counts per resource
		open_counts_rows = session.execute(
			sa.select(WorkOrder.assigned_to, sa.func.count(WorkOrder.id).label("cnt")).where(
				WorkOrder.assigned_to.in_(resource_ids),
				WorkOrder.status.in_(("SCHEDULED", "IN_PROGRESS")),
			).group_by(WorkOrder.assigned_to)
		).all()
		open_counts: dict[str, int] = {row.assigned_to: row.cnt for row in open_counts_rows}

		required_set = set(required_skills)
		n_required = max(len(required_set), 1)

		results: list[dict[str, Any]] = []
		for r in resources:
			r_skills = resource_skills.get(r.id, set())
			skills_match = len(required_set & r_skills) / n_required if required_set else 1.0

			territory_match = 1.0 if (
				preferred_territory_id and r.territory_id == preferred_territory_id
			) else 0.0

			capacity = max(int(r.capacity_per_day or 1), 1)
			open_wos = open_counts.get(r.id, 0)
			workload_score = max(0.0, 1.0 - open_wos / capacity)

			composite = (skills_match * 0.5) + (territory_match * 0.3) + (workload_score * 0.2)

			results.append({
				"resource_id": r.id,
				"employee_id": r.employee_id,
				"territory_id": r.territory_id,
				"skills_match_pct": round(skills_match * 100, 1),
				"territory_match": bool(territory_match),
				"open_work_orders": open_wos,
				"capacity_per_day": capacity,
				"workload_score": round(workload_score, 4),
				"composite_score": round(composite, 4),
			})

		results.sort(key=lambda x: x["composite_score"], reverse=True)
		top5 = results[:5]
		log.debug("find_best_technician: wo=%s top candidate score=%.4f", work_order_id, top5[0]["composite_score"] if top5 else 0)
		return top5

	# -----------------------------------------------------------------------
	# Preventive maintenance
	# -----------------------------------------------------------------------

	@staticmethod
	def schedule_preventive_maintenance(
		session: Any,
		as_of_date: datetime,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Generate work orders for all due MaintenancePlans.

		Selects plans where next_due_at <= as_of_date + 7 days AND is_active=True.
		For each plan creates a WorkOrder from work_order_template JSONB fields,
		then updates last_generated_at and advances next_due_at by interval_days.

		Returns a summary dict with lists of generated work order ids and any
		errors encountered (so partial failures are non-fatal).
		"""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, FSMaintenancePlan
		import uuid as _uuid

		from datetime import timedelta

		lookahead = as_of_date + timedelta(days=7)
		if lookahead.tzinfo is None:
			lookahead = lookahead.replace(tzinfo=timezone.utc)

		due_plans: list[Any] = session.execute(
			sa.select(FSMaintenancePlan).where(
				FSMaintenancePlan.tenant_id == tenant_id,
				FSMaintenancePlan.is_active == True,  # noqa: E712
				FSMaintenancePlan.next_due_at != None,  # noqa: E711
				FSMaintenancePlan.next_due_at <= lookahead,
			)
		).scalars().all()

		generated: list[str] = []
		errors: list[dict[str, str]] = []

		for plan in due_plans:
			try:
				tmpl: dict[str, Any] = plan.work_order_template or {}
				wo_number = f"PM-{plan.id[:8].upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

				wo = WorkOrder(
					tenant_id=plan.tenant_id,
					work_order_number=wo_number,
					work_type=tmpl.get("work_type", "MAINTENANCE"),
					priority=tmpl.get("priority", 3),
					address=tmpl.get("address", {}),
					contact_id=tmpl.get("contact_id"),
					account_id=tmpl.get("account_id"),
					failure_code=tmpl.get("failure_code"),
					completion_notes=f"Auto-generated by FSMaintenancePlan {plan.name}",
					maintenance_plan_id=plan.id,
					status="DRAFT",
					parts_used=[],
				)
				session.add(wo)
				session.flush()  # obtain wo.id

				now = datetime.now(timezone.utc)
				plan.last_triggered_at = now

				if plan.plan_type == "CALENDAR" and plan.interval_days:
					next_due = (plan.next_due_at or now) + timedelta(days=plan.interval_days)
				else:
					# METER / CONDITION: clear next_due_at — external system must set it
					next_due = None

				plan.next_due_at = next_due
				generated.append(wo.id)
				log.info("schedule_preventive_maintenance: created WO %s from plan %s", wo_number, plan.name)

			except Exception as exc:  # noqa: BLE001
				log.exception("schedule_preventive_maintenance: failed for plan %s: %s", plan.id, exc)
				errors.append({"plan_id": plan.id, "plan_name": plan.name, "error": str(exc)})

		session.flush()
		return {
			"as_of_date": as_of_date.isoformat(),
			"plans_evaluated": len(due_plans),
			"work_orders_generated": len(generated),
			"generated_work_order_ids": generated,
			"errors": errors,
		}

	# -----------------------------------------------------------------------
	# Cost calculation + GL posting
	# -----------------------------------------------------------------------

	@staticmethod
	def calculate_work_order_cost(
		session: Any,
		work_order_id: str,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Compute total cost for a work order and post a GL journal entry.

		Cost components:
		  parts_cost_cents : sum of FSWorkOrderPart.total_cost_cents
		  labor_cost_cents : labor_minutes / 60 × resource.hourly_rate_cents

		GL posting (non-fatal — missing GL plugin degrades gracefully):
		  DR  6100  Field Service Expense  total_cost_cents
		  CR  2000  Accounts Payable       total_cost_cents

		Returns a dict with parts_cost_cents, labor_cost_cents, total_cost_cents,
		and gl_posted (bool).
		"""
		from pgappforge.plugins.erp.crm.field_service.models import (
			WorkOrder, FSWorkOrderPart, ServiceResource,
		)

		wo: Any = session.execute(
			sa.select(WorkOrder).where(
				WorkOrder.id == work_order_id,
				WorkOrder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")

		# Sum parts cost
		parts_result = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(FSWorkOrderPart.total_cost_cents), 0)).where(
				FSWorkOrderPart.work_order_id == work_order_id,
			)
		).scalar()
		parts_cost_cents: int = int(parts_result or 0)

		# Labor cost
		labor_cost_cents = 0
		if wo.assigned_to and wo.labor_minutes:
			resource: Any = session.execute(
				sa.select(ServiceResource).where(ServiceResource.id == wo.assigned_to)
			).scalar_one_or_none()
			if resource and resource.hourly_rate_cents:
				labor_hours = wo.labor_minutes / 60.0
				labor_cost_cents = int(labor_hours * resource.hourly_rate_cents)

		total_cost_cents = parts_cost_cents + labor_cost_cents

		# GL posting — lazy import, non-fatal
		gl_posted = False
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore[import]
			GLService.post_journal_entry(
				session=session,
				tenant_id=tenant_id,
				reference=f"FS-{work_order_id}",
				lines=[
					{"account_code": "6100", "debit_cents": total_cost_cents, "credit_cents": 0,
					 "description": f"Field service expense WO {wo.work_order_number}"},
					{"account_code": "2000", "debit_cents": 0, "credit_cents": total_cost_cents,
					 "description": f"AP accrual WO {wo.work_order_number}"},
				],
			)
			gl_posted = True
			log.info("calculate_work_order_cost: GL posted for wo=%s total=%d cents", work_order_id, total_cost_cents)
		except Exception as exc:  # noqa: BLE001
			log.debug("calculate_work_order_cost: GL posting skipped (%s)", exc)

		return {
			"work_order_id": work_order_id,
			"work_order_number": wo.work_order_number,
			"parts_cost_cents": parts_cost_cents,
			"labor_cost_cents": labor_cost_cents,
			"total_cost_cents": total_cost_cents,
			"gl_posted": gl_posted,
		}

	# -----------------------------------------------------------------------
	# Customer feedback
	# -----------------------------------------------------------------------

	@staticmethod
	def record_customer_feedback(
		session: Any,
		work_order_id: str,
		rating: int,
		comments: str | None,
		nps_score: int | None = None,
	) -> Any:
		"""Record post-service customer feedback (CSAT + optional NPS).

		Validates rating is 1-5 and nps_score is 0-10 when provided.
		Enforces one-feedback-per-work-order (unique constraint on work_order_id).

		Returns the new CustomerFeedback instance.
		"""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, CustomerFeedback

		if not (1 <= rating <= 5):
			raise FieldServiceValidationError(f"rating must be 1-5, got {rating}")
		if nps_score is not None and not (0 <= nps_score <= 10):
			raise FieldServiceValidationError(f"nps_score must be 0-10, got {nps_score}")

		wo: Any = session.execute(
			sa.select(WorkOrder).where(WorkOrder.id == work_order_id)
		).scalar_one_or_none()
		if wo is None:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id} not found")

		# Reject duplicate — could also rely on the DB unique constraint but a
		# clear error message is friendlier.
		existing: Any = session.execute(
			sa.select(CustomerFeedback).where(CustomerFeedback.work_order_id == work_order_id)
		).scalar_one_or_none()
		if existing is not None:
			raise FieldServiceValidationError(
				f"Feedback already recorded for WorkOrder {work_order_id} (id={existing.id})"
			)

		feedback = CustomerFeedback(
			tenant_id=wo.tenant_id,
			work_order_id=work_order_id,
			rating=rating,
			comments=comments,
			nps_score=nps_score,
			submitted_at=datetime.now(timezone.utc),
		)
		session.add(feedback)
		session.flush()

		log.info("record_customer_feedback: wo=%s rating=%d nps=%s", work_order_id, rating, nps_score)
		return feedback

	# -----------------------------------------------------------------------
	# Dashboard
	# -----------------------------------------------------------------------

	@staticmethod
	def get_service_dashboard(
		session: Any,
		from_date: datetime,
		to_date: datetime,
		territory_id: str | None = None,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Return aggregated service KPIs for a date/territory window.

		Metrics returned:
		  total_work_orders       — all WOs created in window
		  completed_on_time       — COMPLETED WOs where actual_end <= scheduled_end
		  on_time_completion_pct  — completed_on_time / total_completed × 100
		  avg_csat_rating         — mean CustomerFeedback.rating for the window
		  total_revenue_cents     — sum of FSWorkOrderPart.total_cost_cents (proxy for billable revenue)
		  open_work_orders        — WOs still DRAFT|SCHEDULED|IN_PROGRESS at to_date
		  response_breach_count   — WOs with response_breached=True in window
		  resolution_breach_count — WOs with resolution_breached=True in window
		"""
		from pgappforge.plugins.erp.crm.field_service.models import (
			WorkOrder, FSWorkOrderPart, CustomerFeedback, ServiceResource,
		)

		# Base filter predicate for WOs in window
		base_filters = [
			WorkOrder.tenant_id == tenant_id,
			WorkOrder.created_at >= from_date,
			WorkOrder.created_at <= to_date,
		]
		if territory_id:
			# Join through ServiceResource to filter by territory
			resource_ids_in_territory: list[str] = [
				row.id for row in session.execute(
					sa.select(ServiceResource.id).where(
						ServiceResource.territory_id == territory_id,
						ServiceResource.tenant_id == tenant_id,
					)
				).scalars().all()
			]
			base_filters.append(WorkOrder.assigned_to.in_(resource_ids_in_territory))

		total_wo: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(*base_filters)
		).scalar() or 0

		completed_filters = base_filters + [WorkOrder.status == "COMPLETED"]
		total_completed: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(*completed_filters)
		).scalar() or 0

		on_time_filters = completed_filters + [
			WorkOrder.actual_end != None,  # noqa: E711
			WorkOrder.scheduled_end != None,  # noqa: E711
			WorkOrder.actual_end <= WorkOrder.scheduled_end,
		]
		completed_on_time: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(*on_time_filters)
		).scalar() or 0

		on_time_pct: float | None = (
			round(completed_on_time / total_completed * 100, 2) if total_completed > 0 else None
		)

		# Average CSAT — join feedback to work orders in window
		avg_csat_result = session.execute(
			sa.select(sa.func.avg(CustomerFeedback.rating)).select_from(CustomerFeedback).join(
				WorkOrder, WorkOrder.id == CustomerFeedback.work_order_id
			).where(*base_filters)
		).scalar()
		avg_csat: float | None = round(float(avg_csat_result), 2) if avg_csat_result is not None else None

		# Total revenue — sum parts cost for completed WOs in window
		revenue_result = session.execute(
			sa.select(sa.func.coalesce(sa.func.sum(FSWorkOrderPart.total_cost_cents), 0))
			.select_from(FSWorkOrderPart)
			.join(WorkOrder, WorkOrder.id == FSWorkOrderPart.work_order_id)
			.where(*completed_filters)
		).scalar()
		total_revenue_cents: int = int(revenue_result or 0)

		open_wo: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(
				*base_filters,
				WorkOrder.status.in_(("DRAFT", "SCHEDULED", "IN_PROGRESS")),
			)
		).scalar() or 0

		response_breach_count: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(
				*base_filters,
				WorkOrder.response_breached == True,  # noqa: E712
			)
		).scalar() or 0

		resolution_breach_count: int = session.execute(
			sa.select(sa.func.count(WorkOrder.id)).where(
				*base_filters,
				WorkOrder.resolution_breached == True,  # noqa: E712
			)
		).scalar() or 0

		return {
			"from_date": from_date.isoformat(),
			"to_date": to_date.isoformat(),
			"territory_id": territory_id,
			"tenant_id": tenant_id,
			"total_work_orders": total_wo,
			"total_completed": total_completed,
			"completed_on_time": completed_on_time,
			"on_time_completion_pct": on_time_pct,
			"avg_csat_rating": avg_csat,
			"total_revenue_cents": total_revenue_cents,
			"open_work_orders": open_wo,
			"response_breach_count": response_breach_count,
			"resolution_breach_count": resolution_breach_count,
		}

	# -----------------------------------------------------------------------
	# Route optimisation
	# -----------------------------------------------------------------------

	@staticmethod
	def route_optimize(
		session: Any,
		resource_id: str,
		work_date: datetime,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Order a resource's work orders for work_date using nearest-neighbour.

		Nearest-neighbour heuristic: start with the lowest sequence_number (or
		scheduled_start) appointment, then repeatedly pick the unvisited WO
		with the smallest |sequence difference| (proxy for travel distance when
		actual GPS is unavailable).

		If ServiceResource has last_known_lat/lng and WorkOrders carry location
		data, uses Euclidean distance between GeoJSON Point coordinates as the
		proximity metric instead.

		Returns an ordered list of dicts, each containing:
		  sequence, work_order_id, work_order_number, status, scheduled_start,
		  scheduled_end, address, estimated_eta_minutes (cumulative from 08:00)
		"""
		from pgappforge.plugins.erp.crm.field_service.models import WorkOrder, ServiceResource

		resource: Any = session.execute(
			sa.select(ServiceResource).where(
				ServiceResource.id == resource_id,
				ServiceResource.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if resource is None:
			raise ResourceNotFoundError(f"ServiceResource {resource_id} not found")

		# Fetch all WOs assigned to this resource on work_date
		day_start = work_date.replace(hour=0, minute=0, second=0, microsecond=0)
		if day_start.tzinfo is None:
			day_start = day_start.replace(tzinfo=timezone.utc)
		day_end = work_date.replace(hour=23, minute=59, second=59, microsecond=999999)
		if day_end.tzinfo is None:
			day_end = day_end.replace(tzinfo=timezone.utc)

		wos: list[Any] = session.execute(
			sa.select(WorkOrder).where(
				WorkOrder.assigned_to == resource_id,
				WorkOrder.status.in_(("SCHEDULED", "IN_PROGRESS", "DRAFT")),
				WorkOrder.scheduled_start >= day_start,
				WorkOrder.scheduled_start <= day_end,
			).order_by(WorkOrder.scheduled_start)
		).scalars().all()

		if not wos:
			return []

		# Determine whether we can use coordinate-based distance
		def _coords(wo: Any) -> tuple[float, float] | None:
			"""Extract (lat, lng) from WO location (GeoJSON Point or JSONB)."""
			loc = wo.location
			if loc is None:
				return None
			# Geoalchemy2 WKBElement — skip; JSONB GeoJSON path
			if isinstance(loc, dict):
				try:
					coords = loc["coordinates"]  # [lng, lat] per GeoJSON spec
					return float(coords[1]), float(coords[0])
				except (KeyError, IndexError, TypeError):
					return None
			return None

		def _distance(a: tuple[float, float] | None, b: tuple[float, float] | None, idx_a: int, idx_b: int) -> float:
			"""Euclidean distance between coordinate pairs; falls back to index diff."""
			if a and b:
				return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
			return abs(idx_a - idx_b)

		# Nearest-neighbour starting from resource's last known position (index 0)
		unvisited: list[tuple[int, Any]] = list(enumerate(wos))
		ordered: list[tuple[int, Any]] = []

		# Current position: resource GPS if available, else first WO's position
		current_lat = float(resource.last_known_lat) if resource.last_known_lat else None
		current_lng = float(resource.last_known_lng) if resource.last_known_lng else None
		current_coords: tuple[float, float] | None = (current_lat, current_lng) if (current_lat and current_lng) else None
		current_idx = 0

		while unvisited:
			best_dist = float("inf")
			best_entry = unvisited[0]
			for entry in unvisited:
				idx, wo = entry
				wo_coords = _coords(wo)
				d = _distance(current_coords, wo_coords, current_idx, idx)
				if d < best_dist:
					best_dist = d
					best_entry = entry
					best_next_coords = wo_coords
					best_next_idx = idx

			ordered.append(best_entry)
			unvisited.remove(best_entry)
			current_coords = best_next_coords  # type: ignore[possibly-undefined]
			current_idx = best_next_idx  # type: ignore[possibly-undefined]

		# Build output — assume 30 min average travel + scheduled duration per stop
		AVG_TRAVEL_MINUTES = 30
		cumulative_minutes = 0
		result: list[dict[str, Any]] = []

		for seq, (orig_idx, wo) in enumerate(ordered):
			cumulative_minutes += AVG_TRAVEL_MINUTES
			eta_minutes = cumulative_minutes

			# Duration from scheduled window if available
			duration_minutes = 0
			if wo.scheduled_start and wo.scheduled_end:
				ss = wo.scheduled_start
				se = wo.scheduled_end
				if ss.tzinfo is None:
					ss = ss.replace(tzinfo=timezone.utc)
				if se.tzinfo is None:
					se = se.replace(tzinfo=timezone.utc)
				duration_minutes = max(0, int((se - ss).total_seconds() / 60))
			cumulative_minutes += duration_minutes

			result.append({
				"sequence": seq + 1,
				"work_order_id": wo.id,
				"work_order_number": wo.work_order_number,
				"status": wo.status,
				"scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
				"scheduled_end": wo.scheduled_end.isoformat() if wo.scheduled_end else None,
				"address": wo.address,
				"estimated_eta_minutes": eta_minutes,
				"estimated_duration_minutes": duration_minutes,
			})

		log.debug("route_optimize: resource=%s date=%s stops=%d", resource_id, work_date.date(), len(result))
		return result

	# -----------------------------------------------------------------------
	# Contract entitlement
	# -----------------------------------------------------------------------

	@staticmethod
	def check_entitlement(
		session: Any,
		customer_id: str,
		service_type: str,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Check whether a customer is entitled to service under an active contract.

		Looks up the most recent ACTIVE ServiceContract for customer_id that
		covers the requested service_type.  Compares visits_used_this_year
		against max_visits_per_year (NULL = unlimited).

		Returns:
		  entitled          : bool
		  contract_id       : str | None
		  contract_type     : str | None
		  sla_level_name    : str | None
		  max_visits        : int | None  (None means unlimited)
		  visits_used       : int
		  remaining_visits  : int | None  (None means unlimited)
		  service_type_covered : bool
		  reason            : human-readable explanation when not entitled
		"""
		from pgappforge.plugins.erp.crm.field_service.models import ServiceContract, ServiceLevel
		from datetime import date as _date

		today = _date.today()

		# Find the best active contract — prefer highest tier (PLATINUM > GOLD > SILVER)
		tier_order = {"PLATINUM": 0, "GOLD": 1, "SILVER": 2, "CUSTOM": 3}

		contracts: list[Any] = session.execute(
			sa.select(ServiceContract).where(
				ServiceContract.tenant_id == tenant_id,
				ServiceContract.customer_id == customer_id,
				ServiceContract.status == "ACTIVE",
				ServiceContract.start_date <= today,
				ServiceContract.end_date >= today,
			)
		).scalars().all()

		if not contracts:
			return {
				"entitled": False,
				"contract_id": None,
				"contract_type": None,
				"sla_level_name": None,
				"max_visits": None,
				"visits_used": 0,
				"remaining_visits": None,
				"service_type_covered": False,
				"reason": "No active service contract found for this customer",
			}

		# Pick best tier
		contracts.sort(key=lambda c: tier_order.get(c.contract_type, 99))
		contract = contracts[0]

		# Check service type coverage
		covered_types: list[str] = contract.covered_service_types or []
		service_type_covered = service_type in covered_types

		if not service_type_covered:
			return {
				"entitled": False,
				"contract_id": contract.id,
				"contract_type": contract.contract_type,
				"sla_level_name": None,
				"max_visits": contract.max_visits_per_year,
				"visits_used": contract.visits_used_this_year,
				"remaining_visits": None,
				"service_type_covered": False,
				"reason": f"Service type '{service_type}' not covered by contract {contract.id}",
			}

		# Visit quota check
		max_visits: int | None = contract.max_visits_per_year
		visits_used: int = contract.visits_used_this_year or 0
		remaining: int | None = None
		quota_ok = True
		reason = "Entitled"

		if max_visits is not None:
			remaining = max(0, max_visits - visits_used)
			if remaining <= 0:
				quota_ok = False
				reason = f"Visit quota exhausted ({visits_used}/{max_visits} used this year)"
		else:
			remaining = None  # unlimited

		# Resolve SLA level name
		sla_name: str | None = None
		if contract.service_level_id:
			sla: Any = session.execute(
				sa.select(ServiceLevel).where(ServiceLevel.id == contract.service_level_id)
			).scalar_one_or_none()
			if sla:
				sla_name = sla.name

		return {
			"entitled": quota_ok,
			"contract_id": contract.id,
			"contract_type": contract.contract_type,
			"sla_level_name": sla_name,
			"max_visits": max_visits,
			"visits_used": visits_used,
			"remaining_visits": remaining,
			"service_type_covered": service_type_covered,
			"reason": reason,
		}


__all__ = [
	"FieldServiceService",
	"FieldServiceError",
	"WorkOrderNotFoundError",
	"AppointmentNotFoundError",
	"ResourceNotFoundError",
	"FieldServiceValidationError",
]
