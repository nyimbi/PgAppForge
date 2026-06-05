"""
pgappforge/plugins/erp/projects/services.py

ProjectService — stateless business logic for the Project Management / PSA plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

Monetary invariants:
  - All amounts stored and returned as integer cents
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - Hours stored as Decimal (Numeric columns); never float

EVM (Earned Value Management) terminology:
  BAC  = Budget At Completion (original_budget_cents)
  PV   = Planned Value   — budgeted cost of scheduled work
  EV   = Earned Value    — budgeted cost of work performed
  AC   = Actual Cost     — actual cost incurred
  CPI  = Cost Performance Index     = EV / AC
  SPI  = Schedule Performance Index = EV / PV
  EAC  = Estimate At Completion     = AC + (BAC - EV) / CPI
  VAC  = Variance At Completion     = BAC - EAC
  CV   = Cost Variance              = EV - AC
  SV   = Schedule Variance          = EV - PV

IFRS 15 revenue recognition methods:
  POC                — Percentage of Completion (percent_complete × contract_value)
  MILESTONE          — recognised when milestone achieved + invoiced
  COMPLETED_CONTRACT — recognised only on project completion

Public methods:
  create_project(session, data, tenant_id)                      -> Project
  log_time(session, employee_id, project_id, wbs_id,
           work_date, hours, description, tenant_id)            -> ProjectTimesheet
  approve_timesheet(session, timesheet_id, approved_by,
                    tenant_id)                                   -> ProjectTimesheet
  calculate_evm(session, project_id, as_of_date, tenant_id)    -> dict
  generate_invoice(session, project_id, invoice_type,
                   tenant_id, milestone_id=None)                -> ProjectInvoice
  recognise_revenue(session, project_id, method,
                    as_of_date, tenant_id)                      -> dict
  approve_change_order(session, co_id, approved_by,
                       tenant_id)                               -> ChangeOrder
  get_project_portfolio(session, status=None,
                        tenant_id='')                           -> list[dict]
  get_resource_utilization(session, from_date,
                           to_date, tenant_id)                  -> list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProjectServiceError(Exception):
	"""Base domain error for project operations."""


class ProjectNotFoundError(ProjectServiceError):
	pass


class WBSElementNotFoundError(ProjectServiceError):
	pass


class ResourceNotFoundError(ProjectServiceError):
	pass


class TimesheetNotFoundError(ProjectServiceError):
	pass


class MilestoneNotFoundError(ProjectServiceError):
	pass


class ChangeOrderNotFoundError(ProjectServiceError):
	pass


class ProjectStateError(ProjectServiceError):
	"""Invalid state transition."""


class ProjectBillingError(ProjectServiceError):
	"""Billing / invoicing rule violation."""


class ProjectRevenueError(ProjectServiceError):
	"""Revenue recognition rule violation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _cents(d: Decimal) -> int:
	"""Round a Decimal to nearest integer cent (ROUND_HALF_UP)."""
	return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(v: Any) -> Decimal:
	"""Safely coerce a DB value to Decimal (guards against float columns)."""
	if v is None:
		return _ZERO
	return Decimal(str(v))


def _next_invoice_number(session: Any, tenant_id: str) -> str:
	"""Generate a sequential invoice number scoped to the tenant."""
	from pgappforge.plugins.erp.projects.models import ProjectInvoice
	result = session.execute(
		sa.select(sa.func.count()).select_from(ProjectInvoice).where(
			ProjectInvoice.tenant_id == tenant_id
		)
	).scalar_one()
	seq = (result or 0) + 1
	year = datetime.now(timezone.utc).year
	return f"INV-{year}-{seq:04d}"


# ---------------------------------------------------------------------------
# ProjectService
# ---------------------------------------------------------------------------

class ProjectService:
	"""Stateless service for the Project Management / PSA domain.

	All methods are @staticmethod — instantiate if you prefer, but the class
	carries no per-instance state.  Pass the SQLAlchemy session explicitly so
	transaction boundaries remain with the caller.
	"""

	# ------------------------------------------------------------------
	# 1. create_project
	# ------------------------------------------------------------------

	@staticmethod
	def create_project(
		session: Any,
		data: dict[str, Any],
		tenant_id: str,
	) -> Any:
		"""Create and persist a new Project.

		Args:
			session:    Active SQLAlchemy session.
			data:       Dict with project fields.  Required keys:
			              code, name, project_type, customer_id, owner_id,
			              start_date, end_date, original_budget_cents.
			            Optional: program_id, currency_code, risk_level,
			              revised_budget_cents, description, metadata_.
			tenant_id:  Tenant scoping UUID string.

		Returns:
			Persisted Project instance (flushed, id available).

		Raises:
			ProjectStateError: If code already exists for this tenant.
		"""
		from pgappforge.plugins.erp.projects.models import Project
		from pgappforge.plugins.erp.projects.events import ProjectCreatedEvent

		# Guard: unique code per tenant
		existing = session.execute(
			sa.select(Project).where(
				Project.tenant_id == tenant_id,
				Project.code == data["code"],
			)
		).scalar_one_or_none()
		if existing is not None:
			raise ProjectStateError(
				f"Project code {data['code']!r} already exists for tenant {tenant_id!r}"
			)

		budget = int(data["original_budget_cents"])
		project = Project(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			program_id=data.get("program_id"),
			code=data["code"],
			name=data["name"],
			project_type=data["project_type"],
			customer_id=str(data["customer_id"]),
			owner_id=str(data["owner_id"]),
			start_date=data["start_date"],
			end_date=data["end_date"],
			status=data.get("status", "DRAFT"),
			original_budget_cents=budget,
			revised_budget_cents=int(data.get("revised_budget_cents", budget)),
			forecast_at_completion_cents=budget,
			billed_to_date_cents=0,
			recognised_revenue_cents=0,
			percent_complete=Decimal("0.00"),
			risk_level=data.get("risk_level", "LOW"),
			currency_code=data.get("currency_code", "KES"),
			description=data.get("description", ""),
			metadata_=data.get("metadata_", {}),
		)
		session.add(project)
		session.flush()

		# Emit domain event
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				ProjectCreatedEvent(
					aggregate_id=project.id,
					aggregate_type="Project",
					tenant_id=tenant_id,
					project_id=project.id,
					project_code=project.code,
					project_type=project.project_type,
					customer_id=project.customer_id,
					owner_id=project.owner_id,
					original_budget_cents=project.original_budget_cents,
					currency_code=project.currency_code,
					start_date=str(project.start_date),
					end_date=str(project.end_date),
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning("ProjectService.create_project: event emit failed: %s", exc)

		log.info(
			"ProjectService.create_project: created project %s (%s) tenant=%s",
			project.code, project.id, tenant_id,
		)
		return project

	# ------------------------------------------------------------------
	# 2. log_time
	# ------------------------------------------------------------------

	@staticmethod
	def log_time(
		session: Any,
		employee_id: str,
		project_id: str,
		wbs_id: str | None,
		work_date: date,
		hours: Decimal | float | str,
		description: str,
		tenant_id: str,
	) -> Any:
		"""Log a timesheet entry for an employee on a project.

		The entry is created in DRAFT status.  The employee must be an active
		resource on the project (ProjectResource row).

		Args:
			session:     Active SQLAlchemy session.
			employee_id: UUID string of the employee.
			project_id:  UUID string of the project.
			wbs_id:      UUID string of the WBS task, or None.
			work_date:   Calendar date of the work.
			hours:       Hours worked (Decimal-safe; max 24 per entry enforced).
			description: Narrative description of the work.
			tenant_id:   Tenant scoping UUID string.

		Returns:
			Persisted ProjectTimesheet in DRAFT status.

		Raises:
			ProjectNotFoundError:  Project not found or wrong tenant.
			ResourceNotFoundError: Employee not allocated to this project.
			ProjectStateError:     Hours > 24 or project not in billable state.
		"""
		from pgappforge.plugins.erp.projects.models import (
			Project, ProjectResource, ProjectTimesheet,
		)

		hours_dec = _dec(hours)
		if hours_dec <= _ZERO:
			raise ProjectStateError("hours must be positive")
		if hours_dec > Decimal("24"):
			raise ProjectStateError("hours per timesheet entry cannot exceed 24")

		project = session.execute(
			sa.select(Project).where(
				Project.id == project_id,
				Project.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if project is None:
			raise ProjectNotFoundError(f"Project {project_id!r} not found for tenant {tenant_id!r}")
		if project.status in ("COMPLETED", "CANCELLED"):
			raise ProjectStateError(
				f"Cannot log time on project in status {project.status!r}"
			)

		resource = session.execute(
			sa.select(ProjectResource).where(
				ProjectResource.project_id == project_id,
				ProjectResource.employee_id == employee_id,
				ProjectResource.tenant_id == tenant_id,
				ProjectResource.is_active == True,  # noqa: E712
			)
		).scalars().first()
		if resource is None:
			raise ResourceNotFoundError(
				f"Employee {employee_id!r} is not an active resource on project {project_id!r}"
			)

		# Validate wbs_element belongs to this project
		if wbs_id is not None:
			from pgappforge.plugins.erp.projects.models import WBSElement
			wbs = session.execute(
				sa.select(WBSElement).where(
					WBSElement.id == wbs_id,
					WBSElement.project_id == project_id,
				)
			).scalar_one_or_none()
			if wbs is None:
				raise WBSElementNotFoundError(
					f"WBS element {wbs_id!r} not found on project {project_id!r}"
				)

		ts = ProjectTimesheet(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			project_id=project_id,
			wbs_element_id=wbs_id,
			employee_id=employee_id,
			work_date=work_date,
			hours=hours_dec,
			description=description,
			status="DRAFT",
		)
		session.add(ts)
		session.flush()

		log.debug(
			"ProjectService.log_time: ts=%s project=%s employee=%s date=%s hours=%s",
			ts.id, project_id, employee_id, work_date, hours_dec,
		)
		return ts

	# ------------------------------------------------------------------
	# 3. approve_timesheet
	# ------------------------------------------------------------------

	@staticmethod
	def approve_timesheet(
		session: Any,
		timesheet_id: str,
		approved_by: str,
		tenant_id: str,
	) -> Any:
		"""Approve a SUBMITTED timesheet entry.

		Side effects:
		  - Sets status=APPROVED, approved_by, approved_at.
		  - Computes and stores cost_cents and bill_amount_cents from the
		    employee's ProjectResource rates.
		  - Increments WBSElement.actual_hours and .actual_cost_cents.
		  - Increments ProjectResource.actual_hours.
		  - Emits TimesheetApprovedEvent.

		Args:
			session:       Active SQLAlchemy session.
			timesheet_id:  UUID string of the timesheet entry.
			approved_by:   UUID string of the approving user.
			tenant_id:     Tenant scoping UUID string.

		Returns:
			Updated ProjectTimesheet instance.

		Raises:
			TimesheetNotFoundError: Timesheet not found or wrong tenant.
			ProjectStateError:      Timesheet not in SUBMITTED status.
		"""
		from pgappforge.plugins.erp.projects.models import (
			ProjectTimesheet, ProjectResource, WBSElement,
		)
		from pgappforge.plugins.erp.projects.events import TimesheetApprovedEvent

		ts = session.execute(
			sa.select(ProjectTimesheet).where(
				ProjectTimesheet.id == timesheet_id,
				ProjectTimesheet.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if ts is None:
			raise TimesheetNotFoundError(
				f"Timesheet {timesheet_id!r} not found for tenant {tenant_id!r}"
			)
		if ts.status != "SUBMITTED":
			raise ProjectStateError(
				f"Timesheet must be SUBMITTED to approve; current status={ts.status!r}"
			)

		# Lookup resource rates
		resource = session.execute(
			sa.select(ProjectResource).where(
				ProjectResource.project_id == ts.project_id,
				ProjectResource.employee_id == ts.employee_id,
				ProjectResource.tenant_id == tenant_id,
			)
		).scalars().first()

		hours = _dec(ts.hours)
		cost_cents = _ZERO
		bill_cents = _ZERO
		if resource is not None:
			cost_cents = hours * _dec(resource.cost_rate_cents_per_hour)
			bill_cents = hours * _dec(resource.bill_rate_cents_per_hour)
			# Update resource actual_hours
			resource.actual_hours = _dec(resource.actual_hours) + hours

		ts.status = "APPROVED"
		ts.approved_by = approved_by
		ts.approved_at = _now()
		ts.cost_cents = _cents(cost_cents)
		ts.bill_amount_cents = _cents(bill_cents)

		# Roll up to WBS element
		if ts.wbs_element_id is not None:
			wbs = session.execute(
				sa.select(WBSElement).where(WBSElement.id == ts.wbs_element_id)
			).scalar_one_or_none()
			if wbs is not None:
				wbs.actual_hours = _dec(wbs.actual_hours) + hours
				wbs.actual_cost_cents = (wbs.actual_cost_cents or 0) + _cents(cost_cents)
				if wbs.status == "NOT_STARTED":
					wbs.status = "IN_PROGRESS"
					if wbs.actual_start is None:
						wbs.actual_start = ts.work_date

		session.flush()

		# Emit event
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				TimesheetApprovedEvent(
					aggregate_id=ts.id,
					aggregate_type="ProjectTimesheet",
					tenant_id=tenant_id,
					timesheet_id=ts.id,
					project_id=ts.project_id,
					employee_id=ts.employee_id,
					wbs_element_id=ts.wbs_element_id or "",
					work_date=str(ts.work_date),
					hours=str(ts.hours),
					approved_by=approved_by,
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning("ProjectService.approve_timesheet: event emit failed: %s", exc)

		log.info(
			"ProjectService.approve_timesheet: approved ts=%s project=%s hours=%s cost=%d¢",
			ts.id, ts.project_id, ts.hours, ts.cost_cents,
		)
		return ts

	# ------------------------------------------------------------------
	# 4. calculate_evm
	# ------------------------------------------------------------------

	@staticmethod
	def calculate_evm(
		session: Any,
		project_id: str,
		as_of_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Compute Earned Value Management metrics for a project.

		BAC  = project.original_budget_cents
		PV   = sum(planned_cost_cents) for WBS tasks where planned_end <= as_of_date
		EV   = sum(planned_cost_cents × (actual_hours / planned_hours))
		       for WBS tasks with actual_hours > 0 and planned_hours > 0
		AC   = sum(actual_cost_cents) across ALL WBS elements

		Derived metrics:
		  CPI = EV / AC          (0 when AC=0)
		  SPI = EV / PV          (0 when PV=0)
		  EAC = AC + (BAC-EV) / CPI  (falls back to BAC when CPI=0)
		  VAC = BAC - EAC
		  CV  = EV - AC
		  SV  = EV - PV

		Side effect:
		  Updates project.forecast_at_completion_cents = EAC.

		Returns:
			dict with keys: project_id, as_of_date, BAC, PV, EV, AC,
			CPI, SPI, EAC, VAC, CV, SV (all monetary values as int cents,
			index values as Decimal strings rounded to 4dp).
		"""
		from pgappforge.plugins.erp.projects.models import Project, WBSElement

		project = session.execute(
			sa.select(Project).where(
				Project.id == project_id,
				Project.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if project is None:
			raise ProjectNotFoundError(
				f"Project {project_id!r} not found for tenant {tenant_id!r}"
			)

		bac = Decimal(str(project.original_budget_cents))

		# Pull all WBS task/deliverable/phase elements for this project
		wbs_rows = session.execute(
			sa.select(WBSElement).where(
				WBSElement.project_id == project_id,
				WBSElement.element_type.in_(["TASK", "DELIVERABLE", "PHASE"]),
			)
		).scalars().all()

		pv = _ZERO
		ev = _ZERO
		ac = _ZERO

		for w in wbs_rows:
			p_cost = _dec(w.planned_cost_cents)
			a_cost = _dec(w.actual_cost_cents)
			p_hours = _dec(w.planned_hours)
			a_hours = _dec(w.actual_hours)
			ac += a_cost

			# PV: planned work that should have been done by as_of_date
			if w.planned_end is not None and w.planned_end <= as_of_date:
				pv += p_cost

			# EV: earned value based on actual progress ratio
			if p_hours > _ZERO:
				progress = min(a_hours / p_hours, Decimal("1"))
				ev += p_cost * progress
			elif w.status == "COMPLETED":
				# Zero-hour milestones count as 100% earned when completed
				ev += p_cost

		# CPI / SPI — guard division by zero
		cpi = (ev / ac).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if ac > _ZERO else _ZERO
		spi = (ev / pv).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if pv > _ZERO else _ZERO

		# EAC: use CPI-adjusted estimate; fall back to BAC when CPI=0 (no actuals yet)
		if cpi > _ZERO:
			eac = ac + (bac - ev) / cpi
		else:
			eac = bac

		vac = bac - eac
		cv = ev - ac
		sv = ev - pv

		eac_cents = _cents(eac)
		# Update project EAC
		project.forecast_at_completion_cents = eac_cents
		session.flush()

		result = {
			"project_id": project_id,
			"as_of_date": str(as_of_date),
			# Monetary values — integer cents
			"BAC": int(bac),
			"PV": _cents(pv),
			"EV": _cents(ev),
			"AC": _cents(ac),
			"EAC": eac_cents,
			"VAC": _cents(vac),
			"CV": _cents(cv),
			"SV": _cents(sv),
			# Index values — Decimal strings (4dp)
			"CPI": str(cpi),
			"SPI": str(spi),
			# Human-friendly health signal
			"health": (
				"GREEN" if cpi >= Decimal("0.9") and spi >= Decimal("0.9")
				else "AMBER" if cpi >= Decimal("0.75") or spi >= Decimal("0.75")
				else "RED"
			),
		}
		log.info(
			"ProjectService.calculate_evm: project=%s BAC=%d EV=%d AC=%d CPI=%s SPI=%s",
			project_id, result["BAC"], result["EV"], result["AC"], cpi, spi,
		)
		return result

	# ------------------------------------------------------------------
	# 5. generate_invoice
	# ------------------------------------------------------------------

	@staticmethod
	def generate_invoice(
		session: Any,
		project_id: str,
		invoice_type: str,
		tenant_id: str,
		milestone_id: str | None = None,
	) -> Any:
		"""Generate a project invoice.

		T_AND_M:
		  - Pulls all APPROVED timesheets with invoice_id IS NULL.
		  - Sums bill_amount_cents into invoice.amount_cents.
		  - Marks those timesheets status=BILLED, invoice_id=invoice.id.
		  - Posts GL: DR AR 1200 / CR Revenue 4000.

		MILESTONE:
		  - milestone_id must be provided and in ACHIEVED status.
		  - Sets invoice.amount_cents = milestone.amount_cents.
		  - Transitions milestone to INVOICED.

		RETAINER / ADVANCE:
		  - amount_cents must be supplied in kwargs; caller populates
		    data dict — pass as extra key in the calling dict or supply
		    via a post-create update.  Here we raise if amount is zero.

		VAT: not computed here (tax_cents remains 0 — add a tax engine hook).
		total_cents = amount_cents + tax_cents.

		Returns:
			Persisted ProjectInvoice in DRAFT status.

		Raises:
			ProjectNotFoundError:  Project not found.
			ProjectBillingError:   No billable timesheets, or milestone issue.
		"""
		from pgappforge.plugins.erp.projects.models import (
			Project, ProjectTimesheet, ProjectMilestone, ProjectInvoice,
		)
		from pgappforge.plugins.erp.projects.events import InvoiceGeneratedEvent

		project = session.execute(
			sa.select(Project).where(
				Project.id == project_id,
				Project.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if project is None:
			raise ProjectNotFoundError(
				f"Project {project_id!r} not found for tenant {tenant_id!r}"
			)
		if project.status in ("CANCELLED",):
			raise ProjectBillingError(
				f"Cannot invoice a CANCELLED project"
			)

		amount_cents = 0
		today = date.today()

		if invoice_type == "T_AND_M":
			# Collect all approved, unbilled timesheets
			timesheets = session.execute(
				sa.select(ProjectTimesheet).where(
					ProjectTimesheet.project_id == project_id,
					ProjectTimesheet.tenant_id == tenant_id,
					ProjectTimesheet.status == "APPROVED",
					ProjectTimesheet.invoice_id == None,  # noqa: E711
				)
			).scalars().all()
			if not timesheets:
				raise ProjectBillingError(
					f"No approved unbilled timesheets for project {project_id!r}"
				)
			amount_cents = sum(ts.bill_amount_cents or 0 for ts in timesheets)

		elif invoice_type == "MILESTONE":
			if milestone_id is None:
				raise ProjectBillingError("milestone_id is required for MILESTONE invoice type")
			milestone = session.execute(
				sa.select(ProjectMilestone).where(
					ProjectMilestone.id == milestone_id,
					ProjectMilestone.project_id == project_id,
					ProjectMilestone.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if milestone is None:
				raise MilestoneNotFoundError(
					f"Milestone {milestone_id!r} not found on project {project_id!r}"
				)
			if milestone.status != "ACHIEVED":
				raise ProjectBillingError(
					f"Milestone must be ACHIEVED to invoice; current status={milestone.status!r}"
				)
			amount_cents = milestone.amount_cents

		elif invoice_type in ("RETAINER", "ADVANCE"):
			# For retainer/advance the caller must have set amount via project contract value
			# or pass via a separate update.  We require non-zero — caller sets amount_cents
			# by passing it in data if needed; here we derive from project budget / 12.
			# Sensible default: one month of original_budget_cents / 12.
			amount_cents = project.original_budget_cents // 12
			if amount_cents <= 0:
				raise ProjectBillingError(
					f"Cannot generate zero-amount {invoice_type} invoice; "
					"set project.original_budget_cents first"
				)
		else:
			raise ProjectBillingError(f"Unknown invoice_type {invoice_type!r}")

		tax_cents = 0  # VAT hook: extend here with tax engine
		total_cents = amount_cents + tax_cents
		invoice_number = _next_invoice_number(session, tenant_id)

		invoice = ProjectInvoice(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			project_id=project_id,
			invoice_number=invoice_number,
			invoice_type=invoice_type,
			invoice_date=today,
			due_date=date(today.year, today.month, today.day) + timedelta(days=30),
			amount_cents=amount_cents,
			tax_cents=tax_cents,
			total_cents=total_cents,
			status="DRAFT",
		)
		session.add(invoice)
		session.flush()  # get invoice.id

		# Mark timesheets as BILLED
		if invoice_type == "T_AND_M":
			for ts in timesheets:
				ts.status = "BILLED"
				ts.invoice_id = invoice.id

		# Transition milestone to INVOICED
		if invoice_type == "MILESTONE" and milestone_id is not None:
			milestone.status = "INVOICED"
			milestone.invoice_id = invoice.id

		# Update project.billed_to_date_cents
		project.billed_to_date_cents = (project.billed_to_date_cents or 0) + total_cents

		# Post GL: DR AR 1200 / CR Revenue 4000
		gl_journal_id: str | None = None
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
			journal = GLService.post_journal(
				session=session,
				tenant_id=tenant_id,
				description=f"Project invoice {invoice_number}",
				lines=[
					{"account": "1200", "debit_cents": total_cents, "credit_cents": 0,
					 "ref": invoice.id, "memo": f"AR — {invoice_number}"},
					{"account": "4000", "debit_cents": 0, "credit_cents": total_cents,
					 "ref": invoice.id, "memo": f"Project revenue — {invoice_number}"},
				],
			)
			gl_journal_id = journal.id if hasattr(journal, "id") else str(journal)
			invoice.gl_journal_id = gl_journal_id
		except (ImportError, AttributeError) as exc:
			log.debug("ProjectService.generate_invoice: GL posting skipped (%s)", exc)

		session.flush()

		# Emit event
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				InvoiceGeneratedEvent(
					aggregate_id=invoice.id,
					aggregate_type="ProjectInvoice",
					tenant_id=tenant_id,
					invoice_id=invoice.id,
					project_id=project_id,
					invoice_number=invoice_number,
					invoice_type=invoice_type,
					amount_cents=amount_cents,
					tax_cents=tax_cents,
					total_cents=total_cents,
					currency_code=project.currency_code,
					invoice_date=str(today),
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning("ProjectService.generate_invoice: event emit failed: %s", exc)

		log.info(
			"ProjectService.generate_invoice: invoice=%s project=%s type=%s total=%d¢",
			invoice_number, project_id, invoice_type, total_cents,
		)
		return invoice

	# ------------------------------------------------------------------
	# 6. recognise_revenue
	# ------------------------------------------------------------------

	@staticmethod
	def recognise_revenue(
		session: Any,
		project_id: str,
		method: str,
		as_of_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Post an IFRS 15 revenue recognition entry for a project.

		Supported methods:
		  POC (Percentage of Completion):
		    recognised = project.percent_complete / 100 × contract_value
		    contract_value = project.original_budget_cents (or revised if amended)
		    incremental = recognised - project.recognised_revenue_cents
		    GL: DR deferred_revenue 2310 / CR project_revenue 4000

		  MILESTONE:
		    recognised = sum of INVOICED milestone.amount_cents
		    incremental = recognised - project.recognised_revenue_cents

		  COMPLETED_CONTRACT:
		    recognised = contract_value (only when project.status=COMPLETED)
		    incremental = contract_value - project.recognised_revenue_cents

		Side effect:
		  Updates project.recognised_revenue_cents += incremental.

		Returns:
			dict with keys: project_id, method, as_of_date,
			contract_value_cents, recognised_to_date_cents,
			incremental_cents, gl_journal_id, percent_complete.

		Raises:
			ProjectNotFoundError:  Project not found.
			ProjectRevenueError:   Method-specific preconditions not met.
		"""
		from pgappforge.plugins.erp.projects.models import Project, ProjectMilestone
		from pgappforge.plugins.erp.projects.events import RevenueRecognisedEvent

		project = session.execute(
			sa.select(Project).where(
				Project.id == project_id,
				Project.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if project is None:
			raise ProjectNotFoundError(
				f"Project {project_id!r} not found for tenant {tenant_id!r}"
			)

		contract_value = Decimal(str(project.revised_budget_cents or project.original_budget_cents))
		already = Decimal(str(project.recognised_revenue_cents or 0))
		pct = _dec(project.percent_complete)

		if method == "POC":
			recognised = (pct / _HUNDRED * contract_value).quantize(
				Decimal("1"), rounding=ROUND_HALF_UP
			)
		elif method == "MILESTONE":
			rows = session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(ProjectMilestone.amount_cents), 0)).where(
					ProjectMilestone.project_id == project_id,
					ProjectMilestone.tenant_id == tenant_id,
					ProjectMilestone.status.in_(["INVOICED", "PAID"]),
				)
			).scalar_one()
			recognised = Decimal(str(rows))
		elif method == "COMPLETED_CONTRACT":
			if project.status != "COMPLETED":
				raise ProjectRevenueError(
					"COMPLETED_CONTRACT method requires project.status=COMPLETED"
				)
			recognised = contract_value
		else:
			raise ProjectRevenueError(
				f"Unknown revenue recognition method {method!r}; "
				"expected POC | MILESTONE | COMPLETED_CONTRACT"
			)

		incremental = max(_ZERO, recognised - already)
		incremental_cents = _cents(incremental)

		if incremental_cents <= 0:
			log.info(
				"ProjectService.recognise_revenue: project=%s no incremental revenue (already=%d recognised=%d)",
				project_id, int(already), int(recognised),
			)
			return {
				"project_id": project_id,
				"method": method,
				"as_of_date": str(as_of_date),
				"contract_value_cents": int(contract_value),
				"recognised_to_date_cents": int(already),
				"incremental_cents": 0,
				"gl_journal_id": None,
				"percent_complete": str(pct),
			}

		# Update project cumulative recognised
		project.recognised_revenue_cents = int(already) + incremental_cents

		# Post GL: DR deferred_revenue 2310 / CR project_revenue 4000
		gl_journal_id: str | None = None
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService  # type: ignore
			journal = GLService.post_journal(
				session=session,
				tenant_id=tenant_id,
				description=f"IFRS 15 revenue recognition — {method} project {project_id}",
				lines=[
					{
						"account": "2310",
						"debit_cents": incremental_cents,
						"credit_cents": 0,
						"ref": project_id,
						"memo": f"Deferred revenue release — {method}",
					},
					{
						"account": "4000",
						"debit_cents": 0,
						"credit_cents": incremental_cents,
						"ref": project_id,
						"memo": f"Project revenue recognised — {method}",
					},
				],
			)
			gl_journal_id = journal.id if hasattr(journal, "id") else str(journal)
		except (ImportError, AttributeError) as exc:
			log.debug("ProjectService.recognise_revenue: GL posting skipped (%s)", exc)

		session.flush()

		# Emit event
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				RevenueRecognisedEvent(
					aggregate_id=project_id,
					aggregate_type="Project",
					tenant_id=tenant_id,
					project_id=project_id,
					method=method,
					as_of_date=str(as_of_date),
					recognised_amount_cents=incremental_cents,
					cumulative_recognised_cents=project.recognised_revenue_cents,
					percent_complete=str(pct),
					gl_journal_id=gl_journal_id or "",
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning("ProjectService.recognise_revenue: event emit failed: %s", exc)

		result = {
			"project_id": project_id,
			"method": method,
			"as_of_date": str(as_of_date),
			"contract_value_cents": int(contract_value),
			"recognised_to_date_cents": project.recognised_revenue_cents,
			"incremental_cents": incremental_cents,
			"gl_journal_id": gl_journal_id,
			"percent_complete": str(pct),
		}
		log.info(
			"ProjectService.recognise_revenue: project=%s method=%s incremental=%d¢ cumulative=%d¢",
			project_id, method, incremental_cents, project.recognised_revenue_cents,
		)
		return result

	# ------------------------------------------------------------------
	# 7. approve_change_order
	# ------------------------------------------------------------------

	@staticmethod
	def approve_change_order(
		session: Any,
		co_id: str,
		approved_by: str,
		tenant_id: str,
	) -> Any:
		"""Approve a change order, updating project budget and schedule.

		Side effects:
		  - ChangeOrder status → APPROVED.
		  - project.revised_budget_cents += co.budget_delta_cents.
		  - project.end_date += timedelta(days=co.schedule_delta_days).
		  - Emits ChangeOrderApprovedEvent.

		Args:
			session:     Active SQLAlchemy session.
			co_id:       UUID string of the ChangeOrder.
			approved_by: UUID string of the approving user.
			tenant_id:   Tenant scoping UUID string.

		Returns:
			Updated ChangeOrder instance.

		Raises:
			ChangeOrderNotFoundError: CO not found or wrong tenant.
			ProjectStateError:        CO not in SUBMITTED status.
		"""
		from pgappforge.plugins.erp.projects.models import ChangeOrder, Project
		from pgappforge.plugins.erp.projects.events import ChangeOrderApprovedEvent

		co = session.execute(
			sa.select(ChangeOrder).where(
				ChangeOrder.id == co_id,
				ChangeOrder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if co is None:
			raise ChangeOrderNotFoundError(
				f"ChangeOrder {co_id!r} not found for tenant {tenant_id!r}"
			)
		if co.status != "SUBMITTED":
			raise ProjectStateError(
				f"ChangeOrder must be SUBMITTED to approve; current status={co.status!r}"
			)

		project = session.execute(
			sa.select(Project).where(Project.id == co.project_id)
		).scalar_one_or_none()
		if project is None:
			raise ProjectNotFoundError(
				f"Project {co.project_id!r} not found for change order {co_id!r}"
			)

		# Apply budget delta
		new_budget = (project.revised_budget_cents or project.original_budget_cents) + co.budget_delta_cents
		project.revised_budget_cents = max(0, new_budget)

		# Apply schedule delta
		new_end = project.end_date + timedelta(days=co.schedule_delta_days)
		project.end_date = new_end

		# Transition change order
		co.status = "APPROVED"
		co.approved_by = approved_by
		co.approved_at = _now()

		session.flush()

		# Emit event
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				ChangeOrderApprovedEvent(
					aggregate_id=co_id,
					aggregate_type="ChangeOrder",
					tenant_id=tenant_id,
					change_order_id=co_id,
					project_id=co.project_id,
					co_number=co.co_number,
					budget_delta_cents=co.budget_delta_cents,
					schedule_delta_days=co.schedule_delta_days,
					new_revised_budget_cents=project.revised_budget_cents,
					new_end_date=str(new_end),
					approved_by=approved_by,
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning("ProjectService.approve_change_order: event emit failed: %s", exc)

		log.info(
			"ProjectService.approve_change_order: co=%s project=%s "
			"budget_delta=%+d¢ new_budget=%d¢ new_end=%s",
			co_id, co.project_id, co.budget_delta_cents,
			project.revised_budget_cents, new_end,
		)
		return co

	# ------------------------------------------------------------------
	# 8. get_project_portfolio
	# ------------------------------------------------------------------

	@staticmethod
	def get_project_portfolio(
		session: Any,
		status: str | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Return a portfolio summary list of projects.

		Each dict contains:
		  project_id, code, name, project_type, status, customer_id,
		  owner_id, start_date, end_date, original_budget_cents,
		  revised_budget_cents, forecast_at_completion_cents,
		  billed_to_date_cents, recognised_revenue_cents,
		  percent_complete, risk_level, currency_code,
		  variance_at_completion_cents (= revised_budget - EAC),
		  programme_code (if linked).

		Args:
			session:   Active SQLAlchemy session.
			status:    Optional status filter (e.g. "ACTIVE").
			tenant_id: Tenant scoping UUID string.

		Returns:
			List of project summary dicts, ordered by start_date DESC.
		"""
		from pgappforge.plugins.erp.projects.models import Project, Program

		stmt = (
			sa.select(Project, Program.code.label("programme_code"))
			.outerjoin(Program, Project.program_id == Program.id)
			.where(Project.tenant_id == tenant_id)
		)
		if status is not None:
			stmt = stmt.where(Project.status == status)
		stmt = stmt.order_by(Project.start_date.desc())

		rows = session.execute(stmt).all()
		result = []
		for proj, prog_code in rows:
			eac = proj.forecast_at_completion_cents or proj.original_budget_cents
			revised = proj.revised_budget_cents or proj.original_budget_cents
			result.append({
				"project_id": proj.id,
				"code": proj.code,
				"name": proj.name,
				"project_type": proj.project_type,
				"status": proj.status,
				"customer_id": proj.customer_id,
				"owner_id": proj.owner_id,
				"start_date": str(proj.start_date),
				"end_date": str(proj.end_date),
				"original_budget_cents": proj.original_budget_cents,
				"revised_budget_cents": revised,
				"forecast_at_completion_cents": eac,
				"variance_at_completion_cents": revised - eac,
				"billed_to_date_cents": proj.billed_to_date_cents or 0,
				"recognised_revenue_cents": proj.recognised_revenue_cents or 0,
				"percent_complete": str(proj.percent_complete or "0.00"),
				"risk_level": proj.risk_level,
				"currency_code": proj.currency_code,
				"programme_code": prog_code,
			})
		return result

	# ------------------------------------------------------------------
	# 9. get_resource_utilization
	# ------------------------------------------------------------------

	@staticmethod
	def get_resource_utilization(
		session: Any,
		from_date: date,
		to_date: date,
		tenant_id: str,
	) -> list[dict[str, Any]]:
		"""Return resource utilization statistics for a date range.

		Aggregates approved/billed timesheets by employee across all projects.

		Each dict contains:
		  employee_id, total_hours, total_cost_cents, total_bill_cents,
		  project_count (distinct projects with logged hours),
		  utilization_pct (total_hours / available_hours × 100 where
		    available_hours = working_days_in_range × 8; a rough proxy —
		    replace with calendar service if available).

		Args:
			session:   Active SQLAlchemy session.
			from_date: Start of analysis window (inclusive).
			to_date:   End of analysis window (inclusive).
			tenant_id: Tenant scoping UUID string.

		Returns:
			List of resource utilization dicts, ordered by total_hours DESC.
		"""
		from pgappforge.plugins.erp.projects.models import ProjectTimesheet

		stmt = (
			sa.select(
				ProjectTimesheet.employee_id,
				sa.func.sum(ProjectTimesheet.hours).label("total_hours"),
				sa.func.sum(ProjectTimesheet.cost_cents).label("total_cost_cents"),
				sa.func.sum(ProjectTimesheet.bill_amount_cents).label("total_bill_cents"),
				sa.func.count(sa.distinct(ProjectTimesheet.project_id)).label("project_count"),
			)
			.where(
				ProjectTimesheet.tenant_id == tenant_id,
				ProjectTimesheet.work_date >= from_date,
				ProjectTimesheet.work_date <= to_date,
				ProjectTimesheet.status.in_(["APPROVED", "BILLED"]),
			)
			.group_by(ProjectTimesheet.employee_id)
			.order_by(sa.text("total_hours DESC"))
		)
		rows = session.execute(stmt).all()

		# Available hours heuristic: working days × 8h
		# Mon–Fri count between from_date and to_date
		total_days = (to_date - from_date).days + 1
		# Rough: 5/7 of days are working days
		available_hours = Decimal(str(total_days)) * Decimal("5") / Decimal("7") * Decimal("8")

		result = []
		for row in rows:
			total_h = _dec(row.total_hours)
			util_pct = (
				(total_h / available_hours * _HUNDRED).quantize(
					Decimal("0.01"), rounding=ROUND_HALF_UP
				)
				if available_hours > _ZERO
				else _ZERO
			)
			result.append({
				"employee_id": row.employee_id,
				"total_hours": str(total_h),
				"total_cost_cents": int(row.total_cost_cents or 0),
				"total_bill_cents": int(row.total_bill_cents or 0),
				"project_count": row.project_count,
				"utilization_pct": str(util_pct),
			})
		return result


__all__ = [
	"ProjectService",
	"ProjectServiceError",
	"ProjectNotFoundError",
	"WBSElementNotFoundError",
	"ResourceNotFoundError",
	"TimesheetNotFoundError",
	"MilestoneNotFoundError",
	"ChangeOrderNotFoundError",
	"ProjectStateError",
	"ProjectBillingError",
	"ProjectRevenueError",
]
