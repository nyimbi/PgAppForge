"""
pgappforge/plugins/erp/foundation/__init__.py

FoundationPlugin — root ERP plugin.  All other ERP plugins declare
depends_on = ["foundation"].

Exposes: Party, Currency, Country, CodeTable, Address, Contact, Note,
         Attachment, DomainEventLog, ExchangeRate, PartyRole

Usage
-----
Add to your app config::

    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.erp.foundation"]

Or instantiate directly::

    from pgappforge.plugins.erp.foundation import FoundationPlugin
    plugin = FoundationPlugin(appbuilder)
    plugin.activate()

Events emitted
--------------
  party.created, party.updated, party.merged, exchange_rate.updated

Events consumed
---------------
  (none — root plugin)
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class FoundationPlugin(BasePlugin):
	"""Root ERP Foundation plugin.

	Registers master-data CRUD views and seeds reference data on first run.

	Class-level attributes used by dependent plugins for dependency resolution:
	    name     = "foundation"
	    domain   = "platform"
	    depends_on = []
	"""

	name = "foundation"
	domain = "platform"
	depends_on: list[str] = []

	# ------------------------------------------------------------------
	# BasePlugin.metadata (required abstract property)
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="foundation",
			version="1.0.0",
			description=(
				"ERP Foundation — shared master-data entities (Party, Currency, "
				"Country, CodeTable, Address, Contact, Note, Attachment, "
				"DomainEventLog) used by all ERP plugins."
			),
			author="PgAppForge Contributors",
			tags=["erp", "foundation", "platform", "master-data"],
			priority=PluginPriority.HIGH,
			permissions=[
				"can_foundation_party_list",
				"can_foundation_party_write",
				"can_foundation_fx_read",
				"can_foundation_fx_write",
				"can_foundation_codes_read",
				"can_foundation_codes_write",
				"can_foundation_events_read",
				"can_foundation_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# get_events / subscribe_to  (ERP plugin contract)
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"party.created",
			"party.updated",
			"party.merged",
			"exchange_rate.updated",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes — none, it is the root."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults.  No heavy work here — keep it fast."""
		defaults: dict[str, Any] = {
			"FOUNDATION_MENU_CATEGORY": "Master Data",
			"FOUNDATION_SEED_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("FoundationPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Optionally seed reference data after initialize()."""
		if self.config.get("FOUNDATION_SEED_ON_INIT", True):
			self._try_seed()

	def register_views(self) -> None:
		"""Register Foundation views under the configured menu category."""
		from pgappforge.plugins.erp.foundation.views import (
			CodeTableView,
			DomainEventLogView,
			ExchangeRateView,
			FoundationReportView,
			PartyView,
		)

		cat = self.config.get("FOUNDATION_MENU_CATEGORY", "Master Data")

		self.add_view(
			PartyView,
			"Parties",
			icon="fa-users",
			category=cat,
		)
		self.add_view(
			ExchangeRateView,
			"Exchange Rates",
			icon="fa-exchange",
			category=cat,
		)
		self.add_view(
			CodeTableView,
			"Code Tables",
			icon="fa-list",
			category=cat,
		)
		self.add_view(
			FoundationReportView,
			"Foundation Reports",
			icon="fa-file-text-o",
			category=cat,
		)
		self.add_view_no_menu(DomainEventLogView)

		log.info("FoundationPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.foundation.models import (
			Address,
			Attachment,
			CodeTable,
			Contact,
			Country,
			Currency,
			DomainEventLog,
			ExchangeRate,
			Note,
			Party,
			PartyRole,
		)
		return [
			Party, PartyRole, Address, Contact,
			Currency, ExchangeRate,
			Country, CodeTable,
			Note, Attachment,
			DomainEventLog,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 5 rulesets in the Rules Engine for common Party scenarios.

		Call once at app startup after the rules tables are created.
		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("FoundationPlugin.setup_rules: rules plugin not available, skipping")
			return

		RULESETS = [
			{
				"name": "party.required_fields",
				"description": "Require name and party_type on Party create",
				"model_name": "Party",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_missing_name",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "name", "op": "eq", "value": ""}],
						"actions_json": [{"type": "raise_error", "message": "Party name is required"}],
					},
				],
			},
			{
				"name": "party.deactivation_guard",
				"description": "Prevent deactivating a Party with active roles",
				"model_name": "Party",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_deactivate_with_roles",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_new_is_active", "op": "eq", "value": False},
							{"field": "_old_is_active", "op": "eq", "value": True},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Cannot deactivate Party with active roles; close roles first"}
						],
					},
				],
			},
			{
				"name": "party_role.temporal_validity",
				"description": "Ensure effective_to is after effective_from",
				"model_name": "PartyRole",
				"stop_on_match": True,
				"rules": [
					{
						"name": "effective_to_after_from",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "effective_to", "op": "lt", "value": "{{effective_from}}"},
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "effective_to must be after effective_from"}
						],
					},
				],
			},
			{
				"name": "exchange_rate.positive_rate",
				"description": "Exchange rate must be positive",
				"model_name": "ExchangeRate",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_non_positive_rate",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "rate", "op": "lte", "value": 0}],
						"actions_json": [
							{"type": "raise_error", "message": "Exchange rate must be positive"}
						],
					},
				],
			},
			{
				"name": "attachment.size_quota",
				"description": "Attachment size must not exceed 50 MB",
				"model_name": "Attachment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_oversized_attachment",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "size_bytes", "op": "gt", "value": 52_428_800}
						],
						"actions_json": [
							{"type": "raise_error",
							 "message": "Attachment exceeds the 50 MB size limit"}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				__import__("sqlalchemy", fromlist=["select"])
				.select(RuleSet)
				.where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("FoundationPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal seed helper
	# ------------------------------------------------------------------

	def _try_seed(self) -> None:
		"""Attempt to seed currencies and countries; log failures, never raise."""
		try:
			from flask import current_app
			from pgappforge.plugins.erp.foundation.services import FoundationService
			svc = FoundationService()
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			n_ccy = svc.seed_major_currencies(session)
			n_cty = svc.seed_major_countries(session)
			if n_ccy or n_cty:
				session.commit()
				log.info(
					"FoundationPlugin seed: inserted %d currencies, %d countries",
					n_ccy, n_cty,
				)
		except RuntimeError:
			# No app context yet (e.g. called during import); skip silently
			pass
		except Exception as exc:
			log.warning("FoundationPlugin._try_seed failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> FoundationPlugin:
	"""Construct and return a FoundationPlugin bound to *appbuilder*.

	Does NOT call activate()::

	    plugin = create_plugin(appbuilder)
	    plugin.activate()
	"""
	return FoundationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.foundation.models import (  # noqa: E402
	Address,
	Attachment,
	CodeTable,
	Contact,
	Country,
	Currency,
	DomainEventLog,
	ExchangeRate,
	Note,
	Party,
	PartyRole,
)
from pgappforge.plugins.erp.foundation.events import (  # noqa: E402
	DomainEvent,
	ExchangeRateUpdatedEvent,
	PartyCreatedEvent,
	PartyMergedEvent,
	PartyUpdatedEvent,
	emit_event,
	subscribe,
	unsubscribe,
)
from pgappforge.plugins.erp.foundation.services import (  # noqa: E402
	ExchangeRateNotFoundError,
	FoundationService,
	FoundationServiceError,
	PartyNotFoundError,
)

__all__ = [
	# plugin
	"FoundationPlugin",
	"create_plugin",
	# models
	"Party",
	"PartyRole",
	"Address",
	"Contact",
	"Currency",
	"ExchangeRate",
	"Country",
	"CodeTable",
	"Note",
	"Attachment",
	"DomainEventLog",
	# events
	"DomainEvent",
	"PartyCreatedEvent",
	"PartyUpdatedEvent",
	"PartyMergedEvent",
	"ExchangeRateUpdatedEvent",
	"emit_event",
	"subscribe",
	"unsubscribe",
	# services
	"FoundationService",
	"FoundationServiceError",
	"PartyNotFoundError",
	"ExchangeRateNotFoundError",
]
