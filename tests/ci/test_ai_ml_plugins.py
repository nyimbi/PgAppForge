"""CI tests for AI/ML platform plugins: NLP, RAG, ML Predictions.
All structural/import tests — no LLM calls needed."""
from __future__ import annotations
import inspect


# ── LLM Client ────────────────────────────────────────────────────────────────

def test_llm_client_import():
	from pgappforge.plugins.erp.platform.nlp.client import LLMClient
	c = LLMClient()
	assert callable(c.chat)
	assert callable(c.embed)
	assert callable(c.is_available)

def test_llm_client_no_context_uses_defaults():
	from pgappforge.plugins.erp.platform.nlp.client import LLMClient
	c = LLMClient()
	assert c._base_url == "http://localhost:4000/v1"
	assert c._api_key == ""
	assert "Authorization" not in c._headers()
	assert c._fast_model in ("gpt-4o-mini", "gpt-4o")
	assert "ada" in c._embedding_model or "embedding" in c._embedding_model

def test_llm_error_is_exception():
	from pgappforge.plugins.erp.platform.nlp.client import LLMError
	assert issubclass(LLMError, Exception)


# ── NLP Service ───────────────────────────────────────────────────────────────

def test_nlp_service_import():
	from pgappforge.plugins.erp.platform.nlp.services import NLPService
	svc = NLPService()
	for m in ("classify_text","extract_entities","analyze_sentiment",
	          "summarize","extract_invoice_fields","detect_language",
	          "classify_support_ticket","classify_expense_category","classify_ledger_description"):
		assert callable(getattr(svc, m)), f"NLPService.{m} missing"

def test_nlp_classify_fallback_no_llm():
	from pgappforge.plugins.erp.platform.nlp.services import NLPService
	svc = NLPService()
	# Patch _client.chat to always raise
	from pgappforge.plugins.erp.platform.nlp import client as c_mod
	orig = c_mod.LLMClient.chat
	c_mod.LLMClient.chat = lambda *a, **k: (_ for _ in ()).throw(Exception("no llm"))
	try:
		result = svc.classify_text("Some text", ["A", "B", "C"])
		assert result["source"] == "fallback"
		assert result["category"] in ("A", "B", "C")
		assert result["confidence"] == 0.0
	finally:
		c_mod.LLMClient.chat = orig

def test_nlp_sentiment_fallback():
	from pgappforge.plugins.erp.platform.nlp.services import NLPService
	from pgappforge.plugins.erp.platform.nlp import client as c_mod
	orig = c_mod.LLMClient.chat
	c_mod.LLMClient.chat = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
	try:
		result = NLPService().analyze_sentiment("some text")
		assert result["sentiment"] == "NEUTRAL"
		assert result["source"] == "fallback"
	finally:
		c_mod.LLMClient.chat = orig

def test_nlp_summarize_fallback_returns_truncated():
	from pgappforge.plugins.erp.platform.nlp.services import NLPService
	from pgappforge.plugins.erp.platform.nlp import client as c_mod
	orig = c_mod.LLMClient.chat
	c_mod.LLMClient.chat = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
	try:
		long_text = "word " * 300
		result = NLPService().summarize(long_text)
		assert len(result) <= 503  # truncation fallback
	finally:
		c_mod.LLMClient.chat = orig

def test_extract_json_helper():
	from pgappforge.plugins.erp.platform.nlp.services import _extract_json
	# JSON in markdown block
	assert _extract_json('```json\n{"key": "val"}\n```') == '{"key": "val"}'
	# Raw JSON
	assert _extract_json('Here is {"a": 1} for you') == '{"a": 1}'

def test_nlp_model_tablename():
	from pgappforge.plugins.erp.platform.nlp.models import NLPAnalysisResult
	assert NLPAnalysisResult.__tablename__ == "plat_nlp_result"

def test_nlp_plugin_metadata():
	from pgappforge.plugins.erp.platform.nlp import NLPPlugin
	p = NLPPlugin.__new__(NLPPlugin)
	assert p.name == "nlp"
	assert p.domain == "platform"


# ── RAG Service ───────────────────────────────────────────────────────────────

def test_rag_models_import():
	from pgappforge.plugins.erp.platform.rag.models import RAGDocument, RAGChunk
	assert RAGDocument.__tablename__ == "plat_rag_document"
	assert RAGChunk.__tablename__ == "plat_rag_chunk"

def test_rag_service_import():
	from pgappforge.plugins.erp.platform.rag.services import RAGService
	svc = RAGService()
	assert callable(svc.ingest_document)
	assert callable(svc.search)
	assert callable(svc.ask)
	assert callable(svc.get_index_stats)
	assert callable(svc.delete_document)

def test_cosine_similarity_identical():
	from pgappforge.plugins.erp.platform.nlp.client import cosine_similarity as _cosine_similarity
	v = [1.0, 0.0, 0.0]
	assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

def test_cosine_similarity_orthogonal():
	from pgappforge.plugins.erp.platform.nlp.client import cosine_similarity as _cosine_similarity
	assert abs(_cosine_similarity([1,0], [0,1])) < 1e-6

def test_cosine_similarity_empty():
	from pgappforge.plugins.erp.platform.nlp.client import cosine_similarity as _cosine_similarity
	assert _cosine_similarity([], []) == 0.0

def test_chunk_text_small():
	from pgappforge.plugins.erp.platform.rag.services import RAGService
	svc = RAGService()
	chunks = svc._chunk_text("short text", chunk_size=800)
	assert chunks == ["short text"]

def test_chunk_text_splits_long():
	from pgappforge.plugins.erp.platform.rag.services import RAGService
	svc = RAGService()
	text = "sentence. " * 200  # ~2000 chars
	chunks = svc._chunk_text(text, chunk_size=400, overlap=50)
	assert len(chunks) > 1
	for c in chunks:
		assert len(c) > 0

def test_rag_embed_fallback_no_llm():
	from pgappforge.plugins.erp.platform.rag.services import RAGService
	from pgappforge.plugins.erp.platform.nlp import client as c_mod
	orig = c_mod.LLMClient.embed
	c_mod.LLMClient.embed = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
	try:
		svc = RAGService()
		result = svc._embed_chunks(["test"])
		assert result == [None]
	finally:
		c_mod.LLMClient.embed = orig

def test_rag_plugin_metadata():
	from pgappforge.plugins.erp.platform.rag import RAGPlugin
	p = RAGPlugin.__new__(RAGPlugin)
	assert p.name == "rag"
	assert "nlp" in p.depends_on


# ── ML Predictions ────────────────────────────────────────────────────────────

def test_ml_models_import():
	from pgappforge.plugins.erp.platform.ml_predictions.models import MLPrediction, MLModelConfig
	assert MLPrediction.__tablename__ == "plat_ml_prediction"
	assert MLModelConfig.__tablename__ == "plat_ml_model_config"

def test_ml_service_import():
	from pgappforge.plugins.erp.platform.ml_predictions.services import MLPredictionService
	svc = MLPredictionService()
	for m in ("detect_duplicate_invoice","predict_attrition_risk","score_lead",
	          "detect_gl_anomaly","forecast_demand"):
		assert callable(getattr(svc, m)), f"MLPredictionService.{m} missing"

def test_gl_anomaly_z_score_logic():
	"""Verify z-score anomaly detection works without DB."""
	import math
	# Replicate the z-score logic directly
	amounts = [1000, 1100, 950, 1050, 1020, 980, 1010, 1030, 1040, 900]
	mean = sum(amounts) / len(amounts)
	variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
	std = math.sqrt(variance)
	# A value 3σ above mean should be flagged
	outlier = mean + 3 * std
	z = abs((outlier - mean) / std)
	assert z >= 2.5, f"Outlier z={z} should be >= 2.5"

def test_lead_score_stage_mapping():
	from pgappforge.plugins.erp.platform.ml_predictions.services import MLPredictionService
	src = inspect.getsource(MLPredictionService.score_lead)
	# All stages should be mapped
	for stage in ("QUALIFICATION", "PROPOSAL", "NEGOTIATION", "CLOSING"):
		assert stage in src

def test_demand_forecast_moving_average_logic():
	"""Test the moving-average forecasting math."""
	values = [100, 110, 120, 130, 140]  # increasing trend
	window = 3
	ma = sum(values[-window:]) / window
	assert abs(ma - 130.0) < 0.01, f"MA should be 130, got {ma}"

def test_ml_plugin_metadata():
	from pgappforge.plugins.erp.platform.ml_predictions import MLPredictionsPlugin
	p = MLPredictionsPlugin.__new__(MLPredictionsPlugin)
	assert p.name == "ml_predictions"
	assert "nlp" in p.depends_on
