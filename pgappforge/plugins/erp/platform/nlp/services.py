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

from pgappforge.plugins.erp.platform.nlp.client import LLMClient

log = logging.getLogger(__name__)
_client = LLMClient()

_ENTITY_KEYS = ("persons", "organisations", "dates", "amounts", "locations")
_SENTIMENTS = {"POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"}
_SUMMARY_STYLES = {
	"executive": "Write an executive summary in plain language.",
	"technical": "Write a technical summary preserving key details.",
	"bullet_points": "Summarize as 3-5 bullet points starting with '-'.",
}
_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


class NLPInputError(ValueError):
	"""Raised when caller supplied NLP inputs are outside the service contract."""


def _extract_json(text: str) -> str:
	"""Extract the first JSON object or array from an LLM response."""
	if not isinstance(text, str):
		return ""
	fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
	candidates = [fenced.group(1), text] if fenced else [text]
	for candidate in candidates:
		extracted = _first_balanced_json(candidate)
		if extracted:
			return extracted
	return text.strip()


def _first_balanced_json(text: str) -> str:
	start_index = -1
	stack: list[str] = []
	in_string = False
	escaped = False
	for index, char in enumerate(text):
		if start_index < 0:
			if char in "{[":
				start_index = index
				stack = ["}" if char == "{" else "]"]
				in_string = False
				escaped = False
			continue

		if in_string:
			if escaped:
				escaped = False
			elif char == "\\":
				escaped = True
			elif char == '"':
				in_string = False
			continue

		if char == '"':
			in_string = True
		elif char in "{[":
			stack.append("}" if char == "{" else "]")
		elif char in "}]":
			if not stack or char != stack[-1]:
				start_index = -1
				stack = []
				continue
			stack.pop()
			if not stack:
				return text[start_index:index + 1].strip()
	return ""


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
		text = self._require_text(text, "text", max_length=20_000)
		categories = self._normalize_categories(categories)
		context = self._optional_text(context, "context", max_length=2000)
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
			data = self._parse_json_object(response)
			category = self._coerce_category(data.get("category"), categories)
			if category is None:
				raise ValueError("LLM returned category outside the allowed set")
			return {
				"category": category,
				"confidence": self._clamp_float(data.get("confidence", 0.5), 0.0, 1.0),
				"reasoning": self._optional_text(
					data.get("reasoning", ""), "reasoning", max_length=1000
				) or "",
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
		text = self._require_text(text, "text", max_length=20_000)
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
			data = self._parse_json_object(response)
			return {key: self._coerce_string_list(data.get(key, [])) for key in _ENTITY_KEYS}
		except Exception as exc:
			log.debug("extract_entities failed: %s", exc)
			return {key: [] for key in _ENTITY_KEYS}

	# ------------------------------------------------------------------
	# Sentiment Analysis
	# ------------------------------------------------------------------

	def analyze_sentiment(self, text: str) -> dict[str, Any]:
		"""Analyse the sentiment of customer/employee feedback.

		Returns:
			{sentiment ("POSITIVE"|"NEGATIVE"|"NEUTRAL"|"MIXED"),
		 score (-1.0..1.0), summary, source}
		"""
		text = self._require_text(text, "text", max_length=20_000)
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
			data = self._parse_json_object(response)
			sentiment = self._optional_text(
				data.get("sentiment", "NEUTRAL"),
				"sentiment",
				max_length=20,
				uppercase=True,
			) or "NEUTRAL"
			if sentiment not in _SENTIMENTS:
				raise ValueError("LLM returned invalid sentiment")
			return {
				"sentiment": sentiment,
				"score": self._clamp_float(data.get("score", 0.0), -1.0, 1.0),
				"summary": self._optional_text(
					data.get("summary", ""), "summary", max_length=1000
				) or "",
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
		text = self._require_text(text, "text", max_length=50_000)
		max_sentences = self._normalize_max_sentences(max_sentences)
		style = self._normalize_style(style)
		try:
			style_instruction = _SUMMARY_STYLES[style]
			prompt = (
				f"{style_instruction} Limit to {max_sentences} sentences.\n\n"
				f"Text:\n{text[:5000]}"
			)
			summary = _client.chat(
				[{"role": "user", "content": prompt}],
				model=_client._model,
				max_tokens=300,
			)
			return self._require_text(summary, "summary", max_length=5000)
		except Exception as exc:
			log.debug("summarize failed: %s", exc)
			return self._fallback_summary(text)

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
		text = self._require_text(text, "text", max_length=50_000)
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
			return self._normalize_invoice_fields(self._parse_json_object(response))
		except Exception as exc:
			log.debug("extract_invoice_fields failed: %s", exc)
			return {}

	# ------------------------------------------------------------------
	# Language Detection
	# ------------------------------------------------------------------

	def detect_language(self, text: str) -> dict[str, Any]:
		"""Detect the language of *text*.

		Returns:
			{language_code (ISO 639-1), language_name, confidence (0-1)}
		"""
		text = self._require_text(text, "text", max_length=20_000)
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
			return self._normalize_language_result(self._parse_json_object(response))
		except Exception as exc:
			log.debug("detect_language failed: %s", exc)
			return {"language_code": "en", "language_name": "English", "confidence": 0.0}

	# ------------------------------------------------------------------
	# Validation and normalization helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _require_text(value: Any, field_name: str, *, max_length: int) -> str:
		if not isinstance(value, str):
			raise NLPInputError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			raise NLPInputError(f"{field_name} is required")
		if "\x00" in text:
			raise NLPInputError(f"{field_name} cannot contain NUL bytes")
		if len(text) > max_length:
			raise NLPInputError(f"{field_name} cannot exceed {max_length} characters")
		return text

	@classmethod
	def _optional_text(
		cls,
		value: Any,
		field_name: str,
		*,
		max_length: int,
		uppercase: bool = False,
	) -> str | None:
		if value is None:
			return None
		if isinstance(value, (int, float)) and not isinstance(value, bool):
			value = str(value)
		if not isinstance(value, str):
			raise NLPInputError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			return None
		if "\x00" in text:
			raise NLPInputError(f"{field_name} cannot contain NUL bytes")
		if len(text) > max_length:
			raise NLPInputError(f"{field_name} cannot exceed {max_length} characters")
		return text.upper() if uppercase else text

	@classmethod
	def _normalize_categories(cls, categories: Any) -> list[str]:
		if not isinstance(categories, list):
			raise NLPInputError("categories must be a list of strings")
		normalized: list[str] = []
		seen: set[str] = set()
		for item in categories:
			text = cls._optional_text(item, "category", max_length=80)
			if text is None:
				continue
			key = text.casefold()
			if key not in seen:
				normalized.append(text)
				seen.add(key)
		if not normalized:
			raise NLPInputError("categories must contain at least one non-empty item")
		if len(normalized) > 50:
			raise NLPInputError("categories cannot contain more than 50 unique items")
		return normalized

	@classmethod
	def _parse_json_object(cls, response: Any) -> dict[str, Any]:
		text = cls._require_text(response, "response", max_length=100_000)
		try:
			data = json.loads(_extract_json(text))
		except json.JSONDecodeError as exc:
			raise ValueError("LLM response did not contain valid JSON") from exc
		if not isinstance(data, dict):
			raise ValueError("LLM response JSON must be an object")
		return data

	@staticmethod
	def _coerce_category(value: Any, categories: list[str]) -> str | None:
		if not isinstance(value, str):
			return None
		text = value.strip()
		for category in categories:
			if text == category:
				return category
		casefolded = text.casefold()
		for category in categories:
			if casefolded == category.casefold():
				return category
		return None

	@staticmethod
	def _clamp_float(value: Any, lower: float, upper: float) -> float:
		if isinstance(value, bool):
			raise ValueError("numeric value cannot be boolean")
		number = float(value)
		if number < lower:
			return lower
		if number > upper:
			return upper
		return number

	@classmethod
	def _coerce_string_list(cls, value: Any, *, max_items: int = 50) -> list[str]:
		if not isinstance(value, list):
			return []
		normalized: list[str] = []
		seen: set[str] = set()
		for item in value:
			try:
				text = cls._optional_text(item, "list_item", max_length=200)
			except NLPInputError:
				continue
			if text is None:
				continue
			key = text.casefold()
			if key in seen:
				continue
			normalized.append(text)
			seen.add(key)
			if len(normalized) >= max_items:
				break
		return normalized

	@staticmethod
	def _normalize_max_sentences(value: Any) -> int:
		if isinstance(value, bool) or not isinstance(value, int):
			raise NLPInputError("max_sentences must be an integer")
		return max(1, min(value, 10))

	@staticmethod
	def _normalize_style(value: Any) -> str:
		if not isinstance(value, str):
			raise NLPInputError("style must be a string")
		style = value.strip().lower()
		return style if style in _SUMMARY_STYLES else "executive"

	@staticmethod
	def _fallback_summary(text: str) -> str:
		return text[:500] + ("..." if len(text) > 500 else "")

	@classmethod
	def _normalize_invoice_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
		currency = cls._optional_text(data.get("currency"), "currency", max_length=12)
		if currency:
			currency = currency.upper()
			if not re.fullmatch(r"[A-Z]{3}", currency):
				currency = None
		line_items: list[dict[str, Any]] = []
		raw_items = data.get("line_items")
		if isinstance(raw_items, list):
			for item in raw_items[:100]:
				if not isinstance(item, dict):
					continue
				line_items.append({
					"description": cls._optional_text(
						item.get("description"), "description", max_length=500
					),
					"quantity": cls._optional_number(item.get("quantity")),
					"unit_price": cls._optional_number(item.get("unit_price")),
					"total": cls._optional_number(item.get("total")),
				})
		return {
			"vendor_name": cls._optional_text(data.get("vendor_name"), "vendor_name", max_length=200),
			"invoice_number": cls._optional_text(
				data.get("invoice_number"), "invoice_number", max_length=120
			),
			"date": cls._optional_text(data.get("date"), "date", max_length=40),
			"due_date": cls._optional_text(data.get("due_date"), "due_date", max_length=40),
			"total_amount": cls._optional_number(data.get("total_amount")),
			"currency": currency,
			"payment_terms": cls._optional_text(
				data.get("payment_terms"), "payment_terms", max_length=500
			),
			"line_items": line_items,
		}

	@staticmethod
	def _optional_number(value: Any) -> float | None:
		if value is None or value == "":
			return None
		if isinstance(value, bool):
			return None
		try:
			return float(value)
		except (TypeError, ValueError):
			return None

	@classmethod
	def _normalize_language_result(cls, data: dict[str, Any]) -> dict[str, Any]:
		code = cls._optional_text(
			data.get("language_code"), "language_code", max_length=20
		)
		code = code.lower() if code else "en"
		if not _LANGUAGE_CODE_RE.fullmatch(code):
			code = "en"
		name = cls._optional_text(
			data.get("language_name"), "language_name", max_length=80
		) or "English"
		return {
			"language_code": code,
			"language_name": name,
			"confidence": cls._clamp_float(data.get("confidence", 0.0), 0.0, 1.0),
		}

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


__all__ = ["NLPService", "NLPInputError", "_extract_json"]
