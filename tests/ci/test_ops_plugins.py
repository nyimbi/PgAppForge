"""
tests/ci/test_ops_plugins.py

Compile-check and unit tests for the three Operations ERP plugins:
  - pgappforge.plugins.erp.operations.production  (PP)
  - pgappforge.plugins.erp.operations.scm         (SCM)
  - pgappforge.plugins.erp.operations.quality     (QC)

Tests verify:
  1. All modules import without error
  2. Plugin classes instantiate with a mock appbuilder
  3. get_events() / subscribe_to() return non-empty lists
  4. Model classes have correct __tablename__ prefixes and required columns
  5. Service classes are instantiable and expose expected methods
  6. Event dataclasses have correct event_type defaults
  7. BOM explosion logic (PPService.explode_bom — unit, no DB)
  8. QC sample quantity computation (QCService.compute_sample_quantity — no DB)
  9. SCM preferred source selection logic (smoke only)
 10. Status transition guard in PPService / QCService / SCMService
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ab():
    ab = MagicMock()
    ab.add_view = MagicMock()
    return ab


# ===========================================================================
# 1. Import checks
# ===========================================================================

def test_production_imports():
    from pgappforge.plugins.erp.operations.production import (
        PPPlugin,
        BillOfMaterials,
        BOMLine,
        WorkCenter,
        ProductionOrder,
        ProductionOrderLine,
        WorkOrderOperation,
        DemandForecast,
        PPService,
        BOMActivatedEvent,
        ProductionOrderReleasedEvent,
        ProductionOrderCompletedEvent,
    )
    assert PPPlugin is not None
    assert BillOfMaterials.__tablename__ == "pp_bom"
    assert BOMLine.__tablename__ == "pp_bom_line"
    assert WorkCenter.__tablename__ == "pp_work_center"
    assert ProductionOrder.__tablename__ == "pp_production_order"
    assert ProductionOrderLine.__tablename__ == "pp_production_order_line"
    assert WorkOrderOperation.__tablename__ == "pp_work_order_operation"
    assert DemandForecast.__tablename__ == "pp_demand_forecast"


def test_scm_imports():
    from pgappforge.plugins.erp.operations.scm import (
        SCMPlugin,
        Supplier,
        SupplierProduct,
        PurchaseRequisition,
        PurchaseOrder,
        POLine,
        GoodsReceipt,
        GoodsReceiptLine,
        SupplierInvoice,
        DemandForecast,
        ShipmentTracking,
        SCMService,
        SupplierCreatedEvent,
        PurchaseOrderCreatedEvent,
        GoodsReceiptCreatedEvent,
        SupplierInvoiceMatchedEvent,
        SupplierInvoiceDisputedEvent,
        ShipmentDeliveredEvent,
        RequisitionNotFoundError,
        PurchaseOrderNotFoundError,
        MatchError,
    )
    assert SCMPlugin is not None
    assert Supplier.__tablename__ == "scm_supplier"
    assert SupplierProduct.__tablename__ == "scm_supplier_product"
    assert PurchaseRequisition.__tablename__ == "scm_purchase_requisition"
    assert PurchaseOrder.__tablename__ == "scm_purchase_order"
    assert POLine.__tablename__ == "scm_po_line"
    assert GoodsReceipt.__tablename__ == "scm_goods_receipt"
    assert GoodsReceiptLine.__tablename__ == "scm_goods_receipt_line"
    assert SupplierInvoice.__tablename__ == "scm_supplier_invoice"
    assert DemandForecast.__tablename__ == "scm_demand_forecast"
    assert ShipmentTracking.__tablename__ == "scm_shipment_tracking"


def test_quality_imports():
    from pgappforge.plugins.erp.operations.quality import (
        QCPlugin,
        InspectionPlan,
        QualityInspection,
        NonConformanceReport,
        QCService,
        InspectionCreatedEvent,
        NCROpenedEvent,
    )
    assert QCPlugin is not None
    assert InspectionPlan.__tablename__ == "qc_inspection_plan"
    assert QualityInspection.__tablename__ == "qc_inspection"
    assert NonConformanceReport.__tablename__ == "qc_ncr"


# ===========================================================================
# 2. Plugin instantiation and metadata
# ===========================================================================

def test_pp_plugin_metadata():
    from pgappforge.plugins.erp.operations.production import PPPlugin
    plugin = PPPlugin(_mock_ab())
    assert plugin.name == "production"
    assert plugin.domain == "operations"
    assert "foundation" in plugin.depends_on
    meta = plugin.metadata
    assert meta.version == "1.0.0"
    assert "erp" in meta.tags
    assert len(meta.permissions) >= 10


def test_scm_plugin_metadata():
    from pgappforge.plugins.erp.operations.scm import SCMPlugin
    plugin = SCMPlugin(_mock_ab())
    assert plugin.name == "scm"
    assert plugin.domain == "operations"
    assert "foundation" in plugin.depends_on


def test_qc_plugin_metadata():
    from pgappforge.plugins.erp.operations.quality import QCPlugin
    plugin = QCPlugin(_mock_ab())
    assert plugin.name == "quality"
    assert plugin.domain == "operations"
    assert "foundation" in plugin.depends_on


# ===========================================================================
# 3. get_events / subscribe_to
# ===========================================================================

def test_pp_events():
    from pgappforge.plugins.erp.operations.production import PPPlugin
    p = PPPlugin(_mock_ab())
    events = p.get_events()
    subs = p.subscribe_to()
    assert "pp.production_order.completed" in events
    assert "pp.bom.activated" in events
    assert "scm.shipment.delivered" in subs
    assert "qc.inspection.failed" in subs


def test_scm_events():
    from pgappforge.plugins.erp.operations.scm import SCMPlugin
    p = SCMPlugin(_mock_ab())
    assert "scm.shipment.delivered" in p.get_events()
    assert "scm.supplier.kpi_updated" in p.get_events()
    assert "ap.invoice.approved" in p.subscribe_to()
    assert "pp.production_order.released" in p.subscribe_to()


def test_qc_events():
    from pgappforge.plugins.erp.operations.quality import QCPlugin
    p = QCPlugin(_mock_ab())
    assert "qc.inspection.failed" in p.get_events()
    assert "qc.ncr.closed" in p.get_events()
    assert "pp.production_order.completed" in p.subscribe_to()
    assert "ap.grn.posted" in p.subscribe_to()


# ===========================================================================
# 4. Model column presence
# ===========================================================================

def test_bom_model_columns():
    from pgappforge.plugins.erp.operations.production.models import BillOfMaterials
    cols = {c.name for c in BillOfMaterials.__table__.columns}
    for required in ("id", "tenant_id", "product_id", "version", "status",
                     "effective_from", "is_phantom", "uom", "yield_pct"):
        assert required in cols, f"BillOfMaterials missing column: {required}"


def test_bom_line_model_columns():
    from pgappforge.plugins.erp.operations.production.models import BOMLine
    cols = {c.name for c in BOMLine.__table__.columns}
    for required in ("id", "tenant_id", "bom_id", "component_product_id",
                     "quantity", "uom", "position", "scrap_factor", "is_critical"):
        assert required in cols, f"BOMLine missing column: {required}"


def test_production_order_model_columns():
    from pgappforge.plugins.erp.operations.production.models import ProductionOrder
    cols = {c.name for c in ProductionOrder.__table__.columns}
    for required in ("id", "tenant_id", "order_number", "product_id", "bom_id",
                     "planned_quantity", "produced_quantity", "start_date", "end_date",
                     "status", "planned_cost_cents", "actual_cost_cents"):
        assert required in cols, f"ProductionOrder missing column: {required}"


def test_demand_forecast_model_columns():
    from pgappforge.plugins.erp.operations.production.models import DemandForecast
    cols = {c.name for c in DemandForecast.__table__.columns}
    for required in ("id", "tenant_id", "product_id", "forecast_date",
                     "forecast_quantity", "forecast_method", "confidence_interval"):
        assert required in cols, f"DemandForecast missing column: {required}"


def test_supplier_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import Supplier
    cols = {c.name for c in Supplier.__table__.columns}
    for required in (
        "id", "tenant_id", "supplier_code", "name", "supplier_type", "status",
        "country_code", "rating", "on_time_delivery_pct", "quality_score",
        "lead_time_days", "min_order_qty", "minimum_order_value_cents",
        "credit_limit_cents", "preferred", "payment_terms_days", "currency_code",
    ):
        assert required in cols, f"Supplier missing column: {required}"


def test_purchase_requisition_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import PurchaseRequisition
    cols = {c.name for c in PurchaseRequisition.__table__.columns}
    for required in (
        "id", "tenant_id", "requester_id", "department_id",
        "req_date", "required_by", "status", "items",
    ):
        assert required in cols, f"PurchaseRequisition missing column: {required}"


def test_purchase_order_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import PurchaseOrder
    cols = {c.name for c in PurchaseOrder.__table__.columns}
    for required in (
        "id", "tenant_id", "po_number", "supplier_id", "requisition_id",
        "order_date", "expected_delivery_date", "status",
        "total_amount_cents", "currency_code", "payment_terms_days",
        "shipping_terms", "incoterm",
    ):
        assert required in cols, f"PurchaseOrder missing column: {required}"


def test_po_line_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import POLine
    cols = {c.name for c in POLine.__table__.columns}
    for required in (
        "id", "po_id", "line_number", "product_code", "description",
        "ordered_qty", "received_qty", "invoiced_qty",
        "unit_of_measure", "unit_price_cents", "line_total_cents", "status",
    ):
        assert required in cols, f"POLine missing column: {required}"


def test_goods_receipt_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import GoodsReceipt
    cols = {c.name for c in GoodsReceipt.__table__.columns}
    for required in (
        "id", "tenant_id", "po_id", "grn_number",
        "received_date", "received_by", "warehouse_id",
    ):
        assert required in cols, f"GoodsReceipt missing column: {required}"


def test_goods_receipt_line_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import GoodsReceiptLine
    cols = {c.name for c in GoodsReceiptLine.__table__.columns}
    for required in (
        "id", "grn_id", "po_line_id", "received_qty", "accepted_qty",
        "rejected_qty", "rejection_reason", "lot_number", "expiry_date",
    ):
        assert required in cols, f"GoodsReceiptLine missing column: {required}"


def test_supplier_invoice_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import SupplierInvoice
    cols = {c.name for c in SupplierInvoice.__table__.columns}
    for required in (
        "id", "tenant_id", "po_id", "supplier_id", "invoice_number",
        "invoice_date", "due_date", "currency_code",
        "subtotal_cents", "tax_cents", "total_cents", "status",
    ):
        assert required in cols, f"SupplierInvoice missing column: {required}"


def test_demand_forecast_scm_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import DemandForecast
    cols = {c.name for c in DemandForecast.__table__.columns}
    for required in (
        "id", "tenant_id", "product_code", "period_month",
        "forecast_qty", "actual_qty", "forecast_method", "confidence_pct",
    ):
        assert required in cols, f"SCM DemandForecast missing column: {required}"


def test_supplier_product_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import SupplierProduct
    cols = {c.name for c in SupplierProduct.__table__.columns}
    for required in ("id", "tenant_id", "supplier_id", "product_id", "supplier_sku",
                     "lead_time_days", "minimum_quantity", "price_cents",
                     "currency_code", "valid_from", "valid_to", "is_preferred"):
        assert required in cols, f"SupplierProduct missing column: {required}"


def test_shipment_tracking_model_columns():
    from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
    cols = {c.name for c in ShipmentTracking.__table__.columns}
    for required in ("id", "tenant_id", "carrier", "tracking_number",
                     "shipped_at", "estimated_arrival", "actual_arrival",
                     "status", "events"):
        assert required in cols, f"ShipmentTracking missing column: {required}"


def test_inspection_plan_model_columns():
    from pgappforge.plugins.erp.operations.quality.models import InspectionPlan
    cols = {c.name for c in InspectionPlan.__table__.columns}
    for required in ("id", "tenant_id", "product_id", "inspection_type",
                     "sampling_pct", "acceptance_criteria", "is_active"):
        assert required in cols, f"InspectionPlan missing column: {required}"


def test_quality_inspection_model_columns():
    from pgappforge.plugins.erp.operations.quality.models import QualityInspection
    cols = {c.name for c in QualityInspection.__table__.columns}
    for required in ("id", "tenant_id", "reference_type", "reference_id",
                     "plan_id", "inspected_quantity", "accepted_quantity",
                     "rejected_quantity", "status", "findings"):
        assert required in cols, f"QualityInspection missing column: {required}"


def test_ncr_model_columns():
    from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport
    cols = {c.name for c in NonConformanceReport.__table__.columns}
    for required in ("id", "tenant_id", "ncr_number", "source_type",
                     "product_id", "quantity_affected", "severity", "description",
                     "status", "root_cause", "corrective_action", "preventive_action",
                     "owner_id", "due_date", "closed_at"):
        assert required in cols, f"NonConformanceReport missing column: {required}"


# ===========================================================================
# 5. Event dataclasses — correct event_type defaults
# ===========================================================================

def test_pp_event_types():
    from pgappforge.plugins.erp.operations.production.events import (
        BOMActivatedEvent,
        BOMObsoletedEvent,
        ProductionOrderReleasedEvent,
        ProductionOrderCompletedEvent,
        ComponentIssuedEvent,
        OperationCompletedEvent,
        DemandForecastUpdatedEvent,
    )
    assert BOMActivatedEvent().event_type == "pp.bom.activated"
    assert BOMObsoletedEvent().event_type == "pp.bom.obsoleted"
    assert ProductionOrderReleasedEvent().event_type == "pp.production_order.released"
    assert ProductionOrderCompletedEvent().event_type == "pp.production_order.completed"
    assert ComponentIssuedEvent().event_type == "pp.component.issued"
    assert OperationCompletedEvent().event_type == "pp.operation.completed"
    assert DemandForecastUpdatedEvent().event_type == "pp.forecast.updated"


def test_scm_event_types():
    from pgappforge.plugins.erp.operations.scm.events import (
        SupplierCreatedEvent,
        SupplierApprovedEvent,
        SupplierKPIUpdatedEvent,
        PurchaseRequisitionCreatedEvent,
        PurchaseRequisitionApprovedEvent,
        PurchaseOrderCreatedEvent,
        GoodsReceiptCreatedEvent,
        SupplierInvoiceMatchedEvent,
        SupplierInvoiceDisputedEvent,
        ShipmentCreatedEvent,
        ShipmentDeliveredEvent,
        ShipmentExceptionEvent,
    )
    assert SupplierCreatedEvent().event_type == "scm.supplier.created"
    assert SupplierApprovedEvent().event_type == "scm.supplier.approved"
    assert SupplierKPIUpdatedEvent().event_type == "scm.supplier.kpi_updated"
    assert PurchaseRequisitionCreatedEvent().event_type == "scm.purchase_requisition.created"
    assert PurchaseRequisitionApprovedEvent().event_type == "scm.purchase_requisition.approved"
    assert PurchaseOrderCreatedEvent().event_type == "scm.purchase_order.created"
    assert GoodsReceiptCreatedEvent().event_type == "scm.goods_receipt.created"
    assert SupplierInvoiceMatchedEvent().event_type == "scm.supplier_invoice.matched"
    assert SupplierInvoiceDisputedEvent().event_type == "scm.supplier_invoice.disputed"
    assert ShipmentCreatedEvent().event_type == "scm.shipment.created"
    assert ShipmentDeliveredEvent().event_type == "scm.shipment.delivered"
    assert ShipmentExceptionEvent().event_type == "scm.shipment.exception"


def test_qc_event_types():
    from pgappforge.plugins.erp.operations.quality.events import (
        InspectionCreatedEvent,
        InspectionPassedEvent,
        InspectionFailedEvent,
        NCROpenedEvent,
        NCRClosedEvent,
        NCRReopenedEvent,
    )
    assert InspectionCreatedEvent().event_type == "qc.inspection.created"
    assert InspectionPassedEvent().event_type == "qc.inspection.passed"
    assert InspectionFailedEvent().event_type == "qc.inspection.failed"
    assert NCROpenedEvent().event_type == "qc.ncr.opened"
    assert NCRClosedEvent().event_type == "qc.ncr.closed"
    assert NCRReopenedEvent().event_type == "qc.ncr.reopened"


# ===========================================================================
# 6. PPService — BOM explosion (unit test, no DB)
# ===========================================================================

def test_bom_explosion_no_scrap():
    """BOM explosion with zero scrap factor: gross qty == base qty * order qty."""
    from pgappforge.plugins.erp.operations.production.services import PPService

    svc = PPService()

    # Use SimpleNamespace objects to avoid SQLAlchemy relationship machinery
    line1 = SimpleNamespace(
        id="line-1",
        component_product_id="comp-X",
        quantity=Decimal("2"),
        uom="EA",
        position=1,
        scrap_factor=Decimal("0"),
        is_critical=False,
    )
    line2 = SimpleNamespace(
        id="line-2",
        component_product_id="comp-Y",
        quantity=Decimal("0.5"),
        uom="KG",
        position=2,
        scrap_factor=Decimal("0"),
        is_critical=True,
    )
    bom = SimpleNamespace(
        product_id="prod-A",
        tenant_id="t1",
        status="ACTIVE",
        lines=[line1, line2],
    )

    with patch.object(svc, "get_active_bom", return_value=bom):
        result = svc.explode_bom("prod-A", Decimal("10"), "t1", None, session=None)

    assert len(result) == 2
    comp_x = next(r for r in result if r["product_id"] == "comp-X")
    comp_y = next(r for r in result if r["product_id"] == "comp-Y")
    assert comp_x["required_quantity"] == Decimal("20")
    assert comp_y["required_quantity"] == Decimal("5")
    assert comp_y["is_critical"] is True


def test_bom_explosion_with_scrap():
    """BOM explosion with 10% scrap: gross = base × order × 1.1."""
    from pgappforge.plugins.erp.operations.production.services import PPService

    svc = PPService()
    line = SimpleNamespace(
        id="line-3",
        component_product_id="comp-Z",
        quantity=Decimal("1"),
        uom="EA",
        position=1,
        scrap_factor=Decimal("0.10"),
        is_critical=False,
    )
    bom = SimpleNamespace(
        product_id="prod-B",
        tenant_id="t1",
        status="ACTIVE",
        lines=[line],
    )

    with patch.object(svc, "get_active_bom", return_value=bom):
        result = svc.explode_bom("prod-B", Decimal("100"), "t1", None, session=None)

    assert len(result) == 1
    assert result[0]["required_quantity"] == Decimal("110.0000")


def test_bom_explosion_no_active_bom():
    """explode_bom returns [] when no active BOM exists."""
    from pgappforge.plugins.erp.operations.production.services import PPService
    svc = PPService()
    with patch.object(svc, "get_active_bom", return_value=None):
        result = svc.explode_bom("prod-C", Decimal("5"), "t1", None, session=None)
    assert result == []


# ===========================================================================
# 7. QCService — sample quantity computation (no DB)
# ===========================================================================

def test_sample_quantity_100pct():
    """100% sampling returns lot_quantity exactly."""
    from pgappforge.plugins.erp.operations.quality.services import QCService
    from pgappforge.plugins.erp.operations.quality.models import InspectionPlan

    svc = QCService()
    plan = InspectionPlan()
    plan.id = "plan-1"
    plan.sampling_pct = Decimal("100")

    session = MagicMock()
    session.get.return_value = plan

    result = svc.compute_sample_quantity("plan-1", Decimal("500"), session)
    assert result == Decimal("500")


def test_sample_quantity_10pct():
    """10% sampling of 100 units → 10 units."""
    from pgappforge.plugins.erp.operations.quality.services import QCService
    from pgappforge.plugins.erp.operations.quality.models import InspectionPlan

    svc = QCService()
    plan = InspectionPlan()
    plan.id = "plan-2"
    plan.sampling_pct = Decimal("10")

    session = MagicMock()
    session.get.return_value = plan

    result = svc.compute_sample_quantity("plan-2", Decimal("100"), session)
    assert result == Decimal("10.0000")


def test_sample_quantity_minimum_one():
    """Very small lot: sample quantity floored to 1."""
    from pgappforge.plugins.erp.operations.quality.services import QCService
    from pgappforge.plugins.erp.operations.quality.models import InspectionPlan

    svc = QCService()
    plan = InspectionPlan()
    plan.id = "plan-3"
    plan.sampling_pct = Decimal("5")

    session = MagicMock()
    session.get.return_value = plan

    # 5% of 1 unit = 0.05 → floors to minimum 1
    result = svc.compute_sample_quantity("plan-3", Decimal("1"), session)
    assert result == Decimal("1")


# ===========================================================================
# 8. Service — status transition guards (no DB needed)
# ===========================================================================

def test_pp_invalid_status_transition():
    """PPService raises InvalidStatusTransitionError for bad transitions."""
    from pgappforge.plugins.erp.operations.production.services import (
        PPService, InvalidStatusTransitionError,
    )
    from pgappforge.plugins.erp.operations.production.models import ProductionOrder

    svc = PPService()
    order = ProductionOrder()
    order.id = "ord-1"
    order.status = "COMPLETED"  # already terminal
    order.tenant_id = "t1"
    order.order_number = "MO-001"
    order.product_id = "prod-A"
    order.work_center_id = None

    session = MagicMock()
    session.get.return_value = order

    try:
        svc.release_production_order("ord-1", session)
        assert False, "Should have raised InvalidStatusTransitionError"
    except InvalidStatusTransitionError:
        pass


def test_qc_invalid_ncr_transition():
    """QCService raises InvalidStatusTransitionError for non-sequential NCR advance."""
    from pgappforge.plugins.erp.operations.quality.services import (
        QCService, InvalidStatusTransitionError,
    )
    from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport

    svc = QCService()
    ncr = NonConformanceReport()
    ncr.id = "ncr-1"
    ncr.status = "OPEN"
    ncr.tenant_id = "t1"
    ncr.ncr_number = "NCR-TEST"
    ncr.owner_id = None

    session = MagicMock()
    session.get.return_value = ncr

    try:
        # Trying to skip ANALYSIS and go straight to CLOSED
        svc.advance_ncr("ncr-1", "CLOSED", "user-1", session)
        assert False, "Should have raised InvalidStatusTransitionError"
    except InvalidStatusTransitionError:
        pass


# ===========================================================================
# 9. Service — service class instantiation and method presence
# ===========================================================================

def test_pp_service_methods():
    from pgappforge.plugins.erp.operations.production.services import PPService
    svc = PPService()
    for method in (
        "activate_bom", "get_active_bom", "release_production_order",
        "start_production_order", "complete_production_order",
        "cancel_production_order", "issue_component", "complete_operation",
        "explode_bom", "compute_planned_cost",
    ):
        assert hasattr(svc, method), f"PPService missing method: {method}"


def test_scm_service_methods():
    from pgappforge.plugins.erp.operations.scm.services import SCMService
    svc = SCMService()
    for method in (
        "create_supplier",
        "create_purchase_requisition",
        "approve_requisition",
        "create_purchase_order",
        "receive_goods",
        "match_supplier_invoice",
        "get_supplier_performance",
        "run_demand_forecast",
        "get_procurement_dashboard",
        "get_preferred_source",
        "approve_supplier",
        "refresh_supplier_kpis",
        "add_shipment_event",
        "get_overdue_shipments",
    ):
        assert hasattr(svc, method), f"SCMService missing method: {method}"


def test_qc_service_methods():
    from pgappforge.plugins.erp.operations.quality.services import QCService
    svc = QCService()
    for method in (
        "get_active_plan", "compute_sample_quantity", "create_inspection",
        "record_results", "open_ncr", "advance_ncr",
    ):
        assert hasattr(svc, method), f"QCService missing method: {method}"


# ===========================================================================
# 10. register_models returns correct model lists
# ===========================================================================

def test_pp_register_models():
    from pgappforge.plugins.erp.operations.production import PPPlugin
    plugin = PPPlugin(_mock_ab())
    models = plugin.register_models()
    names = {m.__tablename__ for m in models}
    assert "pp_bom" in names
    assert "pp_production_order" in names
    assert "pp_demand_forecast" in names
    assert len(models) == 7


def test_scm_register_models():
    from pgappforge.plugins.erp.operations.scm import SCMPlugin
    plugin = SCMPlugin(_mock_ab())
    models = plugin.register_models()
    names = {m.__tablename__ for m in models}
    expected = {
        "scm_supplier",
        "scm_supplier_product",
        "scm_purchase_requisition",
        "scm_purchase_order",
        "scm_po_line",
        "scm_goods_receipt",
        "scm_goods_receipt_line",
        "scm_supplier_invoice",
        "scm_demand_forecast",
        "scm_shipment_tracking",
    }
    for name in expected:
        assert name in names, f"SCMPlugin.register_models missing: {name}"
    assert len(models) == 10


def test_qc_register_models():
    from pgappforge.plugins.erp.operations.quality import QCPlugin
    plugin = QCPlugin(_mock_ab())
    models = plugin.register_models()
    names = {m.__tablename__ for m in models}
    assert "qc_inspection_plan" in names
    assert "qc_inspection" in names
    assert "qc_ncr" in names
    # New models added: InspectionLot, InspectionResult, NCR (v2), CalibrationRecord, CAPA
    assert "qc_inspection_lot" in names
    assert "qc_inspection_result" in names
    assert "qc_ncr_v2" in names
    assert "qc_calibration_record" in names
    assert "qc_capa" in names
    assert len(models) == 8


# ===========================================================================
# 11. DomainEvent payload build
# ===========================================================================

def test_production_order_completed_event_payload():
    from pgappforge.plugins.erp.operations.production.events import ProductionOrderCompletedEvent
    evt = ProductionOrderCompletedEvent(
        aggregate_id="ord-1",
        aggregate_type="ProductionOrder",
        tenant_id="t1",
        order_id="ord-1",
        order_number="MO-001",
        product_id="prod-A",
        produced_quantity="50.0000",
        actual_cost_cents=125000,
        planned_cost_cents=120000,
    )
    payload = evt.build_payload()
    assert payload["order_id"] == "ord-1"
    assert payload["actual_cost_cents"] == 125000
    assert payload["produced_quantity"] == "50.0000"
    # Base fields must NOT be in payload
    assert "event_id" not in payload
    assert "tenant_id" not in payload


def test_ncr_opened_event_payload():
    from pgappforge.plugins.erp.operations.quality.events import NCROpenedEvent
    evt = NCROpenedEvent(
        aggregate_id="ncr-1",
        aggregate_type="NonConformanceReport",
        tenant_id="t1",
        ncr_id="ncr-1",
        ncr_number="NCR-20260601-120000",
        product_id="prod-X",
        source_type="SUPPLIER",
        severity="CRITICAL",
        quantity_affected="10.0000",
        owner_id="user-1",
        due_date="2026-06-15",
    )
    payload = evt.build_payload()
    assert payload["severity"] == "CRITICAL"
    assert payload["source_type"] == "SUPPLIER"
    assert "tenant_id" not in payload


# ===========================================================================
# 12. Amount integer-cents discipline
# ===========================================================================

def test_no_float_columns_in_monetary_fields():
    """Monetary columns (cost_cents, price_cents, etc.) are Integer or BigInteger, not Numeric/Float."""
    from sqlalchemy import Integer, BigInteger
    from pgappforge.plugins.erp.operations.production.models import (
        ProductionOrder, WorkCenter,
    )
    from pgappforge.plugins.erp.operations.scm.models import (
        Supplier, SupplierProduct, PurchaseOrder, POLine, SupplierInvoice,
    )
    from pgappforge.plugins.erp.operations.quality.models import NonConformanceReport

    checks = [
        (ProductionOrder, "actual_cost_cents"),
        (ProductionOrder, "planned_cost_cents"),
        (WorkCenter, "overhead_rate_per_hour_cents"),
        (Supplier, "minimum_order_value_cents"),
        (Supplier, "credit_limit_cents"),
        (SupplierProduct, "price_cents"),
        (PurchaseOrder, "total_amount_cents"),
        (POLine, "unit_price_cents"),
        (POLine, "line_total_cents"),
        (SupplierInvoice, "subtotal_cents"),
        (SupplierInvoice, "tax_cents"),
        (SupplierInvoice, "total_cents"),
        (NonConformanceReport, "supplier_claim_value_cents"),
    ]
    for model_cls, col_name in checks:
        col = model_cls.__table__.c[col_name]
        assert isinstance(col.type, (Integer, BigInteger)), (
            f"{model_cls.__name__}.{col_name} should be Integer/BigInteger (cents), "
            f"got {type(col.type).__name__}"
        )


# ===========================================================================
# Runner (for direct execution)
# ===========================================================================

if __name__ == "__main__":
    import asyncio
    import sys

    async def _run_all():
        passed = failed = 0
        tests = [
            v for k, v in list(globals().items())
            if k.startswith("test_") and asyncio.iscoroutinefunction(v)
        ]
        for test_fn in tests:
            try:
                await test_fn()
                print(f"  PASS  {test_fn.__name__}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {test_fn.__name__}: {exc}")
                failed += 1
        print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
        return failed

    sys.exit(asyncio.run(_run_all()))
