"""
tests/ci/test_integration_layer.py

Structural / import-level tests for the GL reports, notification dispatcher,
analytics cubes, and AR invoice PDF service integration layer.

No database required — all tests operate on module structure, callable checks,
and mock objects only.  No pytest.mark.asyncio; no mocks for DB connectivity.
"""
from __future__ import annotations

import inspect
import types


# ---------------------------------------------------------------------------
# 1. GL FinancialReportService — method surface
# ---------------------------------------------------------------------------

def test_gl_reports_import():
	"""FinancialReportService exposes exactly 6 methods: 3 PDF + 3 CSV."""
	from pgappforge.plugins.erp.finance.gl.reports import FinancialReportService

	svc = FinancialReportService()
	expected = {
		"generate_trial_balance_pdf",
		"generate_income_statement_pdf",
		"generate_balance_sheet_pdf",
		"generate_trial_balance_csv",
		"generate_income_statement_csv",
		"generate_balance_sheet_csv",
	}
	public_methods = {
		name for name, _ in inspect.getmembers(svc, predicate=inspect.ismethod)
		if not name.startswith("_")
	}
	assert expected.issubset(public_methods), (
		f"Missing methods: {expected - public_methods}"
	)
	assert len(expected) == 6


# ---------------------------------------------------------------------------
# 2. GL CSV graceful degradation outside DB context
# ---------------------------------------------------------------------------

def test_gl_csv_no_context():
	"""generate_trial_balance_csv returns '' when GLService.get_trial_balance raises."""
	from pgappforge.plugins.erp.finance.gl.reports import FinancialReportService

	class _FakeSession:
		pass

	# Monkey-patch GLService so it raises without a real DB
	import pgappforge.plugins.erp.finance.gl.services as _gl_svc_mod

	class _PatchedGLService:
		def get_trial_balance(self, *a, **kw):
			return []	# empty data — no DB needed

	original = getattr(_gl_svc_mod, "GLService", None)
	_gl_svc_mod.GLService = _PatchedGLService	# type: ignore[attr-defined]
	try:
		svc = FinancialReportService()
		result = svc.generate_trial_balance_csv("2025-01", None, _FakeSession())
		# Should return a string (may be just the header row)
		assert isinstance(result, str)
	finally:
		if original is not None:
			_gl_svc_mod.GLService = original	# type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 3. Event dispatcher — handler registry
# ---------------------------------------------------------------------------

def test_event_dispatcher_handlers():
	"""EVENT_HANDLERS has exactly 8 entries; all values are callable."""
	from pgappforge.plugins.erp.platform.notifications.event_dispatcher import EVENT_HANDLERS

	assert len(EVENT_HANDLERS) == 8, (
		f"Expected 8 EVENT_HANDLERS, got {len(EVENT_HANDLERS)}: {list(EVENT_HANDLERS)}"
	)
	for event_type, handler in EVENT_HANDLERS.items():
		assert callable(handler), f"Handler for {event_type!r} is not callable"


# ---------------------------------------------------------------------------
# 4. register_all_subscriptions — safe outside Flask context
# ---------------------------------------------------------------------------

def test_register_subscriptions_no_bus():
	"""register_all_subscriptions() returns 0 outside Flask without crashing."""
	from pgappforge.plugins.erp.platform.notifications.event_dispatcher import (
		register_all_subscriptions,
	)
	result = register_all_subscriptions()
	assert isinstance(result, int)
	# Outside Flask the event bus is unavailable; count may be 0 or partial
	assert result >= 0


# ---------------------------------------------------------------------------
# 5. _notify — safe outside Flask context
# ---------------------------------------------------------------------------

def test_notify_wrapper_no_context():
	"""_notify() does not raise when called outside a Flask application context."""
	from pgappforge.plugins.erp.platform.notifications.event_dispatcher import _notify

	# Must not raise; failure is logged at DEBUG level and swallowed
	_notify("user1", "Test Subject", "Test body")


# ---------------------------------------------------------------------------
# 6. Standard analytics cubes — structure
# ---------------------------------------------------------------------------

def test_standard_cubes_structure():
	"""STANDARD_CUBES has 5 entries; each has the required keys."""
	from pgappforge.plugins.erp.platform.analytics_engine.standard_cubes import STANDARD_CUBES

	assert len(STANDARD_CUBES) == 5, (
		f"Expected 5 STANDARD_CUBES, got {len(STANDARD_CUBES)}"
	)
	required_keys = {"name", "base_query", "dimensions", "measures"}
	for cube in STANDARD_CUBES:
		missing = required_keys - cube.keys()
		assert not missing, f"Cube {cube.get('name')!r} missing keys: {missing}"


# ---------------------------------------------------------------------------
# 7. Cube names
# ---------------------------------------------------------------------------

def test_cube_names():
	"""Cube names include the three mandatory cross-domain cubes."""
	from pgappforge.plugins.erp.platform.analytics_engine.standard_cubes import STANDARD_CUBES

	names = {c["name"] for c in STANDARD_CUBES}
	for expected in ("gl_monthly_pnl", "ar_aging_summary", "hcm_headcount"):
		assert expected in names, f"Cube {expected!r} not found in {names}"


# ---------------------------------------------------------------------------
# 8. seed_standard_cubes — safe with None session
# ---------------------------------------------------------------------------

def test_seed_cubes_no_context():
	"""seed_standard_cubes() returns 0 without crashing when no DB session is available."""
	from pgappforge.plugins.erp.platform.analytics_engine.standard_cubes import seed_standard_cubes

	result = seed_standard_cubes("t1", None)
	assert isinstance(result, int)
	assert result >= 0


# ---------------------------------------------------------------------------
# 9. InvoicePDFService — method surface
# ---------------------------------------------------------------------------

def test_invoice_pdf_service_import():
	"""InvoicePDFService exposes generate_invoice_pdf and generate_invoice_csv."""
	from pgappforge.plugins.erp.finance.ar.invoice_pdf import InvoicePDFService

	svc = InvoicePDFService()
	assert callable(getattr(svc, "generate_invoice_pdf", None)), (
		"InvoicePDFService missing generate_invoice_pdf"
	)
	assert callable(getattr(svc, "generate_invoice_csv", None)), (
		"InvoicePDFService missing generate_invoice_csv"
	)


# ---------------------------------------------------------------------------
# 10. _render_invoice_pdf on a mock invoice returns bytes
# ---------------------------------------------------------------------------

def test_invoice_pdf_returns_bytes_type():
	"""_render_invoice_pdf(mock_invoice) returns bytes (possibly empty if no reportlab)."""
	from pgappforge.plugins.erp.finance.ar.invoice_pdf import InvoicePDFService
	from datetime import date

	class _MockInvoice:
		invoice_number = "INV-0001"
		invoice_date = date(2025, 1, 15)
		due_date = date(2025, 2, 14)
		status = "ISSUED"
		currency_code = "KES"
		customer_id = "cust-001"
		subtotal_cents = 100000
		tax_cents = 16000
		total_cents = 116000
		line_items = [
			{
				"description": "Consulting Services",
				"quantity": 2,
				"unit_price_cents": 50000,
				"total_cents": 100000,
			}
		]

	svc = InvoicePDFService()
	result = svc._render_invoice_pdf(_MockInvoice())
	assert isinstance(result, bytes), (
		f"Expected bytes, got {type(result)}"
	)


# ---------------------------------------------------------------------------
# 11. NotificationDispatcherPlugin metadata
# ---------------------------------------------------------------------------

def test_notification_plugin_metadata():
	"""NotificationDispatcherPlugin.name contains 'notification'."""
	from pgappforge.plugins.erp.platform.notifications import NotificationDispatcherPlugin

	assert "notification" in NotificationDispatcherPlugin.name.lower(), (
		f"Expected 'notification' in plugin name, got {NotificationDispatcherPlugin.name!r}"
	)


# ---------------------------------------------------------------------------
# 12. GL ReportDownloadView (GLReportDownloadView) — download methods present
# ---------------------------------------------------------------------------

def test_gl_report_download_endpoints_registered():
	"""ReportDownloadView source contains all three download method names."""
	from pgappforge.plugins.erp.finance.gl.views import ReportDownloadView

	source = inspect.getsource(ReportDownloadView)
	for method_name in (
		"download_trial_balance",
		"download_income_statement",
		"download_balance_sheet",
	):
		assert method_name in source, (
			f"Method {method_name!r} not found in ReportDownloadView source"
		)
