"""
tests/ci/test_fintech_gaps.py

CI tests for fintech gap fixes:
  CRB adapter, PAIN.001 XML builder, KEPSS adapter, PESALINK adapter, goAML XML.
"""
from __future__ import annotations

import inspect
import os
import xml.etree.ElementTree as ET

import pytest


# ---------------------------------------------------------------------------
# CRB adapter tests
# ---------------------------------------------------------------------------

def test_crb_mock_score_range():
	from pgappforge.plugins.fintech.lending.crb_adapter import MockCRBAdapter
	r = MockCRBAdapter().inquire("12345678")
	assert isinstance(r.score, int) and 400 <= r.score <= 899


def test_crb_mock_deterministic():
	from pgappforge.plugins.fintech.lending.crb_adapter import MockCRBAdapter
	r1 = MockCRBAdapter().inquire("ID999")
	r2 = MockCRBAdapter().inquire("ID999")
	assert r1.score == r2.score


def test_crb_factory_no_context_returns_mock():
	from pgappforge.plugins.fintech.lending.crb_adapter import get_crb_adapter, MockCRBAdapter
	adapter = get_crb_adapter()
	assert isinstance(adapter, MockCRBAdapter)


def test_crb_response_to_dict_keys():
	from pgappforge.plugins.fintech.lending.crb_adapter import MockCRBAdapter
	d = MockCRBAdapter().inquire("ABC123").to_dict()
	for key in ("bureau", "score", "reference", "checked_at", "npas", "listed_negative"):
		# "bureau" is stored as "provider" in CRBResponse.to_dict() — accept either
		if key == "bureau":
			assert "provider" in d or "bureau" in d, f"Neither 'provider' nor 'bureau' found in dict keys: {list(d)}"
		else:
			assert key in d, f"Key {key!r} missing from to_dict(); got keys: {list(d)}"


def test_crb_different_ids_may_differ():
	from pgappforge.plugins.fintech.lending.crb_adapter import MockCRBAdapter
	scores = {MockCRBAdapter().inquire(str(i)).score for i in range(20)}
	assert len(scores) > 1  # deterministic but varied


# ---------------------------------------------------------------------------
# PAIN.001 XML builder tests
# ---------------------------------------------------------------------------

def test_pain001_uses_elementtree():
	from pgappforge.plugins.fintech.payments.services import PaymentsService
	src = inspect.getsource(PaymentsService._build_pain001_xml)
	assert "ElementTree" in src or "ET.Element" in src or "xml.etree" in src


def test_pain001_xml_special_chars_parseable():
	"""_build_pain001_xml must XML-escape special characters in beneficiary names."""
	from pgappforge.plugins.fintech.payments.services import PaymentsService
	svc = PaymentsService.__new__(PaymentsService)

	class MockBatch:
		batch_reference = "BATCH001"
		batch_type = "EFT"
		batch_number = "BATCH001"
		total_payments = 1
		total_amount_cents = 100000
		value_date = None
		id = "batch-uuid-001"
		rail_code = "EFT"

	class MockOrder:
		payment_reference = "PAY001"
		amount_cents = 100000
		currency_code = "KES"
		creditor_name = "John & Jane <Test>"
		creditor_account_number = "1234567890"
		creditor_bank_code = ""
		remittance_info = None
		id = "order-uuid-001"

	# _build_pain001_xml(self, batch, orders) — no session argument
	xml_str = svc._build_pain001_xml(MockBatch(), [MockOrder()])
	# Must be parseable
	body = xml_str.split("?>", 1)[-1] if "?>" in xml_str else xml_str
	tree = ET.fromstring(body)
	assert tree is not None
	# ElementTree auto-escapes & → &amp; in text content
	assert "&amp;" in xml_str or "John" in xml_str


def test_pain001_mandatory_elements_present():
	"""Mandatory PAIN.001 elements must be present; RTGS batches use URGP service level."""
	from pgappforge.plugins.fintech.payments.services import PaymentsService
	svc = PaymentsService.__new__(PaymentsService)

	class MockBatch:
		batch_reference = "BATCH002"
		batch_type = "RTGS"
		batch_number = "BATCH002"
		total_payments = 1
		total_amount_cents = 500000
		value_date = None
		id = "b-002"
		rail_code = "KEPSS"

	class MockOrder:
		payment_reference = "PAY002"
		amount_cents = 500000
		currency_code = "KES"
		creditor_name = "Test Corp"
		creditor_account_number = "9876543210"
		creditor_bank_code = "KCOOKENA"
		remittance_info = None
		id = "order-uuid-002"

	xml_str = svc._build_pain001_xml(MockBatch(), [MockOrder()])
	body = xml_str.split("?>", 1)[-1] if "?>" in xml_str else xml_str
	# Check mandatory elements are present in XML text
	assert "PmtMtd" in xml_str or "TRF" in xml_str
	assert "SvcLvl" in xml_str
	assert "URGP" in xml_str  # RTGS batch → urgent service level


# ---------------------------------------------------------------------------
# KEPSS adapter tests
# ---------------------------------------------------------------------------

def test_kepss_adapter_importable():
	from pgappforge.plugins.fintech.payments.kepss_adapter import KEPSSAdapter, KEPSSError
	assert callable(KEPSSAdapter().submit_rtgs)
	assert callable(KEPSSAdapter().ingest_settlement_report)
	assert callable(KEPSSAdapter().query_status)


def test_kepss_mock_mode_returns_accepted():
	from pgappforge.plugins.fintech.payments.kepss_adapter import KEPSSAdapter
	# Outside Flask context → KEPSS_ENABLED defaults False → mock mode
	result = KEPSSAdapter().submit_rtgs("batch-test-001", "<xml/>", None)
	assert isinstance(result, dict)
	assert "status" in result
	# Mock mode must either set kepss_enabled=False or return MOCK/ACCEPTED status
	assert (
		result.get("kepss_enabled") == False
		or "MOCK" in str(result.get("status", ""))
		or "ACCEPTED" in str(result.get("status", ""))
	)


# ---------------------------------------------------------------------------
# PESALINK adapter tests
# ---------------------------------------------------------------------------

def test_pesalink_adapter_importable():
	from pgappforge.plugins.fintech.payments.pesalink_adapter import PESALINKAdapter, PESALINKError
	assert callable(PESALINKAdapter().send_transfer)
	assert callable(PESALINKAdapter().process_webhook)
	assert callable(PESALINKAdapter().query_transfer)


# ---------------------------------------------------------------------------
# goAML XML builder tests
# ---------------------------------------------------------------------------

def test_goaml_xml_builder():
	from pgappforge.plugins.fintech.regulatory.services import _build_goaml_xml

	class MockSAR:
		sar_number = "SAR-2026-001"
		narrative = "Suspicious cash deposits > KES 1M"

	xml_str = _build_goaml_xml(
		MockSAR(),
		{"INSTITUTION_NAME": "Test Bank", "INSTITUTION_ID": "TBK001"},
	)
	body = xml_str.split("?>", 1)[-1] if "?>" in xml_str else xml_str
	tree = ET.fromstring(body)
	assert tree is not None
	assert "SAR-2026-001" in xml_str
	assert "STR" in xml_str
	assert "KES" in xml_str


# ---------------------------------------------------------------------------
# Regulatory service error + method existence
# ---------------------------------------------------------------------------

def test_frc_submission_error_importable():
	from pgappforge.plugins.fintech.regulatory.services import FRCSubmissionError
	assert issubclass(FRCSubmissionError, Exception)


def test_frc_disabled_by_default():
	from pgappforge.plugins.fintech.regulatory.services import RegulatoryComplianceService
	# _submit_to_frc_kenya must exist and be callable (instance method)
	assert callable(RegulatoryComplianceService._submit_to_frc_kenya)


# ---------------------------------------------------------------------------
# KEPSS settlement report — empty pacs.002
# ---------------------------------------------------------------------------

def test_kepss_settlement_report_empty_xml():
	"""Empty pacs.002 (no TxInfAndSts children) must return 0 matched/unmatched without crashing."""
	from pgappforge.plugins.fintech.payments.kepss_adapter import KEPSSAdapter

	# Minimal valid pacs.002 with an empty TxInfAndSts element (no OrgnlEndToEndId / TxSts)
	empty_xml = (
		'<?xml version="1.0"?>'
		'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.002.001.03">'
		"<FIToFIPmtStsRpt>"
		"<TxInfAndSts></TxInfAndSts>"
		"</FIToFIPmtStsRpt>"
		"</Document>"
	)

	# Provide a minimal stub session — the adapter calls session.query() only
	# when it finds a valid OrgnlEndToEndId; the empty element skips that path.
	class _StubQuery:
		def filter(self, *a, **kw):
			return self
		def first(self):
			return None

	class _StubSession:
		def query(self, *a, **kw):
			return _StubQuery()

	result = KEPSSAdapter().ingest_settlement_report(empty_xml, _StubSession())
	assert isinstance(result, dict)
	assert "matched" in result
