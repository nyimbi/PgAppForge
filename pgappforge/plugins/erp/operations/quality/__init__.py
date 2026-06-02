"""
pgappforge/plugins/erp/operations/quality/__init__.py

QCPlugin — Quality Management ERP plugin.

InspectionPlan → QualityInspection → NonConformanceReport (CAPA workflow)

Domain: operations
Depends on: foundation
Cross-plugin:
  Emits: qc.inspection.*, qc.ncr.*
  Subscribes: ap.grn.posted (triggers INCOMING inspection),
              pp.production_order.completed (triggers OUTGOING inspection),
              scm.shipment.delivered (may trigger INCOMING inspection)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.operations.quality",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class QCPlugin(BasePlugin):
    """Quality Management ERP plugin.

    Registers 4 view groups and 3 report endpoints.
    Pre-configures 5 Rules Engine rulesets on first run.
    """

    name = "quality"
    domain = "operations"
    depends_on: list[str] = ["foundation"]

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="quality",
            version="1.0.0",
            description=(
                "Quality Management — inspection plans with AQL sampling, "
                "quality inspections with finding records, "
                "NCR / CAPA workflow (OPEN→ANALYSIS→CORRECTION→CLOSED)."
            ),
            author="PgAppForge Contributors",
            tags=["erp", "operations", "quality", "qc", "inspection", "ncr", "capa"],
            priority=PluginPriority.NORMAL,
            permissions=[
                "can_qc_plan_list",
                "can_qc_plan_write",
                "can_qc_inspection_list",
                "can_qc_inspection_write",
                "can_qc_inspection_record",
                "can_qc_ncr_list",
                "can_qc_ncr_write",
                "can_qc_ncr_advance",
                "can_qc_reports",
            ],
            safe_mode_compatible=True,
        )

    def get_events(self) -> list[str]:
        return [
            "qc.inspection.created",
            "qc.inspection.started",
            "qc.inspection.passed",
            "qc.inspection.failed",
            "qc.ncr.opened",
            "qc.ncr.analysis_started",
            "qc.ncr.correction_issued",
            "qc.ncr.closed",
            "qc.ncr.reopened",
        ]

    def subscribe_to(self) -> list[str]:
        """QC consumes:
        - ap.grn.posted:                    triggers INCOMING inspection if plan exists
        - pp.production_order.completed:    triggers OUTGOING inspection if plan exists
        - scm.shipment.delivered:           may trigger INCOMING inspection
        """
        return [
            "ap.grn.posted",
            "pp.production_order.completed",
            "scm.shipment.delivered",
        ]

    def initialize(self) -> None:
        defaults: dict[str, Any] = {
            "QC_MENU_CATEGORY": "Quality",
            "QC_AUTO_CREATE_INCOMING_INSPECTION": True,
            "QC_AUTO_CREATE_OUTGOING_INSPECTION": False,
            "QC_AUTO_NCR_ON_FAILURE": True,
        }
        self.config = {**defaults, **self.config}
        log.info("QCPlugin initialised (config: %s)", list(self.config))

    def register_views(self) -> None:
        from pgappforge.plugins.erp.operations.quality.views import (
            InspectionPlanView,
            NCRView,
            QCReportView,
            QualityInspectionView,
        )
        cat = self.config.get("QC_MENU_CATEGORY", "Quality")
        self.add_view(InspectionPlanView, "Inspection Plans", icon="fa-clipboard", category=cat)
        self.add_view(QualityInspectionView, "Inspections", icon="fa-search", category=cat)
        self.add_view(NCRView, "Non-Conformances", icon="fa-exclamation-triangle", category=cat)
        self.add_view(QCReportView, "QC Reports", icon="fa-bar-chart", category=cat)
        log.info("QCPlugin: views registered under category %r", cat)

    def register_models(self) -> list:
        from pgappforge.plugins.erp.operations.quality.models import (
            InspectionPlan,
            NonConformanceReport,
            QualityInspection,
        )
        return [InspectionPlan, QualityInspection, NonConformanceReport]

    @staticmethod
    def setup_rules(session: Any) -> None:
        """Pre-configure 5 Rules Engine rulesets for Quality domain.

        Idempotent — skips rulesets that already exist.
        """
        try:
            from pgappforge.plugins.rules.models import Rule, RuleSet
        except ImportError:
            log.debug("QCPlugin.setup_rules: rules plugin not available, skipping")
            return

        import sqlalchemy as sa

        RULESETS = [
            {
                "name": "qc.inspection.accepted_plus_rejected_lte_inspected",
                "description": "accepted + rejected must not exceed inspected quantity",
                "model_name": "QualityInspection",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "validate_qty_sum",
                        "trigger_event": "on_before_update",
                        "conditions_json": [
                            {"field": "_accepted_plus_rejected", "op": "gt",
                             "value": "__field:inspected_quantity"},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "accepted_quantity + rejected_quantity cannot exceed inspected_quantity"}
                        ],
                    },
                ],
            },
            {
                "name": "qc.inspection.positive_inspected_quantity",
                "description": "Inspected quantity must be positive",
                "model_name": "QualityInspection",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_positive_inspected_qty",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "inspected_quantity", "op": "lte", "value": 0},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "inspected_quantity must be greater than zero"}
                        ],
                    },
                ],
            },
            {
                "name": "qc.ncr.require_description",
                "description": "NCR description must not be blank",
                "model_name": "NonConformanceReport",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_ncr_description",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "description", "op": "eq", "value": ""},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "NCR description must not be blank"}
                        ],
                    },
                ],
            },
            {
                "name": "qc.ncr.critical_requires_due_date",
                "description": "CRITICAL severity NCRs must have a due_date",
                "model_name": "NonConformanceReport",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_due_date_for_critical",
                        "trigger_event": "on_before_create",
                        "conditions_json": [
                            {"field": "severity", "op": "eq", "value": "CRITICAL"},
                            {"field": "due_date", "op": "eq", "value": None},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "CRITICAL NCRs must have a due_date set"}
                        ],
                    },
                ],
            },
            {
                "name": "qc.ncr.require_root_cause_before_close",
                "description": "Root cause must be recorded before closing an NCR",
                "model_name": "NonConformanceReport",
                "stop_on_match": True,
                "rules": [
                    {
                        "name": "require_root_cause_on_close",
                        "trigger_event": "on_before_update",
                        "conditions_json": [
                            {"field": "_new_status", "op": "eq", "value": "CLOSED"},
                            {"field": "root_cause", "op": "eq", "value": ""},
                        ],
                        "actions_json": [
                            {"type": "raise_error",
                             "message": "root_cause must be recorded before closing an NCR"}
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
        log.info("QCPlugin.setup_rules: %d rulesets configured", len(RULESETS))


def create_plugin(appbuilder: Any, config: dict[str, Any] | None = None) -> QCPlugin:
    return QCPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.operations.quality.models import (  # noqa: E402
    InspectionPlan,
    NonConformanceReport,
    QualityInspection,
)
from pgappforge.plugins.erp.operations.quality.events import (  # noqa: E402
    InspectionCreatedEvent,
    InspectionFailedEvent,
    InspectionPassedEvent,
    InspectionStartedEvent,
    NCRAnalysisStartedEvent,
    NCRClosedEvent,
    NCRCorrectionIssuedEvent,
    NCROpenedEvent,
    NCRReopenedEvent,
)
from pgappforge.plugins.erp.operations.quality.services import (  # noqa: E402
    QCService,
    QCServiceError,
    InspectionNotFoundError,
    InspectionPlanNotFoundError,
    NCRNotFoundError,
    InvalidStatusTransitionError,
)

__all__ = [
    "QCPlugin",
    "create_plugin",
    # models
    "InspectionPlan",
    "QualityInspection",
    "NonConformanceReport",
    # events
    "InspectionCreatedEvent",
    "InspectionStartedEvent",
    "InspectionPassedEvent",
    "InspectionFailedEvent",
    "NCROpenedEvent",
    "NCRAnalysisStartedEvent",
    "NCRCorrectionIssuedEvent",
    "NCRClosedEvent",
    "NCRReopenedEvent",
    # services
    "QCService",
    "QCServiceError",
    "InspectionPlanNotFoundError",
    "InspectionNotFoundError",
    "NCRNotFoundError",
    "InvalidStatusTransitionError",
]
