"""
pgappforge/plugins/erp/platform/nlp/services.py

NLP service — text classification, entity extraction, sentiment analysis,
summarization, invoice field extraction, and language detection.

All methods are non-fatal: on LLM unavailability they return a deterministic
stub response so callers can continue without the ML backend.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pgappforge.plugins.erp.platform.nlp.client import LLMClient, LLMError

log = logging.getLogger(__name__)
_client = LLMClient()


def _extract_json(text: str) -> str:
	"""Extract the first JSON object or array from an LLM response."""
	m = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
	if m:
		return m.group(1)
	m = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
	if m:
		return m.group(1)
	return text


class NLPService:
	"""Natural language processing over business text using the LiteLLM proxy.

	All methods return deterministic stub responses when the LLM backend is
	unavailable, so callers never need to handle LLMError.
	"""

	# ------------------------------------------------------------------
	# Text Classification
	# ------------------------------------------------------------------

	def classify_text(
		self,
		text: str,
		categories: list[str],
		context: str = "",
	) -> dict[str, Any]:
		"""Classify *text* into exactly one of *categories*.

		Returns:
			{category, confidence (0-1), reasoning, source ("llm"|"fallback")}
		"""
		try:
			prompt = (
				f"Classify the following text into exactly one of these categories: "
				f"{', '.join(categories)}.\n"
				f"{'Context: ' + context + chr(10) if context else ''}"
				f"Text: {text[:2000]}\n\n"
				f'Respond in JSON: {{"category": "<one of the categories>", '
				f'"confidence": 0.0-1.0, "reasoning": "..."}}'
			)
			response = _client.chat(
				[{"role": "user", "content": prompt}],
				max_tokens=200,
			)
			data = json.loads(_extract_json(response))
			return {
				"category": data.get("category", categories[0]),
				"confidence": float(data.get("confidence", 0.5)),
				"reasoning": data.get("reasoning", ""),
				"source": "llm",
			}
		except Exception as exc:
			log.debug("classify_text failed: %s", exc)
			return {
				"category": categories[0],
				"confidence": 0.0,
				"reasoning": "",
				"source": "fallback",
			}

	# ------------------------------------------------------------------
	# Named Entity Extraction
	# ------------------------------------------------------------------

	def extract_entities(self, text: str) -> dict[str, list[str]]:
		"""Extract named entities from *text*.

		Returns:
			{persons, organisations, dates, amounts, locations} — each a list of strings.
		"""
		_keys = ("persons", "organisations", "dates", "amounts", "locations")
		try:
			prompt = (
				"Extract named entities from this text. Return JSON with keys: "
				"persons, organisations, dates, amounts, locations (each a list of strings).\n"
				f"Text: {text[:3000]}"
			)
			response = _client.chat(
				[{"role": "user", "content": prompt}],
				max_tokens=400,
			)
			data = json.loads(_extract_json(response))
			return {k: data.get(k, []) for k in _keys}
		except Exception as exc:
			log.debug("extract_entities failed: %s", exc)
			return {k: [] for k in _keys}

	# ------------------------------------------------------------------
	# Sentiment Analysis
	# ------------------------------------------------------------------

	def analyze_sentiment(self, text: str) -> dict[str, Any]:
		"""Analyse the sentiment of customer/employee feedback.

		Returns:
			{sentiment ("POSITIVE"|"NEGATIVE"|"NEUTRAL"|"MIXED"),
			 score (-1.0..1.0), summary, source}
		"""
		try:
			prompt = (
				"Analyse the sentiment of this text. "
				'Respond in JSON: {"sentiment": "POSITIVE|NEGATIVE|NEUTRAL|MIXED", '
				'"score": -1.0 to 1.0, "summary": "one sentence"}\n'
				f"Text: {text[:2000]}"
			)
			response = _client.chat(
				[{"role": "user", "content": prompt}],
				max_tokens=150,
			)
			data = json.loads(_extract_json(response))
			return {
				"sentiment": data.get("sentiment", "NEUTRAL"),
				"score": float(data.get("score", 0.0)),
				"summary": data.get("summary", ""),
				"source": "llm",
			}
		except Exception as exc:
			log.debug("analyze_sentiment failed: %s", exc)
			return {"sentiment": "NEUTRAL", "score": 0.0, "summary": "", "source": "fallback"}

	# ------------------------------------------------------------------
	# Summarization
	# ------------------------------------------------------------------

	def summarize(
		self,
		text: str,
		*,
		max_sentences: int = 3,
		style: str = "executive",
	) -> str:
		"""Summarize *text*.

		Args:
			style: "executive" | "technical" | "bullet_points"
		"""
		try:
			style_instruction = {
				"executive": "Write an executive summary in plain language.",
				"technical": "Write a technical summary preserving key details.",
				"bullet_points": "Summarise as 3-5 bullet points starting with •.",
			}.get(style, "Summarise concisely.")
			prompt = (
				f"{style_instruction} Limit to {max_sentences} sentences.\n\n"
				f"Text:\n{text[:5000]}"
			)
			return _client.chat(
				[{"role": "user", "content": prompt}],
				model=_client._model,
				max_tokens=300,
			)
		except Exception as exc:
			log.debug("summarize failed: %s", exc)
			return text[:500] + ("..." if len(text) > 500 else "")

	# ------------------------------------------------------------------
	# Invoice / Document Key-Value Extraction
	# ------------------------------------------------------------------

	def extract_invoice_fields(self, text: str) -> dict[str, Any]:
		"""Extract structured fields from invoice text (OCR output or pasted text).

		Returns:
			{vendor_name, invoice_number, date (ISO), due_date (ISO),
			 total_amount, currency, payment_terms,
			 line_items: [{description, quantity, unit_price, total}]}
		"""
		try:
			prompt = (
				"Extract invoice fields from this text. Respond in JSON with keys: "
				"vendor_name, invoice_number, date (ISO), due_date (ISO), "
				"total_amount (number), currency, payment_terms, "
				"line_items (list of {description, quantity, unit_price, total}).\n\n"
				f"Invoice text:\n{text[:4000]}"
			)
			response = _client.chat(
				[{"role": "user", "content": prompt}],
				model=_client._model,
				max_tokens=600,
			)
			return json.loads(_extract_json(response))
		except Exception as exc:
			log.debug("extract_invoice_fields failed: %s", exc)
			return {}

	# ------------------------------------------------------------------
	# Language Detection
	# ------------------------------------------------------------------

	def detect_language(self, text: str) -> dict[str, str]:
		"""Detect the language of *text*.

		Returns:
			{language_code (ISO 639-1), language_name, confidence (0-1)}
		"""
		try:
			prompt = (
				"What language is this text? Respond JSON: "
				'{"language_code": "ISO 639-1", "language_name": "English", "confidence": 0.0-1.0}\n'
				f"Text: {text[:500]}"
			)
			response = _client.chat(
				[{"role": "user", "content": prompt}],
				max_tokens=80,
			)
			return json.loads(_extract_json(response))
		except Exception as exc:
			log.debug("detect_language failed: %s", exc)
			return {"language_code": "en", "language_name": "English", "confidence": 0.0}

	# ------------------------------------------------------------------
	# ERP-specific convenience helpers
	# ------------------------------------------------------------------

	def classify_support_ticket(self, description: str) -> dict[str, Any]:
		"""Classify an ERP support ticket description."""
		return self.classify_text(
			description,
			["BILLING", "TECHNICAL", "ACCESS", "DATA_QUALITY", "FEATURE_REQUEST", "OTHER"],
			context="ERP support ticket",
		)

	def classify_expense_category(self, description: str) -> dict[str, Any]:
		"""Classify a business expense line-item description."""
		return self.classify_text(
			description,
			[
				"TRAVEL", "MEALS", "ACCOMMODATION", "OFFICE_SUPPLIES",
				"IT_EQUIPMENT", "TRAINING", "ENTERTAINMENT", "UTILITIES", "OTHER",
			],
			context="Business expense",
		)

	def classify_ledger_description(self, description: str) -> dict[str, Any]:
		"""Classify a general-ledger journal-entry description."""
		return self.classify_text(
			description,
			[
				"REVENUE", "COST_OF_GOODS", "OPERATING_EXPENSE",
				"CAPITAL_EXPENDITURE", "PAYROLL", "TAXES", "INTEREST", "OTHER",
			],
			context="General ledger journal entry",
		)


__all__ = ["NLPService"]
