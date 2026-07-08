"""
tests/ci/test_document_intelligence.py

CI tests for the Document Intelligence plugin.

Tests are structured to run without a live LLM (mocking _extract_with_llm_vision)
and without a real DB (save_extraction is tested with a mock session).
"""
from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.erp.platform.document_intelligence.services import (
	DocumentIntelligenceService,
	DocumentIntelligenceValidationError,
	create_document_extraction_table,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_invoice_fields() -> dict:
	return {
		"vendor_name": "Acme Supplies Ltd",
		"vendor_phone": "+254700000000",
		"invoice_number": "INV-2026-001",
		"invoice_date": "2026-06-01",
		"due_date": "2026-06-30",
		"subtotal_amount": 10000.0,
		"tax_amount": 1600.0,
		"total_amount": 11600.0,
		"currency": "KES",
		"payment_terms": "30 days",
		"line_items": [
			{"description": "Office Supplies", "quantity": 10, "unit_price": 1000.0, "total": 10000.0}
		],
	}


def _fake_kyc_fields() -> dict:
	return {
		"full_name": "Jane Wanjiku Mwangi",
		"id_number": "12345678",
		"date_of_birth": "1990-05-15",
		"nationality": "Kenyan",
		"gender": "Female",
		"expiry_date": None,
		"document_type": "National ID",
	}


# ---------------------------------------------------------------------------
# Tests: extract() dispatch
# ---------------------------------------------------------------------------

class TestDocumentIntelligenceService:

	def test_extract_invoice_from_bytes(self):
		"""LLM vision path returns success with extracted fields."""
		svc = DocumentIntelligenceService()
		fake_bytes = b"fake-image-bytes"

		with patch.object(svc, "_extract_with_llm_vision", return_value=_fake_invoice_fields()):
			result = svc.extract(file_bytes=fake_bytes, document_type="invoice", mime_type="image/jpeg")

		assert result["success"] is True
		assert result["document_type"] == "invoice"
		assert result["model_used"] == "llm_vision"
		assert result["confidence"] == 0.85
		fields = result["extracted_fields"]
		assert fields["vendor_name"] == "Acme Supplies Ltd"
		assert fields["total_amount"] == 11600.0

	def test_extract_national_id(self):
		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision", return_value=_fake_kyc_fields()):
			result = svc.extract(
				file_bytes=b"fake-id-image",
				document_type="national_id",
				mime_type="image/png",
			)
		assert result["success"] is True
		assert result["extracted_fields"]["full_name"] == "Jane Wanjiku Mwangi"

	def test_extract_no_file_returns_error(self):
		svc = DocumentIntelligenceService()
		result = svc.extract()
		assert result["success"] is False
		assert "exactly one" in result["error"]

	def test_extract_unknown_document_type_returns_error(self):
		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision") as extract:
			result = svc.extract(
				file_bytes=b"fake-image",
				document_type="unknown",
				mime_type="image/jpeg",
			)
		assert result["success"] is False
		assert "Unsupported document_type" in result["error"]
		extract.assert_not_called()

	def test_extract_invalid_mime_type_returns_error(self):
		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision") as extract:
			result = svc.extract(
				file_bytes=b"fake-image",
				document_type="invoice",
				mime_type="text/html",
			)
		assert result["success"] is False
		assert "Unsupported mime_type" in result["error"]
		extract.assert_not_called()

	def test_extract_invalid_b64_returns_error(self):
		svc = DocumentIntelligenceService()
		result = svc.extract(file_b64="not valid base64 !!!", document_type="invoice")
		assert result["success"] is False
		assert "base64" in result["error"]

	def test_extract_rejects_ambiguous_document_inputs(self):
		svc = DocumentIntelligenceService()
		result = svc.extract(file_bytes=b"fake", file_b64=base64.standard_b64encode(b"fake").decode())
		assert result["success"] is False
		assert "exactly one" in result["error"]

	def test_extract_llm_failure_non_pdf_returns_error(self):
		"""Non-PDF file with LLM failure returns error (no PDF fallback)."""
		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision", side_effect=RuntimeError("LLM down")):
			result = svc.extract(
				file_bytes=b"fake-image",
				document_type="invoice",
				mime_type="image/jpeg",
			)
		assert result["success"] is False
		assert "LLM down" in result["error"]

	def test_extract_pdf_falls_back_to_text(self):
		"""PDF with LLM failure falls back to PDF text extraction."""
		svc = DocumentIntelligenceService()
		with (
			patch.object(svc, "_extract_with_llm_vision", side_effect=RuntimeError("vision unavailable")),
			patch.object(svc, "_extract_from_pdf_text", return_value=_fake_invoice_fields()),
		):
			result = svc.extract(
				file_bytes=b"%PDF-fake",
				document_type="invoice",
				mime_type="application/pdf",
			)
		assert result["success"] is True
		assert result["model_used"] == "pdf_text"
		assert result["confidence"] == 0.6

	def test_extract_from_file_path(self, tmp_path):
		"""file_path is read and mime_type auto-detected."""
		img_file = tmp_path / "invoice.jpg"
		img_file.write_bytes(b"fake-jpeg-content")

		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision", return_value=_fake_invoice_fields()):
			result = svc.extract(file_path=img_file, document_type="invoice")

		assert result["success"] is True

	def test_extract_from_b64(self):
		b64 = base64.standard_b64encode(b"fake-img").decode()
		svc = DocumentIntelligenceService()
		with patch.object(svc, "_extract_with_llm_vision", return_value=_fake_kyc_fields()):
			result = svc.extract(file_b64=b64, document_type="national_id")
		assert result["success"] is True


# ---------------------------------------------------------------------------
# Tests: save_extraction()
# ---------------------------------------------------------------------------

class TestSaveExtraction:

	def test_save_returns_id(self):
		svc = DocumentIntelligenceService()
		mock_session = MagicMock()
		extraction = {
			"success": True,
			"document_type": "invoice",
			"extracted_fields": _fake_invoice_fields(),
			"confidence": 0.85,
			"model_used": "llm_vision",
		}
		# log_ai_action is lazily imported inside save_extraction — patch at source
		with patch("pgappforge.ai_governance.log_ai_action"):
			entry_id = svc.save_extraction(
				extraction_result=extraction,
				reference_type="purchase_order",
				reference_id="po-001",
				tenant_id="t-001",
				session=mock_session,
			)

		assert entry_id is not None
		assert len(entry_id) > 0
		mock_session.execute.assert_called_once()
		params = mock_session.execute.call_args[0][1]
		assert params["tenant_id"] == "t-001"
		assert params["ref_type"] == "purchase_order"
		assert params["ref_id"] == "po-001"
		assert params["doc_type"] == "invoice"
		assert params["confidence"] == 0.85
		assert json.loads(params["data"])["vendor_name"] == "Acme Supplies Ltd"

	def test_save_handles_db_error_gracefully(self):
		svc = DocumentIntelligenceService()
		mock_session = MagicMock()
		mock_session.execute.side_effect = Exception("DB offline")
		extraction = {
			"success": True,
			"document_type": "invoice",
			"extracted_fields": {},
			"confidence": 0,
			"model_used": "",
		}

		result = svc.save_extraction(extraction, "ref", "id", "t1", mock_session)
		assert result is None

	def test_save_skips_failed_extraction(self):
		svc = DocumentIntelligenceService()
		mock_session = MagicMock()
		extraction = {"success": False, "document_type": "invoice", "extracted_fields": {}}

		result = svc.save_extraction(extraction, "ref", "id", "t1", mock_session)
		assert result is None
		mock_session.execute.assert_not_called()

	def test_parse_json_object_from_wrapped_response(self):
		svc = DocumentIntelligenceService()

		assert svc._parse_json_object("Here is the JSON:\n```json\n{\"ok\": true}\n```") == {"ok": True}
		with pytest.raises(DocumentIntelligenceValidationError, match="JSON object"):
			svc._parse_json_object("[1, 2, 3]")


# ---------------------------------------------------------------------------
# Tests: EXTRACTION_PROMPTS coverage
# ---------------------------------------------------------------------------

class TestExtractionPrompts:

	def test_all_doc_types_have_prompts(self):
		svc = DocumentIntelligenceService()
		for doc_type in ("invoice", "national_id", "payslip", "bank_statement"):
			assert doc_type in svc.EXTRACTION_PROMPTS
			assert len(svc.EXTRACTION_PROMPTS[doc_type]) > 50

	def test_unknown_doc_type_is_rejected(self):
		svc = DocumentIntelligenceService()
		with pytest.raises(DocumentIntelligenceValidationError, match="Unsupported document_type"):
			svc._normalize_document_type("xyz")


# ---------------------------------------------------------------------------
# Tests: DDL helper (no real DB needed — just verify it runs SQL)
# ---------------------------------------------------------------------------

class TestCreateDocumentExtractionTable:

	def test_ddl_executes_without_error(self):
		"""create_document_extraction_table() calls engine.begin() and executes SQL."""
		mock_engine = MagicMock()
		mock_conn = MagicMock()
		mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
		mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

		create_document_extraction_table(mock_engine)
		mock_conn.execute.assert_called_once()
		ddl_text = str(mock_conn.execute.call_args[0][0])
		assert "pgaf_document_extraction" in ddl_text
