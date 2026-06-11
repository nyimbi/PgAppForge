"""
pgappforge/plugins/fintech/embedded_finance/__init__.py

EmbeddedFinancePlugin — embedded finance capabilities for third-party platforms.

Registers
---------
  - EmbeddedPartnerView   (Embedded Finance > Partners)
  - EmbeddedProductView   (Embedded Finance > Products)
  - EmbeddedDashboardView (Embedded Finance > Dashboard)

Events emitted
--------------
  embedded.partner.onboarded, embedded.consent.granted,
  embedded.transaction, embedded.rev_share.calculated

Depends on
----------
  foundation, core_banking, payments
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EmbeddedFinancePlugin(BasePlugin):
	"""Embedded finance plugin.

	Enables third-party platforms to embed financial products (accounts,
	payments, loans, BNPL, etc.) via a consent-gated API with revenue sharing.
	"""

	name = "embedded_finance"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking", "payments"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="embedded_finance",
			version="1.0.0",
			description=(
				"Embedded Finance — partner onboarding, product enablement, "
				"customer consent management, account/payment provisioning, "
				"and revenue share calculation for marketplaces, SaaS platforms, "
				"neobanks, telcos, and logistics operators."
			),
			author="PgAppForge Contributors",
			tags=[
				"fintech",
				"embedded-finance",
				"baas",
				"open-banking",
				"revenue-share",
				"consent",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_emb_partner_list",
				"can_emb_partner_write",
				"can_emb_product_list",
				"can_emb_product_write",
				"can_emb_consent_manage",
				"can_emb_rev_share_read",
				"can_emb_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Events
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.embedded_finance.events import ALL_EMBEDDED_EVENT_TYPES
		return ALL_EMBEDDED_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		# Listen for payments plugin events to trigger rev-share calculation
		return ["py.payment.completed"]

	def on_event(self, event_type: str, payload: dict, session: Any = None) -> None:
		"""Handle inbound events.

		py.payment.completed — if payment has partner_id, calculate rev share.
		Non-fatal: errors are logged and swallowed.
		"""
		if event_type != "py.payment.completed":
			return
		partner_id = payload.get("partner_id") or payload.get("embedded_partner_id")
		if not partner_id:
			return
		gross = payload.get("amount_cents") or payload.get("gross_revenue_cents")
		if not gross:
			return
		product_type = payload.get("product_type", "PAYMENTS")
		tenant_id = payload.get("tenant_id", self.config.get("EMB_DEFAULT_TENANT_ID", "default"))
		import datetime as _dt
		period = _dt.date.today().strftime("%Y-%m")

		_session = session
		if _session is None:
			try:
				from flask import current_app
				ab = current_app.extensions.get("appbuilder")
				_session = ab.get_session if ab else None
			except RuntimeError:
				_session = None

		if _session is None:
			log.warning("EmbeddedFinancePlugin.on_event: no session available, skipping rev-share")
			return

		try:
			from pgappforge.plugins.fintech.embedded_finance.services import EmbeddedFinanceService
			svc = EmbeddedFinanceService(self.config)
			svc.calculate_revenue_share(
				partner_id=partner_id,
				period=period,
				gross_revenue_cents=int(gross),
				product_type=product_type,
				tenant_id=tenant_id,
				session=_session,
			)
			_session.flush()
		except Exception as exc:
			log.warning(
				"EmbeddedFinancePlugin.on_event: rev-share calculation failed (non-fatal): %s",
				exc,
			)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"EMB_MENU_CATEGORY": "Embedded Finance",
			"EMB_DEFAULT_CURRENCY": "KES",
			"EMB_DEFAULT_ACCOUNT_PRODUCT": "CURRENT",
			"EMB_DEFAULT_TENANT_ID": "default",
		}
		self.config = {**defaults, **self.config}
		log.info("EmbeddedFinancePlugin initialised (config: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Register EmbeddedRevShareRecord immutability after models loaded."""
		from pgappforge.plugins.fintech.embedded_finance.models import EmbeddedRevShareRecord
		EmbeddedRevShareRecord._register_immutability()

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.embedded_finance.views import (
			EmbeddedDashboardView,
			EmbeddedPartnerView,
			EmbeddedProductView,
		)

		cat = self.config.get("EMB_MENU_CATEGORY", "Embedded Finance")

		self.add_view(
			EmbeddedPartnerView,
			"Partners",
			icon="fa-handshake",
			category=cat,
		)
		self.add_view(
			EmbeddedProductView,
			"Products",
			icon="fa-th-large",
			category=cat,
		)
		self.add_view(
			EmbeddedDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("EmbeddedFinancePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.embedded_finance.models import (
			EmbeddedConsent,
			EmbeddedPartner,
			EmbeddedProduct,
			EmbeddedRevShareRecord,
		)
		return [
			EmbeddedPartner,
			EmbeddedProduct,
			EmbeddedConsent,
			EmbeddedRevShareRecord,
		]
