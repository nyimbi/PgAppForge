"""
tests/ci/test_grc_gap_close.py

Tests for gap-closed GRC Controls methods:
  - RiskRegister model
  - AuditFinding model
  - PolicyDocument model
  - ControlsService.create_risk
  - ControlsService.assess_control
  - ControlsService.raise_finding
  - ControlsService.remediate_finding
  - ControlsService.get_risk_heat_map
  - ControlsService.get_control_effectiveness_report
  - ControlsService.get_grc_dashboard
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

import pytest


def _uuid() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------

class TestRiskRegisterModel:
	def test_instantiation(self):
		from pgappforge.plugins.erp.grc.controls.models import RiskRegister
		tenant_id = _uuid()
		risk = RiskRegister(
			tenant_id=tenant_id,
			risk_code="RSK-001",
			title="FX Exposure Risk",
			description="Unhedged foreign currency positions",
			risk_category="FINANCIAL",
			likelihood=4,
			impact=5,
			risk_score=20,
			inherent_risk_level="CRITICAL",
			residual_risk_level="HIGH",
			risk_appetite_level="MEDIUM",
			treatment="MITIGATE",
			risk_owner_id=_uuid(),
			review_date=date(2026, 12, 31),
			status="OPEN",
		)
		assert risk.risk_code == "RSK-001"
		assert risk.risk_score == 20
		assert risk.residual_risk_level == "HIGH"

	def test_repr(self):
		from pgappforge.plugins.erp.grc.controls.models import RiskRegister
		risk = RiskRegister(
			tenant_id=_uuid(),
			risk_code="RSK-002",
			title="Fraud Risk",
			description="Internal fraud",
			risk_category="OPERATIONAL",
			likelihood=2,
			impact=4,
			risk_score=8,
			inherent_risk_level="MEDIUM",
			residual_risk_level="MEDIUM",
			risk_appetite_level="LOW",
			treatment="MITIGATE",
			risk_owner_id=_uuid(),
			review_date=date(2026, 6, 30),
			status="OPEN",
		)
		r = repr(risk)
		assert "RSK-002" in r

	def test_in_all_export(self):
		from pgappforge.plugins.erp.grc.controls import models
		assert "RiskRegister" in models.__all__


class TestAuditFindingModel:
	def test_instantiation(self):
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding
		finding = AuditFinding(
			tenant_id=_uuid(),
			control_id=_uuid(),
			finding_type="DEFICIENCY",
			title="Password policy not enforced",
			description="Users can set weak passwords",
			recommendation="Enforce minimum 12-char passwords",
			priority="HIGH",
			due_date=date(2026, 8, 31),
			owner_id=_uuid(),
			status="OPEN",
		)
		assert finding.finding_type == "DEFICIENCY"
		assert finding.status == "OPEN"

	def test_in_all_export(self):
		from pgappforge.plugins.erp.grc.controls import models
		assert "AuditFinding" in models.__all__


class TestPolicyDocumentModel:
	def test_instantiation(self):
		from pgappforge.plugins.erp.grc.controls.models import PolicyDocument
		policy = PolicyDocument(
			tenant_id=_uuid(),
			policy_code="POL-IT-001",
			title="Information Security Policy",
			category="IT",
			body="## 1. Purpose\nThis policy defines...",
			version="2.0",
			status="EFFECTIVE",
			effective_date=date(2026, 1, 1),
			review_date=date(2027, 1, 1),
			owner_id=_uuid(),
		)
		assert policy.policy_code == "POL-IT-001"
		assert policy.version == "2.0"
		assert policy.status == "EFFECTIVE"

	def test_repr(self):
		from pgappforge.plugins.erp.grc.controls.models import PolicyDocument
		policy = PolicyDocument(
			tenant_id=_uuid(),
			policy_code="POL-HR-002",
			title="Leave Policy",
			category="HR",
			body="Leave rules...",
			version="1.0",
			status="DRAFT",
			effective_date=date(2026, 6, 1),
			review_date=date(2027, 6, 1),
			owner_id=_uuid(),
		)
		r = repr(policy)
		assert "POL-HR-002" in r

	def test_in_all_export(self):
		from pgappforge.plugins.erp.grc.controls import models
		assert "PolicyDocument" in models.__all__


# ---------------------------------------------------------------------------
# ControlsService.create_risk
# ---------------------------------------------------------------------------

class TestCreateRisk:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_session(self) -> MagicMock:
		session = MagicMock()
		session.flush.return_value = None
		session.add.return_value = None
		return session

	def test_creates_risk_with_computed_score(self):
		session = self._make_session()
		data = {
			"risk_code": "RSK-001",
			"title": "Liquidity Risk",
			"description": "Short-term cash shortfall",
			"risk_category": "FINANCIAL",
			"likelihood": 3,
			"impact": 4,
			"treatment": "MITIGATE",
			"risk_owner_id": _uuid(),
			"review_date": date(2026, 12, 31),
		}
		risk = self.svc.create_risk(session, data, self.tenant_id)
		assert risk.risk_score == 12  # 3 × 4
		assert risk.inherent_risk_level == "HIGH"  # 10-16
		assert risk.residual_risk_level == "HIGH"
		session.add.assert_called_once_with(risk)
		session.flush.assert_called_once()

	def test_score_thresholds(self):
		"""Verify all four threshold bands."""
		session = self._make_session()
		svc = self.svc
		base = {
			"risk_code": "X",
			"title": "T",
			"description": "D",
			"risk_category": "OPERATIONAL",
			"treatment": "ACCEPT",
			"risk_owner_id": _uuid(),
			"review_date": date(2026, 12, 31),
		}
		cases = [
			(1, 1, "LOW"),      # score=1  → LOW  (1-4)
			(2, 2, "LOW"),      # score=4  → LOW  (boundary)
			(3, 2, "MEDIUM"),   # score=6  → MEDIUM (5-9)
			(4, 4, "HIGH"),     # score=16 → HIGH  (10-16 boundary)
			(5, 5, "CRITICAL"), # score=25 → CRITICAL (17-25)
		]
		for lkh, imp, expected_level in cases:
			session.add.reset_mock()
			session.flush.reset_mock()
			data = {**base, "likelihood": lkh, "impact": imp}
			risk = svc.create_risk(session, data, self.tenant_id)
			assert risk.residual_risk_level == expected_level, (
				f"likelihood={lkh} impact={imp} score={lkh*imp} "
				f"expected={expected_level} got={risk.residual_risk_level}"
			)

	def test_invalid_category_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		session = self._make_session()
		with pytest.raises(ControlsServiceError, match="risk_category"):
			self.svc.create_risk(session, {
				"risk_code": "X",
				"title": "T",
				"description": "D",
				"risk_category": "POLITICAL",
				"likelihood": 2,
				"impact": 2,
				"treatment": "ACCEPT",
				"risk_owner_id": _uuid(),
				"review_date": date(2026, 12, 31),
			}, self.tenant_id)

	def test_invalid_treatment_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		session = self._make_session()
		with pytest.raises(ControlsServiceError, match="treatment"):
			self.svc.create_risk(session, {
				"risk_code": "X",
				"title": "T",
				"description": "D",
				"risk_category": "FINANCIAL",
				"likelihood": 2,
				"impact": 2,
				"treatment": "IGNORE",
				"risk_owner_id": _uuid(),
				"review_date": date(2026, 12, 31),
			}, self.tenant_id)

	def test_likelihood_out_of_range_raises(self):
		session = self._make_session()
		with pytest.raises(AssertionError):
			self.svc.create_risk(session, {
				"risk_code": "X",
				"title": "T",
				"description": "D",
				"risk_category": "FINANCIAL",
				"likelihood": 6,  # invalid
				"impact": 3,
				"treatment": "MITIGATE",
				"risk_owner_id": _uuid(),
				"review_date": date(2026, 12, 31),
			}, self.tenant_id)


# ---------------------------------------------------------------------------
# ControlsService.assess_control
# ---------------------------------------------------------------------------

class TestAssessControl:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_control(self) -> MagicMock:
		ctrl = MagicMock()
		ctrl.id = _uuid()
		ctrl.tenant_id = self.tenant_id
		ctrl.control_code = "CTL-001"
		ctrl.status = "ACTIVE"
		ctrl.updated_at = None
		return ctrl

	def _make_session(self, control: MagicMock) -> MagicMock:
		from pgappforge.plugins.erp.grc.controls.models import Control
		session = MagicMock()
		session.flush.return_value = None
		session.add.return_value = None
		def _get(model, pk):
			if model is Control and pk == control.id:
				return control
			return None
		session.get.side_effect = _get
		return session

	def test_no_exceptions_gives_passed_effective(self):
		ctrl = self._make_control()
		session = self._make_session(ctrl)
		test = self.svc.assess_control(
			session=session,
			control_id=ctrl.id,
			test_data={
				"test_date": date(2026, 6, 1),
				"tested_by": _uuid(),
				"test_method": "INSPECTION",
				"population_size": 100,
				"sample_size": 25,
				"exceptions_found": 0,
			},
			tenant_id=self.tenant_id,
		)
		assert test.test_conclusion == "PASSED"
		assert ctrl.status == "EFFECTIVE"

	def test_rate_below_20pct_gives_qualified_partial(self):
		ctrl = self._make_control()
		session = self._make_session(ctrl)
		test = self.svc.assess_control(
			session=session,
			control_id=ctrl.id,
			test_data={
				"test_date": date(2026, 6, 1),
				"tested_by": _uuid(),
				"test_method": "REPERFORMANCE",
				"population_size": 200,
				"sample_size": 30,
				"exceptions_found": 3,  # 10% rate
			},
			tenant_id=self.tenant_id,
		)
		assert test.test_conclusion == "QUALIFIED"
		assert ctrl.status == "PARTIALLY_EFFECTIVE"

	def test_rate_at_20pct_gives_failed_ineffective(self):
		ctrl = self._make_control()
		session = self._make_session(ctrl)
		test = self.svc.assess_control(
			session=session,
			control_id=ctrl.id,
			test_data={
				"test_date": date(2026, 6, 1),
				"tested_by": _uuid(),
				"test_method": "OBSERVATION",
				"population_size": 50,
				"sample_size": 10,
				"exceptions_found": 2,  # 20% rate
			},
			tenant_id=self.tenant_id,
		)
		assert test.test_conclusion == "FAILED"
		assert ctrl.status == "INEFFECTIVE"

	def test_control_not_found_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlNotFoundError
		session = MagicMock()
		session.get.return_value = None
		with pytest.raises(ControlNotFoundError):
			self.svc.assess_control(
				session=session,
				control_id=_uuid(),
				test_data={
					"test_date": date(2026, 6, 1),
					"tested_by": _uuid(),
					"test_method": "INSPECTION",
					"population_size": 10,
					"sample_size": 5,
					"exceptions_found": 0,
				},
				tenant_id=self.tenant_id,
			)

	def test_invalid_test_method_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		ctrl = self._make_control()
		session = self._make_session(ctrl)
		with pytest.raises(ControlsServiceError, match="test_method"):
			self.svc.assess_control(
				session=session,
				control_id=ctrl.id,
				test_data={
					"test_date": date(2026, 6, 1),
					"tested_by": _uuid(),
					"test_method": "GUESSING",
					"population_size": 10,
					"sample_size": 5,
					"exceptions_found": 0,
				},
				tenant_id=self.tenant_id,
			)


# ---------------------------------------------------------------------------
# ControlsService.raise_finding / remediate_finding
# ---------------------------------------------------------------------------

class TestAuditFindings:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_session(self) -> MagicMock:
		session = MagicMock()
		session.flush.return_value = None
		session.add.return_value = None
		return session

	def test_raise_finding_creates_open_finding(self):
		session = self._make_session()
		finding = self.svc.raise_finding(
			session=session,
			control_id=_uuid(),
			finding_type="DEFICIENCY",
			title="Missing access log retention",
			description="Logs older than 30 days are deleted",
			recommendation="Retain logs for 12 months",
			priority="HIGH",
			due_date=date(2026, 9, 30),
			owner_id=_uuid(),
			tenant_id=self.tenant_id,
		)
		assert finding.status == "OPEN"
		assert finding.finding_type == "DEFICIENCY"
		session.add.assert_called_once_with(finding)

	def test_raise_finding_invalid_type_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		session = self._make_session()
		with pytest.raises(ControlsServiceError, match="finding_type"):
			self.svc.raise_finding(
				session=session,
				control_id=_uuid(),
				finding_type="CRITICAL_BUG",
				title="T",
				description="D",
				recommendation="R",
				priority="HIGH",
				due_date=date(2026, 9, 30),
				owner_id=_uuid(),
				tenant_id=self.tenant_id,
			)

	def test_raise_finding_invalid_priority_raises(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		session = self._make_session()
		with pytest.raises(ControlsServiceError, match="priority"):
			self.svc.raise_finding(
				session=session,
				control_id=_uuid(),
				finding_type="OBSERVATION",
				title="T",
				description="D",
				recommendation="R",
				priority="URGENT",
				due_date=date(2026, 9, 30),
				owner_id=_uuid(),
				tenant_id=self.tenant_id,
			)

	def test_raise_finding_with_risk_id(self):
		session = self._make_session()
		risk_id = _uuid()
		finding = self.svc.raise_finding(
			session=session,
			control_id=None,
			finding_type="OBSERVATION",
			title="Emerging cyber threat",
			description="Ransomware targeting ERP systems",
			recommendation="Patch within 30 days",
			priority="MEDIUM",
			due_date=date(2026, 7, 31),
			owner_id=_uuid(),
			tenant_id=self.tenant_id,
			risk_id=risk_id,
		)
		assert finding.risk_id == risk_id
		assert finding.control_id is None

	def test_remediate_finding(self):
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding
		finding = MagicMock(spec=AuditFinding)
		finding.id = _uuid()
		finding.tenant_id = self.tenant_id
		finding.status = "OPEN"
		finding.management_response = None
		finding.closed_at = None
		finding.updated_at = None

		session = MagicMock()
		session.flush.return_value = None
		def _get(model, pk):
			if model is AuditFinding and pk == finding.id:
				return finding
			return None
		session.get.side_effect = _get

		result = self.svc.remediate_finding(
			session=session,
			finding_id=finding.id,
			management_response="Access log retention extended to 13 months",
			tenant_id=self.tenant_id,
		)
		assert result.status == "REMEDIATED"
		assert result.management_response == "Access log retention extended to 13 months"
		assert result.closed_at is not None

	def test_remediate_already_remediated_raises(self):
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		finding = MagicMock(spec=AuditFinding)
		finding.id = _uuid()
		finding.tenant_id = self.tenant_id
		finding.status = "REMEDIATED"

		session = MagicMock()
		def _get(model, pk):
			return finding if model is AuditFinding else None
		session.get.side_effect = _get

		with pytest.raises(ControlsServiceError):
			self.svc.remediate_finding(
				session=session,
				finding_id=finding.id,
				management_response="Already done",
				tenant_id=self.tenant_id,
			)

	def test_remediate_wrong_tenant_raises(self):
		from pgappforge.plugins.erp.grc.controls.models import AuditFinding
		from pgappforge.plugins.erp.grc.controls.services import ControlsServiceError
		finding = MagicMock(spec=AuditFinding)
		finding.id = _uuid()
		finding.tenant_id = _uuid()  # different tenant
		finding.status = "OPEN"

		session = MagicMock()
		def _get(model, pk):
			return finding if model is AuditFinding else None
		session.get.side_effect = _get

		with pytest.raises(ControlsServiceError):
			self.svc.remediate_finding(
				session=session,
				finding_id=finding.id,
				management_response="Fix",
				tenant_id=self.tenant_id,
			)


# ---------------------------------------------------------------------------
# ControlsService.get_risk_heat_map
# ---------------------------------------------------------------------------

class TestGetRiskHeatMap:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_risk(self, likelihood: int, impact: int) -> MagicMock:
		from pgappforge.plugins.erp.grc.controls.services import ControlsService as _CS
		r = MagicMock()
		r.id = _uuid()
		r.title = f"Risk L{likelihood}I{impact}"
		r.likelihood = likelihood
		r.impact = impact
		r.risk_score = likelihood * impact
		r.residual_risk_level = _CS._risk_level_from_score(likelihood * impact)
		r.risk_category = "FINANCIAL"
		r.treatment = "MITIGATE"
		r.status = "OPEN"
		return r

	def test_heat_map_structure(self):
		risks = [self._make_risk(3, 4), self._make_risk(1, 2)]
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = risks
		session.execute.return_value = exec_result

		heat_map = self.svc.get_risk_heat_map(session, self.tenant_id)
		assert len(heat_map) == 2
		required_keys = {"risk_id", "title", "x", "y", "score", "level", "category", "treatment", "status"}
		for entry in heat_map:
			assert required_keys == set(entry.keys())

	def test_heat_map_values(self):
		risk = self._make_risk(4, 5)
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = [risk]
		session.execute.return_value = exec_result

		heat_map = self.svc.get_risk_heat_map(session, self.tenant_id)
		entry = heat_map[0]
		assert entry["x"] == 4
		assert entry["y"] == 5
		assert entry["score"] == 20
		assert entry["level"] == "CRITICAL"

	def test_empty_heat_map(self):
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = []
		session.execute.return_value = exec_result

		heat_map = self.svc.get_risk_heat_map(session, self.tenant_id)
		assert heat_map == []


# ---------------------------------------------------------------------------
# ControlsService.get_control_effectiveness_report
# ---------------------------------------------------------------------------

class TestGetControlEffectivenessReport:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_control(self, status: str) -> MagicMock:
		c = MagicMock()
		c.id = _uuid()
		c.tenant_id = self.tenant_id
		c.status = status
		c.coso_component = "CONTROL_ACTIVITIES"
		c.control_code = f"CTL-{_uuid()[:6]}"
		c.control_name = "Some control"
		c.control_type = "PREVENTIVE"
		c.frequency = "MONTHLY"
		return c

	def test_report_keys(self):
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = []
		session.execute.return_value = exec_result

		report = self.svc.get_control_effectiveness_report(session, self.tenant_id)
		assert "by_status" in report
		assert "by_coso_component" in report
		assert "total" in report

	def test_effective_control_counted(self):
		ctrl = self._make_control("EFFECTIVE")
		session = MagicMock()

		call_count = [0]
		def _exec(q):
			res = MagicMock()
			if call_count[0] == 0:
				# all_controls query
				res.scalars.return_value.all.return_value = [ctrl]
			else:
				# latest_tests query
				res.scalars.return_value.all.return_value = []
			call_count[0] += 1
			return res
		session.execute.side_effect = _exec

		report = self.svc.get_control_effectiveness_report(session, self.tenant_id)
		assert report["total"] == 1
		assert report["by_status"]["EFFECTIVE"] == 1

	def test_not_tested_control_counted(self):
		ctrl = self._make_control("ACTIVE")  # legacy status = not tested
		session = MagicMock()

		call_count = [0]
		def _exec(q):
			res = MagicMock()
			if call_count[0] == 0:
				res.scalars.return_value.all.return_value = [ctrl]
			else:
				res.scalars.return_value.all.return_value = []
			call_count[0] += 1
			return res
		session.execute.side_effect = _exec

		report = self.svc.get_control_effectiveness_report(session, self.tenant_id)
		assert report["by_status"]["NOT_TESTED"] == 1


# ---------------------------------------------------------------------------
# ControlsService.get_grc_dashboard
# ---------------------------------------------------------------------------

class TestGetGRCDashboard:
	def setup_method(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		self.svc = ControlsService()
		self.tenant_id = _uuid()

	def _make_session(self, scalar_values: list[int]) -> MagicMock:
		session = MagicMock()
		call_count = [0]

		def _exec(q):
			res = MagicMock()
			# Risk heat-map query returns rows with .residual_risk_level/.cnt
			res.all.return_value = []
			# scalar queries return values in order
			idx = call_count[0]
			res.scalar_one.return_value = scalar_values[idx] if idx < len(scalar_values) else 0
			call_count[0] += 1
			return res

		session.execute.side_effect = _exec
		return session

	def test_dashboard_keys(self):
		# Queries: risk by level (group-by), findings by priority (group-by),
		# controls_due_test, overdue_findings, policies_due_review
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.all.return_value = []
		exec_result.scalar_one.return_value = 0
		session.execute.return_value = exec_result

		dashboard = self.svc.get_grc_dashboard(session, self.tenant_id)
		assert set(dashboard.keys()) == {
			"open_risks_by_level",
			"open_findings_by_priority",
			"controls_due_test_30d",
			"overdue_findings",
			"policies_due_review",
		}

	def test_open_risks_by_level_initialized(self):
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.all.return_value = []
		exec_result.scalar_one.return_value = 0
		session.execute.return_value = exec_result

		dashboard = self.svc.get_grc_dashboard(session, self.tenant_id)
		levels = dashboard["open_risks_by_level"]
		assert set(levels.keys()) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

	def test_open_findings_by_priority_initialized(self):
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.all.return_value = []
		exec_result.scalar_one.return_value = 0
		session.execute.return_value = exec_result

		dashboard = self.svc.get_grc_dashboard(session, self.tenant_id)
		priorities = dashboard["open_findings_by_priority"]
		assert set(priorities.keys()) == {"HIGH", "MEDIUM", "LOW"}

	def test_risk_level_counts_from_rows(self):
		"""Risk group-by rows are aggregated into the dict."""
		from pgappforge.plugins.erp.grc.controls.services import ControlsService

		session = MagicMock()
		call_count = [0]

		def _exec(q):
			res = MagicMock()
			if call_count[0] == 0:
				# risk by level rows
				high_row = MagicMock()
				high_row.residual_risk_level = "HIGH"
				high_row.cnt = 3
				critical_row = MagicMock()
				critical_row.residual_risk_level = "CRITICAL"
				critical_row.cnt = 1
				res.all.return_value = [high_row, critical_row]
			elif call_count[0] == 1:
				# findings by priority rows
				res.all.return_value = []
			else:
				res.scalar_one.return_value = 0
			call_count[0] += 1
			return res

		session.execute.side_effect = _exec

		dashboard = self.svc.get_grc_dashboard(session, self.tenant_id)
		assert dashboard["open_risks_by_level"]["HIGH"] == 3
		assert dashboard["open_risks_by_level"]["CRITICAL"] == 1
		assert dashboard["open_risks_by_level"]["LOW"] == 0


# ---------------------------------------------------------------------------
# _risk_level_from_score (static helper)
# ---------------------------------------------------------------------------

class TestRiskLevelFromScore:
	def test_all_bands(self):
		from pgappforge.plugins.erp.grc.controls.services import ControlsService
		f = ControlsService._risk_level_from_score
		assert f(1) == "LOW"
		assert f(4) == "LOW"
		assert f(5) == "MEDIUM"
		assert f(9) == "MEDIUM"
		assert f(10) == "HIGH"
		assert f(16) == "HIGH"
		assert f(17) == "CRITICAL"
		assert f(25) == "CRITICAL"
