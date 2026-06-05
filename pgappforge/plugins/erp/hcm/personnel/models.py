"""
pgappforge/plugins/erp/hcm/personnel/models.py

SQLAlchemy models for the HCM Personnel Administration plugin.

Design invariants:
  - ALL PKs: UUID v4 as string
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL monetary amounts: Integer cents (BigInteger)
  - ALL models: tenant_id UUID NOT NULL + AuditMixin
  - EmployeeCompensation: IMMUTABLE — INSERT correction rows, never UPDATE
  - Sensitive fields (national_id, tax_id, bank_iban) are application-level
    encrypted before storage — column type TEXT, prefix "enc:"
  - lazy='select' throughout
  - PostgreSQL ONLY — JSONB used throughout

Table prefix: hcm_per_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	SmallInteger,
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

	background_check_status: NOT_REQUIRED | PENDING | PASSED | FAILED | WAIVED
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
		Index("ix_hcm_emp_probation", "tenant_id", "probation_end_date"),
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

	# Background check — HIGH gap
	background_check_status = Column(
		String(20),
		nullable=False,
		default="NOT_REQUIRED",
		comment="NOT_REQUIRED | PENDING | PASSED | FAILED | WAIVED",
	)
	background_check_provider = Column(String(100), nullable=True)
	background_check_ref = Column(String(100), nullable=True)

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
	contracts: list[EmploymentContract] = relationship(
		"EmploymentContract",
		back_populates="employee",
		order_by="desc(EmploymentContract.created_at)",
		lazy="select",
	)
	disciplinary_cases: list[DisciplinaryCase] = relationship(
		"DisciplinaryCase",
		back_populates="employee",
		foreign_keys="[DisciplinaryCase.employee_id]",
		lazy="select",
	)
	grievance_cases: list[GrievanceCase] = relationship(
		"GrievanceCase",
		back_populates="filed_by",
		foreign_keys="[GrievanceCase.filed_by_employee_id]",
		lazy="select",
	)
	onboarding_plans: list[OnboardingPlan] = relationship(
		"OnboardingPlan",
		back_populates="employee",
		foreign_keys="[OnboardingPlan.employee_id]",
		lazy="select",
	)
	exit_records: list[EmployeeExit] = relationship(
		"EmployeeExit",
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
	Stored as BigInteger to safely accommodate high-value currencies.

	currency_code defaults to KES (Kenya context).
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
	# BigInteger cents — NEVER float
	amount_cents = Column(BigInteger, nullable=False, comment="Gross pay amount in cents at stated frequency")
	currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
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

	# HIGH: Compensation approval workflow
	approval_status = Column(
		String(20),
		nullable=False,
		default="APPROVED",
		comment="PENDING | APPROVED | REJECTED",
	)
	approval_rejected_reason = Column(Text, nullable=True)

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
	"""Employee document metadata with version history.

	Actual file content lives in object storage (S3, GCS, etc.).
	storage_url references the object — application resolves it to a signed URL.

	Versioning: superseded_by_id points to the newer document.
	Active document = row with superseded_by_id IS NULL.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_employee_document"
	__table_args__ = (
		Index("ix_hcm_edoc_employee", "employee_id"),
		Index("ix_hcm_edoc_tenant", "tenant_id"),
		Index("ix_hcm_edoc_expiry", "expiry_date"),
		Index("ix_hcm_edoc_active", "employee_id", "document_type", "superseded_by_id"),
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

	# MEDIUM: Document version history
	version = Column(Integer, nullable=False, default=1)
	superseded_by_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hcm_per_employee_document.id"),
		nullable=True,
		comment="Points to newer version; NULL = current active version",
	)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship("Employee", back_populates="documents", lazy="select")
	superseded_by: EmployeeDocument | None = relationship(
		"EmployeeDocument",
		foreign_keys=[superseded_by_id],
		remote_side="EmployeeDocument.id",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<EmployeeDocument emp={self.employee_id!r} type={self.document_type!r} v={self.version} verified={self.is_verified}>"


# ---------------------------------------------------------------------------
# CRITICAL: EmploymentContract
# ---------------------------------------------------------------------------

class EmploymentContract(AuditMixin, Model):
	"""Employment contract lifecycle — DRAFT → OFFERED → ACCEPTED → ACTIVE → AMENDED → TERMINATED.

	Links to Employee. Enforces Kenya Employment Act s.35 notice period storage.
	contract_type: PERMANENT | FIXED_TERM | CASUAL | INTERNSHIP
	status: DRAFT | OFFERED | ACCEPTED | ACTIVE | AMENDED | TERMINATED
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_contract"
	__table_args__ = (
		Index("ix_hcm_con_employee", "employee_id"),
		Index("ix_hcm_con_tenant", "tenant_id"),
		Index("ix_hcm_con_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)

	contract_type = Column(
		String(20),
		nullable=False,
		default="PERMANENT",
		comment="PERMANENT | FIXED_TERM | CASUAL | INTERNSHIP",
	)
	status = Column(
		String(20),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | OFFERED | ACCEPTED | ACTIVE | AMENDED | TERMINATED",
	)

	offer_date = Column(Date, nullable=True, comment="Date contract was offered to candidate")
	accepted_date = Column(Date, nullable=True, comment="Date candidate accepted the offer")
	start_date = Column(Date, nullable=False, comment="Contract start / employment commencement date")
	end_date = Column(Date, nullable=True, comment="NULL for permanent contracts")
	probation_end_date = Column(Date, nullable=True)
	confirmed_date = Column(Date, nullable=True, comment="Date probation was confirmed / contract activated")
	terminated_date = Column(Date, nullable=True)

	# Kenya Employment Act s.35: minimum notice period
	notice_period_days = Column(
		Integer,
		nullable=False,
		default=28,
		comment="Minimum notice period in days per Employment Act 2007 s.35",
	)
	# Pay in lieu of notice — BigInteger cents
	notice_pay_in_lieu_cents = Column(
		BigInteger,
		nullable=True,
		comment="Notice pay in lieu (cents) if notice waived on termination",
	)

	# Amendments trail — JSONB array of {date, changed_by, summary}
	amendments = Column(JSONB, nullable=True, default=list)

	notes = Column(Text, nullable=True)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship("Employee", back_populates="contracts", lazy="select")

	def __repr__(self) -> str:
		return f"<EmploymentContract emp={self.employee_id!r} type={self.contract_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CRITICAL: DisciplinaryCase + DisciplinaryAction
# ---------------------------------------------------------------------------

class DisciplinaryCase(AuditMixin, Model):
	"""Disciplinary case entity.

	status: OPEN → SHOW_CAUSE_ISSUED → HEARING_SCHEDULED → HEARING_COMPLETE → CLOSED
	case_type: VERBAL_WARNING | WRITTEN_WARNING | FINAL_WARNING | DISMISSAL | OTHER

	DISMISSAL outcome must precede terminate_employee(termination_type=INVOLUNTARY).
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_disciplinary_case"
	__table_args__ = (
		Index("ix_hcm_disc_employee", "employee_id"),
		Index("ix_hcm_disc_tenant", "tenant_id"),
		Index("ix_hcm_disc_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)

	case_number = Column(String(30), nullable=False, comment="Human-readable case reference")
	case_type = Column(
		String(30),
		nullable=False,
		comment="VERBAL_WARNING | WRITTEN_WARNING | FINAL_WARNING | DISMISSAL | OTHER",
	)
	status = Column(
		String(30),
		nullable=False,
		default="OPEN",
		comment="OPEN | SHOW_CAUSE_ISSUED | HEARING_SCHEDULED | HEARING_COMPLETE | CLOSED",
	)

	offence_description = Column(Text, nullable=False)
	offence_date = Column(Date, nullable=True)

	# Show cause
	show_cause_issued_at = Column(Date, nullable=True)
	show_cause_response = Column(Text, nullable=True)
	show_cause_response_date = Column(Date, nullable=True)

	# Hearing
	hearing_date = Column(Date, nullable=True)
	hearing_notes = Column(Text, nullable=True)
	presiding_officer_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — soft FK")

	# Outcome
	outcome = Column(
		String(30),
		nullable=True,
		comment="WARNING_ISSUED | DISMISSED | SUSPENDED | EXONERATED | OTHER",
	)
	outcome_date = Column(Date, nullable=True)
	outcome_notes = Column(Text, nullable=True)

	# Suspension details
	suspension_start_date = Column(Date, nullable=True)
	suspension_end_date = Column(Date, nullable=True)
	suspension_is_paid = Column(Boolean, nullable=True, default=True)

	# Extensible attributes
	extra = Column(JSONB, nullable=True, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship(
		"Employee",
		back_populates="disciplinary_cases",
		foreign_keys=[employee_id],
		lazy="select",
	)
	actions: list[DisciplinaryAction] = relationship(
		"DisciplinaryAction",
		back_populates="case",
		order_by="DisciplinaryAction.issued_at",
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<DisciplinaryCase {self.case_number!r} type={self.case_type!r} status={self.status!r}>"


class DisciplinaryAction(AuditMixin, Model):
	"""Individual action within a disciplinary case.

	action_type: VERBAL_WARNING | WRITTEN_WARNING | FINAL_WARNING | SUSPENSION | DISMISSAL
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_disciplinary_action"
	__table_args__ = (
		Index("ix_hcm_disc_act_case", "case_id"),
		Index("ix_hcm_disc_act_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	case_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_disciplinary_case.id"), nullable=False, index=True)

	action_type = Column(
		String(30),
		nullable=False,
		comment="VERBAL_WARNING | WRITTEN_WARNING | FINAL_WARNING | SUSPENSION | DISMISSAL",
	)
	issued_at = Column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
	issued_by = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — soft FK")
	notes = Column(Text, nullable=True)
	# Letter / document reference stored in object store
	letter_document_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to hcm_per_employee_document")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	case: DisciplinaryCase = relationship("DisciplinaryCase", back_populates="actions", lazy="select")

	def __repr__(self) -> str:
		return f"<DisciplinaryAction case={self.case_id!r} type={self.action_type!r} issued={self.issued_at}>"


# ---------------------------------------------------------------------------
# CRITICAL: GrievanceCase
# ---------------------------------------------------------------------------

class GrievanceCase(AuditMixin, Model):
	"""Grievance case — Kenya Employment Act s.47 internal grievance procedure.

	status: FILED → ACKNOWLEDGED → UNDER_REVIEW → RESOLVED → ESCALATED → CLOSED
	grievance_type: HARASSMENT | DISCRIMINATION | UNSAFE_CONDITIONS | COMPENSATION | OTHER
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_grievance"
	__table_args__ = (
		Index("ix_hcm_griev_filed_by", "filed_by_employee_id"),
		Index("ix_hcm_griev_tenant", "tenant_id"),
		Index("ix_hcm_griev_status", "tenant_id", "status"),
		Index("ix_hcm_griev_due", "tenant_id", "due_date"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	filed_by_employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)
	respondent_employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=True, index=True)
	assigned_to_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — soft FK")

	case_number = Column(String(30), nullable=False, comment="Human-readable grievance reference")
	grievance_type = Column(
		String(30),
		nullable=False,
		comment="HARASSMENT | DISCRIMINATION | UNSAFE_CONDITIONS | COMPENSATION | OTHER",
	)
	status = Column(
		String(20),
		nullable=False,
		default="FILED",
		comment="FILED | ACKNOWLEDGED | UNDER_REVIEW | RESOLVED | ESCALATED | CLOSED",
	)

	description = Column(Text, nullable=False)
	filed_date = Column(Date, nullable=False)
	due_date = Column(Date, nullable=True, comment="SLA resolution deadline")
	acknowledged_date = Column(Date, nullable=True)
	resolved_date = Column(Date, nullable=True)
	closed_date = Column(Date, nullable=True)

	resolution_notes = Column(Text, nullable=True)
	escalation_reason = Column(Text, nullable=True)
	escalated_to_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user escalated to")

	# Extensible attributes
	extra = Column(JSONB, nullable=True, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	filed_by: Employee = relationship(
		"Employee",
		back_populates="grievance_cases",
		foreign_keys=[filed_by_employee_id],
		lazy="select",
	)
	respondent: Employee | None = relationship(
		"Employee",
		foreign_keys=[respondent_employee_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<GrievanceCase {self.case_number!r} type={self.grievance_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# HIGH: OnboardingPlan + OnboardingTask
# ---------------------------------------------------------------------------

class OnboardingPlan(AuditMixin, Model):
	"""Structured onboarding workflow for a new employee.

	status: PENDING | IN_PROGRESS | COMPLETED | CANCELLED
	checklist_items: JSONB array of {key, label, due_days_from_start, owner_role, completed_at, completed_by}
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_onboarding"
	__table_args__ = (
		Index("ix_hcm_onb_employee", "employee_id"),
		Index("ix_hcm_onb_tenant", "tenant_id"),
		Index("ix_hcm_onb_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)

	template_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to configurable onboarding template (soft)")
	assigned_buddy_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=True)
	induction_date = Column(Date, nullable=True)
	target_completion_date = Column(Date, nullable=True)
	completed_date = Column(Date, nullable=True)

	status = Column(
		String(20),
		nullable=False,
		default="PENDING",
		comment="PENDING | IN_PROGRESS | COMPLETED | CANCELLED",
	)

	# JSONB checklist — each item: {key, label, due_days_from_start, owner_role, completed_at, completed_by}
	checklist_items = Column(JSONB, nullable=False, default=list)

	# Extensible attributes
	extra = Column(JSONB, nullable=True, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship(
		"Employee",
		back_populates="onboarding_plans",
		foreign_keys=[employee_id],
		lazy="select",
	)
	buddy: Employee | None = relationship(
		"Employee",
		foreign_keys=[assigned_buddy_id],
		lazy="select",
	)

	def __repr__(self) -> str:
		return f"<OnboardingPlan emp={self.employee_id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CRITICAL: EmployeeExit (Offboarding)
# ---------------------------------------------------------------------------

class EmployeeExit(AuditMixin, Model):
	"""Exit / offboarding record.

	status: INITIATED → IN_PROGRESS → CLEARED → CLOSED
	exit_type: RESIGNATION | REDUNDANCY | RETIREMENT | DISMISSAL | END_OF_CONTRACT | DEATH

	clearance_items: JSONB array of {key, label, cleared_by, cleared_at, notes}
	Standard items: IT_EQUIPMENT, ACCESS_CARDS, LOANS, LIBRARY, SACCO_DEDUCTIONS,
	                ID_BADGE, COMPANY_PROPERTY, HR_DOCUMENTS

	severance_amount_cents: Kenya Employment Act s.40 — 15 days per year of service.
	notice_pay_in_lieu_cents: when notice waived.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_per_exit"
	__table_args__ = (
		Index("ix_hcm_exit_employee", "employee_id"),
		Index("ix_hcm_exit_tenant", "tenant_id"),
		Index("ix_hcm_exit_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	employee_id = Column(UUID(as_uuid=False), ForeignKey("hcm_per_employee.id"), nullable=False, index=True)

	exit_type = Column(
		String(30),
		nullable=False,
		comment="RESIGNATION | REDUNDANCY | RETIREMENT | DISMISSAL | END_OF_CONTRACT | DEATH",
	)
	status = Column(
		String(20),
		nullable=False,
		default="INITIATED",
		comment="INITIATED | IN_PROGRESS | CLEARED | CLOSED",
	)

	resignation_date = Column(Date, nullable=True, comment="Date resignation letter received")
	last_working_day = Column(Date, nullable=True)
	exit_interview_date = Column(Date, nullable=True)
	exit_reason = Column(Text, nullable=True)

	# Financial settlement — BigInteger cents
	severance_amount_cents = Column(BigInteger, nullable=True, comment="Kenya EA s.40: 15 days per year of service")
	notice_pay_in_lieu_cents = Column(BigInteger, nullable=True, comment="Pay in lieu of notice (cents)")
	final_settlement_amount_cents = Column(BigInteger, nullable=True, comment="Total final pay settlement (cents)")
	currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")
	settlement_paid_date = Column(Date, nullable=True)

	# Notice enforcement (Kenya Employment Act s.35)
	notice_period_days = Column(Integer, nullable=True)
	notice_waived = Column(Boolean, nullable=False, default=False)
	notice_waiver_reason = Column(Text, nullable=True)

	# Clearance checklist — JSONB array
	clearance_items = Column(JSONB, nullable=False, default=list)

	# Closed by
	cleared_by_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — soft FK")
	cleared_date = Column(Date, nullable=True)
	closed_by_id = Column(UUID(as_uuid=False), nullable=True, comment="FK to ab_user — soft FK")
	closed_date = Column(Date, nullable=True)

	# Certificate of service issued
	certificate_issued = Column(Boolean, nullable=False, default=False)
	certificate_issued_date = Column(Date, nullable=True)

	# Extensible
	extra = Column(JSONB, nullable=True, default=dict)

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	# Relationships
	employee: Employee = relationship("Employee", back_populates="exit_records", lazy="select")

	def __repr__(self) -> str:
		return f"<EmployeeExit emp={self.employee_id!r} type={self.exit_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# HIGH: OrgJobGrade — salary band enforcement
# ---------------------------------------------------------------------------

class OrgJobGrade(AuditMixin, Model):
	"""Job grade / salary band.

	Enforces min/max salary band per grade per effective date.
	Monetary columns are BigInteger cents.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hcm_org_job_grade"
	__table_args__ = (
		Index("ix_hcm_jg_tenant", "tenant_id"),
		Index("ix_hcm_jg_code_eff", "tenant_id", "grade_code", "effective_date"),
		UniqueConstraint("tenant_id", "grade_code", "effective_date", name="uq_hcm_jg_tenant_code_eff"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	grade_code = Column(String(20), nullable=False)
	label = Column(String(100), nullable=True)
	effective_date = Column(Date, nullable=False)

	# BigInteger cents
	min_amount_cents = Column(BigInteger, nullable=False)
	max_amount_cents = Column(BigInteger, nullable=False)
	currency_code = Column(String(3), nullable=False, default="KES", server_default="KES")

	created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))
	updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=sa.text("NOW()"))

	def __repr__(self) -> str:
		return f"<OrgJobGrade {self.grade_code!r} [{self.min_amount_cents}¢–{self.max_amount_cents}¢] eff={self.effective_date}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Employee",
	"EmployeeCompensation",
	"EmployeeDocument",
	"EmploymentContract",
	"DisciplinaryCase",
	"DisciplinaryAction",
	"GrievanceCase",
	"OnboardingPlan",
	"EmployeeExit",
	"OrgJobGrade",
]
