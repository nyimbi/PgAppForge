"""
pgappforge/fastapi_services/ai_inference.py

Async AI inference endpoints for high-throughput NL-to-SQL and document extraction.

These offload blocking LLM calls from Flask request threads via FastAPI + anyio.

pip install fastapi uvicorn
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

try:
	from fastapi import APIRouter, HTTPException
	from pydantic import BaseModel, Field

	router = APIRouter()

	# ------------------------------------------------------------------ #
	# Request / response schemas
	# ------------------------------------------------------------------ #

	class NLQueryRequest(BaseModel):
		question: str = Field(..., min_length=3, max_length=2000)
		tenant_id: str = ""
		top_k: int = Field(default=5, ge=1, le=50)

	class NLQueryResponse(BaseModel):
		sql: str = ""
		result: list[dict] = []
		explanation: str = ""
		error: str | None = None

	class DocumentExtractionRequest(BaseModel):
		file_b64: str = Field(..., description="Base64-encoded file bytes")
		document_type: str = Field(default="invoice", pattern="^(invoice|national_id|payslip|bank_statement)$")
		mime_type: str = "image/jpeg"
		tenant_id: str = ""

	class DocumentExtractionResponse(BaseModel):
		success: bool
		document_type: str = ""
		extracted_fields: dict = {}
		confidence: float = 0.0
		model_used: str = ""
		error: str | None = None

	# ------------------------------------------------------------------ #
	# NL-to-SQL
	# ------------------------------------------------------------------ #

	@router.post("/nl-query", response_model=NLQueryResponse)
	async def nl_query(request: NLQueryRequest):
		"""Convert a natural-language question to SQL and execute it.

		Delegates to NLAnalyticsService (Vanna.ai backed).
		Runs in a thread-pool executor so the event loop stays unblocked.
		"""
		import asyncio

		loop = asyncio.get_event_loop()
		try:
			result = await loop.run_in_executor(
				None,
				_sync_nl_query,
				request.question,
				request.tenant_id,
				request.top_k,
			)
			return result
		except Exception as exc:
			log.error("nl_query failed: %s", exc, exc_info=True)
			raise HTTPException(status_code=500, detail=str(exc))

	def _sync_nl_query(question: str, tenant_id: str, top_k: int) -> dict:
		try:
			from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService  # type: ignore[import]
			svc = NLAnalyticsService()
			result = svc.query(question, session=None, tenant_id=tenant_id)
			return {
				"sql": result.get("sql", ""),
				"result": result.get("result", [])[:top_k],
				"explanation": result.get("explanation", ""),
				"error": result.get("error"),
			}
		except ImportError:
			return {
				"sql": "",
				"result": [],
				"explanation": "",
				"error": "nl_analytics plugin not installed",
			}
		except Exception as exc:
			return {"sql": "", "result": [], "explanation": "", "error": str(exc)}

	# ------------------------------------------------------------------ #
	# Document extraction
	# ------------------------------------------------------------------ #

	@router.post("/document-extract", response_model=DocumentExtractionResponse)
	async def document_extract(request: DocumentExtractionRequest):
		"""Extract structured fields from a base64-encoded document.

		Delegates to DocumentIntelligenceService (LLM vision backed).
		"""
		import asyncio

		loop = asyncio.get_event_loop()
		try:
			result = await loop.run_in_executor(
				None,
				_sync_document_extract,
				request.file_b64,
				request.document_type,
				request.mime_type,
			)
			return result
		except Exception as exc:
			log.error("document_extract failed: %s", exc, exc_info=True)
			raise HTTPException(status_code=500, detail=str(exc))

	def _sync_document_extract(file_b64: str, document_type: str, mime_type: str) -> dict:
		try:
			from pgappforge.plugins.erp.platform.document_intelligence.services import (  # type: ignore[import]
				DocumentIntelligenceService,
			)
			result = DocumentIntelligenceService().extract(
				file_b64=file_b64,
				document_type=document_type,
				mime_type=mime_type,
			)
			return result
		except ImportError:
			return {
				"success": False,
				"document_type": document_type,
				"extracted_fields": {},
				"confidence": 0.0,
				"model_used": "",
				"error": "document_intelligence plugin not installed",
			}
		except Exception as exc:
			return {
				"success": False,
				"document_type": document_type,
				"extracted_fields": {},
				"confidence": 0.0,
				"model_used": "",
				"error": str(exc),
			}

	# ------------------------------------------------------------------ #
	# Health
	# ------------------------------------------------------------------ #

	@router.get("/health")
	async def ai_health():
		"""AI service health — check which backends are available."""
		backends: dict[str, bool] = {}

		try:
			from pgappforge.plugins.erp.platform.nl_analytics.services import NLAnalyticsService  # type: ignore[import]
			backends["nl_analytics"] = True
		except ImportError:
			backends["nl_analytics"] = False

		try:
			from pgappforge.plugins.erp.platform.document_intelligence.services import DocumentIntelligenceService  # type: ignore[import]
			backends["document_intelligence"] = True
		except ImportError:
			backends["document_intelligence"] = False

		return {"status": "ok", "backends": backends}

except ImportError:
	# FastAPI not installed — stub router
	class _StubRouter:  # type: ignore[no-redef]
		def post(self, *a, **k):
			return lambda f: f

		def get(self, *a, **k):
			return lambda f: f

	router = _StubRouter()  # type: ignore[assignment]

__all__ = ["router"]
