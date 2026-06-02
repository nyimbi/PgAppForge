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


__all__ = [
	"ControlFramework",
	"Control",
	"ControlTest",
	"SegregationOfDuties",
]
