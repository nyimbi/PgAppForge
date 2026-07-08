"""
pgappforge/plugins/erp/platform/nlp/__init__.py

NLPPlugin — natural language processing for business text.

Domain:    platform
Depends:   foundation

Capabilities
------------
  * Text classification (support tickets, expenses, GL descriptions, custom)
  * Named entity extraction (persons, orgs, dates, amounts, locations)
  * Sentiment analysis (-1.0 … +1.0 score)
  * Summarization (executive / technical / bullet-points)
  * Invoice field extraction from OCR/pasted text
  * Language detection

LLM backend
-----------
  Calls the LiteLLM proxy (OpenAI-compatible REST).  All methods degrade
  gracefully to stub responses when the proxy is unreachable, so the plugin
  can be activated in environments without LLM access.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class NLPPlugin(BasePlugin):
	"""NLP plugin — LLM-backed text analysis for ERP modules."""

	name = "nlp"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="nlp",
			version="1.0.0",
			description=(
				"Natural language processing: classify text, extract entities, "
				"analyse sentiment, summarize, extract invoice fields, and detect language. "
				"Backed by LiteLLM proxy; degrades gracefully when unavailable."
			),
			author="PgAppForge Contributors",
			tags=["platform", "nlp", "ai", "ml", "text", "llm", "classification", "sentiment"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_nlp_classify",
				"can_nlp_entities",
				"can_nlp_sentiment",
				"can_nlp_summarize",
				"can_nlp_extract_invoice",
				"can_nlp_detect_language",
				"can_nlp_result_read",
				"can_nlp_dashboard_view",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.nlp.classification.completed",
			"platform.nlp.entities.extracted",
			"platform.nlp.sentiment.analysed",
			"platform.nlp.summarization.completed",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"LITELLM_URL": "http://localhost:4000/v1",
			"LITELLM_API_KEY": "",
			"LLM_MODEL": "gpt-4o",
			"LLM_FAST_MODEL": "gpt-4o-mini",
			"LLM_EMBEDDING_MODEL": "text-embedding-ada-002",
			# Persist each analysis call to NLPAnalysisResult for audit + caching
			"NLP_CACHE_RESULTS": True,
		}
		# Only set keys that are not already present in app config
		try:
			from flask import current_app
			for key, val in defaults.items():
				current_app.config.setdefault(key, val)
		except RuntimeError:
			# No app context during import — values will be read lazily from config
			pass
		self.config = {**defaults, **self.config}
		log.info("NLPPlugin initialised")

	def register_models(self) -> list[type]:
		from pgappforge.plugins.erp.platform.nlp.models import NLPAnalysisResult
		return [NLPAnalysisResult]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.platform.nlp.views import (
			NLPAnalysisResultView,
			NLPDashboardView,
		)
		cat = self.config.get("NLP_MENU_CATEGORY", "AI & NLP")
		self.add_view(
			NLPDashboardView,
			"NLP Dashboard",
			icon="fa-brain",
			category=cat,
		)
		self.add_view(
			NLPAnalysisResultView,
			"Analysis Results",
			icon="fa-list-alt",
			category=cat,
		)
		log.info("NLPPlugin: views registered under %r", cat)


def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> NLPPlugin:
	return NLPPlugin(appbuilder, config=config or {})


# Convenience re-exports so callers can do:
#   from pgappforge.plugins.erp.platform.nlp import NLPService, NLPAnalysisResult
from pgappforge.plugins.erp.platform.nlp.client import (  # noqa: E402
	LLMClient,
	LLMConfigError,
	LLMError,
	LLMResponseError,
)
from pgappforge.plugins.erp.platform.nlp.models import NLPAnalysisResult  # noqa: E402
from pgappforge.plugins.erp.platform.nlp.services import NLPInputError, NLPService  # noqa: E402

__all__ = [
	"NLPPlugin",
	"create_plugin",
	"LLMClient",
	"LLMError",
	"LLMConfigError",
	"LLMResponseError",
	"NLPAnalysisResult",
	"NLPInputError",
	"NLPService",
]
