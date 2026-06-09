"""
tests/ci/test_base_erp_view.py

Unit tests for BaseERPView helper methods and BaseERPModelView class attributes.

The conftest.py stubs flask_appbuilder before collection, so BaseERPView can be
instantiated without a live Flask app context.  kpi_cards() only touches
StatCardWidget (pure Python), so no app context is needed there either.
"""
from __future__ import annotations

import pytest
from markupsafe import Markup

from pgappforge.plugins.erp.base_view import BaseERPView, BaseERPModelView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_view() -> BaseERPView:
	"""Return a BaseERPView instance.  The FAB stub __init__ accepts anything."""
	return BaseERPView()


# ---------------------------------------------------------------------------
# kpi_cards — basic rendering
# ---------------------------------------------------------------------------

def test_kpi_cards_returns_markup():
	view = _make_view()
	result = view.kpi_cards([
		{"label": "Test", "value": 42, "icon": "fa-check", "color": "#0e9f6e"},
	])
	assert isinstance(result, Markup)
	assert "42" in str(result)


def test_kpi_cards_empty_list():
	view = _make_view()
	result = view.kpi_cards([])
	assert isinstance(result, Markup)
	# Empty list → just the wrapper divs, no error
	assert result is not None


# ---------------------------------------------------------------------------
# kpi_cards — sanitisation
# ---------------------------------------------------------------------------

def test_kpi_cards_invalid_color_fallback():
	"""A color that isn't a valid #rrggbb hex must be replaced, not echoed."""
	view = _make_view()
	result = view.kpi_cards([
		{"label": "X", "value": 1, "color": "javascript:alert(1)"},
	])
	assert "javascript:alert" not in str(result)


def test_kpi_cards_invalid_icon_fallback():
	"""An icon that injects HTML must be replaced, not echoed."""
	view = _make_view()
	result = view.kpi_cards([
		{"label": "X", "value": 1, "icon": "<script>bad</script>"},
	])
	assert "<script>" not in str(result)


# ---------------------------------------------------------------------------
# kpi_cards — determinism
# ---------------------------------------------------------------------------

def test_kpi_cards_deterministic_ids():
	"""Container IDs are positional (kpi_0, kpi_1, …) — no UUID randomness."""
	view = _make_view()
	kpis = [
		{"label": "Alpha", "value": 1, "icon": "fa-check", "color": "#1a56db"},
		{"label": "Beta",  "value": 2, "icon": "fa-times", "color": "#0e9f6e"},
	]
	first  = str(view.kpi_cards(kpis))
	second = str(view.kpi_cards(kpis))
	assert first == second


def test_kpi_cards_spark_canvas_ids_are_positional():
	"""When trend data is present the canvas id is kpi_<index>_spark (positional)."""
	view = _make_view()
	result = str(view.kpi_cards([
		{"label": "A", "value": 10, "trend": 8,  "icon": "fa-check", "color": "#1a56db"},
		{"label": "B", "value": 20, "trend": 18, "icon": "fa-times", "color": "#0e9f6e"},
	]))
	assert "kpi_0_spark" in result
	assert "kpi_1_spark" in result


# ---------------------------------------------------------------------------
# kpi_cards — value rendering
# ---------------------------------------------------------------------------

def test_kpi_cards_zero_value():
	view = _make_view()
	result = view.kpi_cards([{"label": "Nothing", "value": 0, "color": "#1a56db"}])
	assert isinstance(result, Markup)
	assert "0" in str(result)


def test_kpi_cards_large_value():
	view = _make_view()
	result = view.kpi_cards([{"label": "Big", "value": 1_000_000, "color": "#1a56db"}])
	assert isinstance(result, Markup)
	# StatCardWidget integer format: "1,000,000"
	assert "1,000,000" in str(result)


def test_kpi_cards_multiple_items():
	view = _make_view()
	kpis = [
		{"label": "Sales",   "value": 100, "icon": "fa-dollar",  "color": "#1a56db"},
		{"label": "Returns", "value": 5,   "icon": "fa-refresh", "color": "#9e1c00"},
		{"label": "Net",     "value": 95,  "icon": "fa-check",   "color": "#0e9f6e"},
	]
	result = str(view.kpi_cards(kpis))
	assert "100" in result
	assert "95"  in result


# ---------------------------------------------------------------------------
# BaseERPModelView — class-level attributes
# ---------------------------------------------------------------------------

def test_base_erp_model_view_has_audit_excludes():
	assert "id"         in BaseERPModelView.add_exclude_columns
	assert "created_on" in BaseERPModelView.add_exclude_columns


def test_base_erp_model_view_edit_excludes_match():
	assert set(BaseERPModelView.add_exclude_columns) == set(BaseERPModelView.edit_exclude_columns)


def test_base_erp_model_view_page_size():
	assert BaseERPModelView.page_size == 50


def test_base_erp_model_view_audit_columns_complete():
	expected = {"id", "created_on", "changed_on", "created_at", "updated_at"}
	actual   = set(BaseERPModelView.add_exclude_columns)
	assert expected == actual
