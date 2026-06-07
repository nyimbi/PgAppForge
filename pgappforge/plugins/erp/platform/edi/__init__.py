"""
pgappforge/plugins/erp/platform/edi/__init__.py

EDI Framework plugin — multi-protocol B2B message exchange.

Supported formats:
  X12        — 850/810/856/997 parse + 850/810 generation
  EDIFACT    — partner registration (format generation planned)
  PEPPOL     — BIS 3.0 UBL 2.1 invoice XML generation
  ETIMS      — KRA eTIMS JSON v3 (Kenya e-invoicing mandate)
  GENERIC_REST — HTTP/HTTPS delivery for custom REST partners

Events emitted:
  platform.edi.message.sent
  platform.edi.message.received
  platform.edi.partner.registered
  platform.edi.parse.error

Usage
-----
    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.platform.edi"]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EDIPlugin(BasePlugin):
	"""EDI Framework — multi-protocol B2B message exchange and e-invoicing."""

	name = "edi"
	domain = "platform"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="edi",
			version="1.0.0",
			description=(
				"EDI Framework — trading partner registry, X12 (850/810/856/997) "
				"parse/generate, EDIFACT partner support, Peppol BIS 3.0 UBL 2.1 XML, "
				"and KRA eTIMS JSON v3 for Kenya e-invoicing mandate."
			),
			author="PgAppForge Contributors",
			tags=[
				"platform", "edi", "x12", "edifact", "peppol", "etims",
				"b2b", "integration",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_edi_partners_read",
				"can_edi_partners_write",
				"can_edi_messages_read",
				"can_edi_messages_write",
				"can_edi_dispatch",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"platform.edi.message.sent",
			"platform.edi.message.received",
			"platform.edi.partner.registered",
			"platform.edi.parse.error",
		]

	def subscribe_to(self) -> list[str]:
		return []

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"EDI_DEFAULT_PROTOCOL": "X12",
			"EDI_DISPATCH_TIMEOUT_SECS": 30,
		}
		self.config = {**defaults, **self.config}
		log.info("EDIPlugin initialised")

	def register_models(self) -> list:
		from pgappforge.plugins.erp.platform.edi.models import EDIPartner, EDIMessage
		return [EDIPartner, EDIMessage]


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> EDIPlugin:
	return EDIPlugin(appbuilder, config=config or {})


from pgappforge.plugins.erp.platform.edi.models import EDIPartner, EDIMessage  # noqa: E402
from pgappforge.plugins.erp.platform.edi.services import EDIService  # noqa: E402

__all__ = [
	"EDIPlugin",
	"create_plugin",
	"EDIPartner",
	"EDIMessage",
	"EDIService",
]
