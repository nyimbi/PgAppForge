"""
tests/ci/test_tax_compliance.py

CI tests for the Tax Compliance plugin.

Tests cover:
  1. test_service_imports             — TaxComplianceService importable
  2. test_no_country_config           — no COMPLIANCE_COUNTRY → helpful error
  3. test_disabled                    — TAX_COMPLIANCE_ENABLED=False returns correct message
  4. test_get_submission_record_no_table  — returns None gracefully when table absent
  5. test_compliance_status_no_table  — returns empty submissions list when table absent
  6. test_plugin_metadata             — name=tax_compliance, domain=finance
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. Importability
# ---------------------------------------------------------------------------

def test_service_imports():
	from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService
	svc = TaxComplianceService()
	assert callable(svc.submit_invoice)
	assert callable(svc.get_compliance_status)
	assert callable(svc.subscribe_to_invoice_events)
	assert callable(svc.create_compliance_tables)


# ---------------------------------------------------------------------------
# 2. No COMPLIANCE_COUNTRY configured
# ---------------------------------------------------------------------------

def test_no_country_config():
	from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

	mock_app = MagicMock()
	mock_app.config.get.side_effect = lambda key, default=None: {
		"COMPLIANCE_COUNTRY": "",
		"TAX_COMPLIANCE_ENABLED": True,
	}.get(key, default)

	svc = TaxComplianceService()
	session = MagicMock()

	with patch("flask.current_app", mock_app):
		result = svc.submit_invoice("inv-001", "tenant-001", session)

	assert result["submitted"] is False
	assert result["authority"] is None
	assert result["control_number"] is None
	assert "COMPLIANCE_COUNTRY" in (result.get("error") or "")


# ---------------------------------------------------------------------------
# 3. TAX_COMPLIANCE_ENABLED = False
# ---------------------------------------------------------------------------

def test_disabled():
	from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

	mock_app = MagicMock()
	mock_app.config.get.side_effect = lambda key, default=None: {
		"COMPLIANCE_COUNTRY": "KE",
		"TAX_COMPLIANCE_ENABLED": False,
	}.get(key, default)

	svc = TaxComplianceService()
	session = MagicMock()

	with patch("flask.current_app", mock_app):
		result = svc.submit_invoice("inv-002", "tenant-001", session)

	assert result["submitted"] is False
	assert result["authority"] == "KE"
	assert result["control_number"] is None
	assert "TAX_COMPLIANCE_ENABLED=False" in (result.get("error") or "")


# ---------------------------------------------------------------------------
# 4. _get_submission_record when table does not exist
# ---------------------------------------------------------------------------

def test_get_submission_record_no_table():
	from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

	import sqlalchemy as sa

	# Session that raises OperationalError on execute (table doesn't exist)
	session = MagicMock()
	session.execute.side_effect = Exception("relation pgaf_tax_submission does not exist")

	svc = TaxComplianceService()
	result = svc._get_submission_record("inv-003", session)

	# Must return None gracefully, not propagate the exception
	assert result is None


# ---------------------------------------------------------------------------
# 5. get_compliance_status when table does not exist
# ---------------------------------------------------------------------------

def test_compliance_status_no_table():
	from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService

	session = MagicMock()
	session.execute.side_effect = Exception("relation pgaf_tax_submission does not exist")

	svc = TaxComplianceService()
	result = svc.get_compliance_status("inv-004", session)

	assert result["invoice_id"] == "inv-004"
	assert result["submissions"] == []
	assert result["compliant"] is False


# ---------------------------------------------------------------------------
# 6. Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata():
	from pgappforge.plugins.erp.finance.tax_compliance import TaxCompliancePlugin

	# TaxCompliancePlugin requires an appbuilder; pass a minimal mock
	appbuilder = MagicMock()
	plugin = TaxCompliancePlugin(appbuilder)

	assert plugin.name == "tax_compliance"
	assert plugin.domain == "finance"
	assert "foundation" in plugin.depends_on
	assert "ar" in plugin.depends_on

	meta = plugin.metadata
	assert meta.name == "tax_compliance"
	assert "africa" in meta.tags or "etims" in meta.tags
	assert "finance.ar.invoice.approved" in plugin.subscribe_to()
	assert "finance.ar.invoice.finalized" in plugin.subscribe_to()
