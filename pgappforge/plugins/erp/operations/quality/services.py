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


	# ------------------------------------------------------------------
	# InspectionLot lifecycle
	# ------------------------------------------------------------------

	def create_inspection_lot(
		self,
		session: Any,
		product_code: str,
		quantity: Decimal,
		source_type: str,
		source_ref_id: str,
		plan_id: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Create an InspectionLot in CREATED status.

		Generates lot_number as LOT-YYYYMMDD-HHMMSS-<6hex>.
		Links to InspectionPlan when plan_id is supplied.
		"""
		from pgappforge.plugins.erp.operations.quality.models import InspectionLot
		import secrets

		ts = datetime.now(timezone.utc)
		lot_number = f"LOT-{ts.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"

		lot = InspectionLot(
			tenant_id=tenant_id,
			lot_number=lot_number,
			source_type=source_type,
			source_ref_id=source_ref_id,
			product_code=product_code,
			quantity=quantity,
			plan_id=plan_id,
			status="CREATED",
			inspected_qty=Decimal("0"),
			accepted_qty=Decimal("0"),
			rejected_qty=Decimal("0"),
		)
		session.add(lot)
		session.flush()
		log.debug("QCService.create_inspection_lot: created %s for product=%s qty=%s", lot_number, product_code, quantity)
		return lot

	def record_inspection_result(
		self,
		session: Any,
		lot_id: str,
		characteristic_name: str,
		value: Decimal | None,
		inspector_id: str,
		tenant_id: str,
	) -> Any:
		"""Record a single characteristic measurement against an InspectionLot.

		Auto-checks measurement_value against USL/LSL from the lot's
		InspectionPlan characteristics list.  Sets out_of_spec and pass_fail
		accordingly.  Updates lot.inspected_qty / accepted_qty / rejected_qty.

		Plan characteristics schema:
		  [{"name": "...", "type": "VARIABLE|ATTRIBUTE", "usl": ..., "lsl": ..., ...}]
		"""
		from pgappforge.plugins.erp.operations.quality.models import InspectionLot, InspectionResult

		lot = session.get(InspectionLot, lot_id)
		if lot is None:
			raise InspectionNotFoundError(f"InspectionLot {lot_id!r} not found")

		# Lazy-transition to IN_INSPECTION on first result
		if lot.status == "CREATED":
			lot.status = "IN_INSPECTION"
			lot.inspector_id = inspector_id
			lot.started_at = datetime.now(timezone.utc)

		# Determine pass/fail from plan characteristics
		pass_fail = "NA"
		out_of_spec = False

		if value is not None and lot.plan is not None:
			chars: list[dict[str, Any]] = lot.plan.acceptance_criteria.get("characteristics", [])
			char_def = next((c for c in chars if c.get("name") == characteristic_name), None)
			if char_def:
				usl = char_def.get("usl")
				lsl = char_def.get("lsl")
				v = value
				too_high = usl is not None and v > Decimal(str(usl))
				too_low = lsl is not None and v < Decimal(str(lsl))
				if too_high or too_low:
					out_of_spec = True
					pass_fail = "FAIL"
				else:
					pass_fail = "PASS"
			else:
				# Characteristic not in plan — record measurement, result NA
				pass_fail = "NA"
		elif value is not None:
			# No plan: can't auto-evaluate; default PASS (inspector responsible)
			pass_fail = "PASS"

		result = InspectionResult(
			tenant_id=tenant_id,
			lot_id=lot_id,
			characteristic_name=characteristic_name,
			measurement_value=value,
			pass_fail=pass_fail,
			out_of_spec=out_of_spec,
		)
		session.add(result)

		# Update running tallies
		lot.inspected_qty = Decimal(str(lot.inspected_qty)) + Decimal("1")
		if pass_fail == "PASS":
			lot.accepted_qty = Decimal(str(lot.accepted_qty)) + Decimal("1")
		elif pass_fail == "FAIL":
			lot.rejected_qty = Decimal(str(lot.rejected_qty)) + Decimal("1")
		lot.updated_at = datetime.now(timezone.utc)

		session.flush()
		return result

	def complete_inspection(
		self,
		session: Any,
		lot_id: str,
		tenant_id: str,
	) -> Any:
		"""Finalise an InspectionLot and determine PASSED or FAILED.

		Pass criterion:
		  If the linked plan has sampling_pct (used as AQL acceptance rate here):
		    pass_rate_pct = accepted_qty / inspected_qty * 100
		    PASSED when pass_rate_pct >= plan.sampling_pct (re-purposed as AQL threshold)
		  If no plan or no results: status → PASSED by default.

		Emits InspectionPassedEvent or InspectionFailedEvent.
		"""
		from pgappforge.plugins.erp.operations.quality.models import InspectionLot
		from pgappforge.plugins.erp.operations.quality.events import (
			InspectionPassedEvent,
			InspectionFailedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		lot = session.get(InspectionLot, lot_id)
		if lot is None:
			raise InspectionNotFoundError(f"InspectionLot {lot_id!r} not found")
		if lot.status not in ("CREATED", "IN_INSPECTION"):
			raise InvalidStatusTransitionError(
				f"Cannot complete lot in status {lot.status!r}"
			)

		inspected = Decimal(str(lot.inspected_qty))
		accepted = Decimal(str(lot.accepted_qty))

		if inspected > Decimal("0"):
			pass_rate = (accepted / inspected * Decimal("100")).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)
		else:
			pass_rate = Decimal("100")

		# AQL threshold from plan.sampling_pct (repurposed as minimum pass rate)
		aql_threshold = Decimal("100")
		if lot.plan is not None:
			aql_threshold = Decimal(str(lot.plan.sampling_pct))

		passed = pass_rate >= aql_threshold
		lot.status = "PASSED" if passed else "FAILED"
		lot.completed_at = datetime.now(timezone.utc)
		lot.updated_at = datetime.now(timezone.utc)

		if passed:
			emit_event(
				InspectionPassedEvent(
					aggregate_id=lot_id,
					aggregate_type="InspectionLot",
					tenant_id=tenant_id,
					inspection_id=lot_id,
					reference_type="InspectionLot",
					reference_id=lot_id,
					product_id=lot.product_code,
					accepted_quantity=str(accepted),
					rejected_quantity=str(lot.rejected_qty),
					disposition="ACCEPT",
				),
				session,
			)
		else:
			emit_event(
				InspectionFailedEvent(
					aggregate_id=lot_id,
					aggregate_type="InspectionLot",
					tenant_id=tenant_id,
					inspection_id=lot_id,
					reference_type="InspectionLot",
					reference_id=lot_id,
					product_id=lot.product_code,
					accepted_quantity=str(accepted),
					rejected_quantity=str(lot.rejected_qty),
					failure_summary=f"pass_rate={pass_rate}% < aql={aql_threshold}%",
				),
				session,
			)

		session.flush()
		return lot

	def raise_ncr(
		self,
		session: Any,
		lot_id: str,
		description: str,
		severity: str,
		raised_by: str,
		tenant_id: str,
	) -> Any:
		"""Raise a structured NCR against an InspectionLot.

		Generates ncr_number as NCRV2-YYYYMMDD-HHMMSS.
		Severity must be one of: CRITICAL | MAJOR | MINOR.
		"""
		from pgappforge.plugins.erp.operations.quality.models import InspectionLot, NCR

		lot = session.get(InspectionLot, lot_id)
		if lot is None:
			raise InspectionNotFoundError(f"InspectionLot {lot_id!r} not found")

		ts = datetime.now(timezone.utc)
		ncr_number = f"NCRV2-{ts.strftime('%Y%m%d-%H%M%S')}"

		ncr = NCR(
			tenant_id=tenant_id,
			ncr_number=ncr_number,
			lot_id=lot_id,
			product_code=lot.product_code,
			description=description,
			severity=severity,
			status="OPEN",
			raised_by=raised_by,
		)
		session.add(ncr)
		session.flush()
		log.info("QCService.raise_ncr: %s raised for lot=%s severity=%s", ncr_number, lot_id, severity)
		return ncr

	def disposition_ncr(
		self,
		session: Any,
		ncr_id: str,
		disposition: str,
		root_cause: str,
		corrective_action: str,
		tenant_id: str,
	) -> Any:
		"""Set disposition on an NCR and advance status to DISPOSITION.

		Valid dispositions: ACCEPT_AS_IS | REWORK | SCRAP | RETURN_TO_SUPPLIER
		Transition: any non-CLOSED status → DISPOSITION.
		"""
		from pgappforge.plugins.erp.operations.quality.models import NCR

		ncr = session.get(NCR, ncr_id)
		if ncr is None:
			raise NCRNotFoundError(f"NCR {ncr_id!r} not found")
		if ncr.status == "CLOSED":
			raise InvalidStatusTransitionError("Cannot disposition a CLOSED NCR")

		ncr.disposition = disposition
		ncr.root_cause = root_cause
		ncr.corrective_action = corrective_action
		ncr.status = "DISPOSITION"
		ncr.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.info(
			"QCService.disposition_ncr: %s → DISPOSITION disposition=%s", ncr_id, disposition
		)
		return ncr

	def create_capa(
		self,
		session: Any,
		ncr_id: str | None,
		capa_type: str,
		description: str,
		action_plan: str,
		owner_id: str,
		target_date: date,
		tenant_id: str,
	) -> Any:
		"""Create a CAPA linked to an NCR (or standalone for PREVENTIVE type).

		Generates capa_number as CAPA-YYYYMMDD-HHMMSS.
		root_cause is copied from the linked NCR when ncr_id is given.
		"""
		from pgappforge.plugins.erp.operations.quality.models import CAPA, NCR

		root_cause = description  # fallback
		if ncr_id is not None:
			ncr = session.get(NCR, ncr_id)
			if ncr is None:
				raise NCRNotFoundError(f"NCR {ncr_id!r} not found")
			root_cause = ncr.root_cause or description

		ts = datetime.now(timezone.utc)
		capa_number = f"CAPA-{ts.strftime('%Y%m%d-%H%M%S')}"

		capa = CAPA(
			tenant_id=tenant_id,
			capa_number=capa_number,
			ncr_id=ncr_id,
			capa_type=capa_type,
			description=description,
			root_cause=root_cause,
			action_plan=action_plan,
			status="OPEN",
			owner_id=owner_id,
			target_date=target_date,
			effectiveness_verified=False,
		)
		session.add(capa)
		session.flush()
		log.info("QCService.create_capa: %s created type=%s owner=%s", capa_number, capa_type, owner_id)
		return capa

	def verify_capa(
		self,
		session: Any,
		capa_id: str,
		verified_by: str,
		tenant_id: str,
	) -> Any:
		"""Mark a CAPA as effectiveness-verified and advance status to VERIFIED.

		Transition: IN_PROGRESS → VERIFIED.
		Sets effectiveness_verified=True.
		"""
		from pgappforge.plugins.erp.operations.quality.models import CAPA

		capa = session.get(CAPA, capa_id)
		if capa is None:
			raise QCServiceError(f"CAPA {capa_id!r} not found")
		if capa.status not in ("OPEN", "IN_PROGRESS"):
			raise InvalidStatusTransitionError(
				f"Cannot verify CAPA in status {capa.status!r}"
			)

		capa.effectiveness_verified = True
		capa.status = "VERIFIED"
		capa.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.info("QCService.verify_capa: %s verified by %s", capa_id, verified_by)
		return capa

	def get_quality_dashboard(
		self,
		session: Any,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Return quality KPI summary for a tenant.

		Returned dict:
		  lots_passed      — int: InspectionLots with status=PASSED
		  lots_failed      — int: InspectionLots with status=FAILED
		  pass_rate_pct    — float: lots_passed / (lots_passed + lots_failed) * 100
		  open_ncrs_by_severity — dict: {CRITICAL: n, MAJOR: n, MINOR: n}
		  open_capas       — int: CAPAs not in VERIFIED/CLOSED
		  overdue_calibrations — int: CalibrationRecords where next_due_date < today
		"""
		from pgappforge.plugins.erp.operations.quality.models import (
			CAPA,
			CalibrationRecord,
			InspectionLot,
			NCR,
		)

		today = date.today()

		# Lot counts
		lots_passed: int = session.execute(
			sa.select(sa.func.count()).select_from(InspectionLot).where(
				InspectionLot.tenant_id == tenant_id,
				InspectionLot.status == "PASSED",
			)
		).scalar_one()

		lots_failed: int = session.execute(
			sa.select(sa.func.count()).select_from(InspectionLot).where(
				InspectionLot.tenant_id == tenant_id,
				InspectionLot.status == "FAILED",
			)
		).scalar_one()

		total_closed = lots_passed + lots_failed
		pass_rate_pct = (
			round(lots_passed / total_closed * 100, 2) if total_closed > 0 else 0.0
		)

		# Open NCRs by severity
		open_ncrs_rows = session.execute(
			sa.select(NCR.severity, sa.func.count().label("cnt"))
			.where(
				NCR.tenant_id == tenant_id,
				NCR.status.notin_(["CLOSED"]),
			)
			.group_by(NCR.severity)
		).all()
		open_ncrs_by_severity: dict[str, int] = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0}
		for row in open_ncrs_rows:
			open_ncrs_by_severity[row.severity] = row.cnt

		# Open CAPAs
		open_capas: int = session.execute(
			sa.select(sa.func.count()).select_from(CAPA).where(
				CAPA.tenant_id == tenant_id,
				CAPA.status.notin_(["VERIFIED", "CLOSED"]),
			)
		).scalar_one()

		# Overdue calibrations
		overdue_calibrations: int = session.execute(
			sa.select(sa.func.count()).select_from(CalibrationRecord).where(
				CalibrationRecord.tenant_id == tenant_id,
				CalibrationRecord.next_due_date < today,
			)
		).scalar_one()

		return {
			"lots_passed": lots_passed,
			"lots_failed": lots_failed,
			"pass_rate_pct": pass_rate_pct,
			"open_ncrs_by_severity": open_ncrs_by_severity,
			"open_capas": open_capas,
			"overdue_calibrations": overdue_calibrations,
		}


__all__ = [
	"QCService",
	"QCServiceError",
	"InspectionPlanNotFoundError",
	"InspectionNotFoundError",
	"NCRNotFoundError",
	"InvalidStatusTransitionError",
]
