"""Regression tests for platform foundation hardening improvements."""
from __future__ import annotations

from decimal import Decimal

import pytest


class _ScalarResult:
	def __init__(self, *, scalar_value=None, row=None, rows=None):
		self._scalar_value = scalar_value
		self._row = row
		self._rows = rows or []

	def scalar_one_or_none(self):
		return self._row

	def scalar(self):
		return self._scalar_value

	def scalars(self):
		return self

	def all(self):
		return self._rows


def test_query_guard_rejects_statement_chaining() -> None:
	from pgappforge.plugins.erp.platform.query_guard import QueryGuardError, validate_read_only_sql

	with pytest.raises(QueryGuardError, match="one SQL statement"):
		validate_read_only_sql("SELECT 1; DROP TABLE pgaf_report")


def test_query_guard_rejects_unsafe_generated_identifiers() -> None:
	from pgappforge.plugins.erp.platform.query_guard import QueryGuardError, validate_sql_identifier

	with pytest.raises(QueryGuardError, match="Unsafe"):
		validate_sql_identifier("amount); DROP TABLE x; --")


def test_report_builder_rejects_commented_mutation() -> None:
	from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService

	svc = ReportBuilderService()
	with pytest.raises(ValueError, match="Only SELECT or WITH"):
		svc.get_data_for_report("-- harmless looking\nUPDATE account SET name = 'x'", object())


def test_analytics_query_cube_validates_schema_and_generated_sql() -> None:
	from pgappforge.plugins.erp.platform.analytics_engine.services import AnalyticsEngineService

	class _Cube:
		tenant_id = "tenant-1"
		base_query = "SELECT tenant_id, amount_cents FROM fact_sales"
		dimensions = [{"name": "tenant_id", "field": "tenant_id", "type": "string"}]
		measures = [{"name": "total_amount", "field": "amount_cents", "agg": "SUM"}]

	class _Result:
		def keys(self):
			return ["tenant_id", "total_amount"]

		def fetchmany(self, limit):
			assert limit == 1000
			return [("tenant-1", 12345)]

	class _Session:
		def __init__(self):
			self.sql = ""
			self.params = {}

		def get(self, model, cube_id):
			return _Cube()

		def execute(self, sql, params=None):
			self.sql = str(sql)
			self.params = params or {}
			return _Result()

	session = _Session()
	rows = AnalyticsEngineService().query_cube(
		"cube-1",
		{"tenant_id": "tenant-1"},
		["tenant_id"],
		session,
		tenant_id="tenant-1",
	)

	assert rows == [{"tenant_id": "tenant-1", "total_amount": 12345}]
	assert "SUM(amount_cents) AS total_amount" in session.sql
	assert "GROUP BY tenant_id" in session.sql
	assert session.params == {"f0": "tenant-1"}


def test_analytics_query_cube_rejects_unsafe_measure_alias() -> None:
	from pgappforge.plugins.erp.platform.analytics_engine.services import AnalyticsEngineService

	class _Cube:
		tenant_id = "tenant-1"
		base_query = "SELECT tenant_id, amount_cents FROM fact_sales"
		dimensions = [{"name": "tenant_id", "field": "tenant_id", "type": "string"}]
		measures = [{"name": "total); DROP TABLE x", "field": "amount_cents", "agg": "SUM"}]

	class _Session:
		def get(self, model, cube_id):
			return _Cube()

	with pytest.raises(ValueError, match="Unsafe"):
		AnalyticsEngineService().query_cube("cube-1", {}, ["tenant_id"], _Session())


def test_tenant_control_monthly_usage_enforces_plan_limits() -> None:
	from pgappforge.plugins.erp.platform.tenant_control.models import TenantPlanLimit, TenantProfile
	from pgappforge.plugins.erp.platform.tenant_control.services import TenantControlService

	profile = TenantProfile(id="tenant-1", name="Tenant", plan_tier="STARTER", status="ACTIVE")
	limit = TenantPlanLimit(
		id="limit-1",
		plan_tier="STARTER",
		resource="api_calls_per_month",
		limit_value=Decimal("10000"),
	)

	class _Session:
		def __init__(self):
			self.calls = 0

		def get(self, model, tenant_id):
			return profile

		def execute(self, stmt):
			self.calls += 1
			if self.calls == 1:
				assert "platform_tenant_plan_limit" in str(stmt)
				return _ScalarResult(row=limit)
			assert "platform_tenant_usage_event" in str(stmt)
			assert "recorded_at" in str(stmt)
			return _ScalarResult(scalar_value=Decimal("9999"))

	assert TenantControlService().check_plan_limits(
		"tenant-1",
		"api_calls_per_month",
		_Session(),
	) is True


def test_tenant_control_rejects_unknown_plan_tier() -> None:
	from pgappforge.plugins.erp.platform.tenant_control.services import TenantControlService

	with pytest.raises(ValueError, match="Unknown plan tier"):
		TenantControlService().provision_tenant("tenant-1", "Tenant", "UNKNOWN")


def test_setup_declares_single_merged_analytics_extra() -> None:
	text = open("setup.py", encoding="utf-8").read()
	assert text.count('"analytics": [') == 1
	for dep in ("duckdb", "matplotlib", "numpy", "pandas", "plotly", "scikit-learn", "seaborn"):
		assert dep in text
