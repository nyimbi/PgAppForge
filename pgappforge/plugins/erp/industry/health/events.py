"""
pgappforge/plugins/erp/industry/health/events.py

Domain events for the Health Cloud plugin.

Clinical data is PHI — event payloads carry only identifiers and status
codes, never raw clinical values, to limit PHI exposure in the event log.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Patient lifecycle
# ---------------------------------------------------------------------------

@dataclass
class PatientRegisteredEvent(DomainEvent):
	"""New patient record created."""
	event_type: str = "health.patient.registered"
	patient_id: str = ""
	party_id: str = ""
	patient_number: str = ""


@dataclass
class PatientUpdatedEvent(DomainEvent):
	"""Patient demographics or insurance updated."""
	event_type: str = "health.patient.updated"
	patient_id: str = ""
	patient_number: str = ""
	changed_fields: list = None

	def __post_init__(self):
		if self.changed_fields is None:
			self.changed_fields = []


# ---------------------------------------------------------------------------
# Encounter lifecycle
# ---------------------------------------------------------------------------

@dataclass
class EncounterStartedEvent(DomainEvent):
	"""Clinical encounter transitioned to IN_PROGRESS."""
	event_type: str = "health.encounter.started"
	encounter_id: str = ""
	patient_id: str = ""
	encounter_type: str = ""
	provider_id: str = ""


@dataclass
class EncounterCompletedEvent(DomainEvent):
	"""Encounter marked COMPLETED with discharge details."""
	event_type: str = "health.encounter.completed"
	encounter_id: str = ""
	patient_id: str = ""
	discharge_disposition: str = ""


# ---------------------------------------------------------------------------
# Clinical records
# ---------------------------------------------------------------------------

@dataclass
class DiagnosisConfirmedEvent(DomainEvent):
	"""Attending physician confirmed a DiagnosisRecord."""
	event_type: str = "health.diagnosis.confirmed"
	diagnosis_id: str = ""
	encounter_id: str = ""
	patient_id: str = ""
	icd10_code: str = ""
	diagnosis_type: str = ""


@dataclass
class PrescriptionIssuedEvent(DomainEvent):
	"""New prescription issued — PHI-safe: carries only IDs and NDC code."""
	event_type: str = "health.prescription.issued"
	prescription_id: str = ""
	encounter_id: str = ""
	patient_id: str = ""
	ndc_code: str = ""
	prescribed_by: str = ""


@dataclass
class PrescriptionDiscontinuedEvent(DomainEvent):
	"""Prescription status changed to DISCONTINUED."""
	event_type: str = "health.prescription.discontinued"
	prescription_id: str = ""
	patient_id: str = ""
	discontinued_by: str = ""


# ---------------------------------------------------------------------------
# Lab
# ---------------------------------------------------------------------------

@dataclass
class LabResultedEvent(DomainEvent):
	"""Lab result moved to RESULTED status — PHI-safe (no result_value)."""
	event_type: str = "health.lab.resulted"
	lab_result_id: str = ""
	patient_id: str = ""
	loinc_code: str = ""
	abnormal_flag: str = ""    # N | H | L | HH | LL | "" (empty = normal/pending)


@dataclass
class LabCriticalValueEvent(DomainEvent):
	"""Critical lab value (abnormal_flag in HH, LL) — triggers urgent notification."""
	event_type: str = "health.lab.critical_value"
	lab_result_id: str = ""
	patient_id: str = ""
	loinc_code: str = ""
	abnormal_flag: str = ""
	provider_id: str = ""       # Clinician to notify


__all__ = [
	"emit_event",
	"PatientRegisteredEvent",
	"PatientUpdatedEvent",
	"EncounterStartedEvent",
	"EncounterCompletedEvent",
	"DiagnosisConfirmedEvent",
	"PrescriptionIssuedEvent",
	"PrescriptionDiscontinuedEvent",
	"LabResultedEvent",
	"LabCriticalValueEvent",
]
