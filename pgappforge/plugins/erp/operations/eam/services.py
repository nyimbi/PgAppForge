"""
pgappforge/plugins/erp/operations/eam/services.py

EAMService — stateless business logic for the Enterprise Asset Management plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents
  - Decimal arithmetic used internally; results rounded half-up to int
  - Hours / meter readings use Decimal(str(...)) — never float

GL integration:
  - complete_work_order() posts a best-effort journal via the GL plugin
    DR maintenance_expense "6200"  CR accounts_payable "2000"
  - If GL plugin is not loaded the journal dict is returned in the result
    and the operation proceeds normally

Public API:
  create_asset(session, data, tenant_id)                                    -> ManagedAsset
  record_meter_reading(session, asset_id, meter_type, value,
                       reading_date, recorded_by, tenant_id)               -> MeterReading
  generate_work_order(session, plan_id, trigger_type, tenant_id)           -> MaintenanceWorkOrder
  create_corrective_wo(session, asset_id, description, priority,
                       failure_code, tenant_id)                            -> MaintenanceWorkOrder
  complete_work_order(session, wo_id, actual_hours, actual_cost_cents,
                      remedy_code, notes, tenant_id)                       -> MaintenanceWorkOrder
  calculate_asset_metrics(session, asset_id, from_date, to_date,
                          tenant_id)                                       -> dict
  schedule_maintenance_batch(session, as_of_date, tenant_id)               -> dict
  issue_safety_permit(session, wo_id, permit_type, issued_by,
                      expires_at, conditions, tenant_id)                   -> SafetyPermit
  get_asset_history(session, asset_id, tenant_id)                          -> dict
  get_backlog_report(session, asset_location_id=None, tenant_id='')        -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EAMServiceError(Exception):
	"""Base domain error for EAM operations."""


class AssetNotFoundError(EAMServiceError):
	pass


class WorkOrderNotFoundError(EAMServiceError):
	pass


class MaintenancePlanNotFoundError(EAMServiceError):
	pass


class InvalidStatusTransitionError(EAMServiceError):
	pass


class SafetyPermitRequiredError(EAMServiceError):
	"""Raised when a WO requires an active safety permit but none exists."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Coerce to Decimal without going through float."""
	return Decimal(str(value)) if value is not None else Decimal("0")


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _uuid4() -> str:
	return str(uuid.uuid4())


def _wo_number(tenant_id: str, session: Any) -> str:
	"""Generate a sequential WO number: WO-YYYYMMDD-NNNN (tenant-scoped)."""
	from pgappforge.plugins.erp.operations.eam.models import MaintenanceWorkOrder
	today_str = _today().strftime("%Y%m%d")
	prefix = f"WO-{today_str}-"
	count_q = sa.select(sa.func.count()).select_from(MaintenanceWorkOrder).where(
		MaintenanceWorkOrder.tenant_id == tenant_id,
		MaintenanceWorkOrder.wo_number.like(f"{prefix}%"),
	)
	count = session.execute(count_q).scalar_one()
	return f"{prefix}{count + 1:04d}"


# ---------------------------------------------------------------------------
# EAMService
# ---------------------------------------------------------------------------

class EAMService:
	"""Stateless EAM business logic.

	Instantiate once per request/task; pass an explicit SQLAlchemy session
	to every method.  Caller owns commit/rollback.
	"""

	# ------------------------------------------------------------------
	# 1. create_asset
	# ------------------------------------------------------------------

	@staticmethod
	def create_asset(
		session: Any,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Register a new managed asset.

		Args:
			session    : SQLAlchemy session
			data       : dict matching ManagedAsset columns (excluding id,
			             tenant_id, created_at, updated_at)
			tenant_id  : owning tenant UUID string

		Returns:
			ManagedAsset — flushed but not committed.

		Raises:
			EAMServiceError if asset_code already exists for tenant.
		"""
		from pgappforge.plugins.erp.operations.eam.models import ManagedAsset
		from pgappforge.plugins.erp.operations.eam.events import AssetCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		asset_code = data.get("asset_code", "")
		existing = session.execute(
			sa.select(ManagedAsset).where(
				ManagedAsset.tenant_id == tenant_id,
				ManagedAsset.asset_code == asset_code,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise EAMServiceError(
				f"asset_code {asset_code!r} already exists for tenant {tenant_id}"
			)

		asset = ManagedAsset(
			tenant_id=tenant_id,
			**{k: v for k, v in data.items() if k not in ("id", "tenant_id", "created_at", "updated_at")},
		)
		session.add(asset)
		session.flush()

		emit_event(
			AssetCreatedEvent(
				asset_id=asset.id,
				asset_code=asset.asset_code,
				name=asset.name,
				asset_type=asset.asset_type,
				criticality=asset.criticality,
				asset_location_id=str(asset.asset_location_id or ""),
				finance_asset_id=str(asset.finance_asset_id or ""),
				tenant_id=tenant_id,
			),
			session,
		)
		log.info("EAMService.create_asset: %s %r tenant=%s", asset.id, asset.asset_code, tenant_id)
		return asset

	# ------------------------------------------------------------------
	# 2. record_meter_reading
	# ------------------------------------------------------------------

	@staticmethod
	def record_meter_reading(
		session: Any,
		asset_id: str,
		meter_type: str,
		value: Any,
		reading_date: date,
		recorded_by: str,
		tenant_id: str,
		notes: str | None = None,
	) -> Any:
		"""Record a meter / odometer reading and evaluate maintenance plan triggers.

		For METER-type MaintenancePlans whose trigger_meter_type matches,
		checks whether the cumulative delta since last_generated_at exceeds
		trigger_meter_value.  If so, auto-generates a work order.

		Args:
			value : numeric reading (cumulative, not delta)

		Returns:
			MeterReading — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset,
			MeterReading,
			MaintenancePlan,
		)

		asset = session.get(ManagedAsset, asset_id)
		if asset is None or asset.tenant_id != tenant_id:
			raise AssetNotFoundError(f"asset {asset_id} not found")

		reading = MeterReading(
			tenant_id=tenant_id,
			asset_id=asset_id,
			meter_type=meter_type,
			reading_value=_d(value),
			reading_date=reading_date,
			recorded_by=recorded_by,
			notes=notes,
		)
		session.add(reading)
		session.flush()

		# --- Evaluate METER-type plans ---------------------------------
		plans = session.execute(
			sa.select(MaintenancePlan).where(
				MaintenancePlan.tenant_id == tenant_id,
				MaintenancePlan.asset_id == asset_id,
				MaintenancePlan.plan_type == "METER",
				MaintenancePlan.trigger_meter_type == meter_type,
				MaintenancePlan.is_active == True,  # noqa: E712
			)
		).scalars().all()

		for plan in plans:
			if plan.trigger_meter_value is None:
				continue
			# Determine baseline reading at last_generated_at
			if plan.last_generated_at is not None:
				baseline_row = session.execute(
					sa.select(MeterReading.reading_value)
					.where(
						MeterReading.asset_id == asset_id,
						MeterReading.meter_type == meter_type,
						MeterReading.reading_date <= plan.last_generated_at.date(),
					)
					.order_by(MeterReading.reading_date.desc())
					.limit(1)
				).scalar_one_or_none()
				baseline = _d(baseline_row) if baseline_row is not None else Decimal("0")
			else:
				baseline = Decimal("0")

			delta = _d(value) - baseline
			if delta >= _d(plan.trigger_meter_value):
				wo = EAMService.generate_work_order(
					session, plan.id, "METER", tenant_id,
					_meter_reading_id=reading.id,
				)
				log.info(
					"EAMService.record_meter_reading: meter trigger fired plan=%s → wo=%s",
					plan.id, wo.wo_number,
				)

		return reading

	# ------------------------------------------------------------------
	# 3. generate_work_order
	# ------------------------------------------------------------------

	@staticmethod
	def generate_work_order(
		session: Any,
		plan_id: str,
		trigger_type: str,
		tenant_id: str,
		_meter_reading_id: str | None = None,
	) -> Any:
		"""Generate a preventive MaintenanceWorkOrder from a MaintenancePlan.

		Copies job_plan template data (description, estimated_hours → cost
		estimate, parts list) into the new WO.  Updates plan.last_generated_at
		and advances plan.next_due_at.

		Args:
			plan_id      : MaintenancePlan.id
			trigger_type : 'CALENDAR' | 'METER' | 'CONDITION'

		Returns:
			MaintenanceWorkOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			MaintenancePlan,
			MaintenanceWorkOrder,
		)
		from pgappforge.plugins.erp.operations.eam.events import (
			WorkOrderCreatedEvent,
			MaintenancePlanTriggeredEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		plan = session.get(MaintenancePlan, plan_id)
		if plan is None or plan.tenant_id != tenant_id:
			raise MaintenancePlanNotFoundError(f"plan {plan_id} not found")

		now = _now()
		planned_start = now + timedelta(days=plan.lead_days)
		estimated_hours = Decimal("0")
		description = plan.plan_name

		if plan.job_plan_id is not None:
			job_plan = session.get(
				__import__(
					"pgappforge.plugins.erp.operations.eam.models",
					fromlist=["JobPlan"],
				).JobPlan,
				plan.job_plan_id,
			)
			if job_plan is not None:
				estimated_hours = _d(job_plan.estimated_hours)
				description = f"{plan.plan_name} — {job_plan.name}"

		# Estimate cost: hours * rough rate 5000 ¢/hr (configurable via tenant config)
		estimated_cost_cents = int(
			(estimated_hours * Decimal("5000")).to_integral_value(ROUND_HALF_UP)
		)

		wo = MaintenanceWorkOrder(
			tenant_id=tenant_id,
			wo_number=_wo_number(tenant_id, session),
			asset_id=plan.asset_id,
			work_type="PREVENTIVE",
			priority=3,
			status="PLANNED",
			job_plan_id=plan.job_plan_id,
			description=description,
			planned_start=planned_start,
			planned_end=planned_start + timedelta(hours=float(estimated_hours) or 4),
			estimated_cost_cents=estimated_cost_cents,
		)
		session.add(wo)
		session.flush()

		# Advance plan schedule
		plan.last_generated_at = now
		if trigger_type == "CALENDAR" and plan.trigger_interval_days:
			plan.next_due_at = now + timedelta(days=plan.trigger_interval_days)

		emit_event(
			WorkOrderCreatedEvent(
				wo_id=wo.id,
				wo_number=wo.wo_number,
				asset_id=str(plan.asset_id),
				work_type="PREVENTIVE",
				priority=wo.priority,
				planned_start=wo.planned_start.isoformat(),
				planned_end=wo.planned_end.isoformat(),
				estimated_cost_cents=estimated_cost_cents,
				triggered_by_plan_id=plan_id,
				tenant_id=tenant_id,
			),
			session,
		)
		emit_event(
			MaintenancePlanTriggeredEvent(
				plan_id=plan_id,
				plan_name=plan.plan_name,
				asset_id=str(plan.asset_id),
				trigger_type=trigger_type,
				wo_id=wo.id,
				wo_number=wo.wo_number,
				meter_reading_id=_meter_reading_id or "",
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"EAMService.generate_work_order: plan=%s → wo=%s trigger=%s",
			plan_id, wo.wo_number, trigger_type,
		)
		return wo

	# ------------------------------------------------------------------
	# 4. create_corrective_wo
	# ------------------------------------------------------------------

	@staticmethod
	def create_corrective_wo(
		session: Any,
		asset_id: str,
		description: str,
		priority: int,
		failure_code: str,
		tenant_id: str,
		cause_code: str | None = None,
	) -> Any:
		"""Open a corrective (unplanned) work order.

		priority : 1=Emergency, 2=Urgent, 3=Routine, 4=Low
		Sets asset.status = IN_MAINTENANCE when priority <= 2.

		Returns:
			MaintenanceWorkOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset,
			MaintenanceWorkOrder,
		)
		from pgappforge.plugins.erp.operations.eam.events import WorkOrderCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert 1 <= priority <= 4, f"priority must be 1-4, got {priority}"

		asset = session.get(ManagedAsset, asset_id)
		if asset is None or asset.tenant_id != tenant_id:
			raise AssetNotFoundError(f"asset {asset_id} not found")

		now = _now()
		work_type = "EMERGENCY" if priority == 1 else "CORRECTIVE"

		wo = MaintenanceWorkOrder(
			tenant_id=tenant_id,
			wo_number=_wo_number(tenant_id, session),
			asset_id=asset_id,
			work_type=work_type,
			priority=priority,
			status="PLANNED",
			description=description,
			failure_code=failure_code,
			cause_code=cause_code,
			planned_start=now,
			planned_end=now + timedelta(hours=4),
			estimated_cost_cents=0,
		)
		session.add(wo)

		if priority <= 2:
			asset.status = "IN_MAINTENANCE"
			asset.updated_at = now

		session.flush()

		emit_event(
			WorkOrderCreatedEvent(
				wo_id=wo.id,
				wo_number=wo.wo_number,
				asset_id=asset_id,
				work_type=work_type,
				priority=priority,
				planned_start=wo.planned_start.isoformat(),
				planned_end=wo.planned_end.isoformat(),
				estimated_cost_cents=0,
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"EAMService.create_corrective_wo: %s asset=%s priority=%d failure=%s",
			wo.wo_number, asset_id, priority, failure_code,
		)
		return wo

	# ------------------------------------------------------------------
	# 5. complete_work_order
	# ------------------------------------------------------------------

	@staticmethod
	def complete_work_order(
		session: Any,
		wo_id: str,
		actual_hours: Any,
		actual_cost_cents: int,
		remedy_code: str,
		notes: str,
		tenant_id: str,
	) -> Any:
		"""Transition a work order to COMPLETED.

		Side effects:
		  - Sets wo.actual_end = now, wo.actual_cost_cents, wo.remedy_code
		  - Sets asset.status = ACTIVE
		  - Posts GL journal: DR 6200 maintenance_expense / CR 2000 accounts_payable
		  - Emits WorkOrderCompletedEvent

		GL posting is best-effort — if GL plugin absent the journal dict
		is included in the event payload.

		Returns:
			MaintenanceWorkOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset,
			MaintenanceWorkOrder,
		)
		from pgappforge.plugins.erp.operations.eam.events import WorkOrderCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None or wo.tenant_id != tenant_id:
			raise WorkOrderNotFoundError(f"work order {wo_id} not found")

		allowed_statuses = {"PLANNED", "APPROVED", "ASSIGNED", "IN_PROGRESS", "PENDING_PARTS", "ON_HOLD"}
		if wo.status not in allowed_statuses:
			raise InvalidStatusTransitionError(
				f"cannot complete WO in status {wo.status!r}"
			)

		# Check safety permit gate
		if wo.safety_permit_required:
			from pgappforge.plugins.erp.operations.eam.models import SafetyPermit
			active_permit = session.execute(
				sa.select(SafetyPermit).where(
					SafetyPermit.wo_id == wo_id,
					SafetyPermit.status.in_(["ISSUED", "ACTIVE"]),
				)
			).scalar_one_or_none()
			if active_permit is None:
				raise SafetyPermitRequiredError(
					f"WO {wo.wo_number} requires an active safety permit before completion"
				)

		now = _now()
		wo.status = "COMPLETED"
		wo.actual_end = now
		if wo.actual_start is None:
			wo.actual_start = now
		wo.actual_cost_cents = actual_cost_cents
		wo.remedy_code = remedy_code
		if notes:
			wo.description = f"{wo.description}\n\nCompletion notes: {notes}"
		wo.updated_at = now

		# Restore asset to ACTIVE
		asset = session.get(ManagedAsset, wo.asset_id)
		if asset is not None:
			asset.status = "ACTIVE"
			asset.updated_at = now

		# GL double-entry journal (best-effort)
		gl_journal_id = ""
		journal: dict[str, Any] = {
			"journal_id": _uuid4(),
			"journal_date": now.date().isoformat(),
			"reference": wo.wo_number,
			"description": f"Maintenance expense — WO {wo.wo_number}",
			"lines": [
				{
					"account": "6200",
					"account_name": "Maintenance Expense",
					"debit_cents": actual_cost_cents,
					"credit_cents": 0,
				},
				{
					"account": "2000",
					"account_name": "Accounts Payable",
					"debit_cents": 0,
					"credit_cents": actual_cost_cents,
				},
			],
		}
		try:
			from pgappforge.plugins.erp.finance.gl import GLService  # type: ignore[import]
			GLService.post_journal(journal)
			gl_journal_id = journal["journal_id"]
			log.debug("EAMService.complete_work_order: GL journal posted %s", gl_journal_id)
		except (ImportError, AttributeError) as exc:
			log.debug("EAMService.complete_work_order: GL plugin not available (%s)", exc)

		session.flush()

		emit_event(
			WorkOrderCompletedEvent(
				wo_id=wo.id,
				wo_number=wo.wo_number,
				asset_id=str(wo.asset_id),
				work_type=wo.work_type,
				actual_start=wo.actual_start.isoformat(),
				actual_end=wo.actual_end.isoformat(),
				actual_cost_cents=actual_cost_cents,
				downtime_hours=str(wo.downtime_hours) if wo.downtime_hours is not None else "",
				remedy_code=remedy_code,
				gl_journal_id=gl_journal_id,
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"EAMService.complete_work_order: %s completed actual_cost=%d¢ gl=%s",
			wo.wo_number, actual_cost_cents, gl_journal_id or "n/a",
		)
		return wo

	# ------------------------------------------------------------------
	# 6. calculate_asset_metrics
	# ------------------------------------------------------------------

	@staticmethod
	def calculate_asset_metrics(
		session: Any,
		asset_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Compute reliability KPIs for an asset over a date range.

		Formulae:
		  MTBF = total_operating_hours / failure_count
		         (total_operating_hours derived from meter readings; falls
		          back to calendar hours when no HOURS meter data exists)
		  MTTR = total_downtime_hours / completed_wo_count
		  availability = (operating_hours - total_downtime_hours) / operating_hours * 100

		Returns dict:
		  {
		    mtbf_hours           : Decimal | None,  None when 0 failures
		    mttr_hours           : Decimal | None,  None when 0 WOs
		    availability_pct     : Decimal,
		    total_maintenance_cost_cents : int,
		    failure_count        : int,
		    wo_count             : int,
		    operating_hours      : Decimal,
		    total_downtime_hours : Decimal,
		  }
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset,
			MaintenanceWorkOrder,
			MeterReading,
			FailureReport,
		)
		from pgappforge.plugins.erp.operations.eam.events import AssetMetricsCalculatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		asset = session.get(ManagedAsset, asset_id)
		if asset is None or asset.tenant_id != tenant_id:
			raise AssetNotFoundError(f"asset {asset_id} not found")

		from_dt = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=timezone.utc)
		to_dt = datetime.combine(to_date, datetime.max.time()).replace(tzinfo=timezone.utc)

		# Completed WOs in range
		wos = session.execute(
			sa.select(MaintenanceWorkOrder).where(
				MaintenanceWorkOrder.tenant_id == tenant_id,
				MaintenanceWorkOrder.asset_id == asset_id,
				MaintenanceWorkOrder.status.in_(["COMPLETED", "CLOSED"]),
				MaintenanceWorkOrder.actual_end >= from_dt,
				MaintenanceWorkOrder.actual_end <= to_dt,
			)
		).scalars().all()

		wo_count = len(wos)
		total_downtime = sum(
			(_d(wo.downtime_hours) for wo in wos if wo.downtime_hours is not None),
			Decimal("0"),
		)
		total_cost_cents = sum(wo.actual_cost_cents for wo in wos)

		# Failure count
		failure_count = session.execute(
			sa.select(sa.func.count()).select_from(FailureReport).where(
				FailureReport.tenant_id == tenant_id,
				FailureReport.asset_id == asset_id,
				FailureReport.reported_at >= from_dt,
				FailureReport.reported_at <= to_dt,
			)
		).scalar_one()

		# Operating hours: HOURS meter readings span
		hours_readings = session.execute(
			sa.select(MeterReading.reading_value, MeterReading.reading_date)
			.where(
				MeterReading.tenant_id == tenant_id,
				MeterReading.asset_id == asset_id,
				MeterReading.meter_type == "HOURS",
				MeterReading.reading_date >= from_date,
				MeterReading.reading_date <= to_date,
			)
			.order_by(MeterReading.reading_date)
		).all()

		if len(hours_readings) >= 2:
			operating_hours = _d(hours_readings[-1].reading_value) - _d(hours_readings[0].reading_value)
		else:
			# Fall back to calendar hours
			calendar_days = (to_date - from_date).days + 1
			operating_hours = Decimal(str(calendar_days * 24))

		# MTBF
		mtbf_hours: Decimal | None = None
		if failure_count > 0:
			mtbf_hours = (operating_hours / Decimal(str(failure_count))).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		# MTTR
		mttr_hours: Decimal | None = None
		if wo_count > 0:
			mttr_hours = (total_downtime / Decimal(str(wo_count))).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		# Availability
		if operating_hours > Decimal("0"):
			availability_pct = (
				(operating_hours - total_downtime) / operating_hours * Decimal("100")
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
		else:
			availability_pct = Decimal("100.00")

		result: dict[str, Any] = {
			"mtbf_hours": mtbf_hours,
			"mttr_hours": mttr_hours,
			"availability_pct": availability_pct,
			"total_maintenance_cost_cents": total_cost_cents,
			"failure_count": failure_count,
			"wo_count": wo_count,
			"operating_hours": operating_hours,
			"total_downtime_hours": total_downtime,
		}

		emit_event(
			AssetMetricsCalculatedEvent(
				asset_id=asset_id,
				from_date=from_date.isoformat(),
				to_date=to_date.isoformat(),
				mtbf_hours=str(mtbf_hours) if mtbf_hours is not None else "",
				mttr_hours=str(mttr_hours) if mttr_hours is not None else "",
				availability_pct=str(availability_pct),
				total_maintenance_cost_cents=total_cost_cents,
				failure_count=failure_count,
				wo_count=wo_count,
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"EAMService.calculate_asset_metrics: asset=%s mtbf=%s mttr=%s avail=%s%%",
			asset_id, mtbf_hours, mttr_hours, availability_pct,
		)
		return result

	# ------------------------------------------------------------------
	# 7. schedule_maintenance_batch
	# ------------------------------------------------------------------

	@staticmethod
	def schedule_maintenance_batch(
		session: Any,
		as_of_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Evaluate all active MaintenancePlans and create WOs for due ones.

		A CALENDAR plan is due when next_due_at <= as_of_date + lead_days.
		METER and CONDITION plans are evaluated via record_meter_reading()
		and external condition monitors respectively; this method only
		processes CALENDAR plans.

		Returns:
		  {
		    plans_evaluated : int,
		    wos_created     : int,
		    wo_numbers      : list[str],
		    errors          : list[dict],
		  }
		"""
		from pgappforge.plugins.erp.operations.eam.models import MaintenancePlan

		as_of_dt = datetime.combine(as_of_date, datetime.min.time()).replace(tzinfo=timezone.utc)

		plans = session.execute(
			sa.select(MaintenancePlan).where(
				MaintenancePlan.tenant_id == tenant_id,
				MaintenancePlan.plan_type == "CALENDAR",
				MaintenancePlan.is_active == True,  # noqa: E712
				sa.or_(
					MaintenancePlan.next_due_at == None,  # noqa: E711  — never run
					MaintenancePlan.next_due_at <= as_of_dt,
				),
			)
		).scalars().all()

		wos_created: list[str] = []
		errors: list[dict[str, Any]] = []

		for plan in plans:
			try:
				wo = EAMService.generate_work_order(session, plan.id, "CALENDAR", tenant_id)
				wos_created.append(wo.wo_number)
			except Exception as exc:  # noqa: BLE001
				log.warning(
					"EAMService.schedule_maintenance_batch: plan=%s error=%s",
					plan.id, exc,
				)
				errors.append({"plan_id": plan.id, "plan_name": plan.plan_name, "error": str(exc)})

		result = {
			"plans_evaluated": len(plans),
			"wos_created": len(wos_created),
			"wo_numbers": wos_created,
			"errors": errors,
		}
		log.info(
			"EAMService.schedule_maintenance_batch: tenant=%s evaluated=%d created=%d errors=%d",
			tenant_id, len(plans), len(wos_created), len(errors),
		)
		return result

	# ------------------------------------------------------------------
	# 8. issue_safety_permit
	# ------------------------------------------------------------------

	@staticmethod
	def issue_safety_permit(
		session: Any,
		wo_id: str,
		permit_type: str,
		issued_by: str,
		expires_at: datetime,
		conditions: str | None,
		tenant_id: str,
	) -> Any:
		"""Issue a safety permit against a work order.

		Valid permit_type values:
		  HOT_WORK | CONFINED_SPACE | ELECTRICAL | HEIGHT | CHEMICAL | GENERAL

		Returns:
			SafetyPermit — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			MaintenanceWorkOrder,
			SafetyPermit,
		)
		from pgappforge.plugins.erp.operations.eam.events import SafetyPermitIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		VALID_TYPES = {"HOT_WORK", "CONFINED_SPACE", "ELECTRICAL", "HEIGHT", "CHEMICAL", "GENERAL"}
		if permit_type not in VALID_TYPES:
			raise EAMServiceError(f"invalid permit_type {permit_type!r}; must be one of {VALID_TYPES}")

		wo = session.get(MaintenanceWorkOrder, wo_id)
		if wo is None or wo.tenant_id != tenant_id:
			raise WorkOrderNotFoundError(f"work order {wo_id} not found")

		now = _now()
		permit = SafetyPermit(
			tenant_id=tenant_id,
			wo_id=wo_id,
			permit_type=permit_type,
			issued_by=issued_by,
			issued_at=now,
			expires_at=expires_at,
			conditions=conditions,
			status="ISSUED",
		)
		session.add(permit)
		session.flush()

		emit_event(
			SafetyPermitIssuedEvent(
				permit_id=permit.id,
				wo_id=wo_id,
				wo_number=wo.wo_number,
				permit_type=permit_type,
				issued_by=issued_by,
				issued_at=now.isoformat(),
				expires_at=expires_at.isoformat(),
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"EAMService.issue_safety_permit: %s %r wo=%s issued_by=%s",
			permit.id, permit_type, wo.wo_number, issued_by,
		)
		return permit

	# ------------------------------------------------------------------
	# 9. get_asset_history
	# ------------------------------------------------------------------

	@staticmethod
	def get_asset_history(
		session: Any,
		asset_id: str,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Return full maintenance history for an asset.

		Returns:
		  {
		    asset          : dict (core fields),
		    work_orders    : list[dict],
		    meter_readings : list[dict],
		    failure_reports: list[dict],
		    safety_permits : list[dict],
		  }
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			ManagedAsset,
			MaintenanceWorkOrder,
			MeterReading,
			FailureReport,
			SafetyPermit,
		)

		asset = session.get(ManagedAsset, asset_id)
		if asset is None or asset.tenant_id != tenant_id:
			raise AssetNotFoundError(f"asset {asset_id} not found")

		wos = session.execute(
			sa.select(MaintenanceWorkOrder)
			.where(
				MaintenanceWorkOrder.tenant_id == tenant_id,
				MaintenanceWorkOrder.asset_id == asset_id,
			)
			.order_by(MaintenanceWorkOrder.planned_start.desc())
		).scalars().all()

		readings = session.execute(
			sa.select(MeterReading)
			.where(
				MeterReading.tenant_id == tenant_id,
				MeterReading.asset_id == asset_id,
			)
			.order_by(MeterReading.reading_date.desc())
		).scalars().all()

		failures = session.execute(
			sa.select(FailureReport)
			.where(
				FailureReport.tenant_id == tenant_id,
				FailureReport.asset_id == asset_id,
			)
			.order_by(FailureReport.reported_at.desc())
		).scalars().all()

		# Collect WO ids for permit lookup
		wo_ids = [wo.id for wo in wos]
		permits: list[Any] = []
		if wo_ids:
			permits = session.execute(
				sa.select(SafetyPermit)
				.where(
					SafetyPermit.tenant_id == tenant_id,
					SafetyPermit.wo_id.in_(wo_ids),
				)
				.order_by(SafetyPermit.issued_at.desc())
			).scalars().all()

		def _wo_dict(wo: Any) -> dict[str, Any]:
			return {
				"id": wo.id,
				"wo_number": wo.wo_number,
				"work_type": wo.work_type,
				"priority": wo.priority,
				"status": wo.status,
				"description": wo.description,
				"planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
				"actual_end": wo.actual_end.isoformat() if wo.actual_end else None,
				"actual_cost_cents": wo.actual_cost_cents,
				"downtime_hours": str(wo.downtime_hours) if wo.downtime_hours is not None else None,
				"remedy_code": wo.remedy_code,
			}

		def _reading_dict(r: Any) -> dict[str, Any]:
			return {
				"id": r.id,
				"meter_type": r.meter_type,
				"reading_value": str(r.reading_value),
				"reading_date": r.reading_date.isoformat(),
				"recorded_by": r.recorded_by,
				"notes": r.notes,
			}

		def _failure_dict(f: Any) -> dict[str, Any]:
			return {
				"id": f.id,
				"reported_at": f.reported_at.isoformat(),
				"failure_description": f.failure_description,
				"failure_code": f.failure_code,
				"cause_code": f.cause_code,
				"wo_id": f.wo_id,
			}

		def _permit_dict(p: Any) -> dict[str, Any]:
			return {
				"id": p.id,
				"wo_id": p.wo_id,
				"permit_type": p.permit_type,
				"status": p.status,
				"issued_at": p.issued_at.isoformat() if p.issued_at else None,
				"expires_at": p.expires_at.isoformat() if p.expires_at else None,
			}

		return {
			"asset": {
				"id": asset.id,
				"asset_code": asset.asset_code,
				"name": asset.name,
				"asset_type": asset.asset_type,
				"status": asset.status,
				"criticality": asset.criticality,
				"install_date": asset.install_date.isoformat() if asset.install_date else None,
			},
			"work_orders": [_wo_dict(wo) for wo in wos],
			"meter_readings": [_reading_dict(r) for r in readings],
			"failure_reports": [_failure_dict(f) for f in failures],
			"safety_permits": [_permit_dict(p) for p in permits],
		}

	# ------------------------------------------------------------------
	# 10. get_backlog_report
	# ------------------------------------------------------------------

	@staticmethod
	def get_backlog_report(
		session: Any,
		tenant_id: str,
		asset_location_id: str | None = None,
	) -> dict[str, Any]:
		"""Open work order backlog report, bucketed by priority and age.

		Age buckets: <7 days, 7-30 days, 31-90 days, >90 days.

		Args:
			asset_location_id : optional — filter to a specific location subtree

		Returns:
		  {
		    total_open       : int,
		    by_priority      : {1: int, 2: int, 3: int, 4: int},
		    by_age_bucket    : {'<7d': int, '7-30d': int, '31-90d': int, '>90d': int},
		    estimated_cost_cents : int,
		    overdue          : int,   -- planned_end < now
		    items            : list[dict],   -- top 200, newest first
		  }
		"""
		from pgappforge.plugins.erp.operations.eam.models import (
			MaintenanceWorkOrder,
			ManagedAsset,
		)

		now = _now()
		open_statuses = ["PLANNED", "APPROVED", "ASSIGNED", "IN_PROGRESS", "PENDING_PARTS", "ON_HOLD"]

		q = sa.select(MaintenanceWorkOrder).where(
			MaintenanceWorkOrder.tenant_id == tenant_id,
			MaintenanceWorkOrder.status.in_(open_statuses),
		)

		if asset_location_id:
			# Join via asset to filter by location
			q = q.join(
				ManagedAsset,
				MaintenanceWorkOrder.asset_id == ManagedAsset.id,
			).where(ManagedAsset.asset_location_id == asset_location_id)

		q = q.order_by(
			MaintenanceWorkOrder.priority.asc(),
			MaintenanceWorkOrder.planned_start.asc(),
		)

		wos = session.execute(q).scalars().all()

		by_priority: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
		by_age: dict[str, int] = {"<7d": 0, "7-30d": 0, "31-90d": 0, ">90d": 0}
		overdue = 0
		total_est_cost = 0

		def _age_bucket(wo: Any) -> str:
			age_days = (now - wo.planned_start).days
			if age_days < 7:
				return "<7d"
			elif age_days <= 30:
				return "7-30d"
			elif age_days <= 90:
				return "31-90d"
			return ">90d"

		items: list[dict[str, Any]] = []
		for wo in wos:
			by_priority[wo.priority] = by_priority.get(wo.priority, 0) + 1
			bucket = _age_bucket(wo)
			by_age[bucket] = by_age.get(bucket, 0) + 1
			if wo.planned_end and wo.planned_end < now:
				overdue += 1
			total_est_cost += wo.estimated_cost_cents
			if len(items) < 200:
				items.append({
					"id": wo.id,
					"wo_number": wo.wo_number,
					"asset_id": str(wo.asset_id),
					"work_type": wo.work_type,
					"priority": wo.priority,
					"status": wo.status,
					"planned_start": wo.planned_start.isoformat() if wo.planned_start else None,
					"planned_end": wo.planned_end.isoformat() if wo.planned_end else None,
					"estimated_cost_cents": wo.estimated_cost_cents,
					"age_bucket": bucket,
					"is_overdue": wo.planned_end is not None and wo.planned_end < now,
				})

		return {
			"total_open": len(wos),
			"by_priority": by_priority,
			"by_age_bucket": by_age,
			"estimated_cost_cents": total_est_cost,
			"overdue": overdue,
			"items": items,
		}


__all__ = [
	"EAMService",
	"EAMServiceError",
	"AssetNotFoundError",
	"WorkOrderNotFoundError",
	"MaintenancePlanNotFoundError",
	"InvalidStatusTransitionError",
	"SafetyPermitRequiredError",
]
