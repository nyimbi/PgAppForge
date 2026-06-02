"""
pgappforge/plugins/erp/industry/health/models.py

Health Cloud — SQLAlchemy models.

Design rules:
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - JSONB for allergies, active_medications (semi-structured clinical data)
  - lazy='select' throughout (SA 2.x)
  - Clinical coding: ICD-10 for diagnoses, CPT for procedures, LOINC for labs,
    NDC for drugs — stored as VARCHAR, no enum constraint (codes extend frequently)
  - PHI columns commented appropriately
  - Financial records pattern does not apply here (no monetary data), but
    DiagnosisRecord / ProcedureRecord are append-only in practice (no UPDATE
    after attending physician signs off) — enforced via service layer

Table prefix: hlt_
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
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

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------

class Patient(AuditMixin, Model):
	"""Clinical patient record.

	Links to foundation.Party for demographic identity (name, DOB, contacts,
	addresses).  This model carries only clinical and insurance attributes.

	PHI: this table is subject to HIPAA / local data-protection regulations.
	Apply column-level encryption for allergies / active_medications in
	production deployments via pgcrypto or application-layer encryption.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hlt_patient"
	__table_args__ = (
		UniqueConstraint("patient_number", name="uq_hlt_patient_number"),
		Index("ix_hlt_patient_party", "party_id"),
		Index("ix_hlt_patient_tenant", "tenant_id"),
		Index("ix_hlt_patient_pcp", "primary_care_provider_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	# Party linkage (foundation.Party)
	party_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
	)

	patient_number = Column(
		String(50),
		nullable=False,
		comment="Unique medical record number (MRN)",
	)

	# Clinical basics — PHI
	blood_type = Column(
		String(5),
		nullable=True,
		comment="ABO + Rh e.g. A+, O-, AB+",
	)
	allergies: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="PHI: list of {allergen, reaction, severity, noted_at}",
	)
	active_medications: list[Any] = Column(
		JSONB,
		nullable=False,
		default=list,
		comment="PHI: list of {ndc_code, drug_name, dose, frequency}",
	)

	# Primary care
	primary_care_provider_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="FK to ab_user (Provider/Clinician)",
	)

	# Insurance
	insurance_member_id = Column(String(100), nullable=True)
	insurance_plan = Column(String(200), nullable=True)

	# Directives
	advance_directive = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True if patient has a signed advance directive on file",
	)
	organ_donor = Column(Boolean, nullable=False, default=False)

	# Language / access
	preferred_language = Column(
		String(5),
		nullable=True,
		comment="BCP 47 language tag e.g. en-US, ha, yo",
	)
	interpreter_needed = Column(Boolean, nullable=False, default=False)

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

	# Relationships
	encounters: list[ClinicalEncounter] = relationship(
		"ClinicalEncounter",
		back_populates="patient",
		cascade="all, delete-orphan",
		lazy="select",
	)
	lab_results: list[LabResult] = relationship(
		"LabResult",
		back_populates="patient",
		cascade="all, delete-orphan",
		lazy="select",
	)
	prescriptions: list[Prescription] = relationship(
		"Prescription",
		back_populates="patient",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Patient {self.id!r} #{self.patient_number!r} "
			f"blood={self.blood_type!r}>"
		)


# ---------------------------------------------------------------------------
# ClinicalEncounter
# ---------------------------------------------------------------------------

class ClinicalEncounter(AuditMixin, Model):
	"""A clinical visit or interaction between a patient and care team.

	Covers inpatient admissions, outpatient visits, ER presentations, and
	telehealth consultations via encounter_type discriminator.

	discharge_date / discharge_disposition are NULL until encounter is COMPLETED.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hlt_clinical_encounter"
	__table_args__ = (
		Index("ix_hlt_encounter_patient", "patient_id"),
		Index("ix_hlt_encounter_tenant_status", "tenant_id", "encounter_status"),
		Index("ix_hlt_encounter_provider", "provider_id"),
		Index("ix_hlt_encounter_date", "encounter_date"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	patient_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_patient.id", ondelete="RESTRICT"),
		nullable=False,
	)

	encounter_type = Column(
		String(15),
		nullable=False,
		comment="INPATIENT | OUTPATIENT | EMERGENCY | TELEHEALTH",
	)
	encounter_date = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	provider_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="Attending/responsible clinician (FK ab_user)",
	)
	facility_id = Column(
		UUID(as_uuid=False),
		nullable=True,
		comment="Facility UUID (FK to facility registry if available)",
	)

	chief_complaint = Column(Text, nullable=True, comment="Patient's presenting complaint")
	encounter_status = Column(
		String(15),
		nullable=False,
		default="SCHEDULED",
		comment="SCHEDULED | IN_PROGRESS | COMPLETED",
	)

	discharge_date = Column(DateTime(timezone=True), nullable=True)
	discharge_disposition = Column(
		String(100),
		nullable=True,
		comment="e.g. HOME, TRANSFER, EXPIRED, AMA",
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

	# Relationships
	patient: Patient = relationship(
		"Patient",
		back_populates="encounters",
		lazy="select",
	)
	diagnoses: list[DiagnosisRecord] = relationship(
		"DiagnosisRecord",
		back_populates="encounter",
		cascade="all, delete-orphan",
		lazy="select",
	)
	procedures: list[ProcedureRecord] = relationship(
		"ProcedureRecord",
		back_populates="encounter",
		cascade="all, delete-orphan",
		lazy="select",
	)
	prescriptions: list[Prescription] = relationship(
		"Prescription",
		back_populates="encounter",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ClinicalEncounter {self.id!r} patient={self.patient_id!r} "
			f"type={self.encounter_type!r} status={self.encounter_status!r}>"
		)


# ---------------------------------------------------------------------------
# DiagnosisRecord
# ---------------------------------------------------------------------------

class DiagnosisRecord(AuditMixin, Model):
	"""ICD-10 coded diagnosis attached to an encounter.

	Append-only after the attending physician confirms: the service layer
	blocks UPDATE on confirmed=True rows (raise_error via rules engine).

	PRIMARY diagnosis has diagnosis_type='PRIMARY'; only one PRIMARY per
	encounter is enforced at the service layer.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hlt_diagnosis_record"
	__table_args__ = (
		Index("ix_hlt_dx_encounter", "encounter_id"),
		Index("ix_hlt_dx_icd10", "icd10_code"),
		Index("ix_hlt_dx_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	encounter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_clinical_encounter.id", ondelete="RESTRICT"),
		nullable=False,
	)

	icd10_code = Column(
		String(10),
		nullable=False,
		comment="ICD-10-CM code e.g. J18.9 (Pneumonia unspecified)",
	)
	diagnosis_description = Column(String(500), nullable=False)
	diagnosis_type = Column(
		String(15),
		nullable=False,
		default="PRIMARY",
		comment="PRIMARY | SECONDARY | COMPLICATION",
	)
	confirmed = Column(
		Boolean,
		nullable=False,
		default=False,
		comment="True = clinician confirmed; row becomes append-only",
	)
	noted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	encounter: ClinicalEncounter = relationship(
		"ClinicalEncounter",
		back_populates="diagnoses",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<DiagnosisRecord {self.id!r} icd10={self.icd10_code!r} "
			f"type={self.diagnosis_type!r} confirmed={self.confirmed}>"
		)


# ---------------------------------------------------------------------------
# ProcedureRecord
# ---------------------------------------------------------------------------

class ProcedureRecord(AuditMixin, Model):
	"""CPT-coded procedure performed during an encounter."""

	__allow_unmapped__ = True
	__tablename__ = "hlt_procedure_record"
	__table_args__ = (
		Index("ix_hlt_proc_encounter", "encounter_id"),
		Index("ix_hlt_proc_cpt", "cpt_code"),
		Index("ix_hlt_proc_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	encounter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_clinical_encounter.id", ondelete="RESTRICT"),
		nullable=False,
	)

	cpt_code = Column(
		String(10),
		nullable=False,
		comment="CPT (Current Procedural Terminology) code",
	)
	procedure_name = Column(String(500), nullable=False)
	performed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	performed_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
		comment="Performing clinician (FK ab_user)",
	)
	notes = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	encounter: ClinicalEncounter = relationship(
		"ClinicalEncounter",
		back_populates="procedures",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ProcedureRecord {self.id!r} cpt={self.cpt_code!r} "
			f"at={self.performed_at!r}>"
		)


# ---------------------------------------------------------------------------
# Prescription
# ---------------------------------------------------------------------------

class Prescription(AuditMixin, Model):
	"""Medication order linked to an encounter.

	NDC code (National Drug Code) identifies the specific drug/formulation.
	Refill tracking: refills_used must never exceed refills_allowed.
	Status lifecycle: ACTIVE → COMPLETED (all refills consumed or duration
	elapsed) or DISCONTINUED (physician stops early).

	PHI: drug name, dosage, frequency.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hlt_prescription"
	__table_args__ = (
		Index("ix_hlt_rx_encounter", "encounter_id"),
		Index("ix_hlt_rx_patient", "patient_id"),
		Index("ix_hlt_rx_ndc", "ndc_code"),
		Index("ix_hlt_rx_tenant_status", "tenant_id", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	encounter_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_clinical_encounter.id", ondelete="RESTRICT"),
		nullable=False,
	)
	patient_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_patient.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# Drug identification
	ndc_code = Column(
		String(15),
		nullable=False,
		comment="National Drug Code (10 or 11 digit)",
	)
	drug_name = Column(String(300), nullable=False)

	# Dosage — PHI
	dosage = Column(String(100), nullable=False, comment="e.g. 500mg")
	frequency = Column(String(100), nullable=False, comment="e.g. TID, BID, QD")
	duration_days = Column(Integer, nullable=True)

	# Prescriber
	prescribed_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	prescribed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Refills
	refills_allowed = Column(Integer, nullable=False, default=0)
	refills_used = Column(Integer, nullable=False, default=0)

	status = Column(
		String(15),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | DISCONTINUED | COMPLETED",
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

	encounter: ClinicalEncounter = relationship(
		"ClinicalEncounter",
		back_populates="prescriptions",
		lazy="select",
	)
	patient: Patient = relationship(
		"Patient",
		back_populates="prescriptions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<Prescription {self.id!r} ndc={self.ndc_code!r} "
			f"drug={self.drug_name!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# LabResult
# ---------------------------------------------------------------------------

class LabResult(AuditMixin, Model):
	"""Laboratory test result.

	LOINC code identifies the observation type universally.
	result_value is TEXT to accommodate both numeric and coded results
	(e.g. "Positive", "142.5", "DETECTED").

	abnormal_flag uses HL7 interpretation codes:
	  N=Normal, H=High, L=Low, HH=Critical High, LL=Critical Low, NULL=Pending.

	Status lifecycle: ORDERED → COLLECTED → RESULTED → REVIEWED.
	REVIEWED means a clinician has acknowledged the result.
	"""

	__allow_unmapped__ = True
	__tablename__ = "hlt_lab_result"
	__table_args__ = (
		Index("ix_hlt_lab_patient", "patient_id"),
		Index("ix_hlt_lab_loinc", "loinc_code"),
		Index("ix_hlt_lab_tenant_status", "tenant_id", "status"),
		Index("ix_hlt_lab_ordered_at", "ordered_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	patient_id = Column(
		UUID(as_uuid=False),
		ForeignKey("hlt_patient.id", ondelete="RESTRICT"),
		nullable=False,
	)

	# Ordering
	ordered_by = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	ordered_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Test identification (LOINC)
	loinc_code = Column(
		String(10),
		nullable=False,
		comment="LOINC code identifying the observation type",
	)
	test_name = Column(String(300), nullable=False)
	specimen_type = Column(
		String(100),
		nullable=True,
		comment="e.g. Whole Blood, Serum, Urine",
	)

	# Result — PHI
	result_value = Column(
		Text,
		nullable=True,
		comment="PHI: numeric or coded result e.g. '142.5', 'Positive'",
	)
	result_unit = Column(
		String(50),
		nullable=True,
		comment="Unit of measure e.g. mg/dL, mmol/L",
	)
	reference_range = Column(
		String(100),
		nullable=True,
		comment="Normal reference range e.g. '70-100 mg/dL'",
	)
	abnormal_flag = Column(
		String(5),
		nullable=True,
		comment="HL7 interpretation: N | H | L | HH | LL | NULL=pending",
	)

	resulted_at = Column(DateTime(timezone=True), nullable=True)

	status = Column(
		String(10),
		nullable=False,
		default="ORDERED",
		comment="ORDERED | COLLECTED | RESULTED | REVIEWED",
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

	patient: Patient = relationship(
		"Patient",
		back_populates="lab_results",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<LabResult {self.id!r} loinc={self.loinc_code!r} "
			f"patient={self.patient_id!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"Patient",
	"ClinicalEncounter",
	"DiagnosisRecord",
	"ProcedureRecord",
	"Prescription",
	"LabResult",
]
