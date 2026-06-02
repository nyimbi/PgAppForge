"""
pgappforge/plugins/erp/industry/health/views.py

Flask views for the Health Cloud plugin.

Views:
  PatientView           — CRUD + clinical summary
  ClinicalEncounterView — CRUD + start / discharge actions
  DiagnosisView         — add + confirm
  PrescriptionView      — issue + refill
  LabResultView         — order + result (with critical-value path)
  HealthReportView      — 3 reports: Patient Summary, Abnormal Labs,
                          Encounter Volume
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.health.services import HealthService
	return HealthService()


# ---------------------------------------------------------------------------
# PatientView
# ---------------------------------------------------------------------------

class PatientView(BaseView):
	"""Patient CRUD.

	GET  /health/patients/         — list
	GET  /health/patients/<id>     — detail
	POST /health/patients/         — register patient
	"""

	route_base = "/health/patients"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.health.models import Patient
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(Patient).order_by(Patient.patient_number)
		if tenant_id:
			q = q.where(Patient.tenant_id == tenant_id)
		patients = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"patient_number": p.patient_number,
				"blood_type": p.blood_type,
				"insurance_plan": p.insurance_plan,
				"preferred_language": p.preferred_language,
				"interpreter_needed": p.interpreter_needed,
			}
			for p in patients
		])

	@expose("/<string:patient_id>")
	@has_access
	def detail(self, patient_id: str):
		from pgappforge.plugins.erp.industry.health.models import Patient
		session = _get_session()
		patient = session.get(Patient, patient_id)
		if patient is None:
			abort(404)
		return jsonify({
			"id": patient.id,
			"tenant_id": patient.tenant_id,
			"party_id": patient.party_id,
			"patient_number": patient.patient_number,
			"blood_type": patient.blood_type,
			# PHI fields returned — caller must enforce access control
			"allergies": patient.allergies,
			"active_medications": patient.active_medications,
			"primary_care_provider_id": patient.primary_care_provider_id,
			"insurance_member_id": patient.insurance_member_id,
			"insurance_plan": patient.insurance_plan,
			"advance_directive": patient.advance_directive,
			"organ_donor": patient.organ_donor,
			"preferred_language": patient.preferred_language,
			"interpreter_needed": patient.interpreter_needed,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "party_id", "patient_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			result = _svc().register_patient(
				tenant_id=data["tenant_id"],
				party_id=data["party_id"],
				patient_number=data["patient_number"],
				blood_type=data.get("blood_type"),
				insurance_member_id=data.get("insurance_member_id"),
				insurance_plan=data.get("insurance_plan"),
				preferred_language=data.get("preferred_language"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ClinicalEncounterView
# ---------------------------------------------------------------------------

class ClinicalEncounterView(BaseView):
	"""Clinical encounter workflow.

	GET  /health/encounters/                  — list (filterable by patient)
	POST /health/encounters/                  — start encounter
	GET  /health/encounters/<id>              — detail with diagnoses/procedures
	POST /health/encounters/<id>/discharge    — discharge patient
	"""

	route_base = "/health/encounters"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter
		session = _get_session()
		patient_id = request.args.get("patient_id")
		q = (
			sa.select(ClinicalEncounter)
			.order_by(ClinicalEncounter.encounter_date.desc())
			.limit(200)
		)
		if patient_id:
			q = q.where(ClinicalEncounter.patient_id == patient_id)
		encounters = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": e.id,
				"patient_id": e.patient_id,
				"encounter_type": e.encounter_type,
				"encounter_date": e.encounter_date.isoformat() if e.encounter_date else None,
				"encounter_status": e.encounter_status,
				"chief_complaint": e.chief_complaint,
			}
			for e in encounters
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "patient_id", "encounter_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().start_encounter(
				tenant_id=data["tenant_id"],
				patient_id=data["patient_id"],
				encounter_type=data["encounter_type"],
				provider_id=data.get("provider_id"),
				facility_id=data.get("facility_id"),
				chief_complaint=data.get("chief_complaint"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:encounter_id>")
	@has_access
	def detail(self, encounter_id: str):
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter
		session = _get_session()
		enc = session.get(ClinicalEncounter, encounter_id)
		if enc is None:
			abort(404)
		return jsonify({
			"id": enc.id,
			"patient_id": enc.patient_id,
			"encounter_type": enc.encounter_type,
			"encounter_date": enc.encounter_date.isoformat() if enc.encounter_date else None,
			"provider_id": enc.provider_id,
			"facility_id": enc.facility_id,
			"chief_complaint": enc.chief_complaint,
			"encounter_status": enc.encounter_status,
			"discharge_date": enc.discharge_date.isoformat() if enc.discharge_date else None,
			"discharge_disposition": enc.discharge_disposition,
			"diagnoses": [
				{
					"id": d.id,
					"icd10_code": d.icd10_code,
					"diagnosis_description": d.diagnosis_description,
					"diagnosis_type": d.diagnosis_type,
					"confirmed": d.confirmed,
					"noted_at": d.noted_at.isoformat() if d.noted_at else None,
				}
				for d in enc.diagnoses
			],
			"procedures": [
				{
					"id": p.id,
					"cpt_code": p.cpt_code,
					"procedure_name": p.procedure_name,
					"performed_at": p.performed_at.isoformat() if p.performed_at else None,
				}
				for p in enc.procedures
			],
		})

	@expose("/<string:encounter_id>/discharge", methods=["POST"])
	@has_access
	def discharge(self, encounter_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("discharge_disposition"):
			return jsonify({"error": "discharge_disposition required"}), 400
		try:
			result = _svc().discharge_patient(
				encounter_id, data["discharge_disposition"], session
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# DiagnosisView
# ---------------------------------------------------------------------------

class DiagnosisView(BaseView):
	"""Diagnosis management.

	POST /health/diagnoses/                  — add diagnosis to encounter
	POST /health/diagnoses/<id>/confirm      — clinician confirms diagnosis
	"""

	route_base = "/health/diagnoses"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		"""List diagnoses — filterable by encounter_id or icd10_code."""
		from pgappforge.plugins.erp.industry.health.models import DiagnosisRecord
		session = _get_session()
		q = sa.select(DiagnosisRecord).order_by(DiagnosisRecord.noted_at.desc()).limit(500)
		if request.args.get("encounter_id"):
			q = q.where(DiagnosisRecord.encounter_id == request.args["encounter_id"])
		if request.args.get("icd10_code"):
			q = q.where(DiagnosisRecord.icd10_code == request.args["icd10_code"])
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"encounter_id": d.encounter_id,
				"icd10_code": d.icd10_code,
				"diagnosis_description": d.diagnosis_description,
				"diagnosis_type": d.diagnosis_type,
				"confirmed": d.confirmed,
			}
			for d in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "encounter_id", "icd10_code", "diagnosis_description")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().add_diagnosis(
				tenant_id=data["tenant_id"],
				encounter_id=data["encounter_id"],
				icd10_code=data["icd10_code"],
				diagnosis_description=data["diagnosis_description"],
				diagnosis_type=data.get("diagnosis_type", "PRIMARY"),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:diagnosis_id>/confirm", methods=["POST"])
	@has_access
	def confirm(self, diagnosis_id: str):
		session = _get_session()
		try:
			result = _svc().confirm_diagnosis(diagnosis_id, session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# PrescriptionView
# ---------------------------------------------------------------------------

class PrescriptionView(BaseView):
	"""Prescription management.

	POST /health/prescriptions/              — issue prescription
	GET  /health/prescriptions/<id>         — detail
	POST /health/prescriptions/<id>/refill  — consume one refill
	"""

	route_base = "/health/prescriptions"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.health.models import Prescription
		session = _get_session()
		q = sa.select(Prescription).order_by(Prescription.prescribed_at.desc()).limit(200)
		if request.args.get("patient_id"):
			q = q.where(Prescription.patient_id == request.args["patient_id"])
		if request.args.get("status"):
			q = q.where(Prescription.status == request.args["status"])
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": rx.id,
				"patient_id": rx.patient_id,
				"ndc_code": rx.ndc_code,
				"drug_name": rx.drug_name,
				"dosage": rx.dosage,
				"frequency": rx.frequency,
				"refills_allowed": rx.refills_allowed,
				"refills_used": rx.refills_used,
				"status": rx.status,
			}
			for rx in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = (
			"tenant_id", "encounter_id", "patient_id",
			"ndc_code", "drug_name", "dosage", "frequency", "prescribed_by",
		)
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().issue_prescription(
				tenant_id=data["tenant_id"],
				encounter_id=data["encounter_id"],
				patient_id=data["patient_id"],
				ndc_code=data["ndc_code"],
				drug_name=data["drug_name"],
				dosage=data["dosage"],
				frequency=data["frequency"],
				prescribed_by=int(data["prescribed_by"]),
				duration_days=data.get("duration_days"),
				refills_allowed=int(data.get("refills_allowed", 0)),
				session=session,
			)
			session.commit()
			return jsonify(result), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:prescription_id>/refill", methods=["POST"])
	@has_access
	def refill(self, prescription_id: str):
		session = _get_session()
		try:
			result = _svc().use_refill(prescription_id, session)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# LabResultView
# ---------------------------------------------------------------------------

class LabResultView(BaseView):
	"""Lab result management.

	POST /health/labs/               — order lab test
	GET  /health/labs/<id>           — detail
	POST /health/labs/<id>/result    — record result (transitions to RESULTED)
	POST /health/labs/<id>/review    — mark as REVIEWED by clinician
	"""

	route_base = "/health/labs"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.health.models import LabResult
		session = _get_session()
		q = sa.select(LabResult).order_by(LabResult.ordered_at.desc()).limit(200)
		if request.args.get("patient_id"):
			q = q.where(LabResult.patient_id == request.args["patient_id"])
		if request.args.get("status"):
			q = q.where(LabResult.status == request.args["status"])
		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": lr.id,
				"patient_id": lr.patient_id,
				"loinc_code": lr.loinc_code,
				"test_name": lr.test_name,
				"status": lr.status,
				"abnormal_flag": lr.abnormal_flag,
				"ordered_at": lr.ordered_at.isoformat() if lr.ordered_at else None,
			}
			for lr in rows
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Order a lab test (status=ORDERED)."""
		from pgappforge.plugins.erp.industry.health.models import LabResult
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "patient_id", "loinc_code", "test_name")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		lab = LabResult(
			tenant_id=data["tenant_id"],
			patient_id=data["patient_id"],
			ordered_by=data.get("ordered_by"),
			loinc_code=data["loinc_code"],
			test_name=data["test_name"],
			specimen_type=data.get("specimen_type"),
			status="ORDERED",
		)
		session.add(lab)
		session.commit()
		return jsonify({"lab_result_id": lab.id, "status": "ORDERED"}), 201

	@expose("/<string:lab_result_id>")
	@has_access
	def detail(self, lab_result_id: str):
		from pgappforge.plugins.erp.industry.health.models import LabResult
		session = _get_session()
		lab = session.get(LabResult, lab_result_id)
		if lab is None:
			abort(404)
		return jsonify({
			"id": lab.id,
			"patient_id": lab.patient_id,
			"ordered_by": lab.ordered_by,
			"ordered_at": lab.ordered_at.isoformat() if lab.ordered_at else None,
			"loinc_code": lab.loinc_code,
			"test_name": lab.test_name,
			"specimen_type": lab.specimen_type,
			"result_value": lab.result_value,
			"result_unit": lab.result_unit,
			"reference_range": lab.reference_range,
			"abnormal_flag": lab.abnormal_flag,
			"resulted_at": lab.resulted_at.isoformat() if lab.resulted_at else None,
			"status": lab.status,
		})

	@expose("/<string:lab_result_id>/result", methods=["POST"])
	@has_access
	def record_result(self, lab_result_id: str):
		"""Post result values and transition to RESULTED."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if "result_value" not in data:
			return jsonify({"error": "result_value required"}), 400
		try:
			result = _svc().record_lab_result(
				lab_result_id=lab_result_id,
				result_value=data["result_value"],
				result_unit=data.get("result_unit"),
				reference_range=data.get("reference_range"),
				abnormal_flag=data.get("abnormal_flag"),
				session=session,
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:lab_result_id>/review", methods=["POST"])
	@has_access
	def review(self, lab_result_id: str):
		"""Mark lab result as REVIEWED by a clinician."""
		from pgappforge.plugins.erp.industry.health.models import LabResult
		session = _get_session()
		lab = session.get(LabResult, lab_result_id)
		if lab is None:
			abort(404)
		if lab.status != "RESULTED":
			return jsonify({"error": f"LabResult is {lab.status!r}, not RESULTED"}), 422
		lab.status = "REVIEWED"
		session.commit()
		return jsonify({"lab_result_id": lab_result_id, "status": "REVIEWED"})


# ---------------------------------------------------------------------------
# HealthReportView
# ---------------------------------------------------------------------------

class HealthReportView(BaseView):
	"""Canned Health Cloud reports.

	GET /health/reports/                             — index
	GET /health/reports/patient-summary/<patient_id> — clinical profile
	GET /health/reports/abnormal-labs                — all abnormal results
	GET /health/reports/encounter-volume             — encounter count by type/status
	"""

	route_base = "/health/reports"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"reports": [
				{
					"name": "Patient Clinical Summary",
					"endpoint": "/health/reports/patient-summary/<patient_id>",
				},
				{
					"name": "Abnormal Lab Results",
					"endpoint": "/health/reports/abnormal-labs?tenant_id=<id>",
				},
				{
					"name": "Encounter Volume",
					"endpoint": "/health/reports/encounter-volume?tenant_id=<id>",
				},
			]
		})

	@expose("/patient-summary/<string:patient_id>")
	@has_access
	def patient_summary(self, patient_id: str):
		session = _get_session()
		try:
			result = _svc().get_patient_clinical_summary(patient_id, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/abnormal-labs")
	@has_access
	def abnormal_labs(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id required"}), 400
		rows = _svc().get_abnormal_lab_report(tenant_id, session)
		return jsonify({
			"tenant_id": tenant_id,
			"count": len(rows),
			"results": rows,
		})

	@expose("/encounter-volume")
	@has_access
	def encounter_volume(self):
		"""Encounter count grouped by type and status."""
		from pgappforge.plugins.erp.industry.health.models import ClinicalEncounter
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				ClinicalEncounter.encounter_type,
				ClinicalEncounter.encounter_status,
				sa.func.count(ClinicalEncounter.id).label("count"),
			)
			.group_by(
				ClinicalEncounter.encounter_type,
				ClinicalEncounter.encounter_status,
			)
			.order_by(ClinicalEncounter.encounter_type)
		)
		if tenant_id:
			q = q.where(ClinicalEncounter.tenant_id == tenant_id)

		rows = session.execute(q).all()
		return jsonify({
			"tenant_id": tenant_id,
			"encounter_volume": [
				{
					"encounter_type": r.encounter_type,
					"encounter_status": r.encounter_status,
					"count": r.count,
				}
				for r in rows
			],
		})


__all__ = [
	"PatientView",
	"ClinicalEncounterView",
	"DiagnosisView",
	"PrescriptionView",
	"LabResultView",
	"HealthReportView",
]
