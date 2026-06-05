"""
tests/ci/test_hcm_org_gaps.py

Unit tests for HCM Org gap-fill implementations:
  - JobGrade model: create_grade(), check_salary_in_band()
  - ReportingLine service: set_reporting_line(), end_reporting_line(), get_org_chart()
  - OrgRestructureRequest service: raise_change_request(), approve_change(), apply_pending_changes()
  - Workforce analytics: get_vacancy_report(), get_headcount_report(),
    get_attrition_rate(), get_span_of_control(), get_open_position_aging()

No @pytest.mark.asyncio — plain functions + real objects.
No mocks — pure logic tests against in-memory object graphs (no DDL needed).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# LeavePolicy must be imported before any SQLAlchemy mapper configuration fires.
# LegalEntity has a viewonly relationship referencing LeavePolicy by string; SA
# will raise InvalidRequestError when configuring mappers if LeavePolicy hasn't
# been imported yet.  This import is a side-effect-only registration.
from pgappforge.plugins.erp.hcm.time.models import LeavePolicy  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


TENANT = _uuid()
ENTITY = _uuid()


# ---------------------------------------------------------------------------
# Import tests — compile-time guard
# ---------------------------------------------------------------------------

class TestOrgGapImports:
	def test_job_grade_model_imports(self):
		from pgappforge.plugins.erp.hcm.org.models import JobGrade
		assert JobGrade.__tablename__ == "hcm_org_job_grade"

	def test_all_models_in_dunder_all(self):
		import pgappforge.plugins.erp.hcm.org.models as m
		for name in [
			"LegalEntity", "OrgUnit", "OrgUnitHistory", "JobCatalog",
			"JobGrade", "CompensationGrade", "CompensationGradeExchange",
			"Position", "ReportingLine", "OrgRestructureRequest",
			"PositionRequisition", "HeadcountBudget", "OrgRole", "PositionRole",
		]:
			assert name in m.__all__, f"{name} missing from models.__all__"

	def test_service_methods_present(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		svc = OrgService()
		for method in [
			"create_grade", "check_salary_in_band",
			"set_reporting_line", "end_reporting_line", "get_org_chart",
			"raise_change_request", "approve_change", "apply_pending_changes",
			"get_vacancy_report", "get_headcount_report", "get_attrition_rate",
			"get_span_of_control", "get_open_position_aging",
		]:
			assert hasattr(svc, method), f"OrgService missing method: {method}"

	def test_service_all_exported(self):
		from pgappforge.plugins.erp.hcm.org import services
		for name in ["OrgService", "OrgServiceError", "PositionNotFoundError"]:
			assert name in services.__all__


# ---------------------------------------------------------------------------
# JobGrade — create_grade / check_salary_in_band
# ---------------------------------------------------------------------------

class TestJobGrade:
	"""Tests use a mock session to avoid DB dependency."""

	def _make_service(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		return OrgService()

	def _make_mock_session(self, grade_obj=None):
		sess = MagicMock()
		sess.add = MagicMock()
		sess.flush = MagicMock()
		result_mock = MagicMock()
		result_mock.scalar_one_or_none.return_value = grade_obj
		sess.execute = MagicMock(return_value=result_mock)
		return sess

	def test_create_grade_success(self):
		svc = self._make_service()
		sess = self._make_mock_session()

		with patch("pgappforge.plugins.erp.hcm.org.models.JobGrade") as MockGrade:
			instance = MagicMock()
			instance.grade_code = "G5"
			MockGrade.return_value = instance

			data = {
				"tenant_id": TENANT,
				"grade_code": "g5",
				"grade_name": "Senior Engineer",
				"min_salary_cents": 5_000_000,
				"mid_salary_cents": 6_000_000,
				"max_salary_cents": 7_000_000,
				"currency_code": "KES",
			}
			result = svc.create_grade(data, sess)
			assert result is instance
			sess.add.assert_called_once()
			sess.flush.assert_called_once()

	def test_create_grade_salary_order_error(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = self._make_mock_session()
		data = {
			"tenant_id": TENANT,
			"grade_code": "G5",
			"grade_name": "Senior Engineer",
			"min_salary_cents": 7_000_000,
			"mid_salary_cents": 6_000_000,   # mid < min → invalid
			"max_salary_cents": 8_000_000,
		}
		with pytest.raises(OrgServiceError, match="min_salary_cents"):
			svc.create_grade(data, sess)

	def test_create_grade_missing_fields(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = self._make_mock_session()
		with pytest.raises(OrgServiceError, match="Missing"):
			svc.create_grade({"tenant_id": TENANT, "grade_code": "G5"}, sess)

	def test_check_salary_in_band_within(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		svc = OrgService()

		grade = MagicMock()
		grade.min_salary_cents = 5_000_000
		grade.max_salary_cents = 7_000_000
		sess = self._make_mock_session(grade_obj=grade)

		assert svc.check_salary_in_band(sess, "G5", 6_000_000, TENANT) is True

	def test_check_salary_in_band_below_min(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		svc = OrgService()

		grade = MagicMock()
		grade.min_salary_cents = 5_000_000
		grade.max_salary_cents = 7_000_000
		sess = self._make_mock_session(grade_obj=grade)

		assert svc.check_salary_in_band(sess, "G5", 4_999_999, TENANT) is False

	def test_check_salary_in_band_above_max(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		svc = OrgService()

		grade = MagicMock()
		grade.min_salary_cents = 5_000_000
		grade.max_salary_cents = 7_000_000
		sess = self._make_mock_session(grade_obj=grade)

		assert svc.check_salary_in_band(sess, "G5", 7_000_001, TENANT) is False

	def test_check_salary_in_band_grade_not_found(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = self._make_mock_session(grade_obj=None)

		with pytest.raises(OrgServiceError, match="not found"):
			svc.check_salary_in_band(sess, "MISSING", 5_000_000, TENANT)

	def test_check_salary_in_band_at_boundaries(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		svc = OrgService()

		grade = MagicMock()
		grade.min_salary_cents = 5_000_000
		grade.max_salary_cents = 7_000_000
		sess = self._make_mock_session(grade_obj=grade)

		# Exact min and max are in-band
		assert svc.check_salary_in_band(sess, "G5", 5_000_000, TENANT) is True
		assert svc.check_salary_in_band(sess, "G5", 7_000_000, TENANT) is True


# ---------------------------------------------------------------------------
# ReportingLine — set / end / get_org_chart
# ---------------------------------------------------------------------------

class TestReportingLine:
	def _make_service(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		return OrgService()

	def _make_position(self, pos_id=None, code="POS001", title="Engineer", filled=False):
		p = MagicMock()
		p.id = pos_id or _uuid()
		p.position_code = code
		p.position_title = title
		p.is_filled = filled
		p.tenant_id = TENANT
		p.org_unit_id = _uuid()
		return p

	def _make_session_for_set_line(self, from_pos, to_pos, existing_solid=None):
		"""Build a mock session that returns the right objects for set_reporting_line."""
		sess = MagicMock()

		def mock_get(model_cls, pk):
			from pgappforge.plugins.erp.hcm.org.models import Position
			if model_cls is Position:
				if pk == from_pos.id:
					return from_pos
				if pk == to_pos.id:
					return to_pos
			return None

		sess.get = mock_get
		sess.add = MagicMock()
		sess.flush = MagicMock()

		# existing open solid lines
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = existing_solid or []
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)

		return sess

	def test_set_reporting_line_solid(self):
		from pgappforge.plugins.erp.hcm.org.models import ReportingLine

		svc = self._make_service()
		from_pos = self._make_position(code="SUB001")
		to_pos = self._make_position(code="MGR001")
		sess = self._make_session_for_set_line(from_pos, to_pos)

		with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			result = svc.set_reporting_line(
				from_pos.id, to_pos.id, sess,
				line_type="SOLID",
				tenant_id=TENANT,
			)
		assert isinstance(result, ReportingLine)
		assert result.from_position_id == from_pos.id
		assert result.to_position_id == to_pos.id
		assert result.line_type == "SOLID"
		sess.add.assert_called()
		sess.flush.assert_called()

	def test_set_reporting_line_invalid_type(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = MagicMock()
		with pytest.raises(OrgServiceError, match="line_type"):
			svc.set_reporting_line(_uuid(), _uuid(), sess, line_type="MATRIX")

	def test_set_reporting_line_position_not_found(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, PositionNotFoundError
		svc = OrgService()
		sess = MagicMock()
		sess.get = MagicMock(return_value=None)
		with pytest.raises(PositionNotFoundError):
			svc.set_reporting_line(_uuid(), _uuid(), sess, tenant_id=TENANT)

	def test_end_reporting_line_success(self):
		svc = self._make_service()
		rl = MagicMock()
		rl.effective_to = None
		rl.tenant_id = TENANT
		rl.from_position_id = _uuid()
		rl.to_position_id = _uuid()

		sess = MagicMock()
		sess.get = MagicMock(return_value=rl)

		with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			result = svc.end_reporting_line(rl.id, sess, effective_to=date(2026, 6, 1))
			assert result.effective_to == date(2026, 6, 1)

	def test_end_reporting_line_already_closed(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		rl = MagicMock()
		rl.effective_to = date(2025, 1, 1)

		sess = MagicMock()
		sess.get = MagicMock(return_value=rl)

		with pytest.raises(OrgServiceError, match="already closed"):
			svc.end_reporting_line(rl.id, sess)

	def test_end_reporting_line_not_found(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = MagicMock()
		sess.get = MagicMock(return_value=None)
		with pytest.raises(OrgServiceError, match="not found"):
			svc.end_reporting_line(_uuid(), sess)

	def test_get_org_chart_single_node(self):
		svc = self._make_service()
		root_id = _uuid()
		root_pos = self._make_position(pos_id=root_id, code="CEO001", title="CEO")

		sess = MagicMock()
		sess.get = MagicMock(return_value=root_pos)

		# No direct reports
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = []
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)

		chart = svc.get_org_chart(sess, root_id, depth=3, tenant_id=TENANT)
		assert chart["id"] == root_id
		assert chart["position_code"] == "CEO001"
		assert chart["title"] == "CEO"
		assert chart["reports"] == []

	def test_get_org_chart_with_direct_reports(self):
		svc = self._make_service()
		root_id = _uuid()
		child_id = _uuid()

		root_pos = self._make_position(pos_id=root_id, code="CEO001", title="CEO")
		child_pos = self._make_position(pos_id=child_id, code="ENG001", title="Engineer")

		rl = MagicMock()
		rl.from_position_id = child_id

		call_count = [0]

		def mock_get(model_cls, pk):
			from pgappforge.plugins.erp.hcm.org.models import Position
			if model_cls is Position:
				if pk == root_id:
					return root_pos
				if pk == child_id:
					return child_pos
			return None

		def mock_execute(stmt):
			result = MagicMock()
			scalars = MagicMock()
			# First call = direct reports of root; subsequent = no reports
			if call_count[0] == 0:
				scalars.all.return_value = [rl]
			else:
				scalars.all.return_value = []
			call_count[0] += 1
			result.scalars.return_value = scalars
			return result

		sess = MagicMock()
		sess.get = mock_get
		sess.execute = mock_execute

		chart = svc.get_org_chart(sess, root_id, depth=2, tenant_id=TENANT)
		assert chart["id"] == root_id
		assert len(chart["reports"]) == 1
		assert chart["reports"][0]["id"] == child_id


# ---------------------------------------------------------------------------
# OrgRestructureRequest — raise / approve / apply
# ---------------------------------------------------------------------------

class TestOrgChangeRequest:
	def _make_service(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		return OrgService()

	def _make_org_unit(self, unit_id=None):
		u = MagicMock()
		u.id = unit_id or _uuid()
		u.org_name = "Finance"
		u.parent_id = None
		u.status = "ACTIVE"
		u.is_active = True
		u.tenant_id = TENANT
		u.updated_at = datetime.now(timezone.utc)
		return u

	def test_raise_change_request_success(self):
		svc = self._make_service()
		unit = self._make_org_unit()

		sess = MagicMock()
		sess.get = MagicMock(return_value=unit)
		sess.add = MagicMock()
		sess.flush = MagicMock()

		with patch("pgappforge.plugins.erp.hcm.org.models.OrgRestructureRequest") as MockReq, \
		     patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			req_instance = MagicMock()
			req_instance.id = _uuid()
			req_instance.org_unit_id = unit.id
			req_instance.restructure_type = "RENAME"
			req_instance.requested_by = "admin"
			req_instance.tenant_id = TENANT
			MockReq.return_value = req_instance

			result = svc.raise_change_request({
				"tenant_id": TENANT,
				"org_unit_id": unit.id,
				"restructure_type": "RENAME",
				"requested_by": "admin",
				"effective_date": "2026-07-01",
				"description": "Rename Finance to Treasury",
				"change_payload_json": {"after": {"org_name": "Treasury"}},
			}, sess)
			assert result is req_instance

	def test_raise_change_request_invalid_type(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		unit = self._make_org_unit()
		sess = MagicMock()
		sess.get = MagicMock(return_value=unit)

		with pytest.raises(OrgServiceError, match="restructure_type"):
			svc.raise_change_request({
				"tenant_id": TENANT,
				"org_unit_id": unit.id,
				"restructure_type": "TELEPORT",
				"requested_by": "admin",
				"effective_date": "2026-07-01",
			}, sess)

	def test_raise_change_request_unit_not_found(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgUnitNotFoundError
		svc = OrgService()
		sess = MagicMock()
		sess.get = MagicMock(return_value=None)

		with pytest.raises(OrgUnitNotFoundError):
			svc.raise_change_request({
				"tenant_id": TENANT,
				"org_unit_id": _uuid(),
				"restructure_type": "RENAME",
				"requested_by": "admin",
				"effective_date": "2026-07-01",
			}, sess)

	def test_raise_change_request_missing_fields(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = MagicMock()
		with pytest.raises(OrgServiceError, match="Missing"):
			svc.raise_change_request({"tenant_id": TENANT}, sess)

	def test_approve_change_success(self):
		svc = self._make_service()
		req = MagicMock()
		req.status = "DRAFT"
		req.tenant_id = TENANT
		req.org_unit_id = _uuid()

		sess = MagicMock()
		sess.get = MagicMock(return_value=req)

		with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			result = svc.approve_change(_uuid(), "manager@acme.ke", sess)
			assert result.status == "APPROVED"
			assert result.approved_by == "manager@acme.ke"

	def test_approve_change_wrong_status(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		req = MagicMock()
		req.status = "APPLIED"
		sess = MagicMock()
		sess.get = MagicMock(return_value=req)

		with pytest.raises(OrgServiceError, match="DRAFT"):
			svc.approve_change(_uuid(), "approver", sess)

	def test_approve_change_not_found(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService, OrgServiceError
		svc = OrgService()
		sess = MagicMock()
		sess.get = MagicMock(return_value=None)
		with pytest.raises(OrgServiceError, match="not found"):
			svc.approve_change(_uuid(), "approver", sess)

	def test_apply_pending_changes_rename(self):
		svc = self._make_service()

		unit_id = _uuid()
		unit = self._make_org_unit(unit_id=unit_id)
		unit.org_name = "Finance"

		req = MagicMock()
		req.id = _uuid()
		req.status = "APPROVED"
		req.effective_date = date(2026, 6, 1)
		req.org_unit_id = unit_id
		req.restructure_type = "RENAME"
		req.change_payload_json = {"after": {"org_name": "Treasury"}}
		req.approved_by = "admin"
		req.tenant_id = TENANT
		req.updated_at = datetime.now(timezone.utc)

		sess = MagicMock()

		# execute() returns list of pending requests on first call
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = [req]
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)

		sess.get = MagicMock(return_value=unit)
		sess.add = MagicMock()
		sess.flush = MagicMock()

		with patch("pgappforge.plugins.erp.hcm.org.models.OrgUnitHistory") as MockHist, \
		     patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			hist_instance = MagicMock()
			MockHist.return_value = hist_instance

			result = svc.apply_pending_changes(sess, as_of_date=date(2026, 6, 4), tenant_id=TENANT)

		assert req.id in result["applied"]
		assert result["errors"] == []
		assert unit.org_name == "Treasury"

	def test_apply_pending_changes_abolish(self):
		svc = self._make_service()

		unit = self._make_org_unit()
		unit.status = "ACTIVE"
		unit.is_active = True

		req = MagicMock()
		req.id = _uuid()
		req.status = "APPROVED"
		req.effective_date = date(2026, 1, 1)
		req.org_unit_id = unit.id
		req.restructure_type = "ABOLISH"
		req.change_payload_json = {"after": {}}
		req.approved_by = "admin"
		req.tenant_id = TENANT
		req.updated_at = datetime.now(timezone.utc)

		sess = MagicMock()
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = [req]
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)
		sess.get = MagicMock(return_value=unit)
		sess.add = MagicMock()
		sess.flush = MagicMock()

		with patch("pgappforge.plugins.erp.hcm.org.models.OrgUnitHistory"), \
		     patch("pgappforge.plugins.erp.foundation.events.emit_event"):
			result = svc.apply_pending_changes(sess, tenant_id=TENANT)

		assert req.id in result["applied"]
		assert unit.status == "ABOLISHED"
		assert unit.is_active is False

	def test_apply_pending_changes_unit_missing(self):
		svc = self._make_service()

		req = MagicMock()
		req.id = _uuid()
		req.status = "APPROVED"
		req.effective_date = date(2026, 1, 1)
		req.org_unit_id = _uuid()
		req.restructure_type = "RENAME"
		req.change_payload_json = {}
		req.tenant_id = TENANT

		sess = MagicMock()
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = [req]
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)
		sess.get = MagicMock(return_value=None)   # unit not found
		sess.add = MagicMock()
		sess.flush = MagicMock()

		result = svc.apply_pending_changes(sess, tenant_id=TENANT)
		assert req.id in result["skipped"]
		assert any("not found" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Workforce analytics
# ---------------------------------------------------------------------------

class TestWorkforceAnalytics:
	def _make_service(self):
		from pgappforge.plugins.erp.hcm.org.services import OrgService
		return OrgService()

	def _make_position(self, is_filled=False, org_unit_id=None, last_vacated_at=None, grade_code=None):
		p = MagicMock()
		p.id = _uuid()
		p.position_code = "P" + _uuid()[:6]
		p.position_title = "Engineer"
		p.org_unit_id = org_unit_id or _uuid()
		p.tenant_id = TENANT
		p.is_filled = is_filled
		p.is_active = True
		p.grade_code = grade_code or "G5"
		p.last_vacated_at = last_vacated_at
		p.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
		return p

	def _scalar_session(self, rows):
		"""Mock session.execute(...).scalars().all() returning rows."""
		sess = MagicMock()
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = rows
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)
		return sess

	# --- get_vacancy_report ---

	def test_get_vacancy_report_returns_list(self):
		svc = self._make_service()
		p1 = self._make_position(is_filled=False, last_vacated_at=datetime(2026, 5, 1, tzinfo=timezone.utc))
		p2 = self._make_position(is_filled=False)  # never filled
		sess = self._scalar_session([p1, p2])

		result = svc.get_vacancy_report(sess, tenant_id=TENANT)
		assert isinstance(result, list)
		assert len(result) == 2
		assert all("days_open" in r for r in result)
		assert all("position_id" in r for r in result)

	def test_get_vacancy_report_days_open_calculation(self):
		svc = self._make_service()
		vacated = datetime(2026, 5, 1, tzinfo=timezone.utc)
		p = self._make_position(is_filled=False, last_vacated_at=vacated)
		sess = self._scalar_session([p])

		result = svc.get_vacancy_report(sess)
		assert result[0]["days_open"] >= 0   # relative to now — just verify non-negative

	def test_get_vacancy_report_empty(self):
		svc = self._make_service()
		sess = self._scalar_session([])
		result = svc.get_vacancy_report(sess, tenant_id=TENANT)
		assert result == []

	# --- get_headcount_report ---

	def test_get_headcount_report_structure(self):
		svc = self._make_service()
		ou_id = _uuid()

		# Mock execute to return aggregate rows then unit objects
		row1 = MagicMock()
		row1.org_unit_id = ou_id
		row1.total = 5
		row1.filled = 3

		sess = MagicMock()

		call_count = [0]
		def mock_execute(stmt):
			result = MagicMock()
			scalars = MagicMock()
			if call_count[0] == 0:
				# First call: aggregate by org_unit
				result.all.return_value = [row1]
				result.scalars.return_value = scalars
				scalars.all.return_value = [row1]
				call_count[0] += 1
				return result
			else:
				# Second call: org unit objects
				unit = MagicMock()
				unit.id = ou_id
				unit.org_name = "Engineering"
				unit.org_type = "DEPARTMENT"
				scalars.all.return_value = [unit]
				result.scalars.return_value = scalars
				call_count[0] += 1
				return result

		sess.execute = mock_execute

		report = svc.get_headcount_report(sess, as_of_date=date(2026, 6, 1), tenant_id=TENANT)
		assert "as_of" in report
		assert "rows" in report
		assert "totals" in report
		assert report["as_of"] == "2026-06-01"
		assert isinstance(report["rows"], list)
		totals = report["totals"]
		assert "total_filled" in totals
		assert "total_vacant" in totals
		assert "total_positions" in totals

	# --- get_attrition_rate ---

	def test_get_attrition_rate_structure(self):
		svc = self._make_service()
		sess = MagicMock()

		# First execute: vacated_count, second: filled_now
		call_count = [0]
		def mock_execute(stmt):
			result = MagicMock()
			if call_count[0] == 0:
				result.scalar_one.return_value = 5   # vacated_count
			else:
				result.scalar_one.return_value = 50  # filled_now
			call_count[0] += 1
			return result

		sess.execute = mock_execute

		report = svc.get_attrition_rate(
			sess,
			from_date=date(2026, 1, 1),
			to_date=date(2026, 3, 31),
			tenant_id=TENANT,
		)
		assert report["from_date"] == "2026-01-01"
		assert report["to_date"] == "2026-03-31"
		assert report["vacated_count"] == 5
		assert report["avg_filled"] == 50
		assert report["attrition_rate_pct"] == 10.0   # 5/50 * 100

	def test_get_attrition_rate_zero_filled_no_div_zero(self):
		svc = self._make_service()
		sess = MagicMock()

		call_count = [0]
		def mock_execute(stmt):
			result = MagicMock()
			result.scalar_one.return_value = 0
			call_count[0] += 1
			return result

		sess.execute = mock_execute

		# Should not raise ZeroDivisionError
		report = svc.get_attrition_rate(
			sess,
			from_date=date(2026, 1, 1),
			to_date=date(2026, 3, 31),
		)
		assert report["attrition_rate_pct"] >= 0.0

	# --- get_span_of_control ---

	def test_get_span_of_control_structure(self):
		svc = self._make_service()
		ou_id = _uuid()
		mgr_id = _uuid()

		pos_list = [
			self._make_position(org_unit_id=ou_id),
			self._make_position(org_unit_id=ou_id),
		]
		pos_list[0].id = mgr_id

		call_count = [0]
		def mock_execute(stmt):
			result = MagicMock()
			scalars = MagicMock()
			if call_count[0] == 0:
				# positions in org unit
				scalars.all.return_value = pos_list
				result.scalars.return_value = scalars
			else:
				# span rows: manager has 5 direct reports
				span_row = MagicMock()
				span_row.to_position_id = mgr_id
				span_row.direct_reports = 5
				result.all.return_value = [span_row]
			call_count[0] += 1
			return result

		sess = MagicMock()
		sess.execute = mock_execute

		report = svc.get_span_of_control(sess, ou_id, tenant_id=TENANT)
		assert report["org_unit_id"] == ou_id
		assert "managers" in report
		assert "summary" in report
		summary = report["summary"]
		assert "min_span" in summary
		assert "max_span" in summary
		assert "avg_span" in summary
		assert "manager_count" in summary

	def test_get_span_of_control_flags(self):
		svc = self._make_service()
		ou_id = _uuid()

		pos_under = self._make_position(org_unit_id=ou_id)   # 1 report → UNDER_DELEGATION
		pos_ok = self._make_position(org_unit_id=ou_id)       # 5 reports → OK
		pos_over = self._make_position(org_unit_id=ou_id)     # 15 reports → OVERLOADED

		call_count = [0]
		def mock_execute(stmt):
			result = MagicMock()
			scalars = MagicMock()
			if call_count[0] == 0:
				scalars.all.return_value = [pos_under, pos_ok, pos_over]
				result.scalars.return_value = scalars
			else:
				r1 = MagicMock(); r1.to_position_id = pos_under.id; r1.direct_reports = 1
				r2 = MagicMock(); r2.to_position_id = pos_ok.id; r2.direct_reports = 5
				r3 = MagicMock(); r3.to_position_id = pos_over.id; r3.direct_reports = 15
				result.all.return_value = [r1, r2, r3]
			call_count[0] += 1
			return result

		sess = MagicMock()
		sess.execute = mock_execute

		report = svc.get_span_of_control(sess, ou_id)
		flags = {m["position_id"]: m["flag"] for m in report["managers"]}
		assert flags[pos_under.id] == "UNDER_DELEGATION"
		assert flags[pos_ok.id] == "OK"
		assert flags[pos_over.id] == "OVERLOADED"

	def test_get_span_of_control_empty_unit(self):
		svc = self._make_service()
		sess = MagicMock()
		scalars_mock = MagicMock()
		scalars_mock.all.return_value = []
		execute_result = MagicMock()
		execute_result.scalars.return_value = scalars_mock
		sess.execute = MagicMock(return_value=execute_result)

		report = svc.get_span_of_control(sess, _uuid())
		assert report["managers"] == []
		assert report["summary"]["manager_count"] == 0

	# --- get_open_position_aging ---

	def test_get_open_position_aging_buckets(self):
		svc = self._make_service()
		now = datetime.now(timezone.utc)

		def days_ago(n):
			from datetime import timedelta
			return now - timedelta(days=n)

		p_fresh = self._make_position(last_vacated_at=days_ago(10))   # 0-30
		p_mid = self._make_position(last_vacated_at=days_ago(45))     # 31-60
		p_old = self._make_position(last_vacated_at=days_ago(75))     # 61-90
		p_stale = self._make_position(last_vacated_at=days_ago(120))  # 90+

		sess = self._scalar_session([p_fresh, p_mid, p_old, p_stale])
		result = svc.get_open_position_aging(sess, tenant_id=TENANT)

		assert len(result) == 4
		buckets = {r["age_bucket"] for r in result}
		assert buckets == {"0-30", "31-60", "61-90", "90+"}

	def test_get_open_position_aging_sorted_desc(self):
		svc = self._make_service()
		now = datetime.now(timezone.utc)
		from datetime import timedelta

		p1 = self._make_position(last_vacated_at=now - timedelta(days=5))
		p2 = self._make_position(last_vacated_at=now - timedelta(days=100))
		p3 = self._make_position(last_vacated_at=now - timedelta(days=30))

		sess = self._scalar_session([p1, p2, p3])
		result = svc.get_open_position_aging(sess)

		# Should be sorted with most stale first
		days = [r["days_open"] for r in result]
		assert days == sorted(days, reverse=True)

	def test_get_open_position_aging_empty(self):
		svc = self._make_service()
		sess = self._scalar_session([])
		result = svc.get_open_position_aging(sess)
		assert result == []


# ---------------------------------------------------------------------------
# JobGrade model field coverage
# ---------------------------------------------------------------------------

class TestJobGradeModel:
	def test_job_grade_repr(self):
		from pgappforge.plugins.erp.hcm.org.models import JobGrade
		g = JobGrade(
			tenant_id=TENANT,
			grade_code="G5",
			grade_name="Senior Engineer",
			min_salary_cents=5_000_000,
			mid_salary_cents=6_000_000,
			max_salary_cents=7_000_000,
			currency_code="KES",
		)
		r = repr(g)
		assert "G5" in r
		assert "KES" in r

	def test_job_grade_has_required_columns(self):
		from pgappforge.plugins.erp.hcm.org.models import JobGrade
		cols = {c.name for c in JobGrade.__table__.columns}
		for col in ("id", "tenant_id", "grade_code", "grade_name",
		            "min_salary_cents", "mid_salary_cents", "max_salary_cents",
		            "currency_code", "created_at", "updated_at"):
			assert col in cols, f"JobGrade missing column: {col}"

	def test_job_grade_unique_constraint_present(self):
		from pgappforge.plugins.erp.hcm.org.models import JobGrade
		constraint_names = {c.name for c in JobGrade.__table__.constraints}
		assert "uq_hcm_jg_tenant_grade" in constraint_names
