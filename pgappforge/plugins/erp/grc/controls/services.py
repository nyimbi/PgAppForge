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


__all__ = [
	"ControlsService",
	"ControlsServiceError",
	"FrameworkNotFoundError",
	"ControlNotFoundError",
	"SoDConflictError",
	"TestResultInvalidError",
]
