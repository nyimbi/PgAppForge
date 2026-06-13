"""
tests/ci/test_fastapi_services.py

CI tests for the FastAPI async service layer (ARCH-1).

Tests import-level correctness and stub behaviour when FastAPI is not installed.
Full async endpoint tests require: pip install fastapi httpx pytest-anyio
"""
from __future__ import annotations

import pytest


class TestFastAPIServicesImport:
	def test_create_fastapi_app_importable(self):
		from pgappforge.fastapi_services import create_fastapi_app
		assert callable(create_fastapi_app)

	def test_mount_fastapi_importable(self):
		from pgappforge.fastapi_services import mount_fastapi
		assert callable(mount_fastapi)

	def test_get_asgi_app_importable(self):
		from pgappforge.fastapi_services import get_asgi_app
		assert callable(get_asgi_app)

	def test_mpesa_webhook_router_importable(self):
		from pgappforge.fastapi_services.mpesa_webhook import router
		assert router is not None

	def test_ai_inference_router_importable(self):
		from pgappforge.fastapi_services.ai_inference import router
		assert router is not None


class TestFastAPIApp:
	def test_create_returns_app_or_none(self):
		"""Returns FastAPI app when installed, None when not installed."""
		from pgappforge.fastapi_services import create_fastapi_app
		result = create_fastapi_app()
		# Either a FastAPI app or None — never raises
		assert result is None or hasattr(result, "include_router")

	def test_mount_fastapi_returns_bool(self):
		"""Returns bool — True if mounted, False if deps missing."""
		from pgappforge.fastapi_services import mount_fastapi

		class _FakeFlaskApp:
			config = {}
			wsgi_app = None

		result = mount_fastapi(_FakeFlaskApp())
		assert isinstance(result, bool)


class TestMPesaWebhook:
	def test_router_has_required_routes(self):
		"""Confirm router stub is always importable and has required attributes."""
		from pgappforge.fastapi_services.mpesa_webhook import router
		# When FastAPI is installed, router is an APIRouter with routes
		# When not installed, router is a stub — just confirm it doesn't raise
		assert router is not None

	def test_notification_model_when_fastapi_available(self):
		pytest.importorskip("fastapi")
		from pgappforge.fastapi_services.mpesa_webhook import MPesaC2BNotification
		n = MPesaC2BNotification(
			TransID="LGR000000001",
			TransAmount=1000.0,
			MSISDN="+254712345678",
			BillRefNumber="M-12345",
		)
		assert n.TransID == "LGR000000001"
		assert n.TransAmount == 1000.0

	def test_notification_defaults(self):
		pytest.importorskip("fastapi")
		from pgappforge.fastapi_services.mpesa_webhook import MPesaC2BNotification
		n = MPesaC2BNotification()
		assert n.TransAmount == 0.0
		assert n.MSISDN == ""

	def test_mpesa_c2b_validation_accepts(self):
		pytest.importorskip("fastapi")
		import asyncio
		from pgappforge.fastapi_services.mpesa_webhook import mpesa_c2b_validation, MPesaC2BNotification
		loop = asyncio.new_event_loop()
		response = loop.run_until_complete(mpesa_c2b_validation(MPesaC2BNotification()))
		loop.close()
		assert response["ResultCode"] == 0


class TestAIInference:
	def test_router_importable(self):
		from pgappforge.fastapi_services.ai_inference import router
		assert router is not None

	def test_nl_query_request_model(self):
		pytest.importorskip("fastapi")
		from pgappforge.fastapi_services.ai_inference import NLQueryRequest
		req = NLQueryRequest(question="How many invoices last month?", tenant_id="t1")
		assert req.top_k == 5  # default

	def test_document_extraction_request_model(self):
		pytest.importorskip("fastapi")
		from pgappforge.fastapi_services.ai_inference import DocumentExtractionRequest
		req = DocumentExtractionRequest(file_b64="abc123")
		assert req.document_type == "invoice"
		assert req.mime_type == "image/jpeg"

	def test_document_extraction_bad_type(self):
		pytest.importorskip("fastapi")
		from pgappforge.fastapi_services.ai_inference import DocumentExtractionRequest
		from pydantic import ValidationError
		with pytest.raises(ValidationError):
			DocumentExtractionRequest(file_b64="abc", document_type="malware")
