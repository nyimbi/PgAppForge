"""
pgappforge/plugins/erp/industry/health/services.py

HealthService — stateless business logic for the Health Cloud plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.

Key invariants:
  - DiagnosisRecord.confirmed=True rows are append-only (service raises on
    attempted mutation).
  - Lab critical values (HH, LL) emit LabCriticalValueEvent in addition to
    LabResultedEvent so downstream notification plugins can act immediately.
  - Prescription refills_used must never exceed refills_allowed.
  - Only one PRIMARY diagnosis per encounter (enforced here and via rules).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class HealthServiceError(Exception):
	"""Base error for Health Cloud domain violations."""


class PatientNotFoundError(HealthServiceError):
	"""No Patient with the given id."""


class EncounterNotFoundError(HealthServiceError):
	"""No ClinicalEncounter with the given id."""


class DiagnosisNotFoundError(HealthServiceError):
	"""No DiagnosisRecord with the given id."""


class PrescriptionNotFoundError(HealthServiceError):
	"""No Prescription with the given id."""


class LabResultNotFoundError(HealthServiceError):
	"""No LabResult with the given id."""


class EncounterNotActiveError(HealthServiceError):
	"""Operation requires encounter in IN_PROGRESS status."""


class DiagnosisConfirmedError(HealthServiceError):
	"""DiagnosisRecord is confirmed — mutation not allowed."""


class DuplicatePrimaryDiagnosisError(HealthServiceError):
	"""Encounter already has a PRIMARY diagnosis."""


class RefillLimitExceededError(HealthServiceError):
	"""Prescription refills_used would exceed refills_allowed."""


class DuplicatePatientNumberError(HealthServiceError):
	"""patient_number already exists for this tenant."""


# ---------------------------------------------------------------------------
# HealthService
# ---------------------------------------------------------------------------

class HealthService:
	"""Stateless service for Health Cloud operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Patient
	# ------------------------------------------------------------------

	def register_patient(
		self,
		*,
		tenant_id: str,
		party_id: str,
		patient_number: str,
		blood_type: str | None = None,
		insurance_member_id: str | None = None,
		insurance_plan: str | None = None,
		preferred_language: str | None = None,
		session: Any,
	) -> dict:
		"""Create a Patient record linked to a foundation.Party.

		Raises DuplicatePatientNumberError if patient_number exists for tenant.
		"""
		from pgappforge.plugins.erp.industry.health.models import Patient
		from pgappforge.plugins.erp.industry.health.events import (
			PatientRegisteredEvent, emit_event,
		)

		existing = session.execute(
			select(Patient).where(
				Patient.tenant_id == tenant_id,
				Patient.patient_number == patient_number,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicatePatientNumberError(
				f"patient_number {patient_number!r} already exists for tenant {tenant_id!r}"
			)

		patient = Patient(
			tenant_id=tenant_id,
			party_id=party_id,
			patient_number=patient_number,
			blood_type=blood_type,
			allergies=[],
			active_medications=[],
			insurance_member_id=insurance_member_id,
			insurance_plan=insurance_plan,
			preferred_language=preferred_language,
			advance_directive=False,
			organ_donor=False,
			interpreter_needed=False,
		)
		session.add(patient)
		session.flush()

		emit_event(
			PatientRegisteredEvent(
				aggregate_id=patient.id,
				aggregate_type="Patient",
				tenant_id=tenant_id,
				patient_id=patient.id,
				party_id=party_id,
				patient_number=patient_number,
			),
			session,
		)

		log.info("register_patient: created %r", patient_number)
		return {"patient_id": patient.id, "patient_number": patient_number}

	# ------------------------------------------------------------------
	# Encounter
	# ------------------------------------------------------------------

	def start_encounter(
		self,
		*,
		tenant_id: str,
		patient_id: str,
		encounter_type: str,
		provider_id: int | None = None,
		facility_id: str | None = None,
		chief_complaint: str | None = None,
		session: Any,
	) -> dict:
		"""Create a ClinicalEncounter in SCHEDULED status, then transition to IN_PROGRESS."""
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter, Patient
		from pgappforge.plugins.erp.industry.health.events import (
			EncounterStartedEvent, emit_event,
		)

		patient = session.get(Patient, patient_id)
		if patient is None:
			raise PatientNotFoundError(f"Patient {patient_id!r} not found")

		encounter = ClinicalEncounter(
			tenant_id=tenant_id,
			patient_id=patient_id,
			encounter_type=encounter_type,
			provider_id=provider_id,
			facility_id=facility_id,
			chief_complaint=chief_complaint,
			encounter_status="IN_PROGRESS",
		)
		session.add(encounter)
		session.flush()

		emit_event(
			EncounterStartedEvent(
				aggregate_id=encounter.id,
				aggregate_type="ClinicalEncounter",
				tenant_id=tenant_id,
				encounter_id=encounter.id,
				patient_id=patient_id,
				encounter_type=encounter_type,
				provider_id=str(provider_id) if provider_id else "",
			),
			session,
		)

		log.info(
			"start_encounter: %s encounter for patient %r",
			encounter_type, patient_id,
		)
		return {"encounter_id": encounter.id, "encounter_status": "IN_PROGRESS"}

	def discharge_patient(
		self,
		encounter_id: str,
		discharge_disposition: str,
		session: Any,
	) -> dict:
		"""Complete an encounter with discharge details."""
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter
		from pgappforge.plugins.erp.industry.health.events import (
			EncounterCompletedEvent, emit_event,
		)

		encounter = session.get(ClinicalEncounter, encounter_id)
		if encounter is None:
			raise EncounterNotFoundError(f"ClinicalEncounter {encounter_id!r} not found")
		if encounter.encounter_status != "IN_PROGRESS":
			raise EncounterNotActiveError(
				f"Encounter {encounter_id!r} is {encounter.encounter_status!r}, not IN_PROGRESS"
			)

		now = datetime.now(timezone.utc)
		encounter.encounter_status = "COMPLETED"
		encounter.discharge_date = now
		encounter.discharge_disposition = discharge_disposition

		emit_event(
			EncounterCompletedEvent(
				aggregate_id=encounter_id,
				aggregate_type="ClinicalEncounter",
				tenant_id=encounter.tenant_id,
				encounter_id=encounter_id,
				patient_id=encounter.patient_id,
				discharge_disposition=discharge_disposition,
			),
			session,
		)

		return {
			"encounter_id": encounter_id,
			"encounter_status": "COMPLETED",
			"discharge_date": now.isoformat(),
			"discharge_disposition": discharge_disposition,
		}

	# ------------------------------------------------------------------
	# Diagnosis
	# ------------------------------------------------------------------

	def add_diagnosis(
		self,
		*,
		tenant_id: str,
		encounter_id: str,
		icd10_code: str,
		diagnosis_description: str,
		diagnosis_type: str = "PRIMARY",
		session: Any,
	) -> dict:
		"""Add a DiagnosisRecord to an encounter.

		Enforces:
		  - Encounter must be IN_PROGRESS.
		  - Only one PRIMARY diagnosis per encounter.
		"""
		from pgappforge.plugins.erp.industry.health.models import (
			ClinicalEncounter, DiagnosisRecord,
		)

		encounter = session.get(ClinicalEncounter, encounter_id)
		if encounter is None:
			raise EncounterNotFoundError(f"ClinicalEncounter {encounter_id!r} not found")
		if encounter.encounter_status != "IN_PROGRESS":
			raise EncounterNotActiveError(
				f"Cannot add diagnosis to encounter in status {encounter.encounter_status!r}"
			)

		if diagnosis_type == "PRIMARY":
			existing_primary = session.execute(
				select(DiagnosisRecord).where(
					DiagnosisRecord.encounter_id == encounter_id,
					DiagnosisRecord.diagnosis_type == "PRIMARY",
				).limit(1)
			).scalar_one_or_none()
			if existing_primary is not None:
				raise DuplicatePrimaryDiagnosisError(
					f"Encounter {encounter_id!r} already has a PRIMARY diagnosis "
					f"(icd10={existing_primary.icd10_code!r})"
				)

		dx = DiagnosisRecord(
			tenant_id=tenant_id,
			encounter_id=encounter_id,
			icd10_code=icd10_code,
			diagnosis_description=diagnosis_description,
			diagnosis_type=diagnosis_type,
			confirmed=False,
		)
		session.add(dx)
		session.flush()

		log.info(
			"add_diagnosis: %s %r to encounter %r",
			diagnosis_type, icd10_code, encounter_id,
		)
		return {"diagnosis_id": dx.id, "icd10_code": icd10_code, "confirmed": False}

	def confirm_diagnosis(
		self,
		diagnosis_id: str,
		session: Any,
	) -> dict:
		"""Mark a DiagnosisRecord as confirmed by the attending clinician.

		Once confirmed, the record is functionally append-only.
		"""
		from pgappforge.plugins.erp.industry.health.models import DiagnosisRecord, ClinicalEncounter
		from pgappforge.plugins.erp.industry.health.events import (
			DiagnosisConfirmedEvent, emit_event,
		)

		dx = session.get(DiagnosisRecord, diagnosis_id)
		if dx is None:
			raise DiagnosisNotFoundError(f"DiagnosisRecord {diagnosis_id!r} not found")
		if dx.confirmed:
			raise DiagnosisConfirmedError(
				f"DiagnosisRecord {diagnosis_id!r} is already confirmed"
			)

		encounter = session.get(ClinicalEncounter, dx.encounter_id)
		dx.confirmed = True

		emit_event(
			DiagnosisConfirmedEvent(
				aggregate_id=diagnosis_id,
				aggregate_type="DiagnosisRecord",
				tenant_id=dx.tenant_id,
				diagnosis_id=diagnosis_id,
				encounter_id=dx.encounter_id,
				patient_id=encounter.patient_id if encounter else "",
				icd10_code=dx.icd10_code,
				diagnosis_type=dx.diagnosis_type,
			),
			session,
		)

		return {"diagnosis_id": diagnosis_id, "confirmed": True}

	# ------------------------------------------------------------------
	# Prescription
	# ------------------------------------------------------------------

	def issue_prescription(
		self,
		*,
		tenant_id: str,
		encounter_id: str,
		patient_id: str,
		ndc_code: str,
		drug_name: str,
		dosage: str,
		frequency: str,
		prescribed_by: int,
		duration_days: int | None = None,
		refills_allowed: int = 0,
		session: Any,
	) -> dict:
		"""Issue a new Prescription from an active encounter."""
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter, Prescription
		from pgappforge.plugins.erp.industry.health.events import (
			PrescriptionIssuedEvent, emit_event,
		)

		encounter = session.get(ClinicalEncounter, encounter_id)
		if encounter is None:
			raise EncounterNotFoundError(f"ClinicalEncounter {encounter_id!r} not found")

		rx = Prescription(
			tenant_id=tenant_id,
			encounter_id=encounter_id,
			patient_id=patient_id,
			ndc_code=ndc_code,
			drug_name=drug_name,
			dosage=dosage,
			frequency=frequency,
			duration_days=duration_days,
			prescribed_by=prescribed_by,
			refills_allowed=refills_allowed,
			refills_used=0,
			status="ACTIVE",
		)
		session.add(rx)
		session.flush()

		emit_event(
			PrescriptionIssuedEvent(
				aggregate_id=rx.id,
				aggregate_type="Prescription",
				tenant_id=tenant_id,
				prescription_id=rx.id,
				encounter_id=encounter_id,
				patient_id=patient_id,
				ndc_code=ndc_code,
				prescribed_by=str(prescribed_by),
			),
			session,
		)

		log.info("issue_prescription: ndc=%r for patient %r", ndc_code, patient_id)
		return {"prescription_id": rx.id, "ndc_code": ndc_code, "status": "ACTIVE"}

	def use_refill(self, prescription_id: str, session: Any) -> dict:
		"""Increment refills_used. Raises RefillLimitExceededError if at limit."""
		from pgappforge.plugins.erp.industry.health.models import Prescription

		rx = session.get(Prescription, prescription_id)
		if rx is None:
			raise PrescriptionNotFoundError(f"Prescription {prescription_id!r} not found")
		if rx.status != "ACTIVE":
			raise HealthServiceError(
				f"Prescription {prescription_id!r} is {rx.status!r} — cannot refill"
			)
		if rx.refills_used >= rx.refills_allowed:
			raise RefillLimitExceededError(
				f"Prescription {prescription_id!r} has used all {rx.refills_allowed} refill(s)"
			)

		rx.refills_used += 1
		if rx.refills_used >= rx.refills_allowed:
			rx.status = "COMPLETED"

		return {
			"prescription_id": prescription_id,
			"refills_used": rx.refills_used,
			"refills_allowed": rx.refills_allowed,
			"status": rx.status,
		}

	# ------------------------------------------------------------------
	# Lab results
	# ------------------------------------------------------------------

	def record_lab_result(
		self,
		lab_result_id: str,
		result_value: str,
		result_unit: str | None,
		reference_range: str | None,
		abnormal_flag: str | None,
		session: Any,
	) -> dict:
		"""Transition a LabResult from ORDERED/COLLECTED to RESULTED.

		Emits LabResultedEvent. Additionally emits LabCriticalValueEvent for
		HH/LL flags so downstream notification plugins can page the clinician.
		"""
		from pgappforge.plugins.erp.industry.health.models import LabResult, ClinicalEncounter
		from pgappforge.plugins.erp.industry.health.events import (
			LabResultedEvent, LabCriticalValueEvent, emit_event,
		)

		lab = session.get(LabResult, lab_result_id)
		if lab is None:
			raise LabResultNotFoundError(f"LabResult {lab_result_id!r} not found")
		if lab.status == "RESULTED":
			raise HealthServiceError(
				f"LabResult {lab_result_id!r} is already RESULTED"
			)

		now = datetime.now(timezone.utc)
		lab.result_value = result_value
		lab.result_unit = result_unit
		lab.reference_range = reference_range
		lab.abnormal_flag = abnormal_flag
		lab.resulted_at = now
		lab.status = "RESULTED"

		emit_event(
			LabResultedEvent(
				aggregate_id=lab_result_id,
				aggregate_type="LabResult",
				tenant_id=lab.tenant_id,
				lab_result_id=lab_result_id,
				patient_id=lab.patient_id,
				loinc_code=lab.loinc_code,
				abnormal_flag=abnormal_flag or "",
			),
			session,
		)

		if abnormal_flag in ("HH", "LL"):
			emit_event(
				LabCriticalValueEvent(
					aggregate_id=lab_result_id,
					aggregate_type="LabResult",
					tenant_id=lab.tenant_id,
					lab_result_id=lab_result_id,
					patient_id=lab.patient_id,
					loinc_code=lab.loinc_code,
					abnormal_flag=abnormal_flag,
					provider_id=str(lab.ordered_by) if lab.ordered_by else "",
				),
				session,
			)
			log.warning(
				"record_lab_result: CRITICAL value for patient %r loinc=%r flag=%r",
				lab.patient_id, lab.loinc_code, abnormal_flag,
			)

		return {
			"lab_result_id": lab_result_id,
			"status": "RESULTED",
			"abnormal_flag": abnormal_flag,
			"resulted_at": now.isoformat(),
		}

	# ------------------------------------------------------------------
	# Reports
	# ------------------------------------------------------------------

	def get_patient_clinical_summary(self, patient_id: str, session: Any) -> dict:
		"""Return full clinical profile: encounters, active Rx, pending labs."""
		from pgappforge.plugins.erp.industry.health.models import (
			Patient, ClinicalEncounter, Prescription, LabResult,
		)

		patient = session.get(Patient, patient_id)
		if patient is None:
			raise PatientNotFoundError(f"Patient {patient_id!r} not found")

		encounters = session.execute(
			select(ClinicalEncounter)
			.where(ClinicalEncounter.patient_id == patient_id)
			.order_by(ClinicalEncounter.encounter_date.desc())
			.limit(10)
		).scalars().all()

		active_rx = session.execute(
			select(Prescription).where(
				Prescription.patient_id == patient_id,
				Prescription.status == "ACTIVE",
			)
		).scalars().all()

		pending_labs = session.execute(
			select(LabResult).where(
				LabResult.patient_id == patient_id,
				LabResult.status.in_(["ORDERED", "COLLECTED"]),
			)
		).scalars().all()

		return {
			"patient_id": patient_id,
			"patient_number": patient.patient_number,
			"blood_type": patient.blood_type,
			"allergies": patient.allergies,
			"active_medications": patient.active_medications,
			"insurance_member_id": patient.insurance_member_id,
			"insurance_plan": patient.insurance_plan,
			"recent_encounters": [
				{
					"encounter_id": e.id,
					"encounter_type": e.encounter_type,
					"encounter_date": e.encounter_date.isoformat() if e.encounter_date else None,
					"encounter_status": e.encounter_status,
					"chief_complaint": e.chief_complaint,
				}
				for e in encounters
			],
			"active_prescriptions": [
				{
					"prescription_id": rx.id,
					"ndc_code": rx.ndc_code,
					"drug_name": rx.drug_name,
					"dosage": rx.dosage,
					"frequency": rx.frequency,
					"refills_remaining": rx.refills_allowed - rx.refills_used,
				}
				for rx in active_rx
			],
			"pending_lab_orders": [
				{
					"lab_result_id": lr.id,
					"loinc_code": lr.loinc_code,
					"test_name": lr.test_name,
					"ordered_at": lr.ordered_at.isoformat() if lr.ordered_at else None,
					"status": lr.status,
				}
				for lr in pending_labs
			],
		}

	def get_abnormal_lab_report(self, tenant_id: str, session: Any) -> list[dict]:
		"""Return all resulted labs with abnormal flags for the tenant."""
		from pgappforge.plugins.erp.industry.health.models import LabResult

		rows = session.execute(
			select(LabResult).where(
				LabResult.tenant_id == tenant_id,
				LabResult.status.in_(["RESULTED", "REVIEWED"]),
				LabResult.abnormal_flag.isnot(None),
				LabResult.abnormal_flag != "N",
			).order_by(LabResult.resulted_at.desc()).limit(500)
		).scalars().all()

		return [
			{
				"lab_result_id": lr.id,
				"patient_id": lr.patient_id,
				"loinc_code": lr.loinc_code,
				"test_name": lr.test_name,
				"result_value": lr.result_value,
				"result_unit": lr.result_unit,
				"reference_range": lr.reference_range,
				"abnormal_flag": lr.abnormal_flag,
				"resulted_at": lr.resulted_at.isoformat() if lr.resulted_at else None,
				"status": lr.status,
			}
			for lr in rows
		]


__all__ = [
	"HealthService",
	"HealthServiceError",
	"PatientNotFoundError",
	"EncounterNotFoundError",
	"DiagnosisNotFoundError",
	"PrescriptionNotFoundError",
	"LabResultNotFoundError",
	"EncounterNotActiveError",
	"DiagnosisConfirmedError",
	"DuplicatePrimaryDiagnosisError",
	"RefillLimitExceededError",
	"DuplicatePatientNumberError",
]
