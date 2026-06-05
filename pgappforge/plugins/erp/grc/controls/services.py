"""
pgappforge/plugins/erp/grc/controls/services.py

ControlsService — stateless service for GRC Controls domain.

Responsibilities:
  - ControlFramework + Control CRUD
  - ControlTest recording with deficiency tracking
  - SoD conflict detection for role assignment
  - Control effectiveness reporting
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ControlsServiceError(Exception):
	"""Base error for GRC Controls domain violations."""


class FrameworkNotFoundError(ControlsServiceError):
	"""No ControlFramework with the given id."""


class ControlNotFoundError(ControlsServiceError):
	"""No Control with the given id."""


class SoDConflictError(ControlsServiceError):
	"""Role assignment violates a SoD rule."""


class TestResultInvalidError(ControlsServiceError):
	"""test_result not in EFFECTIVE|INEFFECTIVE|NOT_TESTED."""


# ---------------------------------------------------------------------------
# ControlsService
# ---------------------------------------------------------------------------

class ControlsService:
	"""Stateless GRC Controls service."""

	VALID_TEST_RESULTS = frozenset({"EFFECTIVE", "INEFFECTIVE", "NOT_TESTED"})
	VALID_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})

	# ------------------------------------------------------------------
	# Control Framework
	# ------------------------------------------------------------------

	def create_framework(
		self,
		session: Any,
		tenant_id: str,
		name: str,
		version: str,
		description: str | None = None,
	) -> dict:
		"""Create a control framework."""
		from pgappforge.plugins.erp.grc.controls.models import ControlFramework
		fw = ControlFramework(
			tenant_id=tenant_id,
			name=name,
			version=version,
			description=description,
			is_active=True,
		)
		session.add(fw)
		session.flush()
		log.info("ControlsService: created framework %r v%r", name, version)
		return {"framework_id": fw.id, "status": "created"}

	# ------------------------------------------------------------------
	# Control
	# ------------------------------------------------------------------

	def create_control(
		self,
		session: Any,
		tenant_id: str,
		framework_id: str,
		control_code: str,
		control_name: str,
		control_objective: str,
		control_type: str,
		frequency: str,
		automated: bool = False,
		owner_id: str | None = None,
	) -> dict:
		"""Create a control within a framework.

		Emits ControlCreatedEvent.
		"""
		from pgappforge.plugins.erp.grc.controls.models import Control, ControlFramework
		from pgappforge.plugins.erp.grc.controls.events import ControlCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		fw = session.get(ControlFramework, framework_id)
		if fw is None:
			raise FrameworkNotFoundError(
				f"ControlFramework {framework_id!r} not found"
			)

		valid_types = {"PREVENTIVE", "DETECTIVE", "CORRECTIVE"}
		if control_type not in valid_types:
			raise ControlsServiceError(
				f"control_type must be one of {valid_types}, got {control_type!r}"
			)

		valid_freqs = {"CONTINUOUS", "DAILY", "MONTHLY", "QUARTERLY", "ANNUAL"}
		if frequency not in valid_freqs:
			raise ControlsServiceError(
				f"frequency must be one of {valid_freqs}, got {frequency!r}"
			)

		control = Control(
			tenant_id=tenant_id,
			framework_id=framework_id,
			control_code=control_code,
			control_name=control_name,
			control_objective=control_objective,
			control_type=control_type,
			frequency=frequency,
			automated=automated,
			owner_id=owner_id,
			status="ACTIVE",
		)
		session.add(control)
		session.flush()

		emit_event(
			ControlCreatedEvent(
				aggregate_id=control.id,
				aggregate_type="Control",
				tenant_id=tenant_id,
				control_id=control.id,
				control_code=control_code,
				framework_id=framework_id,
				control_type=control_type,
				frequency=frequency,
			),
			session,
		)
		return {"control_id": control.id, "status": "created"}

	def set_control_status(
		self,
		session: Any,
		control_id: str,
		new_status: str,
	) -> dict:
		"""Activate or deactivate a control."""
		from pgappforge.plugins.erp.grc.controls.models import Control
		from pgappforge.plugins.erp.grc.controls.events import ControlStatusChangedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if new_status not in ("ACTIVE", "INACTIVE"):
			raise ControlsServiceError(
				f"status must be ACTIVE|INACTIVE, got {new_status!r}"
			)
		control = session.get(Control, control_id)
		if control is None:
			raise ControlNotFoundError(f"Control {control_id!r} not found")

		old_status = control.status
		control.status = new_status

		emit_event(
			ControlStatusChangedEvent(
				aggregate_id=control_id,
				aggregate_type="Control",
				tenant_id=str(control.tenant_id),
				control_id=control_id,
				control_code=control.control_code,
				old_status=old_status,
				new_status=new_status,
			),
			session,
		)
		return {
			"control_id": control_id,
			"old_status": old_status,
			"new_status": new_status,
		}

	# ------------------------------------------------------------------
	# Control Test
	# ------------------------------------------------------------------

	def record_test(
		self,
		session: Any,
		tenant_id: str,
		control_id: str,
		test_date: date,
		tester_id: str | None,
		test_result: str,
		evidence_urls: list[str] | None = None,
		deficiencies_noted: str | None = None,
		remediation_due: date | None = None,
	) -> dict:
		"""Record a control test result.

		Emits ControlTestCompletedEvent; if deficiencies_noted is non-empty,
		also emits ControlDeficiencyNotedEvent.
		"""
		from pgappforge.plugins.erp.grc.controls.models import Control, ControlTest
		from pgappforge.plugins.erp.grc.controls.events import (
			ControlTestCompletedEvent,
			ControlDeficiencyNotedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		if test_result not in self.VALID_TEST_RESULTS:
			raise TestResultInvalidError(
				f"test_result must be one of {self.VALID_TEST_RESULTS}"
			)

		control = session.get(Control, control_id)
		if control is None:
			raise ControlNotFoundError(f"Control {control_id!r} not found")

		test = ControlTest(
			tenant_id=tenant_id,
			control_id=control_id,
			test_date=test_date,
			tester_id=tester_id,
			test_result=test_result,
			evidence_urls=evidence_urls or [],
			deficiencies_noted=deficiencies_noted,
			remediation_due=remediation_due,
		)
		session.add(test)
		session.flush()

		emit_event(
			ControlTestCompletedEvent(
				aggregate_id=test.id,
				aggregate_type="ControlTest",
				tenant_id=tenant_id,
				test_id=test.id,
				control_id=control_id,
				control_code=control.control_code,
				test_date=test_date.isoformat(),
				test_result=test_result,
			),
			session,
		)

		if deficiencies_noted:
			emit_event(
				ControlDeficiencyNotedEvent(
					aggregate_id=test.id,
					aggregate_type="ControlTest",
					tenant_id=tenant_id,
					test_id=test.id,
					control_id=control_id,
					control_code=control.control_code,
					deficiency_summary=deficiencies_noted[:500],
					remediation_due=remediation_due.isoformat() if remediation_due else "",
				),
				session,
			)

		return {"test_id": test.id, "test_result": test_result, "status": "recorded"}

	# ------------------------------------------------------------------
	# SoD Conflict Detection
	# ------------------------------------------------------------------

	def check_sod_conflict(
		self,
		session: Any,
		tenant_id: str,
		role_a: str,
		role_b: str,
	) -> dict:
		"""Check whether (role_a, role_b) pair violates a SoD rule.

		Checks both (role_a, role_b) and (role_b, role_a) since the pair is
		bidirectional.

		Returns: {"conflict": bool, "risk_level": str|None, "conflict_type": str|None}
		"""
		from pgappforge.plugins.erp.grc.controls.models import SegregationOfDuties

		conflict = session.execute(
			select(SegregationOfDuties).where(
				SegregationOfDuties.tenant_id == tenant_id,
				SegregationOfDuties.is_active.is_(True),
				sa.or_(
					sa.and_(
						SegregationOfDuties.role_a == role_a,
						SegregationOfDuties.role_b == role_b,
					),
					sa.and_(
						SegregationOfDuties.role_a == role_b,
						SegregationOfDuties.role_b == role_a,
					),
				),
			)
		).scalar_one_or_none()

		if conflict:
			return {
				"conflict": True,
				"risk_level": conflict.risk_level,
				"conflict_type": conflict.conflict_type,
				"sod_id": conflict.id,
			}
		return {"conflict": False, "risk_level": None, "conflict_type": None}

	def register_sod_rule(
		self,
		session: Any,
		tenant_id: str,
		role_a: str,
		role_b: str,
		conflict_type: str,
		risk_level: str = "HIGH",
	) -> dict:
		"""Register a new SoD conflict rule."""
		from pgappforge.plugins.erp.grc.controls.models import SegregationOfDuties

		if risk_level not in self.VALID_RISK_LEVELS:
			raise ControlsServiceError(
				f"risk_level must be one of {self.VALID_RISK_LEVELS}"
			)

		sod = SegregationOfDuties(
			tenant_id=tenant_id,
			role_a=role_a,
			role_b=role_b,
			conflict_type=conflict_type,
			risk_level=risk_level,
			is_active=True,
		)
		session.add(sod)
		session.flush()
		log.info(
			"ControlsService: registered SoD rule %r ⚡ %r risk=%r",
			role_a, role_b, risk_level,
		)
		return {"sod_id": sod.id, "status": "created"}

	# ------------------------------------------------------------------
	# Reporting
	# ------------------------------------------------------------------

	def get_control_effectiveness_summary(
		self,
		session: Any,
		tenant_id: str,
		framework_id: str | None = None,
		since_date: date | None = None,
	) -> list[dict]:
		"""Return per-control effectiveness counts (EFFECTIVE/INEFFECTIVE/NOT_TESTED).

		Used by the Controls Effectiveness Report.
		"""
		from pgappforge.plugins.erp.grc.controls.models import Control, ControlTest

		q = (
			select(
				Control.id.label("control_id"),
				Control.control_code,
				Control.control_name,
				Control.control_type,
				Control.frequency,
				ControlTest.test_result,
				func.count().label("count"),
			)
			.join(ControlTest, ControlTest.control_id == Control.id)
			.where(Control.tenant_id == tenant_id)
			.group_by(
				Control.id,
				Control.control_code,
				Control.control_name,
				Control.control_type,
				Control.frequency,
				ControlTest.test_result,
			)
			.order_by(Control.control_code)
		)

		if framework_id:
			q = q.where(Control.framework_id == framework_id)
		if since_date:
			q = q.where(ControlTest.test_date >= since_date)

		rows = session.execute(q).all()

		# Pivot into per-control dicts
		result: dict[str, dict] = {}
		for row in rows:
			key = row.control_id
			if key not in result:
				result[key] = {
					"control_id": row.control_id,
					"control_code": row.control_code,
					"control_name": row.control_name,
					"control_type": row.control_type,
					"frequency": row.frequency,
					"EFFECTIVE": 0,
					"INEFFECTIVE": 0,
					"NOT_TESTED": 0,
				}
			result[key][row.test_result] = row.count

		return list(result.values())

	# ------------------------------------------------------------------
	# Risk Register
	# ------------------------------------------------------------------

	@staticmethod
	def _risk_level_from_score(score: int) -> str:
		if score <= 4:
			return "LOW"
		if score <= 9:
			return "MEDIUM"
		if score <= 16:
			return "HIGH"
		return "CRITICAL"

	def create_risk(
		self,
		session: Any,
		data: dict,
		tenant_id: str,
	) -> Any:
		"""Create a RiskRegister entry.

		Required keys in data:
		  risk_code, title, description, risk_category,
		  likelihood (1-5), impact (1-5), treatment,
		  risk_owner_id, review_date.

		Optional: risk_appetite_level (default MEDIUM), status (default OPEN),
		          residual_likelihood, residual_impact (default == inherent).

		Auto-computes:
		  risk_score = likelihood × impact
		  inherent_risk_level and residual_risk_level from score thresholds.
		"""
		from pgappforge.plugins.erp.grc.controls.models import RiskRegister

		likelihood: int = int(data["likelihood"])
		impact: int = int(data["impact"])
		assert 1 <= likelihood <= 5, "likelihood must be 1–5"
		assert 1 <= impact <= 5, "impact must be 1–5"

		risk_score = likelihood * impact
		inherent_level = self._risk_level_from_score(risk_score)

		# Residual may differ if mitigating controls are already in place
		res_likelihood = int(data.get("residual_likelihood", likelihood))
		res_impact = int(data.get("residual_impact", impact))
		residual_score = res_likelihood * res_impact
		residual_level = self._risk_level_from_score(residual_score)

		valid_categories = {
			"STRATEGIC", "OPERATIONAL", "FINANCIAL",
			"COMPLIANCE", "REPUTATIONAL", "TECHNOLOGY",
		}
		risk_category = data["risk_category"]
		if risk_category not in valid_categories:
			raise ControlsServiceError(
				f"risk_category must be one of {valid_categories}"
			)

		valid_treatments = {"ACCEPT", "MITIGATE", "TRANSFER", "AVOID"}
		treatment = data.get("treatment", "MITIGATE")
		if treatment not in valid_treatments:
			raise ControlsServiceError(
				f"treatment must be one of {valid_treatments}"
			)

		risk = RiskRegister(
			tenant_id=tenant_id,
			risk_code=data["risk_code"],
			title=data["title"],
			description=data["description"],
			risk_category=risk_category,
			likelihood=likelihood,
			impact=impact,
			risk_score=risk_score,
			inherent_risk_level=inherent_level,
			residual_risk_level=residual_level,
			risk_appetite_level=data.get("risk_appetite_level", "MEDIUM"),
			treatment=treatment,
			risk_owner_id=data["risk_owner_id"],
			review_date=data["review_date"],
			status=data.get("status", "OPEN"),
		)
		session.add(risk)
		session.flush()
		log.info(
			"RiskRegister created: %r score=%d level=%s",
			risk.risk_code, risk_score, residual_level,
		)
		return risk

	# ------------------------------------------------------------------
	# Control Assessment (replaces / extends record_test for spec API)
	# ------------------------------------------------------------------

	def assess_control(
		self,
		session: Any,
		control_id: str,
		test_data: dict,
		tenant_id: str,
	) -> Any:
		"""Test a control and update its effectiveness status.

		test_data keys:
		  test_date (date), tested_by (UUID str), test_method, population_size,
		  sample_size, exceptions_found, evidence_ref (optional), notes (optional).

		Exception-rate thresholds:
		  exceptions_found == 0              → PASSED  (control EFFECTIVE)
		  0 < rate < 20%                     → QUALIFIED (control PARTIALLY_EFFECTIVE)
		  rate >= 20%                        → FAILED  (control INEFFECTIVE)

		Updates control.status accordingly.

		Returns ControlTest (the new test record).
		"""
		from pgappforge.plugins.erp.grc.controls.models import Control, ControlTest

		control = session.get(Control, control_id)
		if control is None:
			raise ControlNotFoundError(f"Control {control_id!r} not found")

		sample_size: int = int(test_data["sample_size"])
		exceptions_found: int = int(test_data.get("exceptions_found", 0))
		assert sample_size > 0, "sample_size must be positive"
		assert exceptions_found >= 0, "exceptions_found must be non-negative"

		exception_rate = exceptions_found / sample_size
		if exceptions_found == 0:
			conclusion = "PASSED"
			new_control_status = "EFFECTIVE"
		elif exception_rate >= 0.20:
			conclusion = "FAILED"
			new_control_status = "INEFFECTIVE"
		else:
			conclusion = "QUALIFIED"
			new_control_status = "PARTIALLY_EFFECTIVE"

		valid_methods = {"OBSERVATION", "INQUIRY", "INSPECTION", "REPERFORMANCE"}
		test_method = test_data.get("test_method", "INSPECTION")
		if test_method not in valid_methods:
			raise ControlsServiceError(
				f"test_method must be one of {valid_methods}"
			)

		test = ControlTest(
			tenant_id=tenant_id,
			control_id=control_id,
			test_date=test_data["test_date"],
			tester_id=str(test_data["tested_by"]),
			# Map new conclusion vocabulary to legacy test_result
			test_result=(
				"EFFECTIVE" if conclusion == "PASSED"
				else "INEFFECTIVE" if conclusion == "FAILED"
				else "INEFFECTIVE"  # QUALIFIED maps to INEFFECTIVE for legacy compat
			),
			evidence_urls=[test_data["evidence_ref"]] if test_data.get("evidence_ref") else [],
			deficiencies_noted=test_data.get("notes"),
			remediation_due=None,
		)
		# Attach extended fields dynamically (columns added in gap-close)
		test.test_method = test_method  # type: ignore[attr-defined]
		test.population_size = int(test_data.get("population_size", sample_size))  # type: ignore[attr-defined]
		test.sample_size = sample_size  # type: ignore[attr-defined]
		test.exceptions_found = exceptions_found  # type: ignore[attr-defined]
		test.test_conclusion = conclusion  # type: ignore[attr-defined]

		session.add(test)

		# Update control effectiveness status
		control.status = new_control_status  # type: ignore[assignment]
		if hasattr(control, "updated_at"):
			control.updated_at = datetime.now(timezone.utc)

		session.flush()
		log.info(
			"Control %r assessed: conclusion=%s rate=%.1f%% → status=%s",
			control_id, conclusion, exception_rate * 100, new_control_status,
		)
		return test

	# ------------------------------------------------------------------
	# Audit Findings
	# ------------------------------------------------------------------

	def raise_finding(
		self,
		session: Any,
		control_id: str | None,
		finding_type: str,
		title: str,
		description: str,
		recommendation: str,
		priority: str,
		due_date: date,
		owner_id: str,
		tenant_id: str,
		risk_id: str | None = None,
	) -> Any:
		"""Create an AuditFinding linked to a control and/or risk.

		finding_type: DEFICIENCY | MATERIAL_WEAKNESS | SIGNIFICANT_DEFICIENCY | OBSERVATION
		priority:     HIGH | MEDIUM | LOW
		"""
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding

		valid_types = {
			"DEFICIENCY", "MATERIAL_WEAKNESS", "SIGNIFICANT_DEFICIENCY", "OBSERVATION",
		}
		if finding_type not in valid_types:
			raise ControlsServiceError(
				f"finding_type must be one of {valid_types}"
			)
		if priority not in {"HIGH", "MEDIUM", "LOW"}:
			raise ControlsServiceError("priority must be HIGH|MEDIUM|LOW")

		finding = AuditFinding(
			tenant_id=tenant_id,
			control_id=control_id,
			risk_id=risk_id,
			finding_type=finding_type,
			title=title,
			description=description,
			recommendation=recommendation,
			priority=priority,
			due_date=due_date,
			owner_id=owner_id,
			status="OPEN",
		)
		session.add(finding)
		session.flush()
		log.info(
			"AuditFinding raised: %r type=%s priority=%s",
			finding.id, finding_type, priority,
		)
		return finding

	def remediate_finding(
		self,
		session: Any,
		finding_id: str,
		management_response: str,
		tenant_id: str,
	) -> Any:
		"""Record management response and move finding to REMEDIATED.

		Sets management_response, status → REMEDIATED, closed_at → now.
		"""
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding

		finding = session.get(AuditFinding, finding_id)
		if finding is None:
			raise ControlsServiceError(f"AuditFinding {finding_id!r} not found")
		if str(finding.tenant_id) != str(tenant_id):
			raise ControlsServiceError("AuditFinding does not belong to this tenant")
		if finding.status in ("REMEDIATED", "ACCEPTED"):
			raise ControlsServiceError(
				f"Finding is already {finding.status!r}"
			)

		finding.management_response = management_response
		finding.status = "REMEDIATED"
		finding.closed_at = datetime.now(timezone.utc)
		if hasattr(finding, "updated_at"):
			finding.updated_at = datetime.now(timezone.utc)

		session.flush()
		log.info("AuditFinding %r remediated", finding_id)
		return finding

	# ------------------------------------------------------------------
	# Risk Heat Map
	# ------------------------------------------------------------------

	def get_risk_heat_map(
		self,
		session: Any,
		tenant_id: str,
	) -> list[dict]:
		"""Return all open risks for the heat map UI.

		Returns list of:
		{
		    "risk_id":    str,
		    "title":      str,
		    "x":          int,   # likelihood (1-5)
		    "y":          int,   # impact (1-5)
		    "score":      int,   # x × y
		    "level":      str,   # LOW|MEDIUM|HIGH|CRITICAL
		    "category":   str,
		    "treatment":  str,
		    "status":     str,
		}
		Sorted descending by score.
		"""
		from pgappforge.plugins.erp.grc.controls.models import RiskRegister

		q = (
			select(RiskRegister)
			.where(RiskRegister.tenant_id == tenant_id)
			.where(RiskRegister.status == "OPEN")
			.order_by(sa.desc(RiskRegister.risk_score))
		)
		risks = session.execute(q).scalars().all()

		return [
			{
				"risk_id": str(r.id),
				"title": r.title,
				"x": r.likelihood,
				"y": r.impact,
				"score": r.risk_score,
				"level": r.residual_risk_level,
				"category": r.risk_category,
				"treatment": r.treatment,
				"status": r.status,
			}
			for r in risks
		]

	# ------------------------------------------------------------------
	# Control Effectiveness Report (spec variant)
	# ------------------------------------------------------------------

	def get_control_effectiveness_report(
		self,
		session: Any,
		tenant_id: str,
	) -> dict:
		"""Controls effectiveness breakdown by status and COSO component.

		Returns:
		{
		    "by_status": {
		        "EFFECTIVE": int,
		        "PARTIALLY_EFFECTIVE": int,
		        "INEFFECTIVE": int,
		        "NOT_TESTED": int,
		    },
		    "by_coso_component": {
		        <component>: {"EFFECTIVE": int, ...},
		        ...
		    },
		    "total": int,
		}

		Note: Control.status reflects the latest assessed effectiveness.
		Controls never tested have status 'ACTIVE' (legacy) or will have
		no ControlTest rows — counted as NOT_TESTED.
		"""
		from pgappforge.plugins.erp.grc.controls.models import Control, ControlTest

		# All controls for tenant
		all_controls_q = select(Control).where(Control.tenant_id == tenant_id)
		all_controls = session.execute(all_controls_q).scalars().all()

		# Latest test result per control
		latest_test_subq = (
			select(
				ControlTest.control_id,
				func.max(ControlTest.test_date).label("max_date"),
			)
			.where(ControlTest.tenant_id == tenant_id)
			.group_by(ControlTest.control_id)
			.subquery()
		)
		latest_tests_q = (
			select(ControlTest)
			.join(
				latest_test_subq,
				sa.and_(
					ControlTest.control_id == latest_test_subq.c.control_id,
					ControlTest.test_date == latest_test_subq.c.max_date,
				),
			)
		)
		latest_tests = {
			str(t.control_id): t
			for t in session.execute(latest_tests_q).scalars().all()
		}

		by_status: dict[str, int] = {
			"EFFECTIVE": 0,
			"PARTIALLY_EFFECTIVE": 0,
			"INEFFECTIVE": 0,
			"NOT_TESTED": 0,
		}
		by_coso: dict[str, dict[str, int]] = {}

		effectiveness_map = {
			"EFFECTIVE": "EFFECTIVE",
			"INEFFECTIVE": "INEFFECTIVE",
			"NOT_TESTED": "NOT_TESTED",
			# Legacy status values
			"ACTIVE": "NOT_TESTED",
			"INACTIVE": "NOT_TESTED",
		}

		for control in all_controls:
			test = latest_tests.get(str(control.id))
			if test is None:
				eff_status = "NOT_TESTED"
			else:
				raw = test.test_result
				eff_status = effectiveness_map.get(raw, "NOT_TESTED")

			# Override with control.status if it carries extended values
			ctrl_status = getattr(control, "status", "ACTIVE")
			if ctrl_status in ("EFFECTIVE", "PARTIALLY_EFFECTIVE", "INEFFECTIVE"):
				eff_status = ctrl_status

			by_status[eff_status] = by_status.get(eff_status, 0) + 1

			# COSO breakdown
			coso = getattr(control, "coso_component", None) or "UNCLASSIFIED"
			if coso not in by_coso:
				by_coso[coso] = {
					"EFFECTIVE": 0,
					"PARTIALLY_EFFECTIVE": 0,
					"INEFFECTIVE": 0,
					"NOT_TESTED": 0,
				}
			by_coso[coso][eff_status] = by_coso[coso].get(eff_status, 0) + 1

		return {
			"by_status": by_status,
			"by_coso_component": by_coso,
			"total": len(all_controls),
		}

	# ------------------------------------------------------------------
	# GRC Dashboard
	# ------------------------------------------------------------------

	def get_grc_dashboard(
		self,
		session: Any,
		tenant_id: str,
	) -> dict:
		"""High-level GRC dashboard KPIs.

		Returns:
		{
		    "open_risks_by_level":     {"LOW": int, "MEDIUM": int, "HIGH": int, "CRITICAL": int},
		    "open_findings_by_priority": {"HIGH": int, "MEDIUM": int, "LOW": int},
		    "controls_due_test_30d":   int,   # ACTIVE controls whose last test was >30d ago
		    "overdue_findings":        int,   # OPEN/IN_PROGRESS findings past due_date
		    "policies_due_review":     int,   # EFFECTIVE policies with review_date <= today+30d
		}
		"""
		from pgappforge.plugins.erp.grc.controls.models import (
			AuditFinding, Control, ControlTest, PolicyDocument, RiskRegister,
		)

		today = date.today()
		horizon_30d = date(today.year, today.month, today.day)
		# Simple 30-day horizon: use timedelta
		from datetime import timedelta
		horizon_30d = today + timedelta(days=30)

		# Open risks by level
		risk_q = (
			select(RiskRegister.residual_risk_level, func.count().label("cnt"))
			.where(RiskRegister.tenant_id == tenant_id)
			.where(RiskRegister.status == "OPEN")
			.group_by(RiskRegister.residual_risk_level)
		)
		risk_rows = session.execute(risk_q).all()
		open_risks_by_level: dict[str, int] = {
			"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0,
		}
		for row in risk_rows:
			open_risks_by_level[row.residual_risk_level] = row.cnt

		# Open findings by priority
		finding_q = (
			select(AuditFinding.priority, func.count().label("cnt"))
			.where(AuditFinding.tenant_id == tenant_id)
			.where(AuditFinding.status.in_(["OPEN", "IN_PROGRESS"]))
			.group_by(AuditFinding.priority)
		)
		finding_rows = session.execute(finding_q).all()
		open_findings_by_priority: dict[str, int] = {
			"HIGH": 0, "MEDIUM": 0, "LOW": 0,
		}
		for row in finding_rows:
			open_findings_by_priority[row.priority] = row.cnt

		# Controls due test in 30d: latest test older than 30d ago (or never tested)
		# Use a subquery to find the max test_date per control
		latest_test_subq = (
			select(
				ControlTest.control_id,
				func.max(ControlTest.test_date).label("last_tested"),
			)
			.where(ControlTest.tenant_id == tenant_id)
			.group_by(ControlTest.control_id)
			.subquery()
		)
		cutoff = today - __import__("datetime").timedelta(days=30)
		controls_due_q = (
			select(func.count())
			.select_from(Control)
			.outerjoin(latest_test_subq, Control.id == latest_test_subq.c.control_id)
			.where(Control.tenant_id == tenant_id)
			.where(Control.status.in_(["ACTIVE", "EFFECTIVE", "PARTIALLY_EFFECTIVE", "INEFFECTIVE"]))
			.where(
				sa.or_(
					latest_test_subq.c.last_tested.is_(None),
					latest_test_subq.c.last_tested <= cutoff,
				)
			)
		)
		controls_due_test_30d: int = session.execute(controls_due_q).scalar_one()

		# Overdue findings
		overdue_findings_q = (
			select(func.count())
			.select_from(AuditFinding)
			.where(AuditFinding.tenant_id == tenant_id)
			.where(AuditFinding.status.in_(["OPEN", "IN_PROGRESS"]))
			.where(AuditFinding.due_date < today)
		)
		overdue_findings: int = session.execute(overdue_findings_q).scalar_one()

		# Policies due review (EFFECTIVE, review_date within 30d)
		policies_due_q = (
			select(func.count())
			.select_from(PolicyDocument)
			.where(PolicyDocument.tenant_id == tenant_id)
			.where(PolicyDocument.status == "EFFECTIVE")
			.where(PolicyDocument.review_date <= horizon_30d)
		)
		policies_due_review: int = session.execute(policies_due_q).scalar_one()

		return {
			"open_risks_by_level": open_risks_by_level,
			"open_findings_by_priority": open_findings_by_priority,
			"controls_due_test_30d": controls_due_test_30d,
			"overdue_findings": overdue_findings,
			"policies_due_review": policies_due_review,
		}


__all__ = [
	"ControlsService",
	"ControlsServiceError",
	"FrameworkNotFoundError",
	"ControlNotFoundError",
	"SoDConflictError",
	"TestResultInvalidError",
	# Methods on ControlsService (for discoverability):
	# create_framework, create_control, set_control_status,
	# record_test, check_sod_conflict, register_sod_rule,
	# get_control_effectiveness_summary,
	# create_risk, assess_control, raise_finding, remediate_finding,
	# get_risk_heat_map, get_control_effectiveness_report, get_grc_dashboard
]
