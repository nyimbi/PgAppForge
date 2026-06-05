"""
pgappforge/plugins/erp/grc/controls/models.py

GRC Controls models — control frameworks, individual controls, test results,
and segregation-of-duties conflict matrix.

Entities:
  ControlFramework      — SOX/ISO27001/NIST/GDPR/HIPAA/PCI_DSS framework
  Control               — individual control within a framework
  ControlTest           — periodic test result with evidence links
  SegregationOfDuties   — role-pair conflict registry

Design:
  - All PKs: UUID v4
  - All timestamps: TIMESTAMPTZ DEFAULT NOW()
  - tenant_id: all mutable entities
  - evidence_urls: JSONB list of S3/GCS URLs
  - owner_id / tester_id reference erp_party (logical FK; avoids circular dep)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
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
# ControlFramework
# ---------------------------------------------------------------------------

class ControlFramework(AuditMixin, Model):
	"""Compliance framework definition.

	name uses a controlled vocabulary: SOX, ISO27001, NIST, GDPR, HIPAA, PCI_DSS.
	version: framework version string e.g. '2013' for COSO/SOX, '2022' for ISO27001.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_control_framework"
	__table_args__ = (
		UniqueConstraint("tenant_id", "name", "version",
		                 name="uq_erp_ctlfw_tenant_name_ver"),
		Index("ix_erp_ctlfw_tenant", "tenant_id"),
		Index("ix_erp_ctlfw_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(
		String(20),
		nullable=False,
		comment="SOX | ISO27001 | NIST | GDPR | HIPAA | PCI_DSS",
	)
	version = Column(String(20), nullable=False, comment="Framework version e.g. '2022'")
	description = Column(Text, nullable=True)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	controls: list[Control] = relationship(
		"Control",
		back_populates="framework",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<ControlFramework {self.name!r} v{self.version!r}>"


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------

class Control(AuditMixin, Model):
	"""Individual control within a framework.

	control_code: unique per tenant, used as the stable external reference
	  (e.g. 'SOX-CC6.1', 'ISO-A.9.1.1').
	owner_id: logical FK to erp_party (an Employee party role).
	automated: True if the control is system-enforced; False if manual.
	frequency: how often the control operates / is tested.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_control"
	__table_args__ = (
		UniqueConstraint("tenant_id", "control_code",
		                 name="uq_erp_ctl_tenant_code"),
		Index("ix_erp_ctl_framework", "framework_id"),
		Index("ix_erp_ctl_tenant", "tenant_id"),
		Index("ix_erp_ctl_status", "status"),
		Index("ix_erp_ctl_owner", "owner_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	framework_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_control_framework.id", ondelete="RESTRICT"),
		nullable=False,
	)
	control_code = Column(
		String(50),
		nullable=False,
		comment="Stable external reference e.g. 'SOX-CC6.1'",
	)
	control_name = Column(String(500), nullable=False)
	control_objective = Column(Text, nullable=False)
	control_type = Column(
		String(20),
		nullable=False,
		comment="PREVENTIVE | DETECTIVE | CORRECTIVE",
	)
	frequency = Column(
		String(20),
		nullable=False,
		comment="CONTINUOUS | DAILY | MONTHLY | QUARTERLY | ANNUAL",
	)
	automated = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = system-enforced; False = manual",
	)
	owner_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Employee party responsible for this control",
	)
	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | INACTIVE",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	framework: ControlFramework = relationship(
		"ControlFramework",
		back_populates="controls",
		lazy="select",
	)
	tests: list[ControlTest] = relationship(
		"ControlTest",
		back_populates="control",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Control {self.control_code!r} {self.control_name!r}"
			f" type={self.control_type!r}>"
		)


# ---------------------------------------------------------------------------
# ControlTest
# ---------------------------------------------------------------------------

class ControlTest(AuditMixin, Model):
	"""Periodic test execution result for a control.

	evidence_urls: JSONB list of storage URLs to supporting evidence files.
	test_result:   EFFECTIVE | INEFFECTIVE | NOT_TESTED
	remediation_due: date by which any noted deficiencies must be remediated.

	Immutable after completion — insert a new test record to document follow-up.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_control_test"
	__table_args__ = (
		Index("ix_erp_ctltest_control", "control_id"),
		Index("ix_erp_ctltest_tenant", "tenant_id"),
		Index("ix_erp_ctltest_date", "test_date"),
		Index("ix_erp_ctltest_result", "test_result"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	control_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_control.id", ondelete="RESTRICT"),
		nullable=False,
	)
	test_date = Column(Date, nullable=False)
	tester_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Employee party who performed the test",
	)
	test_result = Column(
		String(15),
		nullable=False,
		comment="EFFECTIVE | INEFFECTIVE | NOT_TESTED",
	)
	evidence_urls: list[str] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="List of storage URLs to evidence files",
	)
	deficiencies_noted = Column(Text, nullable=True)
	remediation_due = Column(Date, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	control: Control = relationship(
		"Control",
		back_populates="tests",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ControlTest {self.id!r} control={self.control_id!r}"
			f" date={self.test_date!r} result={self.test_result!r}>"
		)


# ---------------------------------------------------------------------------
# SegregationOfDuties
# ---------------------------------------------------------------------------

class SegregationOfDuties(AuditMixin, Model):
	"""Role-pair conflict registry for SoD enforcement.

	Records pairs of roles that should not be held simultaneously.
	risk_level indicates severity: LOW → CRITICAL.

	The service layer checks this table when assigning roles to users.
	Conflicts are bidirectional — (A, B) implies (B, A); only one row needed.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_segregation_of_duties"
	__table_args__ = (
		UniqueConstraint("tenant_id", "role_a", "role_b",
		                 name="uq_erp_sod_tenant_roles"),
		Index("ix_erp_sod_tenant", "tenant_id"),
		Index("ix_erp_sod_risk", "risk_level"),
		Index("ix_erp_sod_active", "is_active"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	role_a = Column(String(200), nullable=False, comment="First conflicting role")
	role_b = Column(String(200), nullable=False, comment="Second conflicting role")
	conflict_type = Column(
		String(200),
		nullable=False,
		comment="Human-readable conflict description e.g. 'AP Approval + Payment'",
	)
	risk_level = Column(
		String(10),
		nullable=False,
		default="HIGH",
		comment="LOW | MEDIUM | HIGH | CRITICAL",
	)
	is_active = Column(Boolean, nullable=False, default=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<SegregationOfDuties {self.role_a!r} ⚡ {self.role_b!r}"
			f" risk={self.risk_level!r}>"
		)


# ---------------------------------------------------------------------------
# RiskRegister
# ---------------------------------------------------------------------------

class RiskRegister(AuditMixin, Model):
	"""Enterprise Risk Register entry.

	risk_score = likelihood × impact (1–25 scale).
	Risk levels derived from score:
	  1–4   → LOW
	  5–9   → MEDIUM
	  10–16 → HIGH
	  17–25 → CRITICAL

	inherent_risk_level: before controls.
	residual_risk_level: after controls are applied.
	treatment:
	  ACCEPT   — risk appetite allows it; no action.
	  MITIGATE — reduce likelihood or impact via controls.
	  TRANSFER — insure or outsource.
	  AVOID    — discontinue the activity.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_risk_register"
	__table_args__ = (
		UniqueConstraint("tenant_id", "risk_code", name="uq_erp_risk_tenant_code"),
		Index("ix_erp_risk_tenant", "tenant_id"),
		Index("ix_erp_risk_category", "risk_category"),
		Index("ix_erp_risk_status", "status"),
		Index("ix_erp_risk_owner", "risk_owner_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	risk_code = Column(String(20), nullable=False, comment="e.g. RSK-001")
	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=False)
	risk_category = Column(
		String(20),
		nullable=False,
		comment=(
			"STRATEGIC | OPERATIONAL | FINANCIAL | COMPLIANCE | "
			"REPUTATIONAL | TECHNOLOGY"
		),
	)
	likelihood = Column(
		Integer,
		nullable=False,
		comment="1 (rare) to 5 (almost certain)",
	)
	impact = Column(
		Integer,
		nullable=False,
		comment="1 (insignificant) to 5 (catastrophic)",
	)
	risk_score = Column(
		Integer,
		nullable=False,
		comment="likelihood × impact; computed on insert/update",
	)
	inherent_risk_level = Column(
		String(10),
		nullable=False,
		comment="LOW | MEDIUM | HIGH | CRITICAL — before controls",
	)
	residual_risk_level = Column(
		String(10),
		nullable=False,
		comment="LOW | MEDIUM | HIGH | CRITICAL — after controls",
	)
	risk_appetite_level = Column(
		String(10),
		nullable=False,
		default="MEDIUM",
		comment="LOW | MEDIUM | HIGH — board-approved appetite",
	)
	treatment = Column(
		String(10),
		nullable=False,
		default="MITIGATE",
		comment="ACCEPT | MITIGATE | TRANSFER | AVOID",
	)
	risk_owner_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="Logical FK to erp_party — risk owner",
	)
	review_date = Column(Date, nullable=False, comment="Next scheduled review date")
	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | MITIGATED | ACCEPTED | CLOSED",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	findings: list[AuditFinding] = relationship(
		"AuditFinding",
		back_populates="risk",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<RiskRegister {self.risk_code!r} {self.title!r} "
			f"score={self.risk_score} level={self.residual_risk_level!r} "
			f"status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# AuditFinding
# ---------------------------------------------------------------------------

class AuditFinding(AuditMixin, Model):
	"""Audit or assurance finding linked to a control and/or risk.

	finding_type severity hierarchy:
	  OBSERVATION < DEFICIENCY < SIGNIFICANT_DEFICIENCY < MATERIAL_WEAKNESS

	status lifecycle:
	  OPEN → IN_PROGRESS → REMEDIATED (or ACCEPTED if risk-accepted)

	Either control_id or risk_id (or both) should be non-null.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_audit_finding"
	__table_args__ = (
		Index("ix_erp_afind_tenant", "tenant_id"),
		Index("ix_erp_afind_control", "control_id"),
		Index("ix_erp_afind_risk", "risk_id"),
		Index("ix_erp_afind_status", "status"),
		Index("ix_erp_afind_priority", "priority"),
		Index("ix_erp_afind_due", "due_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	control_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_control.id", ondelete="SET NULL"),
		nullable=True,
	)
	risk_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_risk_register.id", ondelete="SET NULL"),
		nullable=True,
	)
	finding_type = Column(
		String(30),
		nullable=False,
		comment=(
			"DEFICIENCY | MATERIAL_WEAKNESS | SIGNIFICANT_DEFICIENCY | OBSERVATION"
		),
	)
	title = Column(String(300), nullable=False)
	description = Column(Text, nullable=False)
	recommendation = Column(Text, nullable=False)
	management_response = Column(Text, nullable=True)
	priority = Column(
		String(6),
		nullable=False,
		default="MEDIUM",
		comment="HIGH | MEDIUM | LOW",
	)
	status = Column(
		String(15),
		nullable=False,
		default="OPEN",
		comment="OPEN | IN_PROGRESS | REMEDIATED | ACCEPTED",
	)
	due_date = Column(Date, nullable=False, comment="Management agreed remediation date")
	owner_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="Logical FK to erp_party — person responsible for remediation",
	)
	closed_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	control: Control | None = relationship(
		"Control",
		lazy="select",
		foreign_keys=[control_id],
	)
	risk: RiskRegister | None = relationship(
		"RiskRegister",
		back_populates="findings",
		lazy="select",
		foreign_keys=[risk_id],
	)

	def __repr__(self) -> str:
		return (
			f"<AuditFinding {self.id!r} type={self.finding_type!r} "
			f"priority={self.priority!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# PolicyDocument
# ---------------------------------------------------------------------------

class PolicyDocument(AuditMixin, Model):
	"""Policy or procedure document within the GRC policy library.

	version: e.g. '1.0', '2.3', '3.0-DRAFT'.
	status lifecycle:
	  DRAFT → APPROVED → EFFECTIVE → OBSOLETE

	Immutable once EFFECTIVE — revisions create a new row with bumped version
	and reference the prior row (optional; no FK enforced here to keep simple).
	"""

	__allow_unmapped__ = True
	__tablename__ = "erp_policy_document"
	__table_args__ = (
		UniqueConstraint("tenant_id", "policy_code", "version",
		                 name="uq_erp_policy_tenant_code_ver"),
		Index("ix_erp_policy_tenant", "tenant_id"),
		Index("ix_erp_policy_status", "status"),
		Index("ix_erp_policy_review", "review_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	policy_code = Column(String(20), nullable=False, comment="e.g. POL-HR-001")
	title = Column(String(300), nullable=False)
	category = Column(String(50), nullable=False, comment="e.g. HR, Finance, IT, Compliance")
	body = Column(Text, nullable=False, comment="Full policy text (markdown or plain text)")
	version = Column(String(10), nullable=False, comment="e.g. '1.0', '2.3'")
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | APPROVED | EFFECTIVE | OBSOLETE",
	)
	effective_date = Column(Date, nullable=False)
	review_date = Column(Date, nullable=False, comment="Next scheduled review date")
	owner_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="Logical FK to erp_party — policy owner",
	)
	approved_by = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Logical FK to erp_party — approver",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<PolicyDocument {self.policy_code!r} v{self.version!r} "
			f"status={self.status!r}>"
		)


__all__ = [
	"ControlFramework",
	"Control",
	"ControlTest",
	"SegregationOfDuties",
	"RiskRegister",
	"AuditFinding",
	"PolicyDocument",
]
