"""
tests/ci/test_nl_analytics.py

Compile-check and unit tests for:
  - pgappforge/plugins/erp/platform/nl_analytics/
  - pgappforge/semantic.py

Tests use real objects — no mocks, no live DB required for pure logic tests.
DB-dependent tests are guarded with a ``db_session`` fixture skip.

Run with: uv run pytest -vxs tests/ci/test_nl_analytics.py
"""
from __future__ import annotations

import datetime
import decimal


class _FakeNLResult:
	def __init__(
		self,
		*,
		row=None,
		rows=None,
		columns=None,
		fetch_limits=None,
	):
		self.row = row
		self.rows = rows or []
		self.columns = columns or []
		self.fetch_limits = fetch_limits

	def fetchone(self):
		return self.row

	def keys(self):
		return self.columns

	def fetchmany(self, limit):
		if self.fetch_limits is not None:
			self.fetch_limits.append(limit)
		return self.rows[:limit]


class _FakeNLSession:
	def __init__(self, *, cache_sql=None, rows=None, columns=None):
		self.cache_sql = cache_sql
		self.rows = rows or []
		self.columns = columns or []
		self.executed = []
		self.fetch_limits = []

	def execute(self, stmt, params=None):
		sql_text = str(stmt)
		self.executed.append((sql_text, params or {}))
		if "SELECT cached_sql FROM pgaf_nl_query_cache" in sql_text:
			row = (self.cache_sql,) if self.cache_sql is not None else None
			return _FakeNLResult(row=row)
		if sql_text.lstrip().upper().startswith("SELECT"):
			return _FakeNLResult(
				rows=self.rows,
				columns=self.columns,
				fetch_limits=self.fetch_limits,
			)
		return _FakeNLResult()


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

class TestNLAnalyticsImports:
	"""All modules must import without error."""

	def test_services_importable(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import (
			NLAnalyticsService,
			create_cache_table_ddl,
			ensure_cache_table,
		)
		assert callable(create_cache_table_ddl)
		assert callable(ensure_cache_table)
		svc = NLAnalyticsService()
		assert svc is not None

	def test_views_importable(self):
		from pgappforge.plugins.erp.platform.nl_analytics.views import NLAnalyticsDashboardView
		assert NLAnalyticsDashboardView.route_base == "/platform/nl-analytics"

	def test_plugin_importable(self):
		from pgappforge.plugins.erp.platform.nl_analytics import (
			NLAnalyticsPlugin,
			create_plugin,
			NLAnalyticsService,
			NLAnalyticsDashboardView,
			create_cache_table_ddl,
			ensure_cache_table,
		)
		assert NLAnalyticsPlugin.name == "nl_analytics"
		assert NLAnalyticsPlugin.domain == "platform"
		assert "foundation" in NLAnalyticsPlugin.depends_on
		assert "nlp" in NLAnalyticsPlugin.depends_on
		assert callable(create_plugin)
		assert callable(NLAnalyticsService)
		assert callable(NLAnalyticsDashboardView)
		assert callable(create_cache_table_ddl)
		assert callable(ensure_cache_table)


class TestSemanticImports:
	"""pgappforge/semantic.py must import cleanly."""

	def test_semantic_importable(self):
		from pgappforge.semantic import (
			SemanticRegistry,
			SemanticModel,
			SemanticMetric,
			SemanticDimension,
			register_default_semantics,
		)
		assert callable(SemanticRegistry)
		assert callable(SemanticModel)
		assert callable(SemanticMetric)
		assert callable(SemanticDimension)
		assert callable(register_default_semantics)

	def test_dataclasses_instantiate(self):
		from pgappforge.semantic import SemanticMetric, SemanticDimension, SemanticModel

		m = SemanticMetric(
			name="headcount",
			label="Headcount",
			description="Active employee count",
			sql="SELECT COUNT(*) FROM pgaf_employee WHERE employment_status='ACTIVE'",
			unit="count",
		)
		assert m.name == "headcount"
		assert m.aggregation == "SUM"  # default

		d = SemanticDimension(
			name="branch",
			label="Branch",
			table="pgaf_branch",
			key_column="code",
			label_column="name",
		)
		assert d.description == ""

		sm = SemanticModel(domain="fintech", module="sacco")
		assert sm.metrics == []
		assert sm.business_glossary == {}


# ---------------------------------------------------------------------------
# NLAnalyticsService — pure logic
# ---------------------------------------------------------------------------

class TestNLAnalyticsServiceLogic:
	def test_is_safe_sql_allows_select(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		assert NLAnalyticsService._is_safe_sql("SELECT COUNT(*) FROM members") is True
		assert NLAnalyticsService._is_safe_sql("select id from foo LIMIT 10") is True
		assert NLAnalyticsService._is_safe_sql("WITH rows AS (SELECT 1) SELECT * FROM rows") is True

	def test_is_safe_sql_blocks_dml(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		assert NLAnalyticsService._is_safe_sql("INSERT INTO foo VALUES (1)") is False
		assert NLAnalyticsService._is_safe_sql("UPDATE foo SET x=1") is False
		assert NLAnalyticsService._is_safe_sql("DELETE FROM foo") is False
		assert NLAnalyticsService._is_safe_sql("DROP TABLE foo") is False
		assert NLAnalyticsService._is_safe_sql("CREATE TABLE foo (id int)") is False
		assert NLAnalyticsService._is_safe_sql("ALTER TABLE foo ADD col text") is False
		assert NLAnalyticsService._is_safe_sql("TRUNCATE TABLE foo") is False
		assert NLAnalyticsService._is_safe_sql("SELECT * INTO TEMP export_table FROM foo") is False
		assert NLAnalyticsService._is_safe_sql("SELECT pg_read_file('/etc/passwd')") is False

	def test_safe_sql_normalization_strips_comments_not_literals(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		sql = NLAnalyticsService._normalize_safe_sql(
			"SELECT '-- not a comment; UPDATE account' AS note -- DROP TABLE foo"
		)
		assert sql == "SELECT '-- not a comment; UPDATE account' AS note"

	def test_is_safe_sql_rejects_empty(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		assert NLAnalyticsService._is_safe_sql("") is False
		assert NLAnalyticsService._is_safe_sql("  ") is False

	def test_query_hash_deterministic(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		svc = NLAnalyticsService()
		h1 = svc._query_hash("How many active members?")
		h2 = svc._query_hash("How many active members?")
		h3 = svc._query_hash("HOW MANY ACTIVE MEMBERS?")  # normalised to lower
		assert h1 == h2 == h3
		assert len(h1) == 16

	def test_query_hash_differs_for_different_questions(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		svc = NLAnalyticsService()
		assert svc._query_hash("question A") != svc._query_hash("question B")

	def test_builtin_semantic_returns_dict(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService
		sem = NLAnalyticsService._builtin_semantic()
		assert isinstance(sem, dict)
		assert "par30" in sem
		assert "active members" in sem

	def test_jsonify_rows_handles_decimal(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import _jsonify_rows
		rows = [
			{"amount": decimal.Decimal("1234.56"), "name": "foo", "nul": None},
			{"amount": decimal.Decimal("0"), "ts": datetime.datetime(2026, 1, 1)},
		]
		clean = _jsonify_rows(rows)
		assert clean[0]["amount"] == 1234.56
		assert clean[0]["name"] == "foo"
		assert clean[0]["nul"] is None
		assert isinstance(clean[1]["ts"], str)

	def test_cache_table_ddl_contains_expected_columns(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import create_cache_table_ddl
		ddl = create_cache_table_ddl()
		assert "pgaf_nl_query_cache" in ddl
		assert "query_hash" in ddl
		assert "cached_sql" in ddl
		assert "tenant_id" in ddl
		assert "hit_count" in ddl
		assert "CREATE TABLE IF NOT EXISTS" in ddl

	def test_query_returns_error_when_no_session(self):
		"""query() with a None session must return an error dict, not raise."""
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService

		class _FakeSession:
			def execute(self, *a, **kw):
				raise RuntimeError("no db")
			def rollback(self): pass

		svc = NLAnalyticsService()
		# Bypass LLM by giving a safe SELECT directly via monkey-patch
		original = svc._generate_sql
		svc._generate_sql = lambda q, s: "SELECT 1"
		result = svc.query("test question", _FakeSession())
		svc._generate_sql = original

		# Should return structured error dict, not raise
		assert "error" in result
		assert isinstance(result["error"], str)
		assert result["results"] == []

	def test_query_normalizes_generated_sql_and_clamps_row_limit(self, monkeypatch):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService

		monkeypatch.setattr(
			NLAnalyticsService,
			"_config_int",
			staticmethod(lambda key, default: 5000),
		)
		session = _FakeNLSession(
			rows=[(index,) for index in range(1500)],
			columns=["id"],
		)
		svc = NLAnalyticsService()
		svc._generate_sql = lambda q, s: "SELECT id FROM members;"

		result = svc.query("  list members  ", session, tenant_id=" tenant-1 ")

		assert result["sql"] == "SELECT id FROM members"
		assert result["row_count"] == 1000
		assert session.fetch_limits == [1000]
		cache_write = session.executed[-1]
		assert cache_write[1]["q"] == "list members"
		assert cache_write[1]["sql"] == "SELECT id FROM members"
		assert cache_write[1]["t"] == "tenant-1"

	def test_query_rejects_blank_question_before_cache_lookup(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService

		session = _FakeNLSession()
		result = NLAnalyticsService().query("  ", session)

		assert result["error"] == "question is required"
		assert result["results"] == []
		assert session.executed == []

	def test_check_cache_ignores_unsafe_cached_sql(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService

		session = _FakeNLSession(cache_sql="SELECT pg_read_file('/etc/passwd')")
		result = NLAnalyticsService()._check_cache("question", session, tenant_id="tenant-1")

		assert result is None
		assert len(session.executed) == 1

	def test_cache_result_normalizes_sql_before_write(self):
		from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService

		session = _FakeNLSession()
		NLAnalyticsService()._cache_result(
			"  question  ",
			"SELECT 1;",
			session,
			tenant_id=" tenant-1 ",
		)

		cache_write = session.executed[-1]
		assert cache_write[1]["q"] == "question"
		assert cache_write[1]["sql"] == "SELECT 1"
		assert cache_write[1]["t"] == "tenant-1"


# ---------------------------------------------------------------------------
# SemanticRegistry
# ---------------------------------------------------------------------------

class TestSemanticRegistry:
	def setup_method(self):
		"""Reset singleton between tests."""
		from pgappforge.semantic import SemanticRegistry
		SemanticRegistry.reset()

	def test_singleton_pattern(self):
		from pgappforge.semantic import SemanticRegistry
		r1 = SemanticRegistry.get()
		r2 = SemanticRegistry.get()
		assert r1 is r2

	def test_register_and_find_metric(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel, SemanticMetric

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(
			domain="test", module="mod",
			metrics=[
				SemanticMetric("par30", "PAR 30", "desc", "SELECT 1", unit="%"),
			],
		))

		found = reg.find_metric("par30")
		assert found is not None
		assert found.unit == "%"

		found_by_label = reg.find_metric("PAR 30")
		assert found_by_label is not None
		assert found_by_label.name == "par30"

	def test_find_metric_case_insensitive(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel, SemanticMetric

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(
			domain="test", module="m2",
			metrics=[
				SemanticMetric("headcount", "Headcount", "d", "SELECT 1"),
			],
		))
		assert reg.find_metric("HEADCOUNT") is not None
		assert reg.find_metric("headcount") is not None
		assert reg.find_metric("Headcount") is not None

	def test_find_metric_missing(self):
		from pgappforge.semantic import SemanticRegistry
		reg = SemanticRegistry.get()
		assert reg.find_metric("nonexistent_metric_xyz") is None

	def test_get_glossary(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(
			domain="fin", module="x",
			business_glossary={"par30": "Portfolio at Risk 30"},
		))
		glossary = reg.get_glossary()
		assert "par30" in glossary
		assert "Portfolio" in glossary["par30"]

	def test_get_all_metrics_aggregation(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel, SemanticMetric

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(
			domain="a", module="b",
			metrics=[SemanticMetric("m1", "M1", "d1", "SELECT 1")],
		))
		reg.register(SemanticModel(
			domain="a", module="c",
			metrics=[SemanticMetric("m2", "M2", "d2", "SELECT 2")],
		))
		all_metrics = reg.get_all_metrics()
		names = [m.name for m in all_metrics]
		assert "m1" in names
		assert "m2" in names

	def test_build_llm_context_empty(self):
		from pgappforge.semantic import SemanticRegistry
		reg = SemanticRegistry.get()
		ctx = reg.build_llm_context()
		assert isinstance(ctx, str)

	def test_build_llm_context_with_data(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel, SemanticMetric

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(
			domain="fin", module="sacco",
			metrics=[SemanticMetric("par30", "PAR 30", "Portfolio at risk", "SELECT 1", unit="%")],
			business_glossary={"par30": "Portfolio at Risk 30 days"},
		))
		ctx = reg.build_llm_context()
		assert "PAR 30" in ctx
		assert "Portfolio at Risk" in ctx

	def test_list_models(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(domain="dom", module="mod"))
		models = reg.list_models()
		assert ("dom", "mod") in models

	def test_register_default_semantics_no_error(self):
		"""register_default_semantics() must complete without raising."""
		from pgappforge.semantic import register_default_semantics, SemanticRegistry
		# May or may not load YAML files depending on cwd — must not raise
		register_default_semantics()
		reg = SemanticRegistry.get()
		# At minimum the three hardcoded models should be present
		assert reg.find_metric("total_loan_book") is not None
		assert reg.find_metric("net_income") is not None
		assert reg.find_metric("headcount") is not None

	def test_register_default_semantics_glossary(self):
		from pgappforge.semantic import register_default_semantics, SemanticRegistry
		register_default_semantics()
		reg = SemanticRegistry.get()
		glossary = reg.get_glossary()
		assert "par30" in glossary
		assert "fosa" in glossary
		assert "paye" in glossary

	def test_register_overwrites_existing_model(self):
		from pgappforge.semantic import SemanticRegistry, SemanticModel, SemanticMetric

		reg = SemanticRegistry.get()
		reg.register(SemanticModel(domain="x", module="y",
			metrics=[SemanticMetric("m1", "M1 v1", "d", "SELECT 1")]))
		reg.register(SemanticModel(domain="x", module="y",
			metrics=[SemanticMetric("m1", "M1 v2", "d", "SELECT 1")]))

		found = reg.find_metric("m1")
		assert found.label == "M1 v2"  # latest registration wins


# ---------------------------------------------------------------------------
# NLAnalyticsPlugin metadata
# ---------------------------------------------------------------------------

class TestNLAnalyticsPluginMetadata:
	def test_plugin_metadata(self):
		from pgappforge.plugins.erp.platform.nl_analytics import NLAnalyticsPlugin

		class _FakeAB:
			pass

		plugin = NLAnalyticsPlugin(_FakeAB())
		meta = plugin.metadata
		assert meta.name == "nl_analytics"
		assert "can_ai_query_data" in meta.permissions
		assert "can_nl_analytics_api_query" in meta.permissions
		assert meta.safe_mode_compatible is True

	def test_plugin_events(self):
		from pgappforge.plugins.erp.platform.nl_analytics import NLAnalyticsPlugin

		class _FakeAB:
			pass

		plugin = NLAnalyticsPlugin(_FakeAB())
		events = plugin.get_events()
		assert "platform.nl_analytics.query.executed" in events
		assert "platform.nl_analytics.query.cache_hit" in events

	def test_plugin_register_models_empty(self):
		from pgappforge.plugins.erp.platform.nl_analytics import NLAnalyticsPlugin

		class _FakeAB:
			pass

		plugin = NLAnalyticsPlugin(_FakeAB())
		assert plugin.register_models() == []

	def test_plugin_initialize_uses_safe_llm_defaults(self):
		from pgappforge.plugins.erp.platform.nl_analytics import NLAnalyticsPlugin

		class _FakeAB:
			pass

		plugin = NLAnalyticsPlugin(_FakeAB())
		plugin.initialize()

		assert plugin.config["LITELLM_URL"] == "http://localhost:4000/v1"
		assert plugin.config["LITELLM_API_KEY"] == ""
