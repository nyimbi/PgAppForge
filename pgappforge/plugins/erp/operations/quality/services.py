"""
pgappforge/plugins/erp/operations/quality/services.py

Business logic layer for the Quality Management plugin.

Stateless service class.
All monetary values as integer cents.
Quantities as Decimal — never float.
Session passed explicitly; never committed inside service methods.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class QCServiceError(Exception):
	"""Base error for QC service layer."""


class InspectionPlanNotFoundError(QCServiceError):
	pass


class InspectionNotFoundError(QCServiceError):
	pass


class NCRNotFoundError(QCServiceError):
	pass


class InvalidStatusTransitionError(QCServiceError):
	pass


# ---------------------------------------------------------------------------
# QCService
# ---------------------------------------------------------------------------

class QCService:
	"""Stateless Quality Management service."""

	# ------------------------------------------------------------------
	# Inspection plan lookup
	# ------------------------------------------------------------------

	def get_active_plan(
		self,
		product_id: str,
		inspection_type: str,
		tenant_id: str,
		session: Any,
	) -> Any | None:
		"""Return the active InspectionPlan for a product and inspection type."""
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan

		return session.execute(
			sa.select(InspectionPlan).where(
				InspectionPlan.product_id == product_id,
				InspectionPlan.inspection_type == inspection_type,
				InspectionPlan.tenant_id == tenant_id,
				InspectionPlan.is_active == True,
			).limit(1)
		).scalar_one_or_none()

	def compute_sample_quantity(
		self,
		plan_id: str,
		lot_quantity: Decimal,
		session: Any,
	) -> Decimal:
		"""Compute sample quantity from plan's sampling_pct.

		Returns ceiling of lot_quantity * sampling_pct / 100,
		minimum 1 unit.
		"""
		from pgappforge.plugins.erp.operations.quality.models import InspectionPlan

		plan = session.get(InspectionPlan, plan_id)
		if plan is None:
			raise InspectionPlanNotFoundError(f"InspectionPlan {plan_id!r} not found")

		pct = Decimal(str(plan.sampling_pct))
		raw = lot_quantity * pct / Decimal("100")
		sample = raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
		return max(sample, Decimal("1"))

	# ------------------------------------------------------------------
	# Inspection lifecycle
	# ------------------------------------------------------------------

	def create_inspection(
		self,
		reference_type: str,
		reference_id: str,
		product_id: str,
		tenant_id: str,
		lot_quantity: Decimal,
		inspection_date: date,
		inspector_id: str | None,
		session: Any,
		inspection_type: str = "INCOMING",
	) -> Any:
		"""Create a QualityInspection, computing sample qty from active plan.

		If no active plan exists, creates an ad-hoc 100% inspection.
		Emits InspectionCreatedEvent.
		"""
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		from pgappforge.plugins.erp.operations.quality.events import InspectionCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		plan = self.get_active_plan(product_id, inspection_type, tenant_id, session)

		if plan is not None:
			sample_qty = self.compute_sample_quantity(plan.id, lot_quantity, session)
			plan_id = plan.id
		else:
			sample_qty = lot_quantity  # 100% inspection for ad-hoc
			plan_id = None

		insp = QualityInspection(
			tenant_id=tenant_id,
			reference_type=reference_type,
			reference_id=reference_id,
			plan_id=plan_id,
			inspected_quantity=sample_qty,
			accepted_quantity=Decimal("0"),
			rejected_quantity=Decimal("0"),
			inspector_id=inspector_id,
			inspection_date=inspection_date,
			status="PENDING",
		)
		session.add(insp)
		session.flush()

		emit_event(
			InspectionCreatedEvent(
				aggregate_id=insp.id,
				aggregate_type="QualityInspection",
				tenant_id=tenant_id,
				inspection_id=insp.id,
				reference_type=reference_type,
				reference_id=reference_id,
				product_id=product_id,
				inspection_type=inspection_type,
				inspector_id=inspector_id or "",
				inspection_date=inspection_date.isoformat(),
			),
			session,
		)
		return insp

	def record_results(
		self,
		inspection_id: str,
		accepted_quantity: Decimal,
		rejected_quantity: Decimal,
		findings: list[dict[str, Any]],
		disposition: str,
		session: Any,
	) -> Any:
		"""Record inspection results and transition to PASSED or FAILED.

		accepted_quantity + rejected_quantity must equal inspected_quantity.
		disposition: ACCEPT | REJECT | REWORK | USE_AS_IS

		Emits InspectionPassedEvent or InspectionFailedEvent.
		If FAILED, automatically creates an NCR if plan.acceptance_criteria
		includes "auto_ncr": true.
		"""
		from pgappforge.plugins.erp.operations.quality.models import QualityInspection
		from pgappforge.plugins.erp.operations.quality.events import (
			InspectionPassedEvent,
			InspectionFailedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		insp = session.get(QualityInspection, inspection_id)
		if insp is None:
			raise InspectionNotFoundError(f"QualityInspection {inspection_id!r} not found")
		if insp.status not in ("PENDING", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"Inspection already in terminal status {insp.status!r}"
			)

		insp.accepted_quantity = accepted_quantity
		insp.rejected_quantity = rejected_quantity
		insp.findings = findings
		insp.disposition = disposition
		insp.updated_at = datetime.now(timezone.utc)

		# Determine pass/fail: any rejected quantity or REJECT disposition = FAILED
		passed = rejected_quantity == Decimal("0") and disposition != "REJECT"
		insp.status = "PASSED" if passed else "FAILED"
		insp.overall_result = "PASS" if passed else "FAIL"

		# Determine product_id from plan or reference (best-effort)
		product_id = ""
		if insp.plan:
			product_id = insp.plan.product_id

		failure_summary = ""
		if not passed:
			failing = [f for f in findings if f.get("result") == "FAIL"]
			failure_summary = "; ".join(f.get("criterion", "") for f in failing)

		if passed:
			emit_event(
				InspectionPassedEvent(
					aggregate_id=inspection_id,
					aggregate_type="QualityInspection",
					tenant_id=insp.tenant_id,
					inspection_id=inspection_id,
					reference_type=insp.reference_type,
					reference_id=insp.reference_id,
					product_id=product_id,
					accepted_quantity=str(accepted_quantity),
					rejected_quantity=str(rejected_quantity),
					disposition=disposition,
				),
				session,
			)
		else:
			emit_event(
				InspectionFailedEvent(
					aggregate_id=inspection_id,
					aggregate_type="QualityInspection",
					tenant_id=insp.tenant_id,
					inspection_id=inspection_id,
					reference_type=insp.reference_type,
					reference_id=insp.reference_id,
					product_id=product_id,
					accepted_quantity=str(accepted_quantity),
					rejected_quantity=str(rejected_quantity),
					failure_summary=failure_summary,
				),
				session,
			)
			# Auto-NCR if plan dictates it
			if insp.plan and insp.plan.acceptance_criteria.get("auto_ncr"):
				self.open_ncr(
					tenant_id=insp.tenant_id,
					source_type="PRODUCTION" if insp.reference_type == "ProductionOrder" else "SUPPLIER",
					source_reference_id=insp.reference_id,
					inspection_id=inspection_id,
					product_id=product_id,
					quantity_affected=rejected_quantity,
					uom="EA",
					description=f"Auto-NCR from inspection {inspection_id}: {failure_summary}",
					severity="MAJOR",
					session=session,
				)

		return insp

	# ------------------------------------------------------------------
	# NCR lifecycle
	# ------------------------------------------------------------------

	def open_ncr(
		self,
		tenant_id: str,
		source_type: str,
		source_reference_id: str | None,
		inspection_id: str | None,
		product_id: str,
		quantity_affected: Decimal,
		uom: str,
		description: str,
		severity: str,
		session: Any,
		owner_id: str | None = None,
		due_date: date | None = None,
		supplier_id: str | None = None,
	) -> Any:
		"""Create and open a NonConformanceReport. Emits NCROpenedEvent."""
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		from pgappforge.plugins.erp.operations.quality.events import NCROpenedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		# Generate NCR number: NCR-YYYYMMDD-HHMMSS
		ts = datetime.now(timezone.utc)
		ncr_number = f"NCR-{ts.strftime('%Y%m%d-%H%M%S')}"

		ncr = NonConformanceReport(
			tenant_id=tenant_id,
			ncr_number=ncr_number,
			source_type=source_type,
			source_reference_id=source_reference_id,
			inspection_id=inspection_id,
			product_id=product_id,
			quantity_affected=quantity_affected,
			uom=uom,
			description=description,
			severity=severity,
			status="OPEN",
			owner_id=owner_id,
			due_date=due_date,
			supplier_id=supplier_id,
		)
		session.add(ncr)
		session.flush()

		emit_event(
			NCROpenedEvent(
				aggregate_id=ncr.id,
				aggregate_type="NonConformanceReport",
				tenant_id=tenant_id,
				ncr_id=ncr.id,
				ncr_number=ncr_number,
				product_id=product_id,
				source_type=source_type,
				severity=severity,
				quantity_affected=str(quantity_affected),
				owner_id=owner_id or "",
				due_date=due_date.isoformat() if due_date else "",
			),
			session,
		)
		return ncr

	def advance_ncr(
		self,
		ncr_id: str,
		new_status: str,
		updated_by: str,
		session: Any,
		root_cause: str | None = None,
		corrective_action: str | None = None,
		preventive_action: str | None = None,
	) -> Any:
		"""Advance NCR through its status machine with CAPA data.

		Transitions: OPEN → ANALYSIS → CORRECTION → CLOSED
		Emits the appropriate status event.
		"""
		from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
		from pgappforge.plugins.erp.operations.quality.events import (
			NCRAnalysisStartedEvent,
			NCRCorrectionIssuedEvent,
			NCRClosedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		_TRANSITIONS = {
			"OPEN": "ANALYSIS",
			"ANALYSIS": "CORRECTION",
			"CORRECTION": "CLOSED",
		}

		ncr = session.get(NonConformanceReport, ncr_id)
		if ncr is None:
			raise NCRNotFoundError(f"NonConformanceReport {ncr_id!r} not found")

		expected_next = _TRANSITIONS.get(ncr.status)
		if expected_next is None or new_status != expected_next:
			raise InvalidStatusTransitionError(
				f"NCR status {ncr.status!r} → {new_status!r} is not a valid transition"
			)

		if root_cause is not None:
			ncr.root_cause = root_cause
		if corrective_action is not None:
			ncr.corrective_action = corrective_action
		if preventive_action is not None:
			ncr.preventive_action = preventive_action

		ncr.status = new_status
		ncr.updated_at = datetime.now(timezone.utc)

		if new_status == "ANALYSIS":
			emit_event(
				NCRAnalysisStartedEvent(
					aggregate_id=ncr_id,
					aggregate_type="NonConformanceReport",
					tenant_id=ncr.tenant_id,
					ncr_id=ncr_id,
					ncr_number=ncr.ncr_number,
					owner_id=ncr.owner_id or "",
				),
				session,
			)
		elif new_status == "CORRECTION":
			emit_event(
				NCRCorrectionIssuedEvent(
					aggregate_id=ncr_id,
					aggregate_type="NonConformanceReport",
					tenant_id=ncr.tenant_id,
					ncr_id=ncr_id,
					ncr_number=ncr.ncr_number,
					corrective_action=ncr.corrective_action or "",
					preventive_action=ncr.preventive_action or "",
					owner_id=ncr.owner_id or "",
				),
				session,
			)
		elif new_status == "CLOSED":
			ncr.closed_at = datetime.now(timezone.utc)
			ncr.closed_by = updated_by
			emit_event(
				NCRClosedEvent(
					aggregate_id=ncr_id,
					aggregate_type="NonConformanceReport",
					tenant_id=ncr.tenant_id,
					ncr_id=ncr_id,
					ncr_number=ncr.ncr_number,
					closed_by=updated_by,
					root_cause=ncr.root_cause or "",
				),
				session,
			)

		return ncr


__all__ = [
	"QCService",
	"QCServiceError",
	"InspectionPlanNotFoundError",
	"InspectionNotFoundError",
	"NCRNotFoundError",
	"InvalidStatusTransitionError",
]
