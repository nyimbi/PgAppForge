"""Regression tests for NLP and LiteLLM boundary hardening."""
from __future__ import annotations

import json

import pytest

from pgappforge.plugins.erp.platform.nlp.client import (
	LLMClient,
	LLMConfigError,
	LLMResponseError,
)
from pgappforge.plugins.erp.platform.nlp.services import (
	NLPInputError,
	NLPService,
	_extract_json,
)


class _FakeResponse:
	def __init__(self, payload: dict) -> None:
		self._payload = json.dumps(payload).encode("utf-8")

	def __enter__(self) -> "_FakeResponse":
		return self

	def __exit__(self, *args: object) -> None:
		return None

	def read(self, limit: int = -1) -> bytes:
		return self._payload if limit is None or limit < 0 else self._payload[:limit]


def test_llm_client_rejects_unsafe_configuration() -> None:
	with pytest.raises(LLMConfigError):
		LLMClient._normalize_base_url("http://example.com/v1")
	with pytest.raises(LLMConfigError):
		LLMClient._normalize_base_url("https://example.com/v1?debug=true")
	with pytest.raises(LLMConfigError):
		LLMClient._safe_header_value("token\r\nX-Injected: yes")
	with pytest.raises(LLMConfigError):
		LLMClient()._build_url("/../chat/completions")


def test_llm_chat_normalizes_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
	seen: dict[str, object] = {}

	def fake_urlopen(req: object, timeout: int | float) -> _FakeResponse:
		seen["url"] = req.full_url
		seen["method"] = req.get_method()
		seen["timeout"] = timeout
		seen["payload"] = json.loads(req.data.decode("utf-8"))
		return _FakeResponse({"choices": [{"message": {"content": " ok "}}]})

	monkeypatch.setattr(
		"pgappforge.plugins.erp.platform.nlp.client.urllib.request.urlopen",
		fake_urlopen,
	)

	result = LLMClient().chat([{"role": "user", "content": "hello"}], max_tokens=12)

	assert result == "ok"
	assert seen["url"] == "http://localhost:4000/v1/chat/completions"
	assert seen["method"] == "POST"
	assert seen["timeout"] == 30
	assert seen["payload"]["max_tokens"] == 12


def test_llm_client_rejects_invalid_chat_and_embedding_shapes(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	client = LLMClient()

	monkeypatch.setattr(client, "_post", lambda *args, **kwargs: {"choices": []})
	with pytest.raises(LLMResponseError):
		client.chat([{"role": "user", "content": "hello"}])

	monkeypatch.setattr(client, "_post", lambda *args, **kwargs: {"data": [{"embedding": [1]}]})
	with pytest.raises(LLMResponseError):
		client.embed(["a", "b"])


def test_extract_json_uses_first_balanced_payload() -> None:
	assert _extract_json('```json\n{"key": {"nested": true}}\n```') == (
		'{"key": {"nested": true}}'
	)
	assert _extract_json('prefix {"a": {"b": 1}} suffix {"c": 2}') == (
		'{"a": {"b": 1}}'
	)


def test_nlp_service_validates_inputs_before_fallback() -> None:
	service = NLPService()
	with pytest.raises(NLPInputError):
		service.classify_text("", ["A"])
	with pytest.raises(NLPInputError):
		service.classify_text("text", [])
	with pytest.raises(NLPInputError):
		service.summarize("text", max_sentences=True)


def test_classify_text_normalizes_llm_category_and_confidence(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	from pgappforge.plugins.erp.platform.nlp import services as svc_mod

	monkeypatch.setattr(
		svc_mod._client,
		"chat",
		lambda *args, **kwargs: '{"category": "b", "confidence": 1.7, "reasoning": "match"}',
	)

	result = NLPService().classify_text("Some text", ["A", "B"])

	assert result == {
		"category": "B",
		"confidence": 1.0,
		"reasoning": "match",
		"source": "llm",
	}


def test_classify_text_falls_back_for_out_of_contract_llm_category(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	from pgappforge.plugins.erp.platform.nlp import services as svc_mod

	monkeypatch.setattr(
		svc_mod._client,
		"chat",
		lambda *args, **kwargs: '{"category": "OTHER", "confidence": 0.9}',
	)

	result = NLPService().classify_text("Some text", ["A", "B"])

	assert result["source"] == "fallback"
	assert result["category"] == "A"


def test_entities_sentiment_invoice_and_language_are_normalized(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	from pgappforge.plugins.erp.platform.nlp import services as svc_mod

	responses = iter([
		(
			'{"persons": ["Ada", "ada", null], "organisations": ["OpenAI"], '
			'"dates": ["2026-07-08"], "amounts": [123], "locations": ["Nairobi"]}'
		),
		'{"sentiment": "positive", "score": 5, "summary": "Strong feedback"}',
		(
			'{"vendor_name": "Acme Ltd", "invoice_number": "INV-1", '
			'"date": "2026-07-01", "due_date": "2026-07-31", '
			'"total_amount": "123.45", "currency": "usd", "payment_terms": "Net 30", '
			'"line_items": [{"description": "Hosting", "quantity": "2", '
			'"unit_price": "50", "total": "100"}]}'
		),
		'{"language_code": "EN-US", "language_name": "English", "confidence": 1.5}',
	])
	monkeypatch.setattr(svc_mod._client, "chat", lambda *args, **kwargs: next(responses))

	entities = NLPService().extract_entities("Ada from OpenAI visited Nairobi.")
	assert entities["persons"] == ["Ada"]
	assert entities["amounts"] == ["123"]

	sentiment = NLPService().analyze_sentiment("Excellent service.")
	assert sentiment["sentiment"] == "POSITIVE"
	assert sentiment["score"] == 1.0

	invoice = NLPService().extract_invoice_fields("Invoice INV-1")
	assert invoice["currency"] == "USD"
	assert invoice["total_amount"] == 123.45
	assert invoice["line_items"][0]["quantity"] == 2.0

	language = NLPService().detect_language("Hello.")
	assert language == {
		"language_code": "en-us",
		"language_name": "English",
		"confidence": 1.0,
	}
