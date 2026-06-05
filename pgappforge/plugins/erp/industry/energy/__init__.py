"""
pgappforge/plugins/erp/industry/energy/__init__.py

EnergyPlugin — Energy & Utilities Cloud ERP plugin.

Provides:
  - Meter              (electric, gas, water, heat, steam)
  - MeterReading       (actual, estimated, AMR, corrected; IMMUTABLE)
  - EnergyBill         (IMMUTABLE once ISSUED; integer cents)
  - RenewableAttribute (REC/REGO/GO certificates; IMMUTABLE once retired)

Business rules enforced:
  - All monetary amounts: integer cents — never float
  - MeterReading rows are immutable (new row + supersede old for corrections)
  - EnergyBill rows are immutable once status=ISSUED (void + reissue for corrections)
  - RenewableAttribute retired=True is permanent and irreversible
  - Consumption calculated as delta from previous reading × meter multiplier

Events emitted:
  energy.meter.reading_submitted
  energy.bill.issued
  energy.bill.paid
  energy.certificate.retired
  energy.outage.detected
  energy.renewable.certificate.issued
  energy.carbon.calculated

Events consumed:
  grc.sustainability.emission.recorded

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.energy",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class EnergyPlugin(BasePlugin):
	"""Energy & Utilities Cloud ERP plugin.

	Class-level routing metadata:
	    name       = "energy"
	    domain     = "industry"
	    depends_on = ["foundation", "finance.ar", "finance.gl", "grc.sustainability"]
	"""

	name = "energy"
	domain = "industry"
	depends_on: list[str] = ["foundation", "finance.ar", "finance.gl", "grc.sustainability"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="energy",
			version="1.0.0",
			description=(
				"Energy & Utilities Cloud — smart meter management, tariff-based billing, "
				"renewable energy certificate (REC/REGO/GO) issuance and retirement, "
				"carbon footprint calculation, anomaly detection, and demand forecasting."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "energy", "utilities", "meters", "renewables", "carbon"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_energy_meter_read",
				"can_energy_meter_write",
				"can_energy_reading_read",
				"can_energy_reading_write",
				"can_energy_bill_read",
				"can_energy_bill_write",
				"can_energy_bill_issue",
				"can_energy_certificate_read",
				"can_energy_certificate_write",
				"can_energy_certificate_retire",
				"can_energy_carbon_read",
				"can_energy_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"energy.meter.read",
			"energy.bill.generated",
			"energy.outage.detected",
			"energy.renewable.certificate.issued",
			"energy.carbon.calculated",
			# legacy names kept for backward compat
			"energy.meter.reading_submitted",
			"energy.bill.issued",
			"energy.bill.paid",
			"energy.certificate.retired",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"grc.sustainability.emission.recorded",
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"ENERGY_MENU_CATEGORY": "Energy & Utilities",
			"ENERGY_DEFAULT_CURRENCY": "USD",
			"ENERGY_DEFAULT_EMISSION_FACTOR": "0.000233",  # tCO2e per kWh (US average scope 2)
			"ENERGY_ANOMALY_STD_DEV_THRESHOLD": 2,
			"ENERGY_FORECAST_DEFAULT_DAYS": 30,
			"ENERGY_SEED_RULES_ON_INIT": True,
		}
		self.config = {**defaults, **self.config}
		log.info("EnergyPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("ENERGY_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Energy views under the configured menu category."""
		from pgappforge.plugins.erp.industry.energy.views import (
			MeterView,
			MeterReadingView,
			EnergyBillView,
			RenewableAttributeView,
			CarbonDashboardView,
		)

		cat = self.config.get("ENERGY_MENU_CATEGORY", "Energy & Utilities")

		self.add_view(
			MeterView,
			"Meters",
			icon="fa-tachometer",
			category=cat,
		)
		self.add_view(
			MeterReadingView,
			"Meter Readings",
			icon="fa-bar-chart",
			category=cat,
		)
		self.add_view(
			EnergyBillView,
			"Energy Bills",
			icon="fa-file-text-o",
			category=cat,
		)
		self.add_view(
			RenewableAttributeView,
			"Renewable Certificates",
			icon="fa-leaf",
			category=cat,
		)
		self.add_view(
			CarbonDashboardView,
			"Carbon Dashboard",
			icon="fa-cloud",
			category=cat,
		)

		log.info("EnergyPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.energy.models import (
			Meter,
			MeterReading,
			EnergyBill,
			RenewableAttribute,
		)
		return [Meter, MeterReading, EnergyBill, RenewableAttribute]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure domain rulesets for the Energy plugin.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("EnergyPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "energy.bill.no_reissue_after_issued",
				"description": "Block re-issuing a bill that is already ISSUED or PAID",
				"model_name": "EnergyBill",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_bill_reissue",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "status", "op": "in", "value": ["ISSUED", "PAID"]},
							{"field": "_new_status", "op": "eq", "value": "ISSUED"},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "Cannot re-issue a bill that is already ISSUED or PAID. Void it first.",
							}
						],
					},
				],
			},
			{
				"name": "energy.certificate.no_unretire",
				"description": "Prevent un-retiring a REC/REGO once retired=True",
				"model_name": "RenewableAttribute",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_unretire",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "retired", "op": "eq", "value": True},
							{"field": "_new_retired", "op": "eq", "value": False},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": "RenewableAttribute: retired certificates cannot be un-retired.",
							}
						],
					},
				],
			},
			{
				"name": "energy.reading.positive_consumption",
				"description": "Flag negative consumption as anomalous (rollover must be handled explicitly)",
				"model_name": "MeterReading",
				"stop_on_match": False,
				"rules": [
					{
						"name": "warn_negative_consumption",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{"field": "consumption_kwh", "op": "lt", "value": 0},
						],
						"actions_json": [
							{
								"type": "set_field",
								"field": "status",
								"value": "DISPUTED",
							}
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
		log.info(
			"EnergyPlugin.setup_rules: %d rulesets configured", len(RULESETS)
		)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning(
				"EnergyPlugin._try_setup_rules failed (non-fatal): %s", exc
			)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> EnergyPlugin:
	return EnergyPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.energy.models import (  # noqa: E402
	Meter,
	MeterReading,
	EnergyBill,
	RenewableAttribute,
)
from pgappforge.plugins.erp.industry.energy.events import (  # noqa: E402
	MeterReadingSubmittedEvent,
	EnergyBillIssuedEvent,
	EnergyBillPaidEvent,
	RenewableCertificateRetiredEvent,
)
from pgappforge.plugins.erp.industry.energy.services import (  # noqa: E402
	EnergyService,
	EnergyError,
	MeterNotFoundError,
	BillNotFoundError,
	CertificateNotFoundError,
	InvalidReadingError,
	BillAlreadyIssuedError,
)

__all__ = [
	# plugin
	"EnergyPlugin",
	"create_plugin",
	# models
	"Meter",
	"MeterReading",
	"EnergyBill",
	"RenewableAttribute",
	# events
	"MeterReadingSubmittedEvent",
	"EnergyBillIssuedEvent",
	"EnergyBillPaidEvent",
	"RenewableCertificateRetiredEvent",
	# services
	"EnergyService",
	"EnergyError",
	"MeterNotFoundError",
	"BillNotFoundError",
	"CertificateNotFoundError",
	"InvalidReadingError",
	"BillAlreadyIssuedError",
]
