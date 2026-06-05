"""
pgappforge/plugins/erp/finance/assets/__init__.py

Asset Accounting (AA) plugin for the PgAppForge ERP.

Entities:  AssetClass, FixedAsset, AssetDepreciation, AssetImpairment
Service:   AssetService
Events:    asset.capitalised, asset.depreciation_run, asset.disposed,
           asset.impaired, asset.impairment_reversed
Consumes:  exchange_rate.updated (for FX revaluation of foreign-currency assets)

Usage
-----
Add to app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.finance.assets",
    ]

Reports
-------
  /assets/reports/register                   — Fixed Asset Register
  /assets/reports/depreciation-schedule/<id> — Per-asset depreciation schedule
  /assets/reports/nbv-summary                — NBV summary by asset class
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class AssetsPlugin(BasePlugin):
	"""Asset Accounting (AA) plugin.

	Provides: fixed asset register, periodic depreciation, disposal, impairment.
	All financial records are immutable (insert-only correction pattern).
	"""

	name = "assets"
	domain = "finance"
	depends_on: list[str] = ["foundation"]

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="assets",
			version="1.0.0",
			description=(
				"Asset Accounting (AA) — fixed asset register, straight-line / "
				"declining-balance / units-of-production depreciation, IAS 36 "
				"impairment, disposal gain/loss. Immutable ledger pattern."
			),
			author="PgAppForge Contributors",
			tags=["erp", "finance", "assets", "depreciation", "ifrs"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_assets_class_read",
				"can_assets_class_write",
				"can_assets_register_read",
				"can_assets_capitalise",
				"can_assets_dispose",
				"can_assets_impair",
				"can_assets_depreciation_read",
				"can_assets_depreciation_run",
				"can_assets_reports",
				"can_assets_capex_read",
				"can_assets_capex_write",
				"can_assets_revalue",
			],
			safe_mode_compatible=True,
		)

	def get_events(self) -> list[str]:
		return [
			"asset.capitalised",
			"asset.depreciation_run",
			"asset.disposed",
			"asset.impaired",
			"asset.impairment_reversed",
			"asset.capex_project_created",
			"asset.capitalised_from_project",
			"asset.revalued",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"exchange_rate.updated",   # for FX revaluation of foreign-currency assets
		]

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"ASSETS_MENU_CATEGORY": "Fixed Assets",
			"ASSETS_DEFAULT_CURRENCY": "NGN",
		}
		self.config = {**defaults, **self.config}
		log.info("AssetsPlugin initialised")

	def register_views(self) -> None:
		from pgappforge.plugins.erp.finance.assets.views import (
			AssetClassView,
			AssetDepreciationView,
			AssetReportView,
			FixedAssetView,
		)
		cat = self.config.get("ASSETS_MENU_CATEGORY", "Fixed Assets")
		self.add_view(AssetClassView, "Asset Classes", icon="fa-tags", category=cat)
		self.add_view(FixedAssetView, "Asset Register", icon="fa-building", category=cat)
		self.add_view(AssetDepreciationView, "Depreciation", icon="fa-line-chart", category=cat)
		self.add_view(AssetReportView, "Asset Reports", icon="fa-file-text-o", category=cat)
		log.info("AssetsPlugin: views registered under %r", cat)

	def register_models(self) -> list:
		from pgappforge.plugins.erp.finance.assets.models import (
			AssetClass,
			AssetDepreciation,
			AssetDisposal,
			AssetImpairment,
			AssetRevaluation,
			CapexProject,
			FixedAsset,
		)
		return [
			AssetClass, FixedAsset, AssetDepreciation, AssetImpairment,
			CapexProject, AssetDisposal, AssetRevaluation,
		]

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure 4 Rules Engine rulesets for asset domain validation."""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("AssetsPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "asset.positive_cost",
				"description": "Acquisition cost must be > 0",
				"model_name": "FixedAsset",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "acquisition_cost_cents", "op": "lte", "value": 0}],
						"actions_json": [{"type": "raise_error", "message": "acquisition_cost_cents must be positive"}],
					},
				],
			},
			{
				"name": "asset.residual_lt_cost",
				"description": "Residual value must be less than acquisition cost",
				"model_name": "FixedAsset",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_residual_gte_cost",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "residual_value_cents", "op": "gte", "value": "{{acquisition_cost_cents}}"},
						],
						"actions_json": [
							{"type": "raise_error", "message": "residual_value_cents must be less than acquisition_cost_cents"}
						],
					},
				],
			},
			{
				"name": "asset.no_dispose_already_disposed",
				"description": "Cannot dispose an already-disposed asset",
				"model_name": "FixedAsset",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_double_dispose",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "DISPOSED"},
							{"field": "_new_status", "op": "eq", "value": "DISPOSED"},
						],
						"actions_json": [
							{"type": "raise_error", "message": "Asset is already in DISPOSED status"}
						],
					},
				],
			},
			{
				"name": "asset.impairment_positive_loss",
				"description": "Impairment loss must be positive",
				"model_name": "AssetImpairment",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_zero_impairment",
						"trigger_event": "on_before_create",
						"conditions_json": [{"field": "impairment_loss_cents", "op": "lte", "value": 0}],
						"actions_json": [
							{"type": "raise_error", "message": "impairment_loss_cents must be positive"}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
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
		log.info("AssetsPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> AssetsPlugin:
	return AssetsPlugin(appbuilder, config=config or {})


# Public re-exports
from pgappforge.plugins.erp.finance.assets.models import (  # noqa: E402
	AssetClass,
	AssetDepreciation,
	AssetDisposal,
	AssetImpairment,
	AssetRevaluation,
	CapexProject,
	FixedAsset,
)
from pgappforge.plugins.erp.finance.assets.services import (  # noqa: E402
	AssetService,
	AssetServiceError,
	AssetNotFoundError,
	AssetStatusError,
	CapitaliseDetails,
)
from pgappforge.plugins.erp.finance.assets.events import (  # noqa: E402
	AssetCapitalisedEvent,
	AssetDepreciationRunEvent,
	AssetDisposedEvent,
	AssetImpairedEvent,
	AssetImpairmentReversedEvent,
)

__all__ = [
	"AssetsPlugin",
	"create_plugin",
	# models
	"AssetClass",
	"FixedAsset",
	"AssetDepreciation",
	"AssetImpairment",
	"CapexProject",
	"AssetDisposal",
	"AssetRevaluation",
	# services
	"AssetService",
	"AssetServiceError",
	"AssetNotFoundError",
	"AssetStatusError",
	"CapitaliseDetails",
	# events
	"AssetCapitalisedEvent",
	"AssetDepreciationRunEvent",
	"AssetDisposedEvent",
	"AssetImpairedEvent",
	"AssetImpairmentReversedEvent",
]
