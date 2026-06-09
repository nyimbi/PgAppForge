"""
pgappforge/plugins/erp/industry/real_estate/property_management/services.py

PropertyManagementService — stateless business logic for property management.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All amounts stored and returned as integer cents (BigInteger)
  - Escalation rounding uses ROUND_HALF_UP
  - Late fee logic is idempotent per (lease_id, period_month)

Public methods
--------------
  create_unit(property_id, unit_number, tenant_id, session, **kwargs)
  get_rent_roll(property_id, as_of_date, tenant_id, session)
  record_payment(lease_id, amount_cents, payment_date, period_month, tenant_id, session, ...)
  apply_late_fees(property_id, period_month, fee_per_unit_cents, tenant_id, session, ...)
  create_maintenance_request(unit_id, category, description, priority, tenant_id, session, ...)
  assign_work_order(request_id, vendor_id, scheduled_date, quoted_cost_cents, tenant_id, session)
  complete_work_order(work_order_id, actual_cost_cents, tenant_id, session)
  create_move_record(lease_id, move_type, scheduled_date, tenant_id, session, ...)
  complete_move_in(move_record_id, completed_by, tenant_id, session)
  complete_move_out(move_record_id, condition_notes, deposit_returned_cents, completed_by, tenant_id, session)
  offer_renewal(lease_id, new_rent_cents, new_lease_end, tenant_id, session, ...)
  accept_renewal(renewal_id, tenant_id, session)
  apply_escalation(property_id, period_month, tenant_id, session)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)

_HUNDRED = Decimal("100")
_ONE     = Decimal("1")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PropertyManagementError(Exception):
	"""Base domain error for property management operations."""


class UnitNotFoundError(PropertyManagementError):
	pass


class LeaseNotFoundError(PropertyManagementError):
	pass


class WorkOrderNotFoundError(PropertyManagementError):
	pass


class MoveRecordNotFoundError(PropertyManagementError):
	pass


class RenewalNotFoundError(PropertyManagementError):
	pass


class PropertyManagementValidationError(PropertyManagementError):
	pass


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class PropertyManagementService:
	"""Stateless service for property management operations.

	All methods accept an explicit SQLAlchemy *session*; commit/rollback is
	the caller's responsibility.  Monetary values are always integer cents.
	"""

	# ------------------------------------------------------------------
	# Units
	# ------------------------------------------------------------------

	def create_unit(
		self,
		property_id: str,
		unit_number: str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> "PropertyUnit":
		"""Create a new property unit with status VACANT.

		Args:
			property_id: UUID string of the parent re_property row.
			unit_number: Human-readable unit identifier (e.g. "2B", "101").
			tenant_id:   Multi-tenancy scope UUID.
			session:     SQLAlchemy session.
			**kwargs:    Optional column values: floor, sqft, bedrooms, bathrooms.

		Returns:
			Persisted PropertyUnit instance (unflushed — caller flushes/commits).
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import PropertyUnit

		unit = PropertyUnit(
			property_id=property_id,
			unit_number=unit_number,
			tenant_id=tenant_id,
			status="VACANT",
			**{k: v for k, v in kwargs.items() if k in (
				"floor", "sqft", "bedrooms", "bathrooms"
			)},
		)
		session.add(unit)
		log.info("create_unit: property=%s unit=%s", property_id, unit_number)
		return unit

	# ------------------------------------------------------------------
	# Rent roll
	# ------------------------------------------------------------------

	def get_rent_roll(
		self,
		property_id: str,
		as_of_date: date,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return the rent roll for a property as of *as_of_date*.

		Executes a single query: LEFT JOIN pm_tenant_lease + SUM rent payments.

		Returns:
			List of dicts, one per unit, with keys:
			  unit_number, tenant_name, monthly_rent_cents, lease_start,
			  lease_end, days_until_expiry, status, ytd_collected_cents,
			  balance_cents.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			PropertyUnit,
			TenantLease,
			RentPayment,
		)

		year_start = date(as_of_date.year, 1, 1)

		# Subquery: YTD collected per lease
		ytd_sub = (
			sa.select(
				RentPayment.lease_id,
				sa.func.coalesce(
					sa.func.sum(
						sa.case(
							(RentPayment.status.in_(("PAID", "PARTIAL")), RentPayment.amount_cents),
							else_=0,
						)
					),
					0,
				).label("ytd_collected_cents"),
			)
			.where(RentPayment.paid_date >= year_start)
			.where(RentPayment.paid_date <= as_of_date)
			.group_by(RentPayment.lease_id)
			.subquery("ytd")
		)

		# Active lease per unit (most recent ACTIVE lease)
		active_lease_sub = (
			sa.select(
				TenantLease.unit_id,
				sa.func.max(TenantLease.id).label("lease_id"),
			)
			.where(TenantLease.status == "ACTIVE")
			.where(TenantLease.tenant_id == tenant_id)
			.group_by(TenantLease.unit_id)
			.subquery("active_lease")
		)

		rows = session.execute(
			sa.select(
				PropertyUnit.unit_number,
				PropertyUnit.status.label("unit_status"),
				TenantLease.id.label("lease_id"),
				TenantLease.tenant_party_id,
				TenantLease.monthly_rent_cents,
				TenantLease.lease_start,
				TenantLease.lease_end,
				TenantLease.status.label("lease_status"),
				sa.func.coalesce(ytd_sub.c.ytd_collected_cents, 0).label("ytd_collected_cents"),
			)
			.select_from(PropertyUnit)
			.outerjoin(
				active_lease_sub,
				active_lease_sub.c.unit_id == PropertyUnit.id,
			)
			.outerjoin(
				TenantLease,
				TenantLease.id == active_lease_sub.c.lease_id,
			)
			.outerjoin(ytd_sub, ytd_sub.c.lease_id == TenantLease.id)
			.where(PropertyUnit.property_id == property_id)
			.where(PropertyUnit.tenant_id == tenant_id)
			.order_by(PropertyUnit.unit_number)
		).all()

		result = []
		for row in rows:
			lease_end     = row.lease_end
			monthly_rent  = row.monthly_rent_cents or 0
			ytd_collected = row.ytd_collected_cents or 0

			days_until_expiry: int | None = None
			if lease_end is not None:
				days_until_expiry = (lease_end - as_of_date).days

			# balance: expected vs collected for current month
			period = as_of_date.strftime("%Y-%m")
			balance_cents = monthly_rent - ytd_collected if monthly_rent else 0

			result.append({
				"unit_number":         row.unit_number,
				"tenant_name":         str(row.tenant_party_id) if row.tenant_party_id else "",
				"monthly_rent_cents":  monthly_rent,
				"lease_start":         row.lease_start,
				"lease_end":           lease_end,
				"days_until_expiry":   days_until_expiry,
				"status":              row.unit_status,
				"ytd_collected_cents": ytd_collected,
				"balance_cents":       balance_cents,
			})

		return result

	# ------------------------------------------------------------------
	# Payments
	# ------------------------------------------------------------------

	def record_payment(
		self,
		lease_id: str,
		amount_cents: int,
		payment_date: date,
		period_month: str,
		tenant_id: str,
		session: Any,
		*,
		payment_method: str = "CASH",
		reference: str | None = None,
	) -> "RentPayment":
		"""Record a rent payment for a lease period.

		Sets status to PAID if amount_cents >= monthly_rent_cents, else PARTIAL.
		If paid_date > due_date, any existing PENDING payment is marked LATE first.
		Emits RentPaymentReceivedEvent.

		Args:
			lease_id:       UUID of the TenantLease.
			amount_cents:   Amount received in integer cents.
			payment_date:   Date the payment was received.
			period_month:   "YYYY-MM" string for the billing period.
			tenant_id:      Multi-tenancy scope.
			session:        SQLAlchemy session.
			payment_method: One of MPESA/BANK/CASH/CARD.
			reference:      External reference number.

		Returns:
			Persisted RentPayment instance.

		Raises:
			LeaseNotFoundError: If lease_id not found or not ACTIVE.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			RentPayment,
		)
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			RentPaymentReceivedEvent,
			emit_event,
		)

		lease = session.get(TenantLease, lease_id)
		if lease is None or lease.tenant_id != tenant_id:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")

		# Compute due date: 1st of period_month
		year, month = int(period_month[:4]), int(period_month[5:7])
		due_date = date(year, month, 1)

		# Mark any existing PENDING payment for this period as LATE if overdue
		existing_pending = session.execute(
			sa.select(RentPayment).where(
				RentPayment.lease_id == lease_id,
				RentPayment.period_month == period_month,
				RentPayment.status == "PENDING",
			)
		).scalar_one_or_none()

		if existing_pending is not None and payment_date > due_date:
			existing_pending.status = "LATE"

		# Determine new payment status
		if amount_cents >= lease.monthly_rent_cents:
			status = "PAID"
		else:
			status = "PARTIAL"

		payment = RentPayment(
			tenant_id=tenant_id,
			lease_id=lease_id,
			period_month=period_month,
			due_date=due_date,
			paid_date=payment_date,
			amount_cents=amount_cents,
			status=status,
			payment_method=payment_method,
			reference=reference,
		)
		session.add(payment)
		session.flush()

		emit_event(
			RentPaymentReceivedEvent(
				aggregate_id=lease_id,
				aggregate_type="TenantLease",
				tenant_id=tenant_id,
				lease_id=lease_id,
				unit_id=str(lease.unit_id),
				amount_cents=amount_cents,
				period_month=period_month,
			),
			session,
		)

		log.info(
			"record_payment: lease=%s period=%s amount=%d status=%s",
			lease_id, period_month, amount_cents, status,
		)
		return payment

	# ------------------------------------------------------------------
	# Late fees
	# ------------------------------------------------------------------

	def apply_late_fees(
		self,
		property_id: str,
		period_month: str,
		fee_per_unit_cents: int,
		tenant_id: str,
		session: Any,
		*,
		grace_days: int = 5,
	) -> list["LateFeeRecord"]:
		"""Apply late fees for a period across all active leases under a property.

		Idempotent: skips any lease that already has a LateFeeRecord for
		(lease_id, period_month).  Only applies to leases whose payment for the
		period is still PENDING or PARTIAL after grace_days from due_date.

		Emits LateFeeAppliedEvent per fee created.

		Args:
			property_id:        UUID of the parent property.
			period_month:       "YYYY-MM" billing period.
			fee_per_unit_cents: Flat fee amount in integer cents.
			tenant_id:          Multi-tenancy scope.
			session:            SQLAlchemy session.
			grace_days:         Number of days after due_date before fee applies.

		Returns:
			List of created LateFeeRecord instances.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			PropertyUnit,
			TenantLease,
			RentPayment,
			LateFeeRecord,
		)
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			LateFeeAppliedEvent,
			emit_event,
		)

		year, month = int(period_month[:4]), int(period_month[5:7])
		due_date    = date(year, month, 1)
		cutoff_date = due_date + timedelta(days=grace_days)
		today       = date.today()

		if today <= cutoff_date:
			log.info("apply_late_fees: within grace period, no fees applied for %s", period_month)
			return []

		# Active leases under this property
		active_leases = session.execute(
			sa.select(TenantLease)
			.join(PropertyUnit, PropertyUnit.id == TenantLease.unit_id)
			.where(PropertyUnit.property_id == property_id)
			.where(TenantLease.tenant_id == tenant_id)
			.where(TenantLease.status == "ACTIVE")
		).scalars().all()

		created: list[LateFeeRecord] = []

		for lease in active_leases:
			# Idempotency check
			already_exists = session.execute(
				sa.select(LateFeeRecord).where(
					LateFeeRecord.lease_id == lease.id,
					LateFeeRecord.period_month == period_month,
				)
			).scalar_one_or_none()
			if already_exists is not None:
				continue

			# Check payment status for this period
			payment = session.execute(
				sa.select(RentPayment).where(
					RentPayment.lease_id == lease.id,
					RentPayment.period_month == period_month,
					RentPayment.status.in_(("PENDING", "PARTIAL")),
				)
			).scalar_one_or_none()

			if payment is None:
				continue

			fee = LateFeeRecord(
				tenant_id=tenant_id,
				lease_id=lease.id,
				period_month=period_month,
				fee_cents=fee_per_unit_cents,
				applied_at=datetime.now(timezone.utc),
				waived=False,
			)
			session.add(fee)
			session.flush()

			emit_event(
				LateFeeAppliedEvent(
					aggregate_id=lease.id,
					aggregate_type="TenantLease",
					tenant_id=tenant_id,
					lease_id=lease.id,
					fee_cents=fee_per_unit_cents,
					period_month=period_month,
				),
				session,
			)
			created.append(fee)

		log.info(
			"apply_late_fees: property=%s period=%s fees_applied=%d",
			property_id, period_month, len(created),
		)
		return created

	# ------------------------------------------------------------------
	# Maintenance
	# ------------------------------------------------------------------

	def create_maintenance_request(
		self,
		unit_id: str,
		category: str,
		description: str,
		priority: str,
		tenant_id: str,
		session: Any,
		*,
		reported_by: str | None = None,
		photos: list[dict] | None = None,
	) -> "MaintenanceRequest":
		"""Open a new maintenance request for a unit.

		Sets status=OPEN.  Emits MaintenanceRequestCreatedEvent.

		Args:
			unit_id:     UUID of pm_unit.
			category:    One of PLUMBING/ELECTRICAL/HVAC/STRUCTURAL/APPLIANCE/OTHER.
			description: Detailed description of the issue.
			priority:    One of LOW/MEDIUM/HIGH/EMERGENCY.
			tenant_id:   Multi-tenancy scope.
			session:     SQLAlchemy session.
			reported_by: Optional UUID of the reporting user/party.
			photos:      Optional list of {url, caption} dicts.

		Returns:
			Persisted MaintenanceRequest instance.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import MaintenanceRequest
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			MaintenanceRequestCreatedEvent,
			emit_event,
		)

		req = MaintenanceRequest(
			tenant_id=tenant_id,
			unit_id=unit_id,
			reported_by=reported_by,
			category=category,
			description=description,
			priority=priority,
			status="OPEN",
			photos=photos or [],
		)
		session.add(req)
		session.flush()

		emit_event(
			MaintenanceRequestCreatedEvent(
				aggregate_id=req.id,
				aggregate_type="MaintenanceRequest",
				tenant_id=tenant_id,
				request_id=req.id,
				unit_id=unit_id,
				priority=priority,
				category=category,
			),
			session,
		)

		log.info(
			"create_maintenance_request: unit=%s cat=%s pri=%s id=%s",
			unit_id, category, priority, req.id,
		)
		return req

	# ------------------------------------------------------------------
	# Work orders
	# ------------------------------------------------------------------

	def assign_work_order(
		self,
		request_id: str,
		vendor_id: str | None,
		scheduled_date: date | None,
		quoted_cost_cents: int | None,
		tenant_id: str,
		session: Any,
	) -> "WorkOrder":
		"""Create a WorkOrder from a maintenance request and set request to ASSIGNED.

		Args:
			request_id:         UUID of pm_maintenance_request.
			vendor_id:          Optional UUID of the vendor/contractor.
			scheduled_date:     Planned date of work.
			quoted_cost_cents:  Vendor quote in integer cents.
			tenant_id:          Multi-tenancy scope.
			session:            SQLAlchemy session.

		Returns:
			Newly created WorkOrder instance.

		Raises:
			PropertyManagementError: If request_id not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			MaintenanceRequest,
			WorkOrder,
		)

		req = session.get(MaintenanceRequest, request_id)
		if req is None or req.tenant_id != tenant_id:
			raise PropertyManagementError(f"MaintenanceRequest {request_id!r} not found")

		wo = WorkOrder(
			tenant_id=tenant_id,
			request_id=request_id,
			vendor_id=vendor_id,
			work_description=req.description,
			scheduled_date=scheduled_date,
			quoted_cost_cents=quoted_cost_cents,
			status="SCHEDULED" if scheduled_date else "PENDING",
		)
		session.add(wo)

		req.status = "ASSIGNED"
		session.flush()

		log.info("assign_work_order: request=%s vendor=%s wo=%s", request_id, vendor_id, wo.id)
		return wo

	def complete_work_order(
		self,
		work_order_id: str,
		actual_cost_cents: int,
		tenant_id: str,
		session: Any,
	) -> "WorkOrder":
		"""Mark a work order COMPLETED and resolve the parent maintenance request.

		Sets WorkOrder.status=COMPLETED, records actual_cost_cents.
		Sets MaintenanceRequest.status=RESOLVED and actual_cost_cents.
		Emits WorkOrderCompletedEvent.

		Args:
			work_order_id:     UUID of pm_work_order.
			actual_cost_cents: Final cost in integer cents.
			tenant_id:         Multi-tenancy scope.
			session:           SQLAlchemy session.

		Returns:
			Updated WorkOrder instance.

		Raises:
			WorkOrderNotFoundError: If work_order_id not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import WorkOrder
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			WorkOrderCompletedEvent,
			emit_event,
		)

		wo = session.get(WorkOrder, work_order_id)
		if wo is None or wo.tenant_id != tenant_id:
			raise WorkOrderNotFoundError(f"WorkOrder {work_order_id!r} not found")

		wo.status            = "COMPLETED"
		wo.actual_cost_cents = actual_cost_cents
		wo.completed_date    = date.today()

		# Resolve the parent maintenance request
		req = session.get(wo.__class__.__mapper__.relationships["request"].mapper.class_, wo.request_id)
		if req is not None:
			req.status             = "RESOLVED"
			req.actual_cost_cents  = actual_cost_cents
			req.resolved_at        = datetime.now(timezone.utc)

		session.flush()

		emit_event(
			WorkOrderCompletedEvent(
				aggregate_id=work_order_id,
				aggregate_type="WorkOrder",
				tenant_id=tenant_id,
				work_order_id=work_order_id,
				actual_cost_cents=actual_cost_cents,
			),
			session,
		)

		log.info("complete_work_order: wo=%s cost=%d", work_order_id, actual_cost_cents)
		return wo

	# ------------------------------------------------------------------
	# Move records
	# ------------------------------------------------------------------

	def create_move_record(
		self,
		lease_id: str,
		move_type: str,
		scheduled_date: date,
		tenant_id: str,
		session: Any,
		*,
		checklist_items: list[dict] | None = None,
	) -> "MoveRecord":
		"""Create a move-in or move-out record for a lease.

		Args:
			lease_id:         UUID of pm_tenant_lease.
			move_type:        "IN" or "OUT".
			scheduled_date:   Planned date of the move.
			tenant_id:        Multi-tenancy scope.
			session:          SQLAlchemy session.
			checklist_items:  Optional list of {item, checked, notes} dicts.

		Returns:
			Created MoveRecord instance.

		Raises:
			LeaseNotFoundError: If lease_id not found.
			PropertyManagementValidationError: If move_type not in (IN, OUT).
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			MoveRecord,
		)

		if move_type not in ("IN", "OUT"):
			raise PropertyManagementValidationError(f"move_type must be IN or OUT, got {move_type!r}")

		lease = session.get(TenantLease, lease_id)
		if lease is None or lease.tenant_id != tenant_id:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")

		record = MoveRecord(
			tenant_id=tenant_id,
			lease_id=lease_id,
			move_type=move_type,
			scheduled_date=scheduled_date,
			checklist=checklist_items or [],
		)
		session.add(record)
		log.info("create_move_record: lease=%s type=%s scheduled=%s", lease_id, move_type, scheduled_date)
		return record

	def complete_move_in(
		self,
		move_record_id: str,
		completed_by: str,
		tenant_id: str,
		session: Any,
	) -> "MoveRecord":
		"""Complete a move-in: activate lease and mark unit OCCUPIED.

		Sets MoveRecord.completed_date, TenantLease.status=ACTIVE,
		PropertyUnit.status=OCCUPIED.  Emits TenantMoveInEvent.

		Args:
			move_record_id: UUID of pm_move_record.
			completed_by:   UUID of the user completing the move-in.
			tenant_id:      Multi-tenancy scope.
			session:        SQLAlchemy session.

		Returns:
			Updated MoveRecord instance.

		Raises:
			MoveRecordNotFoundError: If move_record_id not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			PropertyUnit,
			MoveRecord,
		)
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			TenantMoveInEvent,
			emit_event,
		)

		record = session.get(MoveRecord, move_record_id)
		if record is None or record.tenant_id != tenant_id:
			raise MoveRecordNotFoundError(f"MoveRecord {move_record_id!r} not found")

		record.completed_date = date.today()
		record.completed_by   = completed_by

		lease = session.get(TenantLease, record.lease_id)
		if lease is not None:
			lease.status = "ACTIVE"
			unit = session.get(PropertyUnit, lease.unit_id)
			if unit is not None:
				unit.status = "OCCUPIED"
			unit_id = str(lease.unit_id)
		else:
			unit_id = ""

		session.flush()

		emit_event(
			TenantMoveInEvent(
				aggregate_id=record.lease_id,
				aggregate_type="TenantLease",
				tenant_id=tenant_id,
				lease_id=record.lease_id,
				unit_id=unit_id,
			),
			session,
		)

		log.info("complete_move_in: record=%s lease=%s", move_record_id, record.lease_id)
		return record

	def complete_move_out(
		self,
		move_record_id: str,
		condition_notes: str,
		deposit_returned_cents: int | None,
		completed_by: str,
		tenant_id: str,
		session: Any,
	) -> "MoveRecord":
		"""Complete a move-out: terminate lease and mark unit VACANT.

		Sets completed_date, TenantLease.status=TERMINATED,
		PropertyUnit.status=VACANT.  Emits TenantMoveOutEvent.

		Args:
			move_record_id:          UUID of pm_move_record.
			condition_notes:         Notes on unit condition at departure.
			deposit_returned_cents:  Security deposit returned in integer cents (or None).
			completed_by:            UUID of the user completing the move-out.
			tenant_id:               Multi-tenancy scope.
			session:                 SQLAlchemy session.

		Returns:
			Updated MoveRecord instance.

		Raises:
			MoveRecordNotFoundError: If move_record_id not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			PropertyUnit,
			MoveRecord,
		)
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			TenantMoveOutEvent,
			emit_event,
		)

		record = session.get(MoveRecord, move_record_id)
		if record is None or record.tenant_id != tenant_id:
			raise MoveRecordNotFoundError(f"MoveRecord {move_record_id!r} not found")

		record.completed_date                    = date.today()
		record.completed_by                      = completed_by
		record.condition_notes                   = condition_notes
		record.security_deposit_returned_cents   = deposit_returned_cents

		lease = session.get(TenantLease, record.lease_id)
		if lease is not None:
			lease.status = "TERMINATED"
			unit = session.get(PropertyUnit, lease.unit_id)
			if unit is not None:
				unit.status = "VACANT"
			unit_id = str(lease.unit_id)
		else:
			unit_id = ""

		session.flush()

		emit_event(
			TenantMoveOutEvent(
				aggregate_id=record.lease_id,
				aggregate_type="TenantLease",
				tenant_id=tenant_id,
				lease_id=record.lease_id,
				unit_id=unit_id,
			),
			session,
		)

		log.info("complete_move_out: record=%s lease=%s", move_record_id, record.lease_id)
		return record

	# ------------------------------------------------------------------
	# Lease renewal
	# ------------------------------------------------------------------

	def offer_renewal(
		self,
		lease_id: str,
		new_rent_cents: int,
		new_lease_end: date | None,
		tenant_id: str,
		session: Any,
		*,
		days_valid: int = 30,
	) -> "LeaseRenewalOffer":
		"""Create a renewal offer for a lease.

		Sets expires_at = now + days_valid days.

		Args:
			lease_id:       UUID of the current TenantLease.
			new_rent_cents: Proposed new monthly rent in integer cents.
			new_lease_end:  Proposed new lease end date (None = month-to-month).
			tenant_id:      Multi-tenancy scope.
			session:        SQLAlchemy session.
			days_valid:     Number of days the offer remains valid (default 30).

		Returns:
			Created LeaseRenewalOffer instance.

		Raises:
			LeaseNotFoundError: If lease_id not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			LeaseRenewalOffer,
		)

		lease = session.get(TenantLease, lease_id)
		if lease is None or lease.tenant_id != tenant_id:
			raise LeaseNotFoundError(f"Lease {lease_id!r} not found")

		now        = datetime.now(timezone.utc)
		expires_at = now + timedelta(days=days_valid)

		# New lease start: day after current lease_end or today
		new_lease_start = (
			lease.lease_end + timedelta(days=1) if lease.lease_end else date.today()
		)

		offer = LeaseRenewalOffer(
			tenant_id=tenant_id,
			lease_id=lease_id,
			new_rent_cents=new_rent_cents,
			new_lease_start=new_lease_start,
			new_lease_end=new_lease_end,
			offered_at=now,
			expires_at=expires_at,
			status="SENT",
		)
		session.add(offer)
		log.info("offer_renewal: lease=%s new_rent=%d expires=%s", lease_id, new_rent_cents, expires_at.date())
		return offer

	def accept_renewal(
		self,
		renewal_id: str,
		tenant_id: str,
		session: Any,
	) -> "TenantLease":
		"""Accept a renewal offer: create a new lease and terminate the old one.

		Emits LeaseRenewalAcceptedEvent.

		Args:
			renewal_id:  UUID of pm_lease_renewal.
			tenant_id:   Multi-tenancy scope.
			session:     SQLAlchemy session.

		Returns:
			Newly created TenantLease instance.

		Raises:
			RenewalNotFoundError: If renewal_id not found or already actioned.
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			TenantLease,
			LeaseRenewalOffer,
		)
		from pgappforge.plugins.erp.industry.real_estate.property_management.events import (
			LeaseRenewalAcceptedEvent,
			emit_event,
		)

		offer = session.get(LeaseRenewalOffer, renewal_id)
		if offer is None or offer.tenant_id != tenant_id:
			raise RenewalNotFoundError(f"LeaseRenewalOffer {renewal_id!r} not found")
		if offer.status != "SENT":
			raise PropertyManagementValidationError(
				f"Renewal offer {renewal_id!r} has status {offer.status!r}, cannot accept"
			)

		old_lease = session.get(TenantLease, offer.lease_id)
		if old_lease is None:
			raise LeaseNotFoundError(f"Lease {offer.lease_id!r} not found")

		# Terminate the old lease
		old_lease.status = "TERMINATED"

		# Create new lease carrying over key attributes from the old one
		new_lease = TenantLease(
			tenant_id=tenant_id,
			unit_id=old_lease.unit_id,
			tenant_party_id=old_lease.tenant_party_id,
			landlord_id=old_lease.landlord_id,
			lease_start=offer.new_lease_start,
			lease_end=offer.new_lease_end,
			monthly_rent_cents=offer.new_rent_cents,
			security_deposit_cents=old_lease.security_deposit_cents,
			lease_type="FIXED" if offer.new_lease_end else "MONTH_TO_MONTH",
			escalation_type=old_lease.escalation_type,
			escalation_pct=old_lease.escalation_pct,
			status="ACTIVE",
			renewal_option=old_lease.renewal_option,
		)
		session.add(new_lease)

		offer.status = "ACCEPTED"
		session.flush()

		new_lease_end_str = offer.new_lease_end.isoformat() if offer.new_lease_end else ""

		emit_event(
			LeaseRenewalAcceptedEvent(
				aggregate_id=offer.lease_id,
				aggregate_type="TenantLease",
				tenant_id=tenant_id,
				lease_id=offer.lease_id,
				new_rent_cents=offer.new_rent_cents,
				new_lease_end=new_lease_end_str,
			),
			session,
		)

		log.info(
			"accept_renewal: old_lease=%s new_lease=%s new_rent=%d",
			offer.lease_id, new_lease.id, offer.new_rent_cents,
		)
		return new_lease

	# ------------------------------------------------------------------
	# Escalation
	# ------------------------------------------------------------------

	def apply_escalation(
		self,
		property_id: str,
		period_month: str,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Apply rent escalation to all eligible active leases under a property.

		Escalation types:
		  FIXED_PCT: new_rent = current_rent * (1 + escalation_pct / 100), ROUND_HALF_UP.
		  CPI:       reads RE_CPI_PCT from Flask app config (default 3.0), same formula.
		  NONE:      skipped.

		Args:
			property_id:  UUID of the parent property.
			period_month: "YYYY-MM" — for logging/audit only (not stored on lease).
			tenant_id:    Multi-tenancy scope.
			session:      SQLAlchemy session.

		Returns:
			List of dicts: [{lease_id, old_rent_cents, new_rent_cents}].
		"""
		from pgappforge.plugins.erp.industry.real_estate.property_management.models import (
			PropertyUnit,
			TenantLease,
		)

		# Attempt to read CPI from Flask config; fall back to 3.0
		cpi_pct = Decimal("3.0")
		try:
			from flask import current_app
			cpi_pct = Decimal(str(current_app.config.get("RE_CPI_PCT", "3.0")))
		except RuntimeError:
			pass

		leases = session.execute(
			sa.select(TenantLease)
			.join(PropertyUnit, PropertyUnit.id == TenantLease.unit_id)
			.where(PropertyUnit.property_id == property_id)
			.where(TenantLease.tenant_id == tenant_id)
			.where(TenantLease.status == "ACTIVE")
			.where(TenantLease.escalation_type != "NONE")
		).scalars().all()

		results: list[dict] = []

		for lease in leases:
			old_rent = Decimal(str(lease.monthly_rent_cents))

			if lease.escalation_type == "FIXED_PCT":
				pct = Decimal(str(lease.escalation_pct or "0"))
			elif lease.escalation_type == "CPI":
				pct = cpi_pct
			else:
				continue

			multiplier = _ONE + pct / _HUNDRED
			new_rent   = int((old_rent * multiplier).to_integral_value(ROUND_HALF_UP))

			lease.monthly_rent_cents = new_rent

			results.append({
				"lease_id":       lease.id,
				"old_rent_cents": int(old_rent),
				"new_rent_cents": new_rent,
			})

		log.info(
			"apply_escalation: property=%s period=%s leases_updated=%d",
			property_id, period_month, len(results),
		)
		return results


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("pm.create_unit", "Create a property unit")
def _bpm_create_unit(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	unit_number: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		svc  = PropertyManagementService()
		unit = svc.create_unit(property_id, unit_number, tenant_id, session, **kw)
		session.flush()
		return {"status": "ok", "unit_id": unit.id}
	except Exception as exc:
		log.exception("BPM pm.create_unit failed")
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("pm.record_payment", "Record rent payment")
def _bpm_record_payment(
	record_ctx: dict,
	session: Any,
	lease_id: str = "",
	amount_cents: int = 0,
	payment_date: str = "",
	period_month: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from datetime import date as _date
		pd = _date.fromisoformat(payment_date) if payment_date else _date.today()
		svc     = PropertyManagementService()
		payment = svc.record_payment(lease_id, amount_cents, pd, period_month, tenant_id, session, **kw)
		session.flush()
		return {"status": "ok", "payment_id": payment.id, "payment_status": payment.status}
	except Exception as exc:
		log.exception("BPM pm.record_payment failed")
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("pm.apply_late_fees", "Apply late fees for a period")
def _bpm_apply_late_fees(
	record_ctx: dict,
	session: Any,
	property_id: str = "",
	period_month: str = "",
	fee_per_unit_cents: int = 0,
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		svc   = PropertyManagementService()
		fees  = svc.apply_late_fees(property_id, period_month, fee_per_unit_cents, tenant_id, session, **kw)
		session.flush()
		return {"status": "ok", "fees_applied": len(fees)}
	except Exception as exc:
		log.exception("BPM pm.apply_late_fees failed")
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register("pm.create_maintenance_request", "Log a maintenance request")
def _bpm_create_maintenance_request(
	record_ctx: dict,
	session: Any,
	unit_id: str = "",
	category: str = "OTHER",
	description: str = "",
	priority: str = "MEDIUM",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		svc = PropertyManagementService()
		req = svc.create_maintenance_request(unit_id, category, description, priority, tenant_id, session, **kw)
		session.flush()
		return {"status": "ok", "request_id": req.id}
	except Exception as exc:
		log.exception("BPM pm.create_maintenance_request failed")
		return {"status": "error", "message": str(exc)}


__all__ = [
	"PropertyManagementService",
	"PropertyManagementError",
	"UnitNotFoundError",
	"LeaseNotFoundError",
	"WorkOrderNotFoundError",
	"MoveRecordNotFoundError",
	"RenewalNotFoundError",
	"PropertyManagementValidationError",
]
