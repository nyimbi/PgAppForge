"""
pgappforge/plugins/erp/hcm/personnel/models.py

SQLAlchemy models for the HCM Personnel Administration plugin.

Design invariants:
  - ALL PKs: UUID v4
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - EmployeeCompensation: IMMUTABLE — INSERT correction rows, never UPDATE
  - Sensitive fields (national_id, tax_id, bank_iban) are application-level
    encrypted before storage — column type TEXT, prefix "enc:"
  - lazy='select' throughout

Table prefix: hcm_per_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

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
# Employee
# ---------------------------------------------------------------------------

class Employee(AuditMixin, Model):
	"""Employee master record — the hire-to-retire anchor entity.

	Demographic data lives on foundation.Party (linked via party_id soft FK).
	This model carries employment-specific state: position assignment, entity,
	org unit, manager chain, employment lifecycle, and encrypted sensitive fields.

	Sensitive fields (national_id_encrypted, tax_id_encrypted,
	bank_account_iban_encrypted) must be application-level encrypted before
	storage. The application decrypts them on read; the database stores ciphertext.

	Multiple active records (same person_id, different entity_id) represent
	concurrent employments across legal entities (secondments, multi-country).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_employee"
	__table_args__ = (
		Index("ix_hcm_emp_tenant", "tenant_id"),
		Index("ix_hcm_emp_entity", "entity_id"),
		Index("ix_hcm_emp_org_unit", "org_unit_id"),
		Index("ix_hcm_emp_position", "position_id"),
		Index("ix_hcm_emp_manager", "manager_id"),
		Index("ix_hcm_emp_tenant_status", "tenant_id", "employment_status"),
		UniqueConstraint("tenant_id", "employee_number", name="uq_hcm_emp_tenant_number"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	employee_number = Column(String(30), nullable=False, comment="Human-readable employee ID; unique per tenant")

	# Soft FK to foundation.Party (no DB constraint — cross-plugin safety)
	party_id = Column(UUID(as_uuid=False), nullable=True, index=True, comment="FK to erp_party.id (soft)")

	# Org placement
	position_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_position.id"), nullable=True, index=True)
	entity_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_legal_entity.id"), nullable=False, index=True)
	org_unit_id = Column(UUID(as_uuid=False), ForeignKey("hcm_org_unit.id"), nullable=True, index=True)

	# Manager chain — self-referencing soft FK; avoids circular constraint issues
	manager_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=True, index=True)

	# Employment classification
	employment_type = Column(
		String(20),
		nullable=False,
		default="FULL_TIME",
		comment="FULL_TIME | PART_TIME | CONTRACT | CASUAL",
	)
	employment_status = Column(
		String(20),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | ON_LEAVE | TERMINATED | RETIRED",
	)

	# Dates
	start_date = Column(Date, nullable=False, comment="Official employment commencement date")
	probation_end_date = Column(Date, nullable=True)
	termination_date = Column(Date, nullable=True)
	termination_type = Column(
		String(20),
		nullable=True,
		comment="VOLUNTARY | INVOLUNTARY | REDUNDANCY | RETIREMENT",
	)
	termination_reason = Column(String(255), nullable=True)
	rehire_eligible = Column(Boolean, nullable=False, default=True)

	# GL coding override
	cost_center_code = Column(String(20), nullable=True, comment="Overrides org unit cost centre for payroll allocation")

	# Encrypted sensitive fields — application must encrypt before storing
	national_id_encrypted = Column(Text, nullable=True, comment="App-encrypted national identity document number")
	tax_id_encrypted = Column(Text, nullable=True, comment="App-encrypted personal tax identification number")
	bank_account_iban_encrypted = Column(Text, nullable=True, comment="App-encrypted destination bank IBAN for payroll")
	bank_bic = Column(String(11), nullable=True, comment="Bank BIC/SWIFT — not sensitive, stored plaintext")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	manager: Employee | None = relationship(
		"Employee",
		remote_side="Employee.id",
		foreign_keys="[Employee.manager_id]",
		lazy="select",
	)
	direct_reports: list[Employee] = relationship(
		"Employee",
		back_populates="manager",
		foreign_keys="[Employee.manager_id]",
		lazy="select",
		overlaps="manager",
	)
	compensation_history: list[EmployeeCompensation] = relationship(
		"EmployeeCompensation",
		back_populates="employee",
		order_by="desc(EmployeeCompensation.effective_date)",
		lazy="select",
	)
	documents: list[EmployeeDocument] = relationship(
		"EmployeeDocument",
		back_populates="employee",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<Employee {self.employee_number!r} status={self.employment_status!r}>"


# ---------------------------------------------------------------------------
# EmployeeCompensation
# ---------------------------------------------------------------------------

class EmployeeCompensation(AuditMixin, Model):
	"""Effective-dated compensation record.

	IMMUTABLE LEDGER: never UPDATE existing rows.  Every pay change inserts
	a new row with a new effective_date.  The active rate is the row with the
	highest effective_date <= today.

	ALL monetary amounts are INTEGER CENTS — never float or Numeric.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_employee_compensation"
	__table_args__ = (
		Index("ix_hcm_ec_employee", "employee_id"),
		Index("ix_hcm_ec_effective", "effective_date"),
		Index("ix_hcm_ec_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	effective_date = Column(Date, nullable=False, index=True, comment="Date from which this pay rate is effective")

	pay_type = Column(
		String(20),
		nullable=False,
		comment="SALARY | HOURLY | COMMISSION",
	)
	# Integer cents — NEVER float
	amount_cents = Column(Integer, nullable=False, comment="Gross pay amount in cents at stated frequency")
	currency_code = Column(String(3), nullable=False, default="USD")
	frequency = Column(
		String(20),
		nullable=False,
		comment="ANNUAL | MONTHLY | BIWEEKLY | HOURLY",
	)
	grade_code = Column(String(20), nullable=True, comment="Pay grade code at time of this change")
	reason = Column(
		String(50),
		nullable=False,
		comment="NEW_HIRE | MERIT | PROMOTION | MARKET | OTHER",
	)
	approved_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — approver")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship("Employee", back_populates="compensation_history", lazy="select")

	def __repr__(self) -> str:
		return f"<EmployeeCompensation emp={self.employee_id!r} amt={self.amount_cents}¢ eff={self.effective_date}>"


# ---------------------------------------------------------------------------
# EmployeeDocument
# ---------------------------------------------------------------------------

class EmployeeDocument(AuditMixin, Model):
	"""Employee document metadata.

	Actual file content lives in object storage (S3, GCS, etc.).
	storage_url references the object — application resolves it to a signed URL.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_employee_document"
	__table_args__ = (
		Index("ix_hcm_edoc_employee", "employee_id"),
		Index("ix_hcm_edoc_tenant", "tenant_id"),
		Index("ix_hcm_edoc_expiry", "expiry_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	document_type = Column(String(50), nullable=False, comment="CONTRACT | PASSPORT | VISA | CERTIFICATE | NDA | OTHER")
	filename = Column(String(500), nullable=False, comment="Original filename as uploaded")
	storage_url = Column(Text, nullable=False, comment="Object store key or URL; resolve to signed URL on read")
	issued_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True, comment="Alert generated when expiry_date < today + 30 days")
	is_verified = Column(Boolean, nullable=False, default=False, comment="HR has verified the document's authenticity")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship("Employee", back_populates="documents", lazy="select")

	def __repr__(self) -> str:
		return f"<EmployeeDocument emp={self.employee_id!r} type={self.document_type!r} verified={self.is_verified}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Employee",
	"EmployeeCompensation",
	"EmployeeDocument",
]
