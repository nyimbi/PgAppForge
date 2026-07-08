from __future__ import annotations
import base64
import binascii
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ALLOWED_MIME_TYPES = frozenset({
	"application/pdf",
	"image/jpeg",
	"image/png",
	"image/webp",
})
_MAX_BASE64_CHARS = 16_000_000
_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_MAX_EXTRACTED_JSON_CHARS = 1_000_000
_MAX_REFERENCE_LENGTH = 100
_MAX_TEXT_CHARS = 4_000


class DocumentIntelligenceValidationError(ValueError):
	"""Raised when document intelligence inputs violate extraction contracts."""


class DocumentIntelligenceService:
	"""Extract structured data from business documents using LLM vision.

	Supports:
	- Invoice PDF/image → structured invoice fields (vendor, amount, line items, tax)
	- National ID / Passport → KYC fields (name, ID number, DOB, expiry)
	- Payslip → income verification (gross, net, deductions, employer)
	- Bank statement → transaction history extraction

	Uses Claude vision API (via LiteLLM) for cloud,
	falls back to text extraction for text-based PDFs.
	"""

	# Document type → extraction prompt template
	EXTRACTION_PROMPTS = {
		"invoice": """Extract all invoice fields from this document.
Return JSON with: vendor_name, vendor_phone, invoice_number, invoice_date (ISO),
due_date (ISO), subtotal_amount, tax_amount, total_amount, currency,
payment_terms, line_items: [{description, quantity, unit_price, total}].
Use null for missing fields. Amounts as numbers.""",

		"national_id": """Extract identity document fields.
Return JSON with: full_name, id_number, date_of_birth (ISO),
nationality, gender, expiry_date (ISO), document_type.
Use null for missing fields.""",

		"payslip": """Extract payslip/payroll fields.
Return JSON with: employee_name, employer_name, period_month (YYYY-MM),
gross_amount, net_amount, paye_tax, nhif, nssf, loan_deductions,
other_deductions, bank_name, account_number_last4.""",

		"bank_statement": """Extract bank statement summary.
Return JSON with: account_holder, account_number_last4, bank_name,
statement_period_start (ISO), statement_period_end (ISO),
opening_balance, closing_balance, total_credits, total_debits,
currency, transactions: [{date, description, credit, debit, balance}] (max 20).""",
	}

	def extract(
		self,
		file_path: str | Path | None = None,
		file_bytes: bytes | None = None,
		file_b64: str | None = None,
		document_type: str = "invoice",
		mime_type: str = "image/jpeg",
	) -> dict[str, Any]:
		"""Extract structured data from a document.

		Provide one of: file_path, file_bytes, or file_b64.
		document_type: invoice | national_id | payslip | bank_statement

		Returns dict with extracted fields + metadata:
		  {success, document_type, extracted_fields, confidence, model_used, error}
		"""
		# Load document bytes
		try:
			document_type = self._normalize_document_type(document_type)
			file_bytes, file_b64, mime_type = self._load_document(
				file_path=file_path,
				file_bytes=file_bytes,
				file_b64=file_b64,
				mime_type=mime_type,
			)
		except Exception as exc:
			return {"success": False, "error": f"Document load failed: {exc}"}

		# Try LLM vision extraction
		try:
			result = self._extract_with_llm_vision(file_b64, mime_type, document_type)
			return {
				"success": True,
				"document_type": document_type,
				"extracted_fields": result,
				"confidence": 0.85,  # LLM vision confidence estimate
				"model_used": "llm_vision",
				"error": None,
			}
		except Exception as exc:
			log.warning("LLM vision extraction failed: %s", exc)

			# Fallback: text extraction for PDFs
			if "pdf" in mime_type.lower() and file_bytes:
				try:
					result = self._extract_from_pdf_text(file_bytes, document_type)
					return {
						"success": True,
						"document_type": document_type,
						"extracted_fields": result,
						"confidence": 0.6,
						"model_used": "pdf_text",
						"error": None,
					}
				except Exception as exc2:
					return {"success": False, "error": f"All extraction methods failed: {exc2}"}

			return {"success": False, "error": str(exc)}

	def _extract_with_llm_vision(self, file_b64: str, mime_type: str, document_type: str) -> dict:
		"""Extract using LLM vision capabilities (Claude vision via LiteLLM)."""
		from pgappforge.plugins.erp.platform.nlp.client import LLMClient
		client = LLMClient()

		document_type = self._normalize_document_type(document_type)
		mime_type = self._normalize_mime_type(mime_type)
		self._decode_b64_document(file_b64)
		prompt = self.EXTRACTION_PROMPTS[document_type]

		# Build multimodal message with image
		messages = [{
			"role": "user",
			"content": [
				{
					"type": "image_url",
					"image_url": {"url": f"data:{mime_type};base64,{file_b64}"},
				},
				{"type": "text", "text": prompt},
			]
		}]

		# Use vision-capable model
		try:
			from flask import current_app
			vision_model = current_app.config.get("VISION_MODEL", "gpt-4o")
		except RuntimeError:
			vision_model = "gpt-4o"

		response = client.chat(messages, model=vision_model, max_tokens=1500, temperature=0.1)
		return self._parse_json_object(response)

	def _extract_from_pdf_text(self, pdf_bytes: bytes, document_type: str) -> dict:
		"""Fallback: extract text from PDF and use LLM text processing."""
		pdf_bytes = self._normalize_bytes(pdf_bytes)
		document_type = self._normalize_document_type(document_type)
		try:
			import pypdf
			import io
			reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
			text = "\n".join((page.extract_text() or "") for page in reader.pages)
		except ImportError:
			raise RuntimeError("pypdf not installed. pip install pypdf")
		if not text.strip():
			raise RuntimeError("PDF text extraction produced no text")

		from pgappforge.plugins.erp.platform.nlp.client import LLMClient
		client = LLMClient()
		prompt = self.EXTRACTION_PROMPTS[document_type]
		response = client.chat(
			[{"role": "user", "content": f"{prompt}\n\nDocument text:\n{text[:_MAX_TEXT_CHARS]}"}],
			max_tokens=1000,
			temperature=0.1,
		)
		return self._parse_json_object(response)

	def save_extraction(
		self,
		extraction_result: dict,
		reference_type: str,
		reference_id: str,
		tenant_id: str,
		session,
	) -> str | None:
		"""Persist extraction result to pgaf_document_extraction table."""
		try:
			import sqlalchemy as sa
			from uuid6 import uuid7
			from datetime import datetime, timezone
			from pgappforge.ai_governance import log_ai_action

			params = self._normalize_extraction_record(
				extraction_result,
				reference_type,
				reference_id,
				tenant_id,
			)
			entry_id = str(uuid7())
			session.execute(sa.text("""
				INSERT INTO pgaf_document_extraction
				(id, tenant_id, reference_type, reference_id, document_type,
				 extracted_json, confidence, model_used, created_at)
				VALUES (:id, :tenant_id, :ref_type, :ref_id, :doc_type,
				        :data::jsonb, :confidence, :model, :ts)
			"""), {
				"id": entry_id,
				**params,
				"ts": datetime.now(timezone.utc),
			})
			log_ai_action(
				"document_extract",
				model_name=extraction_result.get("model_used"),
				reference_type=reference_type,
				reference_id=reference_id,
				session=session,
			)
			return entry_id
		except Exception as exc:
			log.debug("save_extraction failed: %s", exc)
			return None

	@classmethod
	def _normalize_document_type(cls, document_type: Any) -> str:
		if not isinstance(document_type, str):
			raise DocumentIntelligenceValidationError("document_type must be a string")
		value = document_type.strip().lower()
		if value not in cls.EXTRACTION_PROMPTS:
			raise DocumentIntelligenceValidationError(
				f"Unsupported document_type {document_type!r}"
			)
		return value

	@staticmethod
	def _normalize_mime_type(mime_type: Any) -> str:
		if not isinstance(mime_type, str):
			raise DocumentIntelligenceValidationError("mime_type must be a string")
		value = mime_type.strip().lower()
		if value not in _ALLOWED_MIME_TYPES:
			raise DocumentIntelligenceValidationError(f"Unsupported mime_type {mime_type!r}")
		return value

	@staticmethod
	def _normalize_bytes(file_bytes: bytes) -> bytes:
		if not isinstance(file_bytes, bytes):
			raise DocumentIntelligenceValidationError("file_bytes must be bytes")
		if not file_bytes:
			raise DocumentIntelligenceValidationError("file_bytes cannot be empty")
		if len(file_bytes) > _MAX_DOCUMENT_BYTES:
			raise DocumentIntelligenceValidationError(
				f"document cannot exceed {_MAX_DOCUMENT_BYTES} bytes"
			)
		return file_bytes

	@staticmethod
	def _decode_b64_document(file_b64: str) -> bytes:
		if not isinstance(file_b64, str):
			raise DocumentIntelligenceValidationError("file_b64 must be a string")
		value = file_b64.strip()
		if not value:
			raise DocumentIntelligenceValidationError("file_b64 cannot be empty")
		if len(value) > _MAX_BASE64_CHARS:
			raise DocumentIntelligenceValidationError(
				f"file_b64 cannot exceed {_MAX_BASE64_CHARS} characters"
			)
		try:
			decoded = base64.b64decode(value, validate=True)
		except (binascii.Error, ValueError) as exc:
			raise DocumentIntelligenceValidationError("file_b64 is not valid base64") from exc
		return DocumentIntelligenceService._normalize_bytes(decoded)

	@classmethod
	def _load_document(
		cls,
		*,
		file_path: str | Path | None,
		file_bytes: bytes | None,
		file_b64: str | None,
		mime_type: str,
	) -> tuple[bytes | None, str, str]:
		provided = [file_path is not None, file_bytes is not None, file_b64 is not None]
		if sum(provided) != 1:
			raise DocumentIntelligenceValidationError(
				"Provide exactly one of file_path, file_bytes, or file_b64"
			)
		if file_path is not None:
			path = Path(file_path)
			file_bytes = cls._normalize_bytes(path.read_bytes())
			mime_type = mimetypes.guess_type(str(path))[0] or mime_type
			file_b64 = base64.standard_b64encode(file_bytes).decode()
		elif file_bytes is not None:
			file_bytes = cls._normalize_bytes(file_bytes)
			file_b64 = base64.standard_b64encode(file_bytes).decode()
		else:
			file_bytes = cls._decode_b64_document(file_b64 or "")
		return file_bytes, file_b64, cls._normalize_mime_type(mime_type)

	@staticmethod
	def _parse_json_object(response: str) -> dict[str, Any]:
		if not isinstance(response, str) or not response.strip():
			raise DocumentIntelligenceValidationError("LLM response is empty")
		decoder = json.JSONDecoder()
		text = response.strip()
		for index, char in enumerate(text):
			if char != "{":
				continue
			try:
				value, _ = decoder.raw_decode(text[index:])
			except json.JSONDecodeError:
				continue
			if not isinstance(value, dict):
				raise DocumentIntelligenceValidationError("LLM response JSON must be an object")
			return value
		raise DocumentIntelligenceValidationError("LLM response did not contain a JSON object")

	@classmethod
	def _normalize_extraction_record(
		cls,
		extraction_result: Any,
		reference_type: Any,
		reference_id: Any,
		tenant_id: Any,
	) -> dict[str, Any]:
		if not isinstance(extraction_result, dict) or not extraction_result.get("success"):
			raise DocumentIntelligenceValidationError("Only successful extraction results are persisted")
		document_type = cls._normalize_document_type(extraction_result.get("document_type"))
		extracted_fields = extraction_result.get("extracted_fields") or {}
		if not isinstance(extracted_fields, dict):
			raise DocumentIntelligenceValidationError("extracted_fields must be a JSON object")
		data = json.dumps(extracted_fields, sort_keys=True, default=str)
		if len(data) > _MAX_EXTRACTED_JSON_CHARS:
			raise DocumentIntelligenceValidationError("extracted_fields is too large to persist")
		try:
			confidence = float(extraction_result.get("confidence", 0))
		except (TypeError, ValueError) as exc:
			raise DocumentIntelligenceValidationError("confidence must be numeric") from exc
		if confidence < 0 or confidence > 1:
			raise DocumentIntelligenceValidationError("confidence must be between 0 and 1")
		reference_id = cls._bounded_optional_text(
			reference_id, "reference_id", max_length=_MAX_REFERENCE_LENGTH
		)
		model_used = cls._bounded_optional_text(
			extraction_result.get("model_used"), "model_used", max_length=100
		)
		return {
			"tenant_id": cls._require_text(tenant_id, "tenant_id", max_length=64),
			"ref_type": cls._require_text(reference_type, "reference_type", max_length=100),
			"ref_id": reference_id or "",
			"doc_type": document_type,
			"data": data,
			"confidence": confidence,
			"model": model_used or "",
		}

	@staticmethod
	def _require_text(value: Any, field_name: str, *, max_length: int) -> str:
		if not isinstance(value, str):
			raise DocumentIntelligenceValidationError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			raise DocumentIntelligenceValidationError(f"{field_name} is required")
		if len(text) > max_length:
			raise DocumentIntelligenceValidationError(f"{field_name} cannot exceed {max_length} characters")
		return text

	@staticmethod
	def _optional_text(value: Any, field_name: str, *, max_length: int) -> str | None:
		if value is None:
			return None
		return DocumentIntelligenceService._require_text(value, field_name, max_length=max_length)

	@staticmethod
	def _bounded_optional_text(value: Any, field_name: str, *, max_length: int) -> str | None:
		if value is None:
			return None
		if not isinstance(value, str):
			raise DocumentIntelligenceValidationError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			return None
		if len(text) > max_length:
			raise DocumentIntelligenceValidationError(f"{field_name} cannot exceed {max_length} characters")
		return text


def create_document_extraction_table(engine) -> None:
	"""Create pgaf_document_extraction table DDL."""
	import sqlalchemy as sa
	with engine.begin() as conn:
		conn.execute(sa.text("""
		CREATE TABLE IF NOT EXISTS pgaf_document_extraction (
			id               VARCHAR(36)   PRIMARY KEY,
			tenant_id        VARCHAR(36)   NOT NULL,
			reference_type   VARCHAR(100),
			reference_id     VARCHAR(36),
			document_type    VARCHAR(50)   NOT NULL,
			extracted_json   JSONB         NOT NULL DEFAULT '{}',
			confidence       NUMERIC(5,4)  NOT NULL DEFAULT 0,
			model_used       VARCHAR(100),
			created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
		);
		CREATE INDEX IF NOT EXISTS ix_pgaf_docex_tenant
			ON pgaf_document_extraction(tenant_id);
		CREATE INDEX IF NOT EXISTS ix_pgaf_docex_ref
			ON pgaf_document_extraction(reference_type, reference_id);
		"""))


__all__ = [
	"DocumentIntelligenceService",
	"DocumentIntelligenceValidationError",
	"create_document_extraction_table",
]
