"""
tests/ci/test_trade_compliance_plugin.py

CI tests for Trade Compliance plugin.

Tests are import-only / unit-level — no database required.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_trade_events_importable():
	from pgappforge.plugins.erp.procurement.trade_compliance.events import (
		EntityScreenedEvent,
		EntityBlockedEvent,
		HSCodeLookedUpEvent,
		TradeListRefreshedEvent,
	)
	assert EntityScreenedEvent().event_type == "procurement.trade.screened"
	assert EntityBlockedEvent().event_type == "procurement.trade.blocked"
	assert HSCodeLookedUpEvent().event_type == "procurement.trade.hs_lookup"
	assert TradeListRefreshedEvent().event_type == "procurement.trade.list_refreshed"


def test_trade_models_importable():
	from pgappforge.plugins.erp.procurement.trade_compliance.models import (
		TradeRestrictionList,
		TradeScreeningResult,
		HSCodeMapping,
	)
	assert TradeRestrictionList.__tablename__ == "trd_restriction_list"
	assert TradeScreeningResult.__tablename__ == "trd_screening_result"
	assert HSCodeMapping.__tablename__ == "trd_hs_code"


def test_trade_service_importable():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	assert callable(TradeComplianceService)


def test_trade_plugin_importable():
	from pgappforge.plugins.erp.procurement.trade_compliance import (
		TradeCompliancePlugin,
		create_plugin,
	)
	assert TradeCompliancePlugin.name == "trade_compliance"
	assert TradeCompliancePlugin.domain == "procurement"
	assert "foundation" in TradeCompliancePlugin.depends_on


# ---------------------------------------------------------------------------
# Jaro-Winkler similarity
# ---------------------------------------------------------------------------

def test_jaro_winkler_identical():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	svc = TradeComplianceService()
	assert svc._jaro_winkler("ACME CORP", "ACME CORP") == 1.0


def test_jaro_winkler_empty():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	svc = TradeComplianceService()
	assert svc._jaro_winkler("", "ACME") == 0.0
	assert svc._jaro_winkler("ACME", "") == 0.0


def test_jaro_winkler_close_names():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	svc = TradeComplianceService()
	# "MARTHA" vs "MARHTA" — classic Jaro-Winkler example
	score = svc._jaro_winkler("MARTHA", "MARHTA")
	assert score > 0.9, f"Expected >0.9, got {score}"


def test_jaro_winkler_very_different():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	svc = TradeComplianceService()
	score = svc._jaro_winkler("ACME CORPORATION", "ZZZZZZ UNRELATED")
	assert score < 0.6, f"Expected <0.6, got {score}"


def test_jaro_winkler_prefix_boost():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)
	svc = TradeComplianceService()
	# Jaro-Winkler gives prefix bonus — "JOHN" vs "JOHM" should score higher
	# than a pair with no common prefix of equal length
	score_prefix = svc._jaro_winkler("JOHN", "JOHM")
	score_no_prefix = svc._jaro_winkler("ABCD", "WXYZ")
	assert score_prefix > score_no_prefix


# ---------------------------------------------------------------------------
# TradeCompliancePlugin metadata
# ---------------------------------------------------------------------------

def test_trade_plugin_metadata():
	from pgappforge.plugins.erp.procurement.trade_compliance import TradeCompliancePlugin

	class _FakeAB:
		pass

	plugin = TradeCompliancePlugin(_FakeAB())
	meta = plugin.metadata
	assert meta.version == "1.0.0"
	assert "ofac" in meta.tags
	assert "sanctions" in meta.tags
	events = plugin.get_events()
	assert "procurement.trade.screened" in events
	assert "procurement.trade.blocked" in events
	models = plugin.register_models()
	assert len(models) == 3


# ---------------------------------------------------------------------------
# calculate_duty arithmetic
# ---------------------------------------------------------------------------

def test_calculate_duty_no_row(monkeypatch):
	"""Returns zero duty when no HS mapping found (no DB call needed)."""
	from pgappforge.plugins.erp.procurement.trade_compliance.services import (
		TradeComplianceService,
	)

	class _FakeSession:
		def execute(self, *a, **kw):
			class _R:
				def scalar_one_or_none(self):
					return None
			return _R()

	svc = TradeComplianceService()
	result = svc.calculate_duty(
		hs_code="8471.30",
		country_origin="CHN",
		country_dest="KEN",
		value_cents=100000,
		tenant_id="t1",
		session=_FakeSession(),
	)
	assert result["duty_cents"] == 0
	assert result["found"] is False
