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

# Each row: (name, function_a, function_b, risk_level, control_category)
_DEFAULT_CONFLICTS: list[tuple[str, str, str, str, str]] = [
	# PROCURE_TO_PAY
	("P2P-01", "Create Purchase Requisition", "Approve Purchase Requisition", "HIGH",     "PROCURE_TO_PAY"),
	("P2P-02", "Create Purchase Order",       "Approve Purchase Order",       "CRITICAL", "PROCURE_TO_PAY"),
	("P2P-03", "Create Purchase Order",       "Receive Goods (GRN)",          "HIGH",     "PROCURE_TO_PAY"),
	("P2P-04", "Approve Purchase Order",      "Process Supplier Invoice",     "CRITICAL", "PROCURE_TO_PAY"),
	("P2P-05", "Create Supplier Record",      "Approve Supplier Payment",     "CRITICAL", "PROCURE_TO_PAY"),
	# RECORD_TO_REPORT
	("R2R-01", "Create GL Journal",           "Approve GL Journal",           "CRITICAL", "RECORD_TO_REPORT"),
	("R2R-02", "Create GL Journal",           "Post GL Journal",              "HIGH",     "RECORD_TO_REPORT"),
	("R2R-03", "Create Bank Account",         "Authorize Bank Payment",       "CRITICAL", "RECORD_TO_REPORT"),
	("R2R-04", "Manage Chart of Accounts",    "Post Journal Entries",         "HIGH",     "RECORD_TO_REPORT"),
	# ORDER_TO_CASH
	("O2C-01", "Create Customer Record",      "Create Sales Invoice",         "HIGH",     "ORDER_TO_CASH"),
	("O2C-02", "Create Sales Invoice",        "Apply Customer Payment",       "CRITICAL", "ORDER_TO_CASH"),
	("O2C-03", "Create Credit Note",          "Approve Credit Note",          "HIGH",     "ORDER_TO_CASH"),
	("O2C-04", "Approve Customer Credit Limit", "Create Sales Order",         "MEDIUM",   "ORDER_TO_CASH"),
	# PAYROLL
	("PAY-01", "Create Employee Record",      "Approve Payroll Run",          "CRITICAL", "PAYROLL"),
	("PAY-02", "Approve Payroll Run",         "Process Payroll Payment",      "CRITICAL", "PAYROLL"),
	("PAY-03", "Modify Salary/Pay Rate",      "Approve Payroll Run",          "CRITICAL", "PAYROLL"),
	("PAY-04", "Create Employee Record",      "Modify Salary/Pay Rate",       "HIGH",     "PAYROLL"),
	# ACCESS
	("ACC-01", "Create User Account",         "Assign User Roles",            "HIGH",     "ACCESS"),
	("ACC-02", "Reset User Password",         "Assign User Roles",            "MEDIUM",   "ACCESS"),
	("ACC-03", "Create System Configuration", "Approve System Changes",       "HIGH",     "ACCESS"),
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
			name, func_a, func_b, risk, category = defn
			existing = session.execute(
				select(SodConflict).where(
					SodConflict.tenant_id == tenant_id,
					SodConflict.name == name,
				)
			).scalar_one_or_none()
			if existing is not None:
				continue
			session.add(SodConflict(
				tenant_id=tenant_id,
				name=name,
				function_a=func_a,
				function_b=func_b,
				risk_level=risk,
				control_category=category,
				description=f"{func_a} + {func_b} — {risk} risk",
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
