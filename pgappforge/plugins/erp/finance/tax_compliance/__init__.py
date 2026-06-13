"""
pgappforge/plugins/erp/finance/tax_compliance/__init__.py

TaxCompliancePlugin — Africa e-invoicing mandate integration.

Wires AR invoice approval events to the appropriate tax authority connector
based on COMPLIANCE_COUNTRY config:

    KE  → KRA eTIMS
    UG  → URA EFRIS
    ZM  → ZRA Smart Invoice
    NG  → (in progress)
    GH  → (in progress)

Usage::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.ar",
        "pgappforge.plugins.erp.finance.tax_compliance",
    ]

Required config::

    COMPLIANCE_COUNTRY     = "KE"   # KE | UG | ZM | NG | GH
    TAX_COMPLIANCE_ENABLED = True

    # KE
    ETIMS_PIN            = "A000000000Z"
    ETIMS_BRANCH_ID      = "00"

    # UG
    EFRIS_TIN            = "1000000000"
    EFRIS_DEVICE_ID      = "..."

    # ZM
    ZRA_TIN              = "0000000000"
    ZRA_BHFID            = "000"
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class TaxCompliancePlugin(BasePlugin):
	"""Africa tax compliance plugin — auto-submits AR invoices to fiscal authorities.

	Class-level attributes for dependency resolution:
	    name       = "tax_compliance"
	    domain     = "finance"
	    depends_on = ["foundation", "ar"]
	"""

	name = "tax_compliance"
	domain = "finance"
	depends_on: list[str] = ["foundation", "ar"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="tax_compliance",
			version="1.0.0",
			description=(
				"Africa e-invoicing compliance — auto-submits approved AR invoices "
				"to KRA eTIMS (KE), URA EFRIS (UG), or ZRA Smart Invoice (ZM) "
				"based on COMPLIANCE_COUNTRY configuration."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "tax", "compliance", "etims", "efris", "zra", "africa"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_tax_compliance_view",
				"can_tax_compliance_submit",
				"can_tax_compliance_admin",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"finance.tax_compliance.invoice.submitted",
			"finance.tax_compliance.invoice.submission_failed",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"finance.ar.invoice.approved",
			"finance.ar.invoice.finalized",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"TAX_COMPLIANCE_MENU_CATEGORY": "Tax Compliance",
		}
		self.config = {**defaults, **self.config}
		log.info("TaxCompliancePlugin initialised")

	def post_initialize(self) -> None:
		"""Subscribe to AR invoice events and ensure audit table exists."""
		from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService
		self._service = TaxComplianceService()
		self._service.subscribe_to_invoice_events()

		# Create audit table if the engine is available
		try:
			from flask import current_app
			engine = current_app.extensions.get("sqlalchemy_engine") or (
				current_app.extensions.get("sqlalchemy").engine
				if current_app.extensions.get("sqlalchemy")
				else None
			)
			if engine is not None:
				self._service.create_compliance_tables(engine)
				log.info("TaxCompliancePlugin: pgaf_tax_submission table ensured")
		except Exception as exc:
			log.debug("TaxCompliancePlugin.post_initialize: table setup skipped — %s", exc)

	def register_views(self) -> None:
		"""Register compliance dashboard view."""
		from pgappforge.plugins.erp.finance.tax_compliance.views import TaxComplianceDashboardView
		cat = self.config.get("TAX_COMPLIANCE_MENU_CATEGORY", "Tax Compliance")
		self.add_view(
			TaxComplianceDashboardView,
			"Tax Compliance",
			icon="fa-shield-alt",
			category=cat,
		)
		log.info("TaxCompliancePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""No ORM models — the audit table is DDL-managed via create_compliance_tables."""
		return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> TaxCompliancePlugin:
	"""Construct and return a TaxCompliancePlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return TaxCompliancePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.finance.tax_compliance.services import TaxComplianceService  # noqa: E402

__all__ = [
	"TaxCompliancePlugin",
	"TaxComplianceService",
	"create_plugin",
]
