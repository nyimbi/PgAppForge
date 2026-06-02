"""
pgappforge/plugins/erp/operations/quality/models.py

SQLAlchemy models for the Quality Management (QC) plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid() server default + Python default_factory
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - Quantities: NUMERIC (never float) — inspection quantities may be fractional
  - ALL models: tenant_id UUID NOT NULL
  - AuditMixin on every mutable entity
  - lazy='select' throughout (SA 2.x)
  - JSONB for acceptance_criteria and findings
  - NCR is APPEND-ONLY for status progression — correction entries, not UPDATEs
    to root_cause / corrective_action once CLOSED

Table prefix: qc_
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# InspectionPlan
# ---------------------------------------------------------------------------

class InspectionPlan(AuditMixin, Model):
	"""Quality inspection plan for a product and inspection type.

	Defines what to check, how much to sample, and what constitutes pass/fail.

	inspection_type:
	  INCOMING  — incoming goods inspection on receipt from supplier
	  IN_PROCESS — in-process check during production
	  OUTGOING  — final inspection before dispatch to customer

	sampling_pct: percentage of lot to inspect (100 = 100% inspection).
	acceptance_criteria: JSONB — flexible schema per inspection type, e.g.:
	  {
	    "dimensions": [{"attr": "length_mm", "min": 99.5, "max": 100.5}],
	    "visual": ["no_scratches", "no_dents"],
	    "aql": {"level": "II", "acceptable_quality_limit": 1.0}
	  }
	"""

	__allow_unmapped__ = True
	__tablename__ = "qc_inspection_plan"
	__table_args__ = (
		Index("ix_qc_plan_tenant", "tenant_id"),
		Index("ix_qc_plan_product", "product_id"),
		Index("ix_qc_plan_product_type", "product_id", "inspection_type"),
		Index("ix_qc_plan_tenant_active", "tenant_id", "is_active"),
		UniqueConstraint("tenant_id", "product_id", "inspection_type", name="uq_qc_plan_product_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")
	inspection_type = Column(
		String(15),
		nullable=False,
		comment="INCOMING | IN_PROCESS | OUTGOING",
	)
	name = Column(String(200), nullable=False, comment="Plan name / title")
	description = Column(Text, nullable=True)
	sampling_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=100,
		comment="Sample percentage 0.01-100.00 (100 = 100% inspection)",
	)
	acceptance_criteria: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Flexible acceptance criteria JSON (dimensions, visual, AQL, etc.)",
	)
	is_active = Column(Boolean, nullable=False, default=True)
	version = Column(String(20), nullable=False, default="1", comment="Plan revision/version")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	inspections: list[QualityInspection] = relationship(
		"QualityInspection", back_populates="plan", lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<InspectionPlan product={self.product_id!r} "
			f"type={self.inspection_type!r} active={self.is_active}>"
		)


# ---------------------------------------------------------------------------
# QualityInspection
# ---------------------------------------------------------------------------

class QualityInspection(AuditMixin, Model):
	"""Quality inspection event against a reference document.

	reference_type / reference_id: polymorphic reference to the triggering
	document, e.g.:
	  reference_type="APGoodsReceipt" reference_id=<grn.id>
	  reference_type="ProductionOrder" reference_id=<order.id>
	  reference_type="SalesOrder"      reference_id=<so.id>

	findings: JSONB — inspector observations per criterion:
	  [{"criterion": "length_mm", "measured": 100.1, "result": "PASS"}, ...]

	Status machine: PENDING → IN_PROGRESS → PASSED | FAILED
	"""

	__allow_unmapped__ = True
	__tablename__ = "qc_inspection"
	__table_args__ = (
		Index("ix_qc_insp_tenant", "tenant_id"),
		Index("ix_qc_insp_plan", "plan_id"),
		Index("ix_qc_insp_reference", "reference_type", "reference_id"),
		Index("ix_qc_insp_tenant_status", "tenant_id", "status"),
		Index("ix_qc_insp_date", "inspection_date"),
		Index("ix_qc_insp_inspector", "inspector_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Polymorphic reference
	reference_type = Column(
		String(100),
		nullable=False,
		comment="Model class name that triggered this inspection e.g. APGoodsReceipt",
	)
	reference_id = Column(String(64), nullable=False, comment="ID of the triggering document")

	# Plan
	plan_id = Column(UUID(as_uuid=False), ForeignKey("qc_inspection_plan.id"), nullable=True, index=True, comment="NULL = ad-hoc inspection")

	# Quantities
	inspected_quantity = Column(Numeric(15, 4), nullable=False, comment="Quantity pulled for inspection (sample)")
	accepted_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="Quantity passed inspection")
	rejected_quantity = Column(Numeric(15, 4), nullable=False, default=0, comment="Quantity failed inspection")
	uom = Column(String(20), nullable=False, default="EA")

	# Assignment
	inspector_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user assigned as inspector")
	inspection_date = Column(Date, nullable=False)

	# Results
	status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | IN_PROGRESS | PASSED | FAILED",
	)
	findings: list[dict[str, Any]] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment='[{"criterion": "...", "measured": ..., "result": "PASS|FAIL", "note": "..."}]',
	)
	overall_result = Column(
		String(10),
		nullable=True,
		comment="PASS | FAIL | CONDITIONAL — summary result; NULL until completed",
	)
	disposition = Column(
		String(20),
		nullable=True,
		comment="ACCEPT | REJECT | REWORK | USE_AS_IS — final disposition after QA review",
	)

	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	plan: InspectionPlan | None = relationship("InspectionPlan", back_populates="inspections", lazy="select")

	def __repr__(self) -> str:
		return (
			f"<QualityInspection ref={self.reference_type!r}/{self.reference_id!r} "
			f"status={self.status!r} result={self.overall_result!r}>"
		)


# ---------------------------------------------------------------------------
# NonConformanceReport
# ---------------------------------------------------------------------------

class NonConformanceReport(AuditMixin, Model):
	"""Non-Conformance Report (NCR).

	Records quality failures and drives the CAPA (Corrective And Preventive
	Action) workflow.

	source_type:
	  SUPPLIER   — incoming goods NCR (triggers supplier debit note / claim)
	  PRODUCTION — in-process or end-of-line failure
	  CUSTOMER   — customer complaint / field return

	severity:
	  CRITICAL — safety/regulatory; immediate containment required
	  MAJOR    — significant deviation; affects product function
	  MINOR    — cosmetic / minor deviation; acceptable under deviation

	Status machine:
	  OPEN → ANALYSIS → CORRECTION → CLOSED

	IMMUTABLE NOTE: root_cause, corrective_action, preventive_action fields
	should be treated as append-only.  If they need revision, use the notes
	relationship or a new NCR superseding the original.  Never silently UPDATE
	a CLOSED NCR — emit a ReopenedEvent instead.
	"""

	__allow_unmapped__ = True
	__tablename__ = "qc_ncr"
	__table_args__ = (
		Index("ix_qc_ncr_tenant", "tenant_id"),
		Index("ix_qc_ncr_product", "product_id"),
		Index("ix_qc_ncr_tenant_status", "tenant_id", "status"),
		Index("ix_qc_ncr_severity", "severity"),
		Index("ix_qc_ncr_due_date", "due_date"),
		Index("ix_qc_ncr_owner", "owner_id"),
		Index("ix_qc_ncr_source_ref", "source_type", "source_reference_id"),
		UniqueConstraint("tenant_id", "ncr_number", name="uq_qc_ncr_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	ncr_number = Column(String(50), nullable=False, comment="NCR reference number; unique per tenant")

	# Source
	source_type = Column(
		String(15),
		nullable=False,
		comment="SUPPLIER | PRODUCTION | CUSTOMER",
	)
	source_reference_id = Column(
		String(64),
		nullable=True,
		index=True,
		comment="ID of triggering document (GRN, Production Order, Customer Complaint)",
	)
	inspection_id = Column(
		UUID(as_uuid=False),
		ForeignKey("qc_inspection.id"),
		nullable=True,
		index=True,
		comment="Linked inspection that raised this NCR (optional)",
	)

	# Product / quantity
	product_id = Column(UUID(as_uuid=False), nullable=False, index=True, comment="FK to product/item master (app-managed)")
	quantity_affected = Column(Numeric(15, 4), nullable=False, comment="Quantity of product affected by this NCR")
	uom = Column(String(20), nullable=False, default="EA")
	batch_lot_number = Column(String(100), nullable=True, comment="Batch or lot number affected")

	# Classification
	severity = Column(
		String(10),
		nullable=False,
		comment="CRITICAL | MAJOR | MINOR",
	)
	description = Column(Text, nullable=False, comment="Description of the non-conformance")

	# Status
	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | ANALYSIS | CORRECTION | CLOSED",
	)

	# CAPA (Corrective And Preventive Action)
	root_cause = Column(Text, nullable=True, comment="Root cause analysis finding; set during ANALYSIS phase")
	corrective_action = Column(Text, nullable=True, comment="Immediate corrective action taken; set during CORRECTION phase")
	preventive_action = Column(Text, nullable=True, comment="Systemic preventive action to avoid recurrence")

	# Assignment & timeline
	owner_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user responsible for resolution")
	due_date = Column(Date, nullable=True, comment="Target resolution date")
	closed_at = Column(DateTime(timezone=True), nullable=True, comment="Timestamp when NCR reached CLOSED status")
	closed_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user who closed the NCR")

	# Supplier claim linkage (SUPPLIER source_type)
	supplier_claim_value_cents = Column(
		Integer,
		nullable=True,
		comment="Value of claim raised against supplier; integer cents",
	)
	supplier_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		index=True,
		comment="FK to scm_supplier.id (soft) — set for SUPPLIER source NCRs",
	)

	notes = Column(Text, nullable=True)
	metadata_: dict[str, Any] = Column("metadata", JSONB, nullable=False, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	inspection: QualityInspection | None = relationship("QualityInspection", foreign_keys=[inspection_id], lazy="select")

	def __repr__(self) -> str:
		return (
			f"<NCR {self.ncr_number!r} severity={self.severity!r} "
			f"status={self.status!r} product={self.product_id!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"InspectionPlan",
	"QualityInspection",
	"NonConformanceReport",
]
