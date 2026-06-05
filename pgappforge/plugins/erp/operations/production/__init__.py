"""
pgappforge/plugins/erp/operations/production/__init__.py

PPPlugin — Production Planning ERP plugin.

Full manufacturing lifecycle:
  BillOfMaterials / BOMLine → WorkCenter → ProductionOrder →
  ProductionOrderLine (component requirements) → WorkOrderOperation (routing) →
  PPDemandForecast (MRP input)

Domain: operations
Depends on: foundation
Cross-plugin: subscribes to scm.shipment.delivered, qc.inspection.failed
             emits pp.production_order.* events consumed by SCM/QC

Usage
-----
Add to PGAPPFORGE_PLUGINS::

    "pgappforge.plugins.erp.operations.production"

Or instantiate directly::

    from pgappforge.plugins.erp.operations.production import PPPlugin
    plugin = PPPlugin(appbuilder)
    plugin.activate()
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class PPPlugin(BasePlugin):
    """Production Planning ERP plugin.

    Registers 5 view groups and 3 report endpoints.
    Pre-configures 4 Rules Engine rulesets on first run.
    """

    name = "production"
    domain = "operations"
    depends_on: list[str] = ["foundation"]

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="production",
            version="1.0.0",
            description=(
                "Production Planning — bill of materials, work centers, "
                "production orders, component issue, routing operations, "
                "demand forecasting."
            ),
            author="PgAppForge Contributors",
            tags=["erp", "operations", "production", "manufacturing", "mrp", "bom"],
            priority=PluginPriority.NORMAL,
            permissions=[
                "can_pp_bom_list",
                "can_pp_bom_write",
                "can_pp_bom_activate",
                "can_pp_work_center_list",
                "can_pp_work_center_write",
                "can_pp_order_list",
                "can_pp_order_write",
                "can_pp_order_release",
                "can_pp_order_complete",
                "can_pp_component_issue",
                "can_pp_forecast_list",
                "can_pp_forecast_write",
                "can_pp_reports",
            ],
            safe_mode_compatible=True,
        )

    def get_events(self) -> list[str]:
        return [
            "pp.bom.activated",
            "pp.bom.obsoleted",
            "pp.production_order.released",
            "pp.production_order.started",
            "pp.production_order.completed",
            "pp.production_order.cancelled",
            "pp.component.issued",
            "pp.operation.completed",
            "pp.forecast.updated",
        ]

    def subscribe_to(self) -> list[str]:
        """PP consumes:
        - scm.shipment.delivered: may trigger material availability refresh
        - qc.inspection.failed:   may block order release if critical component rejected
        """
        return [
            "scm.shipment.delivered",
            "qc.inspection.failed",
        ]

    def initialize(self) -> None:
        defaults: dict[str, Any] = {
            "PP_MENU_CATEGORY": "Production",
            "PP_AUTO_EXPLODE_BOM_ON_ORDER_CREATE": True,
            "PP_BLOCK_RELEASE_ON_CRITICAL_SHORTAGE": False,
        }
        self.config = {**defaults, **self.config}
        log.info("PPPlugin initialised (config: %s)", list(self.config))

    def register_views(self) -> None:
        from pgappforge.plugins.erp.operations.production.views import (
            BOMView,
            DemandForecastView,
            PPReportView,
            ProductionOrderView,
            WorkCenterView,
        )
        cat = self.config.get("PP_MENU_CATEGORY", "Production")
        self.add_view(BOMView, "Bills of Materials", icon="fa-list-alt", category=cat)
        self.add_view(WorkCenterView, "Work Centers", icon="fa-industry", category=cat)
        self.add_view(ProductionOrderView, "Production Orders", icon="fa-cogs", category=cat)
        self.add_view(DemandForecastView, "Demand Forecasts", icon="fa-line-chart", category=cat)
        self.add_view(PPReportView, "PP Reports", icon="fa-bar-chart", category=cat)
        log.info("PPPlugin: views registered under category %r", cat)

    def register_models(self) -> list:
        from pgappforge.plugins.erp.operations.production.models import (
            BillOfMaterials,
            BOMLine,
            PPDemandForecast,
            ProductionOrder,
            ProductionOrderLine,
            WorkCenter,
            WorkOrderOperation,
        )
        return [
            BillOfMaterials,
            BOMLine,
            WorkCenter,
            ProductionOrder,
            ProductionOrderLine,
            WorkOrderOperation,
            PPDemandForecast,
        ]

    @staticmethod
    def setup_rules(session: Any) -> None:
        """Pre-configure 4 Rules Engine rulesets for Production Planning.

        Idempotent — skips rulesets that already exist.
        """
        try:
            from pgappforge.plugins.rules.models import Rule, RuleSet
        except ImportError:
            log.debug("PPPlugin.setup_rules: rules plugin not available, skipping")
            return

        import sqlalchemy as sa

        RULESETS = [
            {
                "name": "pp.bom.require_active_for_release",
                "description": "Production order release requires an ACTIVE BOM",
                "model_name": "ProductionOrder",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "block_release_without_active_bom",
                        "trigger_event": "on_before_update",
                        "conditions_json": [
                            {"field": "_new_status", "op": "eq", "value": "RELEASED"},
                            {"field": "bom.status", "op": "neq", "value": "ACTIVE"},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "Cannot release production order: BOM is not ACTIVE"}
                        ],
                    },
                ],
            },
            {
                "name": "pp.production_order.positive_quantity",
                "description": "Planned quantity must be positive",
                "model_name": "ProductionOrder",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_positive_planned_qty",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "planned_quantity", "op": "lte", "value": 0},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "planned_quantity must be greater than zero"}
                        ],
                    },
                ],
            },
            {
                "name": "pp.bom_line.positive_quantity",
                "description": "BOM line quantity must be positive",
                "model_name": "BOMLine",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_positive_bom_line_qty",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "quantity", "op": "lte", "value": 0},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "BOM line quantity must be greater than zero"}
                        ],
                    },
                ],
            },
            {
                "name": "pp.bom_line.scrap_factor_range",
                "description": "Scrap factor must be between 0 and 1",
                "model_name": "BOMLine",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "validate_scrap_factor",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "scrap_factor", "op": "gt", "value": 1},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "scrap_factor must be between 0 and 1 (0% to 100%)"}
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
        log.info("PPPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> PPPlugin:
    return PPPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.production.models import (  # noqa: E402
    BillOfMaterials,
    BOMLine,
    PPDemandForecast,
    ProductionOrder,
    ProductionOrderLine,
    WorkCenter,
    WorkOrderOperation,
)
from pgappforge.plugins.erp.operations.production.events import (  # noqa: E402
    BOMActivatedEvent,
    BOMObsoletedEvent,
    ComponentIssuedEvent,
    DemandForecastUpdatedEvent,
    OperationCompletedEvent,
    ProductionOrderCancelledEvent,
    ProductionOrderCompletedEvent,
    ProductionOrderReleasedEvent,
    ProductionOrderStartedEvent,
)
from pgappforge.plugins.erp.operations.production.services import (  # noqa: E402
    PPService,
    PPServiceError,
    BOMNotFoundError,
    ProductionOrderNotFoundError,
    InvalidStatusTransitionError,
    InsufficientQuantityError,
)

__all__ = [
    "PPPlugin",
    "create_plugin",
    # models
    "BillOfMaterials",
    "BOMLine",
    "WorkCenter",
    "ProductionOrder",
    "ProductionOrderLine",
    "WorkOrderOperation",
    "PPDemandForecast",
    # events
    "BOMActivatedEvent",
    "BOMObsoletedEvent",
    "ProductionOrderReleasedEvent",
    "ProductionOrderStartedEvent",
    "ProductionOrderCompletedEvent",
    "ProductionOrderCancelledEvent",
    "ComponentIssuedEvent",
    "OperationCompletedEvent",
    "DemandForecastUpdatedEvent",
    # services
    "PPService",
    "PPServiceError",
    "BOMNotFoundError",
    "ProductionOrderNotFoundError",
    "InvalidStatusTransitionError",
    "InsufficientQuantityError",
    # new service methods (accessed via PPService instance)
    # record_production_output, calculate_production_cost,
    # get_production_schedule, get_oee
]
