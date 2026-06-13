from __future__ import annotations
import base64, json, logging, mimetypes
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


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
			if file_path:
				file_bytes = Path(file_path).read_bytes()
				mime_type = mimetypes.guess_type(str(file_path))[0] or "image/jpeg"

			if file_bytes:
				file_b64 = base64.standard_b64encode(file_bytes).decode()

			if not file_b64:
				return {"success": False, "error": "No document provided"}
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
		from pgappforge.plugins.erp.platform.nlp.client import LLMClient, LLMError
		client = LLMClient()

		prompt = self.EXTRACTION_PROMPTS.get(document_type, self.EXTRACTION_PROMPTS["invoice"])

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

		# Parse JSON from response
		import re
		json_match = re.search(r'\{.*\}', response, re.DOTALL)
		if json_match:
			return json.loads(json_match.group())
		return json.loads(response)

	def _extract_from_pdf_text(self, pdf_bytes: bytes, document_type: str) -> dict:
		"""Fallback: extract text from PDF and use LLM text processing."""
		try:
			import pypdf
			import io
			reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
			text = "\n".join(page.extract_text() for page in reader.pages)
		except ImportError:
			raise RuntimeError("pypdf not installed. pip install pypdf")

		from pgappforge.plugins.erp.platform.nlp.client import LLMClient
		client = LLMClient()
		prompt = self.EXTRACTION_PROMPTS.get(document_type, "")
		response = client.chat(
			[{"role": "user", "content": f"{prompt}\n\nDocument text:\n{text[:4000]}"}],
			max_tokens=1000,
			temperature=0.1,
		)
		import re
		json_match = re.search(r'\{.*\}', response, re.DOTALL)
		return json.loads(json_match.group() if json_match else response)

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

			entry_id = str(uuid7())
			session.execute(sa.text("""
				INSERT INTO pgaf_document_extraction
				(id, tenant_id, reference_type, reference_id, document_type,
				 extracted_json, confidence, model_used, created_at)
				VALUES (:id, :tenant_id, :ref_type, :ref_id, :doc_type,
				        :data::jsonb, :confidence, :model, :ts)
			"""), {
				"id": entry_id,
				"tenant_id": tenant_id,
				"ref_type": reference_type,
				"ref_id": reference_id,
				"doc_type": extraction_result.get("document_type", ""),
				"data": json.dumps(extraction_result.get("extracted_fields", {})),
				"confidence": extraction_result.get("confidence", 0),
				"model": extraction_result.get("model_used", ""),
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


__all__ = ["DocumentIntelligenceService", "create_document_extraction_table"]
