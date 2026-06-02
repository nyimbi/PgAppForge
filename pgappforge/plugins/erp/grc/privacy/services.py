"""
pgappforge/plugins/erp/grc/privacy/services.py

PrivacyService — stateless service for GDPR / Privacy domain.

Responsibilities:
  - Consent lifecycle (grant, withdraw, check active consent)
  - DSR creation, status transitions, overdue detection
  - Data processing record management
  - Automated DSR number generation (DSR-YYYYMM-NNNNN)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)

# GDPR regulatory deadline: 30 days for most DSR types
DSR_DEADLINE_DAYS = 30


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PrivacyServiceError(Exception):
	"""Base error for Privacy domain violations."""


class ConsentNotFoundError(PrivacyServiceError):
	"""No active ConsentRecord for the given party + purpose."""


class DSRNotFoundError(PrivacyServiceError):
	"""No DataSubjectRequest with the given id."""


class DSRStatusError(PrivacyServiceError):
	"""Illegal DSR status transition."""


class ProcessingRecordNotFoundError(PrivacyServiceError):
	"""No DataProcessingRecord with the given id."""


# ---------------------------------------------------------------------------
# PrivacyService
# ---------------------------------------------------------------------------

class PrivacyService:
	"""Stateless GDPR privacy service."""

	VALID_LEGAL_BASES = frozenset({
		"CONSENT",
		"CONTRACT",
		"LEGAL_OBLIGATION",
		"VITAL_INTERESTS",
		"PUBLIC_TASK",
		"LEGITIMATE_INTERESTS",
	})

	VALID_DSR_TYPES = frozenset({
		"ACCESS",
		"ERASURE",
		"RECTIFICATION",
		"PORTABILITY",
		"RESTRICTION",
		"OBJECTION",
	})

	DSR_STATUS_TRANSITIONS: dict[str, set[str]] = {
		"RECEIVED": {"VERIFIED", "REJECTED"},
		"VERIFIED": {"IN_PROGRESS", "REJECTED"},
		"IN_PROGRESS": {"COMPLETED", "REJECTED"},
		"COMPLETED": set(),
		"REJECTED": set(),
	}

	# ------------------------------------------------------------------
	# Consent
	# ------------------------------------------------------------------

	def grant_consent(
		self,
		session: Any,
		tenant_id: str,
		party_id: str,
		purpose: str,
		legal_basis: str,
		source: str | None = None,
		version: str | None = None,
		ip_address: str | None = None,
		expires_at: datetime | None = None,
	) -> dict:
		"""Record a new consent grant.  APPEND-ONLY."""
		from pgappforge.plugins.erp.grc.privacy.models import ConsentRecord
		from pgappforge.plugins.erp.grc.privacy.events import ConsentGrantedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if legal_basis not in self.VALID_LEGAL_BASES:
			raise PrivacyServiceError(
				f"legal_basis must be one of {self.VALID_LEGAL_BASES}"
			)

		now = datetime.now(timezone.utc)
		record = ConsentRecord(
			tenant_id=tenant_id,
			party_id=party_id,
			purpose=purpose,
			legal_basis=legal_basis,
			granted_at=now,
			source=source,
			version=version,
			ip_address=ip_address,
			expires_at=expires_at,
		)
		session.add(record)
		session.flush()

		emit_event(
			ConsentGrantedEvent(
				aggregate_id=record.id,
				aggregate_type="ConsentRecord",
				tenant_id=tenant_id,
				consent_id=record.id,
				party_id=party_id,
				purpose=purpose,
				legal_basis=legal_basis,
				source=source or "",
			),
			session,
		)
		log.info(
			"PrivacyService: consent granted party=%r purpose=%r basis=%r",
			party_id, purpose, legal_basis,
		)
		return {"consent_id": record.id, "status": "granted"}

	def withdraw_consent(
		self,
		session: Any,
		tenant_id: str,
		party_id: str,
		purpose: str,
		ip_address: str | None = None,
	) -> dict:
		"""Record consent withdrawal.  Inserts a new ConsentRecord with withdrawn_at set.

		The original record is NOT modified (append-only ledger).
		"""
		from pgappforge.plugins.erp.grc.privacy.models import ConsentRecord
		from pgappforge.plugins.erp.grc.privacy.events import ConsentWithdrawnEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		now = datetime.now(timezone.utc)
		withdrawal = ConsentRecord(
			tenant_id=tenant_id,
			party_id=party_id,
			purpose=purpose,
			legal_basis="CONSENT",
			granted_at=now,
			withdrawn_at=now,
			source="WITHDRAWAL",
			ip_address=ip_address,
		)
		session.add(withdrawal)
		session.flush()

		emit_event(
			ConsentWithdrawnEvent(
				aggregate_id=withdrawal.id,
				aggregate_type="ConsentRecord",
				tenant_id=tenant_id,
				consent_id=withdrawal.id,
				party_id=party_id,
				purpose=purpose,
				withdrawn_at=now.isoformat(),
			),
			session,
		)
		return {"consent_id": withdrawal.id, "status": "withdrawn"}

	def is_consent_active(
		self,
		session: Any,
		tenant_id: str,
		party_id: str,
		purpose: str,
	) -> bool:
		"""Check if valid consent exists for a party and purpose.

		Active = granted and not withdrawn and not expired.
		"""
		from pgappforge.plugins.erp.grc.privacy.models import ConsentRecord
		now = datetime.now(timezone.utc)

		# Most recent record for this party+purpose
		latest = session.execute(
			select(ConsentRecord)
			.where(
				ConsentRecord.tenant_id == tenant_id,
				ConsentRecord.party_id == party_id,
				ConsentRecord.purpose == purpose,
			)
			.order_by(ConsentRecord.granted_at.desc())
			.limit(1)
		).scalar_one_or_none()

		if latest is None:
			return False
		if latest.withdrawn_at is not None:
			return False
		if latest.expires_at is not None and latest.expires_at < now:
			return False
		return True

	# ------------------------------------------------------------------
	# Data Subject Requests
	# ------------------------------------------------------------------

	def _generate_dsr_number(self, session: Any) -> str:
		"""Generate a unique DSR number: DSR-YYYYMM-NNNNN."""
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		now = datetime.now(timezone.utc)
		prefix = f"DSR-{now.strftime('%Y%m')}-"
		count = session.execute(
			select(func.count()).where(
				DataSubjectRequest.dsr_number.like(f"{prefix}%")
			)
		).scalar_one()
		return f"{prefix}{count + 1:05d}"

	def create_dsr(
		self,
		session: Any,
		tenant_id: str,
		party_id: str,
		request_type: str,
		notes: str | None = None,
		deadline_days: int = DSR_DEADLINE_DAYS,
	) -> dict:
		"""Create a Data Subject Request and emit DSRReceivedEvent."""
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		from pgappforge.plugins.erp.grc.privacy.events import DSRReceivedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if request_type not in self.VALID_DSR_TYPES:
			raise PrivacyServiceError(
				f"request_type must be one of {self.VALID_DSR_TYPES}"
			)

		now = datetime.now(timezone.utc)
		due_at = now + timedelta(days=deadline_days)
		dsr_number = self._generate_dsr_number(session)

		dsr = DataSubjectRequest(
			tenant_id=tenant_id,
			dsr_number=dsr_number,
			party_id=party_id,
			request_type=request_type,
			status="RECEIVED",
			received_at=now,
			due_at=due_at,
			notes=notes,
		)
		session.add(dsr)
		session.flush()

		emit_event(
			DSRReceivedEvent(
				aggregate_id=dsr.id,
				aggregate_type="DataSubjectRequest",
				tenant_id=tenant_id,
				dsr_id=dsr.id,
				dsr_number=dsr_number,
				party_id=party_id,
				request_type=request_type,
				due_at=due_at.isoformat(),
			),
			session,
		)
		log.info(
			"PrivacyService: DSR created %r type=%r due=%s",
			dsr_number, request_type, due_at.date(),
		)
		return {
			"dsr_id": dsr.id,
			"dsr_number": dsr_number,
			"due_at": due_at.isoformat(),
			"status": "RECEIVED",
		}

	def transition_dsr(
		self,
		session: Any,
		dsr_id: str,
		new_status: str,
		response_url: str | None = None,
		notes: str | None = None,
	) -> dict:
		"""Transition a DSR to a new status.

		Valid transitions enforced by DSR_STATUS_TRANSITIONS.
		Emits DSRCompletedEvent on COMPLETED transition.
		"""
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		from pgappforge.plugins.erp.grc.privacy.events import DSRCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		dsr = session.get(DataSubjectRequest, dsr_id)
		if dsr is None:
			raise DSRNotFoundError(f"DataSubjectRequest {dsr_id!r} not found")

		allowed = self.DSR_STATUS_TRANSITIONS.get(dsr.status, set())
		if new_status not in allowed:
			raise DSRStatusError(
				f"Cannot transition DSR from {dsr.status!r} to {new_status!r}. "
				f"Allowed: {allowed}"
			)

		old_status = dsr.status
		dsr.status = new_status
		if notes:
			dsr.notes = (dsr.notes or "") + f"\n[{new_status}] {notes}"
		if response_url:
			dsr.response_url = response_url
		if new_status == "COMPLETED":
			dsr.completed_at = datetime.now(timezone.utc)
			emit_event(
				DSRCompletedEvent(
					aggregate_id=dsr_id,
					aggregate_type="DataSubjectRequest",
					tenant_id=str(dsr.tenant_id),
					dsr_id=dsr_id,
					dsr_number=dsr.dsr_number,
					party_id=str(dsr.party_id),
					request_type=dsr.request_type,
					response_url=response_url or "",
				),
				session,
			)

		log.info(
			"PrivacyService: DSR %r transitioned %r → %r",
			dsr.dsr_number, old_status, new_status,
		)
		return {
			"dsr_id": dsr_id,
			"dsr_number": dsr.dsr_number,
			"old_status": old_status,
			"new_status": new_status,
		}

	def get_overdue_dsrs(
		self, session: Any, tenant_id: str
	) -> list[dict]:
		"""Return all DSRs past their due_at that are not COMPLETED or REJECTED."""
		from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
		now = datetime.now(timezone.utc)

		rows = session.execute(
			select(DataSubjectRequest).where(
				DataSubjectRequest.tenant_id == tenant_id,
				DataSubjectRequest.due_at < now,
				DataSubjectRequest.status.notin_(["COMPLETED", "REJECTED"]),
			).order_by(DataSubjectRequest.due_at)
		).scalars().all()

		return [
			{
				"dsr_id": r.id,
				"dsr_number": r.dsr_number,
				"party_id": str(r.party_id),
				"request_type": r.request_type,
				"status": r.status,
				"due_at": r.due_at.isoformat(),
				"days_overdue": (now - r.due_at).days,
			}
			for r in rows
		]

	# ------------------------------------------------------------------
	# Data Processing Records
	# ------------------------------------------------------------------

	def create_processing_record(
		self,
		session: Any,
		tenant_id: str,
		processing_purpose: str,
		data_categories: list[str],
		data_subjects_description: str,
		legal_basis: str,
		controller_name: str,
		retention_period_days: int,
		recipients: list[dict] | None = None,
		processor_name: str | None = None,
		is_cross_border: bool = False,
		safeguards: list[dict] | None = None,
	) -> dict:
		"""Create an Article 30 data processing record."""
		from pgappforge.plugins.erp.grc.privacy.models import DataProcessingRecord

		if legal_basis not in self.VALID_LEGAL_BASES:
			raise PrivacyServiceError(
				f"legal_basis must be one of {self.VALID_LEGAL_BASES}"
			)

		record = DataProcessingRecord(
			tenant_id=tenant_id,
			processing_purpose=processing_purpose,
			data_categories=data_categories,
			data_subjects_description=data_subjects_description,
			legal_basis=legal_basis,
			controller_name=controller_name,
			retention_period_days=retention_period_days,
			recipients=recipients or [],
			processor_name=processor_name,
			is_cross_border=is_cross_border,
			safeguards=safeguards or [],
		)
		session.add(record)
		session.flush()
		log.info(
			"PrivacyService: processing record created purpose=%r",
			processing_purpose,
		)
		return {"record_id": record.id, "status": "created"}

	def get_processing_records(
		self,
		session: Any,
		tenant_id: str,
		is_cross_border: bool | None = None,
	) -> list[dict]:
		"""List data processing records with optional cross-border filter."""
		from pgappforge.plugins.erp.grc.privacy.models import DataProcessingRecord

		q = select(DataProcessingRecord).where(
			DataProcessingRecord.tenant_id == tenant_id
		).order_by(DataProcessingRecord.processing_purpose)

		if is_cross_border is not None:
			q = q.where(DataProcessingRecord.is_cross_border == is_cross_border)

		rows = session.execute(q).scalars().all()
		return [
			{
				"id": r.id,
				"processing_purpose": r.processing_purpose,
				"data_categories": r.data_categories,
				"legal_basis": r.legal_basis,
				"controller_name": r.controller_name,
				"retention_period_days": r.retention_period_days,
				"is_cross_border": r.is_cross_border,
				"processor_name": r.processor_name,
			}
			for r in rows
		]


__all__ = [
	"PrivacyService",
	"PrivacyServiceError",
	"ConsentNotFoundError",
	"DSRNotFoundError",
	"DSRStatusError",
	"ProcessingRecordNotFoundError",
]
