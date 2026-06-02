"""
pgappforge/plugins/erp/operations/scm/__init__.py

SCMPlugin — Supply Chain Management ERP plugin.

Supplier master → SupplierProduct (sourcing catalogue) →
ShipmentTracking (in-transit milestones)

Domain: operations
Depends on: foundation
Cross-plugin:
  Emits: scm.supplier.*, scm.shipment.*
  Subscribes: ap.invoice.approved (KPI refresh), pp.production_order.released,
              qc.inspection.failed (supplier quality score)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.scm",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class SCMPlugin(BasePlugin):
    """Supply Chain Management ERP plugin.

    Registers 4 view groups and 3 report endpoints.
    Pre-configures 3 Rules Engine rulesets on first run.
    """

    name = "scm"
    domain = "operations"
    depends_on: list[str] = ["foundation"]

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="scm",
            version="1.0.0",
            description=(
                "Supply Chain Management — supplier master with KPI tracking, "
                "supplier product catalogue with price/lead-time validity, "
                "shipment tracking with milestone events."
            ),
            author="PgAppForge Contributors",
            tags=["erp", "operations", "scm", "supply-chain", "supplier", "shipment", "logistics"],
            priority=PluginPriority.NORMAL,
            permissions=[
                "can_scm_supplier_list",
                "can_scm_supplier_write",
                "can_scm_supplier_approve",
                "can_scm_supplier_product_list",
                "can_scm_supplier_product_write",
                "can_scm_shipment_list",
                "can_scm_shipment_write",
                "can_scm_shipment_track",
                "can_scm_reports",
            ],
            safe_mode_compatible=True,
        )

    def get_events(self) -> list[str]:
        return [
            "scm.supplier.created",
            "scm.supplier.approved",
            "scm.supplier.kpi_updated",
            "scm.supplier_product.created",
            "scm.shipment.created",
            "scm.shipment.status_changed",
            "scm.shipment.delivered",
            "scm.shipment.exception",
        ]

    def subscribe_to(self) -> list[str]:
        """SCM consumes:
        - ap.invoice.approved:         may trigger supplier KPI refresh
        - pp.production_order.released: may trigger replenishment PO
        - qc.inspection.failed:        feeds supplier quality_score
        """
        return [
            "ap.invoice.approved",
            "pp.production_order.released",
            "qc.inspection.failed",
        ]

    def initialize(self) -> None:
        defaults: dict[str, Any] = {
            "SCM_MENU_CATEGORY": "Supply Chain",
            "SCM_KPI_REFRESH_PERIOD_DAYS": 365,
            "SCM_OVERDUE_ALERT_DAYS": 3,
        }
        self.config = {**defaults, **self.config}
        log.info("SCMPlugin initialised (config: %s)", list(self.config))

    def register_views(self) -> None:
        from pgappforge.plugins.erp.operations.scm.views import (
            SCMReportView,
            ShipmentTrackingView,
            SupplierProductView,
            SupplierView,
        )
        cat = self.config.get("SCM_MENU_CATEGORY", "Supply Chain")
        self.add_view(SupplierView, "Suppliers", icon="fa-building", category=cat)
        self.add_view(SupplierProductView, "Supplier Products", icon="fa-tags", category=cat)
        self.add_view(ShipmentTrackingView, "Shipments", icon="fa-truck", category=cat)
        self.add_view(SCMReportView, "SCM Reports", icon="fa-bar-chart", category=cat)
        log.info("SCMPlugin: views registered under category %r", cat)

    def register_models(self) -> list:
        from pgappforge.plugins.erp.operations.scm.models import (
            Supplier,
            SupplierProduct,
            ShipmentTracking,
        )
        return [Supplier, SupplierProduct, ShipmentTracking]

    @staticmethod
    def setup_rules(session: Any) -> None:
        """Pre-configure 3 Rules Engine rulesets for SCM domain.

        Idempotent — skips rulesets that already exist.
        """
        try:
            from pgappforge.plugins.rules.models import Rule, RuleSet
        except ImportError:
            log.debug("SCMPlugin.setup_rules: rules plugin not available, skipping")
            return

        import sqlalchemy as sa

        RULESETS = [
            {
                "name": "scm.supplier.require_code_unique",
                "description": "Supplier code must be unique per tenant",
                "model_name": "Supplier",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_non_empty_supplier_code",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "supplier_code", "op": "eq", "value": ""},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "supplier_code must not be empty"}
                        ],
                    },
                ],
            },
            {
                "name": "scm.supplier_product.positive_price",
                "description": "Supplier product price must be non-negative",
                "model_name": "SupplierProduct",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_non_negative_price",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "price_cents", "op": "lt", "value": 0},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "price_cents must be non-negative"}
                        ],
                    },
                ],
            },
            {
                "name": "scm.supplier_product.valid_date_range",
                "description": "valid_to must be after valid_from when set",
                "model_name": "SupplierProduct",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "validate_validity_window",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "valid_to", "op": "lt", "value": "__field:valid_from"},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "valid_to must be on or after valid_from"}
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
        log.info("SCMPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> SCMPlugin:
    return SCMPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.scm.models import (  # noqa: E402
    Supplier,
    SupplierProduct,
    ShipmentTracking,
)
from pgappforge.plugins.erp.operations.scm.events import (  # noqa: E402
    ShipmentCreatedEvent,
    ShipmentDeliveredEvent,
    ShipmentExceptionEvent,
    ShipmentStatusChangedEvent,
    SupplierApprovedEvent,
    SupplierCreatedEvent,
    SupplierKPIUpdatedEvent,
    SupplierProductCreatedEvent,
)
from pgappforge.plugins.erp.operations.scm.services import (  # noqa: E402
    SCMService,
    SCMServiceError,
    ShipmentNotFoundError,
    SupplierNotFoundError,
    SupplierProductNotFoundError,
)

__all__ = [
    "SCMPlugin",
    "create_plugin",
    # models
    "Supplier",
    "SupplierProduct",
    "ShipmentTracking",
    # events
    "SupplierCreatedEvent",
    "SupplierApprovedEvent",
    "SupplierKPIUpdatedEvent",
    "SupplierProductCreatedEvent",
    "ShipmentCreatedEvent",
    "ShipmentStatusChangedEvent",
    "ShipmentDeliveredEvent",
    "ShipmentExceptionEvent",
    # services
    "SCMService",
    "SCMServiceError",
    "SupplierNotFoundError",
    "SupplierProductNotFoundError",
    "ShipmentNotFoundError",
]
