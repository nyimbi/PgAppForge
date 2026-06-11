"""
pgappforge/plugins/fintech/remittance/__init__.py

RemittancePlugin — cross-border money transfer plugin.

Depends on core_banking, foundation, and regulatory (for AML/KYC checks).
Regulatory dependency is soft: all compliance calls fall back gracefully
when the regulatory plugin is not installed.

Registers
---------
  - RemittanceCorridorView   (Remittance → Corridors)
  - RemittanceTransactionView (Remittance → Transfers)
  - RemittanceDashboardView  (Remittance → Dashboard)

Events emitted
--------------
  remittance.quote.generated
  remittance.transfer.initiated
  remittance.transfer.paid
  remittance.transfer.cancelled
  remittance.compliance.checked

BPM actions
-----------
  remittance.get_quote
  remittance.initiate_transfer

Seed data
---------
  RemittancePlugin.post_initialize calls seed_africa_corridors() for 9
  Africa-focused corridors (KE→UG/TZ/RW/GB/US/AE, NG→GB/US, GH→GB).
  Idempotent.
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


class RemittancePlugin(BasePlugin):
	"""Cross-border remittance plugin.

	Class-level attributes:
	    name       = "remittance"
	    domain     = "fintech"
	    depends_on = ["foundation", "core_banking", "regulatory"]
	"""

	name = "remittance"
	domain = "fintech"
	depends_on: list[str] = ["foundation", "core_banking", "regulatory"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="remittance",
			version="1.0.0",
			description=(
				"Cross-border remittance plugin — FX corridors, quote generation, "
				"AML/KYC compliance checks, payout processing, and Africa corridor "
				"seed data (KE/NG/GH to GB/US/AE/EAC neighbours)."
			),
			author="PgAppForge Contributors",
			tags=["fintech", "remittance", "fx", "cross-border", "aml"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_rem_corridor_list",
				"can_rem_corridor_write",
				"can_rem_transfer_list",
				"can_rem_transfer_show",
				"can_rem_dashboard",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# Event bus
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		from pgappforge.plugins.fintech.remittance.events import ALL_REM_EVENT_TYPES
		return ALL_REM_EVENT_TYPES

	def subscribe_to(self) -> list[str]:
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"REM_MENU_CATEGORY": "Remittance",
			"REM_SEED_CORRIDORS": True,
			"REM_DEFAULT_TENANT_ID": "default",
			# FX rates dict keyed "FROM_TO" e.g. {"KE_GB": 0.0066, "KE_US": 0.0077}
			# If empty or key missing, fx_rate defaults to 1.0.
			"REMITTANCE_FX_RATES": {},
			"REM_SCHEDULER_ENABLED": True,
		}
		self.config = {**defaults, **self.config}
		log.info("RemittancePlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed Africa corridors if configured."""
		if self.config.get("REM_SEED_CORRIDORS", True):
			self._try_seed_corridors()

	def register_views(self) -> None:
		from pgappforge.plugins.fintech.remittance.views import (
			RemittanceCorridorView,
			RemittanceDashboardView,
			RemittanceTransactionView,
		)

		cat = self.config.get("REM_MENU_CATEGORY", "Remittance")

		self.add_view(
			RemittanceCorridorView,
			"Corridors",
			icon="fa-route",
			category=cat,
		)
		self.add_view(
			RemittanceTransactionView,
			"Transfers",
			icon="fa-exchange-alt",
			category=cat,
		)
		self.add_view(
			RemittanceDashboardView,
			"Dashboard",
			icon="fa-tachometer-alt",
			category=cat,
		)

		log.info("RemittancePlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.fintech.remittance.models import (
			RemittanceCorridor,
			RemittanceComplianceLog,
			RemittanceQuote,
			RemittanceTransaction,
		)
		return [
			RemittanceCorridor,
			RemittanceQuote,
			RemittanceTransaction,
			RemittanceComplianceLog,
		]

	def register_schedules(self) -> None:
		"""No recurring batch jobs for remittance in v1.0."""
		pass

	# ------------------------------------------------------------------
	# Seed helper
	# ------------------------------------------------------------------

	def _try_seed_corridors(self) -> None:
		"""Attempt corridor seeding; log failures, never raise."""
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			tenant_id = self.config.get("REM_DEFAULT_TENANT_ID", "default")
			from pgappforge.plugins.fintech.remittance.services import RemittanceService
			svc = RemittanceService(config=self.config)
			n = svc.seed_africa_corridors(tenant_id, session)
			if n:
				session.commit()
				log.info("RemittancePlugin: seeded %d Africa corridors", n)
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("RemittancePlugin._try_seed_corridors failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register("remittance.get_quote", "Generate an FX quote for a remittance corridor")
def _bpm_get_quote(
	record_ctx: dict,
	session: Any,
	from_country: str = "",
	to_country: str = "",
	send_amount_cents: int = 0,
	payout_method: str = "BANK",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.remittance.services import (
			RemittanceService,
			CorridorNotFoundError,
		)
	except ImportError:
		return {"status": "error", "message": "remittance plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = RemittanceService()
		quote = svc.get_quote(
			from_country=from_country,
			to_country=to_country,
			send_amount_cents=send_amount_cents,
			payout_method=payout_method,
			tenant_id=_tenant_id,
			session=session,
		)
		return {
			"status": "ok",
			"quote_id": quote.id,
			"receive_amount_cents": quote.receive_amount_cents,
			"fee_cents": quote.fee_cents,
			"fx_rate": str(quote.fx_rate),
			"expires_at": quote.expires_at.isoformat(),
		}
	except Exception as exc:
		log.warning("bpm remittance.get_quote failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"remittance.initiate_transfer",
	"Initiate a cross-border transfer from a quote",
)
def _bpm_initiate_transfer(
	record_ctx: dict,
	session: Any,
	quote_id: str = "",
	sender_customer_id: str = "",
	receiver_name: str = "",
	receiver_phone: str = "",
	tenant_id: str = "",
	receiver_account: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
	except ImportError:
		return {"status": "error", "message": "remittance plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = RemittanceService()
		txn = svc.initiate_transfer(
			quote_id=quote_id,
			sender_customer_id=sender_customer_id,
			receiver_name=receiver_name,
			receiver_phone=receiver_phone,
			tenant_id=_tenant_id,
			session=session,
			receiver_account=receiver_account,
		)
		return {
			"status": "ok",
			"transaction_id": txn.id,
			"reference": txn.reference,
			"transaction_status": txn.status,
		}
	except Exception as exc:
		log.warning("bpm remittance.initiate_transfer failed: %s", exc)
		return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> RemittancePlugin:
	"""Construct and return a RemittancePlugin.  Does NOT call activate()."""
	return RemittancePlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.fintech.remittance.models import (  # noqa: E402
	RemittanceCorridor,
	RemittanceComplianceLog,
	RemittanceQuote,
	RemittanceTransaction,
)
from pgappforge.plugins.fintech.remittance.events import (  # noqa: E402
	ALL_REM_EVENT_TYPES,
	ComplianceCheckEvent,
	QuoteGeneratedEvent,
	REM_COMPLIANCE_CHECKED,
	REM_QUOTE_GENERATED,
	REM_TRANSFER_CANCELLED,
	REM_TRANSFER_INITIATED,
	REM_TRANSFER_PAID,
	TransferCancelledEvent,
	TransferInitiatedEvent,
	TransferPaidEvent,
)
from pgappforge.plugins.fintech.remittance.services import (  # noqa: E402
	CorridorNotFoundError,
	InvalidTransactionStatusError,
	QuoteExpiredError,
	QuoteNotFoundError,
	RemittanceError,
	RemittanceService,
	TransactionNotFoundError,
)
from pgappforge.plugins.fintech.remittance.views import (  # noqa: E402
	RemittanceCorridorView,
	RemittanceDashboardView,
	RemittanceTransactionView,
)

__all__ = [
	# plugin
	"RemittancePlugin",
	"create_plugin",
	# models
	"RemittanceCorridor",
	"RemittanceQuote",
	"RemittanceTransaction",
	"RemittanceComplianceLog",
	# events — classes
	"QuoteGeneratedEvent",
	"TransferInitiatedEvent",
	"TransferPaidEvent",
	"TransferCancelledEvent",
	"ComplianceCheckEvent",
	# events — constants
	"REM_QUOTE_GENERATED",
	"REM_TRANSFER_INITIATED",
	"REM_TRANSFER_PAID",
	"REM_TRANSFER_CANCELLED",
	"REM_COMPLIANCE_CHECKED",
	"ALL_REM_EVENT_TYPES",
	# services
	"RemittanceService",
	"RemittanceError",
	"CorridorNotFoundError",
	"QuoteExpiredError",
	"QuoteNotFoundError",
	"TransactionNotFoundError",
	"InvalidTransactionStatusError",
	# views
	"RemittanceCorridorView",
	"RemittanceTransactionView",
	"RemittanceDashboardView",
]
