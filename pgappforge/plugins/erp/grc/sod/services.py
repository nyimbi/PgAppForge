"""
pgappforge/plugins/erp/grc/sod/services.py

SodAnalyzerService — segregation-of-duties detection, simulation, bulk scan.

Key operations:
  seed_default_conflicts  — idempotent seeding of 20 standard SoD conflicts
  analyze_user            — detect conflicts for a single user
  simulate_role_grant     — hypothetical conflict check before granting a role
  bulk_scan               — tenant-wide scan; creates/updates SodViolation rows
  accept_risk             — acknowledge a violation with a mitigating control
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("SodAnalyzerService: emit suppressed: %s", exc)


# ---------------------------------------------------------------------------
# Default conflict catalogue
# ---------------------------------------------------------------------------

_DEFAULT_CONFLICTS: list[dict] = [
	# PROCURE_TO_PAY
	{
		"name": "P2P-01",
		"function_a": "Create Purchase Requisition",
		"function_b": "Approve Purchase Requisition",
		"risk_level": "HIGH",
		"control_category": "PROCURE_TO_PAY",
		"description": "Creating and approving one's own purchase requisition bypasses budgetary controls.",
	},
	{
		"name": "P2P-02",
		"function_a": "Create Purchase Order",
		"function_b": "Approve Purchase Order",
		"risk_level": "CRITICAL",
		"control_category": "PROCURE_TO_PAY",
		"description": "Authorising purchases one has initiated removes independent review.",
	},
	{
		"name": "P2P-03",
		"function_a": "Create Purchase Order",
		"function_b": "Receive Goods (GRN)",
		"risk_level": "HIGH",
		"control_category": "PROCURE_TO_PAY",
		"description": "Ordering and receiving goods enables fictitious receipt fraud.",
	},
	{
		"name": "P2P-04",
		"function_a": "Approve Purchase Order",
		"function_b": "Process Supplier Invoice",
		"risk_level": "CRITICAL",
		"control_category": "PROCURE_TO_PAY",
		"description": "Approving orders and processing invoices allows fraudulent payments.",
	},
	{
		"name": "P2P-05",
		"function_a": "Create Supplier Record",
		"function_b": "Approve Supplier Payment",
		"risk_level": "CRITICAL",
		"control_category": "PROCURE_TO_PAY",
		"description": "Creating fictitious suppliers and paying them is a classic fraud vector.",
	},
	# RECORD_TO_REPORT
	{
		"name": "R2R-01",
		"function_a": "Create GL Journal",
		"function_b": "Approve GL Journal",
		"risk_level": "CRITICAL",
		"control_category": "RECORD_TO_REPORT",
		"description": "Self-approving journal entries circumvents the four-eyes principle.",
	},
	{
		"name": "R2R-02",
		"function_a": "Create GL Journal",
		"function_b": "Post GL Journal",
		"risk_level": "HIGH",
		"control_category": "RECORD_TO_REPORT",
		"description": "Creating and posting journals without approval allows unreviewed entries.",
	},
	{
		"name": "R2R-03",
		"function_a": "Create Bank Account",
		"function_b": "Authorize Bank Payment",
		"risk_level": "CRITICAL",
		"control_category": "RECORD_TO_REPORT",
		"description": "Setting up bank accounts and authorising payments enables diversion of funds.",
	},
	{
		"name": "R2R-04",
		"function_a": "Manage Chart of Accounts",
		"function_b": "Post Journal Entries",
		"risk_level": "HIGH",
		"control_category": "RECORD_TO_REPORT",
		"description": "Creating accounts and posting to them allows concealment of transactions.",
	},
	# ORDER_TO_CASH
	{
		"name": "O2C-01",
		"function_a": "Create Customer Record",
		"function_b": "Create Sales Invoice",
		"risk_level": "HIGH",
		"control_category": "ORDER_TO_CASH",
		"description": "Creating fictitious customers and invoices them enables revenue fraud.",
	},
	{
		"name": "O2C-02",
		"function_a": "Create Sales Invoice",
		"function_b": "Apply Customer Payment",
		"risk_level": "CRITICAL",
		"control_category": "ORDER_TO_CASH",
		"description": "Raising invoices and applying cash enables lapping/teeming fraud.",
	},
	{
		"name": "O2C-03",
		"function_a": "Create Credit Note",
		"function_b": "Approve Credit Note",
		"risk_level": "HIGH",
		"control_category": "ORDER_TO_CASH",
		"description": "Self-approving credit notes can reverse legitimate revenue.",
	},
	{
		"name": "O2C-04",
		"function_a": "Approve Customer Credit Limit",
		"function_b": "Create Sales Order",
		"risk_level": "MEDIUM",
		"control_category": "ORDER_TO_CASH",
		"description": "Setting one's own credit limits and creating orders bypasses credit controls.",
	},
	# PAYROLL
	{
		"name": "PAY-01",
		"function_a": "Create Employee Record",
		"function_b": "Approve Payroll Run",
		"risk_level": "CRITICAL",
		"control_category": "PAYROLL",
		"description": "Creating ghost employees and approving their payroll is a classic payroll fraud.",
	},
	{
		"name": "PAY-02",
		"function_a": "Approve Payroll Run",
		"function_b": "Process Payroll Payment",
		"risk_level": "CRITICAL",
		"control_category": "PAYROLL",
		"description": "Approving and disbursing payroll removes segregation over cash outflows.",
	},
	{
		"name": "PAY-03",
		"function_a": "Modify Salary/Pay Rate",
		"function_b": "Approve Payroll Run",
		"risk_level": "CRITICAL",
		"control_category": "PAYROLL",
		"description": "Inflating salaries and approving payroll allows self-enrichment.",
	},
	{
		"name": "PAY-04",
		"function_a": "Create Employee Record",
		"function_b": "Modify Salary/Pay Rate",
		"risk_level": "HIGH",
		"control_category": "PAYROLL",
		"description": "Creating employees and setting their pay removes compensation controls.",
	},
	# ACCESS
	{
		"name": "ACC-01",
		"function_a": "Create User Account",
		"function_b": "Assign User Roles",
		"risk_level": "HIGH",
		"control_category": "ACCESS",
		"description": "Creating accounts and assigning privileged roles enables privilege escalation.",
	},
	{
		"name": "ACC-02",
		"function_a": "Reset User Password",
		"function_b": "Assign User Roles",
		"risk_level": "MEDIUM",
		"control_category": "ACCESS",
		"description": "Resetting passwords and assigning roles together enables account takeover.",
	},
	{
		"name": "ACC-03",
		"function_a": "Create System Configuration",
		"function_b": "Approve System Changes",
		"risk_level": "HIGH",
		"control_category": "ACCESS",
		"description": "Self-approving configuration changes removes change-management controls.",
	},
]


# ---------------------------------------------------------------------------
# SodAnalyzerService
# ---------------------------------------------------------------------------

class SodAnalyzerService:
	"""Stateless SoD analysis service."""

	# ------------------------------------------------------------------
	# seed_default_conflicts
	# ------------------------------------------------------------------

	def seed_default_conflicts(self, tenant_id: str, session: Any) -> int:
		"""Idempotently seed the 20 standard SoD conflicts for *tenant_id*.

		Conflicts are matched by (tenant_id, name) — existing rows are skipped.
		Returns the count of newly created rows.
		"""
		from pgappforge.plugins.erp.grc.sod.models import SodConflict

		created = 0
		for defn in _DEFAULT_CONFLICTS:
			existing = session.execute(
				select(SodConflict).where(
					SodConflict.tenant_id == tenant_id,
					SodConflict.name == defn["name"],
				)
			).scalar_one_or_none()
			if existing is not None:
				continue
			session.add(SodConflict(
				tenant_id=tenant_id,
				name=defn["name"],
				function_a=defn["function_a"],
				function_b=defn["function_b"],
				risk_level=defn["risk_level"],
				control_category=defn["control_category"],
				description=defn["description"],
				is_active=True,
			))
			created += 1
		if created:
			session.flush()
		log.info("seed_default_conflicts: %d conflicts created for tenant %s", created, tenant_id)
		return created

	# ------------------------------------------------------------------
	# _get_user_role_names
	# ------------------------------------------------------------------

	def _get_user_role_names(self, user_id: str) -> list[str]:
		"""Return FAB role names held by *user_id*.  Empty list on any failure."""
		try:
			from flask import current_app
			user = current_app.appbuilder.sm.find_user(id=user_id)
			if user is None:
				return []
			return [r.name for r in (user.roles or [])]
		except Exception as exc:
			log.debug("_get_user_role_names(%s): %s", user_id, exc)
			return []

	# ------------------------------------------------------------------
	# analyze_user
	# ------------------------------------------------------------------

	def analyze_user(
		self,
		user_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Detect active SoD violations for *user_id*.

		Checks each active SodConflict: if the user's role names contain a
		prefix match for both function_a AND function_b the conflict fires.

		Returns a list of dicts:
		  {conflict_id, conflict_name, risk_level, function_a, function_b,
		   existing_violation_id}
		"""
		from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation

		role_names = self._get_user_role_names(user_id)
		role_names_lower = [r.lower() for r in role_names]

		conflicts = session.execute(
			select(SodConflict).where(
				SodConflict.tenant_id == tenant_id,
				SodConflict.is_active.is_(True),
			)
		).scalars().all()

		violations: list[dict] = []
		for conflict in conflicts:
			fa = conflict.function_a.lower()
			fb = conflict.function_b.lower()
			has_a = any(rn.startswith(fa) or fa.startswith(rn) for rn in role_names_lower)
			has_b = any(rn.startswith(fb) or fb.startswith(rn) for rn in role_names_lower)
			if not (has_a and has_b):
				continue

			# Check for existing open violation
			existing = session.execute(
				select(SodViolation).where(
					SodViolation.tenant_id == tenant_id,
					SodViolation.user_id == user_id,
					SodViolation.conflict_id == conflict.id,
					SodViolation.status == "OPEN",
				)
			).scalar_one_or_none()

			violations.append({
				"conflict_id": conflict.id,
				"conflict_name": conflict.name,
				"risk_level": conflict.risk_level,
				"function_a": conflict.function_a,
				"function_b": conflict.function_b,
				"existing_violation_id": existing.id if existing else None,
			})
		return violations

	# ------------------------------------------------------------------
	# simulate_role_grant
	# ------------------------------------------------------------------

	def simulate_role_grant(
		self,
		user_id: str,
		new_role_name: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Hypothetically add *new_role_name* and check for new SoD conflicts.

		Returns:
		  {would_create_violations: list[dict], safe_to_grant: bool}
		"""
		from pgappforge.plugins.erp.grc.sod.models import SodConflict
		from pgappforge.plugins.erp.grc.sod.events import SodSimulationRunEvent

		role_names = self._get_user_role_names(user_id)
		hypothetical = [r.lower() for r in role_names] + [new_role_name.lower()]

		conflicts = session.execute(
			select(SodConflict).where(
				SodConflict.tenant_id == tenant_id,
				SodConflict.is_active.is_(True),
			)
		).scalars().all()

		new_violations: list[dict] = []
		for conflict in conflicts:
			fa = conflict.function_a.lower()
			fb = conflict.function_b.lower()
			has_a = any(rn.startswith(fa) or fa.startswith(rn) for rn in hypothetical)
			has_b = any(rn.startswith(fb) or fb.startswith(rn) for rn in hypothetical)
			if has_a and has_b:
				new_violations.append({
					"conflict_name": conflict.name,
					"risk_level": conflict.risk_level,
					"function_a": conflict.function_a,
					"function_b": conflict.function_b,
				})

		_emit(
			SodSimulationRunEvent(
				aggregate_id=user_id,
				aggregate_type="User",
				tenant_id=tenant_id,
				user_id=user_id,
				new_role=new_role_name,
				would_create_violations=new_violations,
			),
			session,
		)
		return {
			"would_create_violations": new_violations,
			"safe_to_grant": len(new_violations) == 0,
		}

	# ------------------------------------------------------------------
	# bulk_scan
	# ------------------------------------------------------------------

	def bulk_scan(self, tenant_id: str, session: Any) -> dict:
		"""Scan all FAB users for SoD violations.

		Creates new SodViolation rows for previously undetected violations.
		Emits SodBulkScanCompletedEvent.

		Returns:
		  {users_scanned, violations_found, critical_count, new_violations}
		"""
		from pgappforge.plugins.erp.grc.sod.models import SodViolation
		from pgappforge.plugins.erp.grc.sod.events import (
			SodBulkScanCompletedEvent,
			SodViolationDetectedEvent,
		)

		users: list[Any] = []
		try:
			from flask import current_app
			users = current_app.appbuilder.sm.get_all_users()
		except Exception as exc:
			log.warning("bulk_scan: could not retrieve users from FAB SM: %s", exc)

		users_scanned = 0
		violations_found = 0
		critical_count = 0
		new_violations = 0

		for user in users:
			user_id = str(getattr(user, "id", "") or "")
			if not user_id:
				continue
			users_scanned += 1
			detected = self.analyze_user(user_id, tenant_id, session)
			for viol in detected:
				violations_found += 1
				if viol["risk_level"] == "CRITICAL":
					critical_count += 1
				if viol["existing_violation_id"] is None:
					# Create new violation row
					role_names = self._get_user_role_names(user_id)
					v = SodViolation(
						tenant_id=tenant_id,
						user_id=user_id,
						conflict_id=viol["conflict_id"],
						risk_level=viol["risk_level"],
						role_ids=role_names,
						detected_at=datetime.now(timezone.utc),
						status="OPEN",
					)
					session.add(v)
					session.flush()
					new_violations += 1
					_emit(
						SodViolationDetectedEvent(
							aggregate_id=v.id,
							aggregate_type="SodViolation",
							tenant_id=tenant_id,
							violation_id=v.id,
							user_id=user_id,
							conflict_name=viol["conflict_name"],
							risk_level=viol["risk_level"],
						),
						session,
					)

		_emit(
			SodBulkScanCompletedEvent(
				aggregate_id=tenant_id,
				aggregate_type="Tenant",
				tenant_id=tenant_id,
				violations_found=violations_found,
				users_scanned=users_scanned,
			),
			session,
		)
		return {
			"users_scanned": users_scanned,
			"violations_found": violations_found,
			"critical_count": critical_count,
			"new_violations": new_violations,
		}

	# ------------------------------------------------------------------
	# accept_risk
	# ------------------------------------------------------------------

	def accept_risk(
		self,
		violation_id: str,
		accepted_by: str,
		mitigating_control: str,
		session: Any,
	) -> Any:
		"""Mark a violation as RISK_ACCEPTED with a documented mitigating control."""
		from pgappforge.plugins.erp.grc.sod.models import SodViolation
		from pgappforge.plugins.erp.grc.sod.events import SodRiskAcceptedEvent

		v = session.execute(
			select(SodViolation).where(SodViolation.id == violation_id)
		).scalar_one_or_none()
		if v is None:
			raise ValueError(f"SodViolation {violation_id!r} not found")

		v.status = "RISK_ACCEPTED"
		v.accepted_by = accepted_by
		v.accepted_at = datetime.now(timezone.utc)
		v.mitigating_control = mitigating_control
		session.flush()

		_emit(
			SodRiskAcceptedEvent(
				aggregate_id=v.id,
				aggregate_type="SodViolation",
				tenant_id=v.tenant_id,
				violation_id=v.id,
				accepted_by=accepted_by,
				mitigating_control=mitigating_control,
			),
			session,
		)
		return v


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"grc.sod.simulate_role_grant",
	"Simulate SoD violations before granting role",
)
def _bpm_sod_simulate(
	record_ctx: dict,
	session: Any,
	user_id: str = "",
	new_role_name: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService
	except ImportError:
		return {"status": "error", "message": "grc.sod plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		result = SodAnalyzerService().simulate_role_grant(
			user_id=user_id,
			new_role_name=new_role_name,
			tenant_id=tenant_id,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm sod.simulate_role_grant failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"grc.sod.bulk_scan",
	"Scan all users for SoD violations",
)
def _bpm_sod_bulk_scan(
	record_ctx: dict,
	session: Any,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService
	except ImportError:
		return {"status": "error", "message": "grc.sod plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		result = SodAnalyzerService().bulk_scan(
			tenant_id=tenant_id,
			session=session,
		)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm sod.bulk_scan failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["SodAnalyzerService"]
