"""
pgappforge/plugins/fintech/__init__.py

Fintech plugin suite — 11 plugins covering the complete fintech stack.

Dependency order (must install in this sequence):
  1. CoreBanking          — foundational: accounts, ledger, interest, products
  2. Lending              — depends on CoreBanking (LOS + LMS)
     Payments             — depends on CoreBanking (payment rails, clearing)
     MobileMoney          — depends on CoreBanking (wallets, agents, USSD)
     PswitchAdapter       — depends on CoreBanking (card auth + settlement via Hyperion-X)
     CardIssuing          — depends on CoreBanking (virtual/physical card lifecycle, PIN, 3DS)
     SWIFT                — depends on CoreBanking + Payments (MT103/MT202/MT700, GPI, nostro)
     Treasury             — depends on CoreBanking + Payments (FX deals, rates, limits)
  3. SACCO                — depends on CoreBanking + Lending
     TradeFinance         — depends on CoreBanking + Payments
  4. Regulatory           — depends on all above (AML, Basel III, IFRS 9, CBK/goAML returns)

Usage::

	from pgappforge.plugins.fintech import install_all

	# Registers all 8 plugins in dependency order
	install_all(appbuilder)

Or individually::

	from pgappforge.plugins.fintech.core_banking import CoreBankingPlugin
	from pgappforge.plugins.fintech.lending import LendingPlugin
	from pgappforge.plugins.fintech.payments import PaymentsPlugin
	from pgappforge.plugins.fintech.mobile_money import MobileMoneyPlugin
	from pgappforge.plugins.fintech.pswitch_adapter import PswitchAdapterPlugin
	from pgappforge.plugins.fintech.card_issuing import CardIssuingPlugin
	from pgappforge.plugins.fintech.swift import SwiftPlugin
	from pgappforge.plugins.fintech.treasury import TreasuryPlugin
	from pgappforge.plugins.fintech.sacco import SACCOPlugin
	from pgappforge.plugins.fintech.trade_finance import TradeFinancePlugin
	from pgappforge.plugins.fintech.regulatory import RegulatoryPlugin

	plugin = CoreBankingPlugin(appbuilder)
	plugin.activate()
"""
from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

log = logging.getLogger(__name__)


# Plugin name → import path mapping (lazy to avoid circular imports at module load).
# Frozen after creation — callers must not mutate this.
PLUGIN_REGISTRY: MappingProxyType[str, str] = MappingProxyType({
	"core_banking":    "pgappforge.plugins.fintech.core_banking",
	"lending":         "pgappforge.plugins.fintech.lending",
	"payments":        "pgappforge.plugins.fintech.payments",
	"mobile_money":    "pgappforge.plugins.fintech.mobile_money",
	"pswitch_adapter": "pgappforge.plugins.fintech.pswitch_adapter",
	"card_issuing":    "pgappforge.plugins.fintech.card_issuing",
	"swift":           "pgappforge.plugins.fintech.swift",
	"treasury":        "pgappforge.plugins.fintech.treasury",
	"sacco":           "pgappforge.plugins.fintech.sacco",
	"trade_finance":   "pgappforge.plugins.fintech.trade_finance",
	"regulatory":      "pgappforge.plugins.fintech.regulatory",
})

# Install order respects dependency graph:
#   CoreBanking → [Lending, Payments, MobileMoney, PswitchAdapter]
#              → [SACCO, TradeFinance] → Regulatory
_INSTALL_ORDER: list[str] = [
	"core_banking",
	"lending",
	"payments",
	"mobile_money",
	"pswitch_adapter",
	"card_issuing",
	"swift",
	"treasury",
	"sacco",
	"trade_finance",
	"regulatory",
]


def install_all(
	appbuilder: Any,
	configs: dict[str, dict[str, Any]] | None = None,
	*,
	skip: list[str] | None = None,
) -> dict[str, Any]:
	"""Activate all fintech plugins in dependency order.

	Parameters
	----------
	appbuilder:
		The AppBuilder instance to register views and permissions against.
	configs:
		Optional per-plugin config overrides keyed by plugin name, e.g.::

			{
				"core_banking": {"CB_DEFAULT_CURRENCY": "USD"},
				"lending": {"LOS_MAX_LOAN_AMOUNT_CENTS": 50_000_000_00},
			}
	skip:
		List of plugin names to skip (e.g. ["sacco"] for non-SACCO deployments).

	Returns
	-------
	dict[str, plugin]
		Mapping of plugin_name → activated plugin instance.
	"""
	configs = configs or {}
	skip = skip or []
	installed: dict[str, Any] = {}

	for name in _INSTALL_ORDER:
		if name in skip:
			log.info("fintech.install_all: skipping plugin %r (in skip list)", name)
			continue

		module_path = PLUGIN_REGISTRY[name]
		plugin_config = configs.get(name, {})

		try:
			import importlib
			mod = importlib.import_module(module_path)
			# Each plugin module exposes create_plugin(appbuilder, config) or
			# a Plugin class named after the plugin (e.g. CoreBankingPlugin).
			if hasattr(mod, "create_plugin"):
				plugin = mod.create_plugin(appbuilder, config=plugin_config)
			else:
				# Fallback: look for <TitleCase>Plugin class
				cls_name = "".join(part.title() for part in name.split("_")) + "Plugin"
				cls = getattr(mod, cls_name, None)
				if cls is None:
					log.warning(
						"fintech.install_all: no create_plugin or %s found in %s; skipping",
						cls_name, module_path,
					)
					continue
				plugin = cls(appbuilder, config=plugin_config)

			plugin.activate()
			installed[name] = plugin
			log.info("fintech.install_all: activated plugin %r", name)

		except ImportError as exc:
			log.warning(
				"fintech.install_all: could not import %r (%s); skipping", name, exc
			)
		except Exception as exc:
			log.error(
				"fintech.install_all: failed to activate plugin %r: %s", name, exc,
				exc_info=True,
			)

	log.info(
		"fintech.install_all: done — %d/%d plugins activated: %s",
		len(installed),
		len(_INSTALL_ORDER) - len(skip),
		list(installed),
	)
	return installed


def list_plugins() -> list[str]:
	"""Return the list of available fintech plugin names in install order."""
	return list(_INSTALL_ORDER)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"install_all",
	"list_plugins",
	"PLUGIN_REGISTRY",
	"_INSTALL_ORDER",
]
