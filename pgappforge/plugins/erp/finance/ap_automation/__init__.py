"""
pgappforge/plugins/erp/finance/ap_automation/__init__.py

APAutomationPlugin — Touchless AP Invoice Automation plugin.

Touchless invoice capture pipeline:
  raw text/PDF/email/CSV
    → InvoiceCapture (field extraction via stdlib regex)
    → vendor match (ILIKE against APSupplier)
    → APInvoice (PENDING_REVIEW, human confirms before GL)

No external ML or OCR dependencies.  Documented hook points for:
  - Google Cloud Vision API
  - Azure Form Recognizer
  - Tesseract + pytesseract

Domain: finance
Depends on: foundation, ap (optional — degrades gracefully if absent)

Events emitted:
  finance.ap_automation.captured
  finance.ap_automation.matched
  finance.ap_automation.rejected
  finance.ap_automation.ap_invoice_created

Events consumed:
  (none — driven by user actions / integrations)

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ap",         # optional but recommended
        "pgappforge.plugins.erp.finance.ap_automation",
    ]

Or instantiate directly::

    from pgappforge.plugins.erp.finance.ap_automation import APAutomationPlugin
    plugin = APAutomationPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class APAutomationPlugin(BasePlugin):
	"""AP Invoice Automation plugin.

	Registers capture, match, and conversion views.
	Exposes 1 BPM action for workflow-driven invoice ingestion.
	"""

	name = "ap_automation"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# Metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="ap_automation",
			version="1.0.0",
			description=(
				"AP Invoice Automation — touchless AP invoice capture pipeline: "
				"raw invoice ingestion (text/PDF/email/CSV), stdlib regex extraction, "
				"fuzzy vendor matching, and AP invoice creation for human review. "
				"Hook points for Google Vision, Azure Form Recognizer, Tesseract. "
				"Intacct Touchless AP equivalent."
			),
			author="PgAppForge Contributors",
			tags=[
				"finance",
				"ap",
				"automation",
				"ocr",
				"invoice-capture",
				"intacct-touchless",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_ap_automation_capture_list",
				"can_ap_automation_capture_write",
				"can_ap_automation_capture_match",
				"can_ap_automation_capture_convert",
				"can_ap_automation_capture_reject",
				"can_ap_automation_accuracy_report",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		return [
			"finance.ap_automation.captured",
			"finance.ap_automation.matched",
			"finance.ap_automation.rejected",
			"finance.ap_automation.ap_invoice_created",
		]

	def subscribe_to(self) -> list[str]:
		# AP Automation is triggered by external pushes (email gateway,
		# file drop, API call).  No upstream ERP events consumed at this layer.
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"AP_AUTOMATION_MENU_CATEGORY": "AP Automation",
			"AP_AUTOMATION_DEFAULT_CURRENCY": "KES",
			"AP_AUTOMATION_AUTO_MATCH": True,
			"AP_AUTOMATION_MATCH_CONFIDENCE_THRESHOLD": 70,
		}
		self.config = {**defaults, **self.config}
		# Ensure BPM registrations are imported
		try:
			import pgappforge.plugins.erp.finance.ap_automation.services  # noqa: F401
		except Exception as exc:
			log.debug("APAutomationPlugin.initialize: services import warning: %s", exc)
		log.info("APAutomationPlugin initialised (config keys: %s)", list(self.config))

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.ap_automation.models import InvoiceCapture
		return [InvoiceCapture]

	def register_views(self) -> None:
		# Views wired here when a views.py is added.
		log.debug("APAutomationPlugin: register_views called (no views module yet)")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> APAutomationPlugin:
	"""Construct an APAutomationPlugin without activating it."""
	return APAutomationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.ap_automation.models import (  # noqa: E402
	InvoiceCapture,
)
from pgappforge.plugins.erp.finance.ap_automation.events import (  # noqa: E402
	APInvoiceCreatedFromCaptureEvent,
	InvoiceCapturedEvent,
	InvoiceMatchedEvent,
	InvoiceRejectedEvent,
)
from pgappforge.plugins.erp.finance.ap_automation.services import (  # noqa: E402
	APAutomationService,
)

__all__ = [
	# plugin
	"APAutomationPlugin",
	"create_plugin",
	# models
	"InvoiceCapture",
	# events
	"InvoiceCapturedEvent",
	"InvoiceMatchedEvent",
	"InvoiceRejectedEvent",
	"APInvoiceCreatedFromCaptureEvent",
	# services
	"APAutomationService",
]
