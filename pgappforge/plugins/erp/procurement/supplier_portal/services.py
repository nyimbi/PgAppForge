"""
pgappforge/plugins/erp/procurement/supplier_portal/services.py

SupplierPortalService — stateless business logic for the Supplier Portal plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Performance composite formula:
  composite = 0.4 * on_time_delivery_pct
            + 0.3 * quality_acceptance_pct
            + 0.2 * invoice_accuracy_pct
            + 0.1 * responsiveness_score

overall_score on SupplierProfile is a rolling average of all SupplierPerformanceCard.composite_score
values for that supplier (updated on every rate_supplier() call).

Status transitions:
  register_supplier    → kyc_status = PENDING
  approve_kyc          → PENDING → APPROVED
  suspend_supplier     → APPROVED → SUSPENDED

BPM registrations:
  procurement.supplier_portal.approve_kyc
  procurement.supplier_portal.rate

Public API:
  register_supplier(company_name, country_code, contact_email, tenant_id, session, ...) -> SupplierProfile
  submit_kyc_documents(supplier_id, documents, session)                                 -> SupplierProfile
  approve_kyc(supplier_id, approver_id, session)                                        -> SupplierProfile
  verify_bank_details(supplier_id, bank_name, account_number, swift, session, ...)      -> SupplierProfile
  rate_supplier(supplier_id, period, on_time_pct, quality_pct, invoice_pct, ...)        -> SupplierPerformanceCard
  suspend_supplier(supplier_id, reason, session)                                        -> SupplierProfile
  get_approved_suppliers(tenant_id, session, *, category=None)                          -> list[SupplierProfile]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SupplierPortalServiceError(Exception):
	"""Base domain error for Supplier Portal operations."""


class SupplierNotFoundError(SupplierPortalServiceError):
	pass


class InvalidStatusTransitionError(SupplierPortalServiceError):
	pass


class PerformanceCardNotFoundError(SupplierPortalServiceError):
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:  # noqa: BLE001
		log.debug("Event emission skipped: %s", exc)


def _generate_supplier_ref(session: Any, tenant_id: str) -> str:
	from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
	today_str = _now_utc().strftime("%Y%m%d")
	prefix = f"SUP-{today_str}-"
	stmt = (
		sa.select(sa.func.count(SupplierProfile.id))
		.where(
			SupplierProfile.tenant_id == tenant_id,
			SupplierProfile.supplier_ref.like(f"{prefix}%"),
		)
	)
	count = int(session.execute(stmt).scalar() or 0)
	return f"{prefix}{count + 1:05d}"


def _compute_overall_score(supplier_id: str, session: Any) -> Decimal:
	"""Rolling average composite_score across all SupplierPerformanceCard rows."""
	from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierPerformanceCard
	stmt = sa.select(
		sa.func.avg(SupplierPerformanceCard.composite_score)
	).where(SupplierPerformanceCard.supplier_id == supplier_id)
	avg = session.execute(stmt).scalar()
	if avg is None:
		return _dec(0)
	return _dec(avg).quantize(_dec("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# SupplierPortalService
# ---------------------------------------------------------------------------

class SupplierPortalService:
	"""Stateless service — all methods are classmethods; instantiation optional."""

	# ------------------------------------------------------------------
	# 1. register_supplier
	# ------------------------------------------------------------------

	@classmethod
	def register_supplier(
		cls,
		company_name: str,
		country_code: str,
		contact_email: str,
		tenant_id: str,
		session: Any,
		*,
		tax_id: str | None = None,
		company_reg_number: str | None = None,
		contact_phone: str | None = None,
		primary_category: str | None = None,
	) -> Any:
		"""Create a new SupplierProfile in PENDING KYC status.

		Generates supplier_ref automatically.
		Emits SupplierRegisteredEvent.
		Returns the persisted SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierProfile, PRIMARY_CATEGORIES,
		)
		from pgappforge.plugins.erp.procurement.supplier_portal.events import SupplierRegisteredEvent

		if not company_name.strip():
			raise SupplierPortalServiceError("company_name cannot be empty")
		if not contact_email.strip():
			raise SupplierPortalServiceError("contact_email cannot be empty")
		if not country_code.strip():
			raise SupplierPortalServiceError("country_code cannot be empty")
		if primary_category and primary_category not in PRIMARY_CATEGORIES:
			raise SupplierPortalServiceError(
				f"Invalid primary_category {primary_category!r}. Choose from {PRIMARY_CATEGORIES}"
			)

		ref = _generate_supplier_ref(session, tenant_id)

		supplier = SupplierProfile(
			tenant_id=tenant_id,
			company_name=company_name.strip(),
			supplier_ref=ref,
			company_reg_number=company_reg_number,
			tax_id=tax_id,
			country_code=country_code.upper().strip(),
			contact_email=contact_email.strip().lower(),
			contact_phone=contact_phone,
			primary_category=primary_category,
			kyc_status="PENDING",
			kyc_documents=[],
			bank_verified=False,
			is_preferred=False,
		)
		session.add(supplier)
		session.flush()

		_emit(
			SupplierRegisteredEvent(
				aggregate_id=supplier.id,
				aggregate_type="SupplierProfile",
				tenant_id=tenant_id,
				supplier_id=supplier.id,
				company_name=supplier.company_name,
			),
			session,
		)

		log.info("Supplier registered: %s (%s) tenant=%s", ref, company_name, tenant_id)
		return supplier

	# ------------------------------------------------------------------
	# 2. submit_kyc_documents
	# ------------------------------------------------------------------

	@classmethod
	def submit_kyc_documents(
		cls,
		supplier_id: str,
		documents: list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Append KYC documents to a supplier profile.

		documents is a list of {doc_type, url, uploaded_at} dicts.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile

		supplier = session.get(SupplierProfile, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		existing: list[dict] = list(supplier.kyc_documents or [])
		now_str = _now_utc().isoformat()
		for doc in documents:
			doc_entry = {
				"doc_type": doc.get("doc_type", "OTHER"),
				"url": doc.get("url", ""),
				"uploaded_at": doc.get("uploaded_at", now_str),
			}
			existing.append(doc_entry)

		supplier.kyc_documents = existing
		session.flush()

		log.debug(
			"KYC documents added to supplier %s: %d new docs",
			supplier_id, len(documents),
		)
		return supplier

	# ------------------------------------------------------------------
	# 3. approve_kyc
	# ------------------------------------------------------------------

	@classmethod
	def approve_kyc(
		cls,
		supplier_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Transition supplier KYC from PENDING → APPROVED.

		Sets kyc_approved_by and kyc_approved_at.
		Emits KYCApprovedEvent.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		from pgappforge.plugins.erp.procurement.supplier_portal.events import KYCApprovedEvent

		supplier = session.get(SupplierProfile, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")
		if supplier.kyc_status not in ("PENDING", "REJECTED"):
			raise InvalidStatusTransitionError(
				f"approve_kyc() requires PENDING or REJECTED status, got {supplier.kyc_status!r}"
			)

		now = _now_utc()
		supplier.kyc_status = "APPROVED"
		supplier.kyc_approved_by = approver_id
		supplier.kyc_approved_at = now
		session.flush()

		_emit(
			KYCApprovedEvent(
				aggregate_id=supplier.id,
				aggregate_type="SupplierProfile",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				approved_by=approver_id,
			),
			session,
		)

		log.info("KYC approved for supplier %s by %s", supplier.supplier_ref, approver_id)
		return supplier

	# ------------------------------------------------------------------
	# 4. verify_bank_details
	# ------------------------------------------------------------------

	@classmethod
	def verify_bank_details(
		cls,
		supplier_id: str,
		bank_name: str,
		account_number: str,
		swift: str,
		session: Any,
		*,
		bank_branch: str | None = None,
		bank_ref: str | None = None,
	) -> Any:
		"""Record and verify bank details for a supplier.

		Sets bank_verified=True and bank_verified_at=now().
		Emits SupplierBankDetailsVerifiedEvent.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		from pgappforge.plugins.erp.procurement.supplier_portal.events import (
			SupplierBankDetailsVerifiedEvent,
		)

		supplier = session.get(SupplierProfile, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		now = _now_utc()
		supplier.bank_name = bank_name.strip()
		supplier.bank_account_number = account_number.strip()
		supplier.bank_swift = swift.strip().upper()
		supplier.bank_branch = bank_branch.strip() if bank_branch else None
		supplier.bank_verified = True
		supplier.bank_verified_at = now
		session.flush()

		_emit(
			SupplierBankDetailsVerifiedEvent(
				aggregate_id=supplier.id,
				aggregate_type="SupplierProfile",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				bank_ref=bank_ref or "",
			),
			session,
		)

		log.info(
			"Bank details verified for supplier %s: %s %s",
			supplier.supplier_ref, bank_name, account_number[-4:],
		)
		return supplier

	# ------------------------------------------------------------------
	# 5. rate_supplier
	# ------------------------------------------------------------------

	@classmethod
	def rate_supplier(
		cls,
		supplier_id: str,
		period: str,
		on_time_pct: Any,
		quality_pct: Any,
		invoice_pct: Any,
		responsiveness: Any,
		session: Any,
		*,
		po_count: int = 0,
		grn_count: int = 0,
	) -> Any:
		"""Create or update a SupplierPerformanceCard for a given period.

		composite = 0.4*on_time + 0.3*quality + 0.2*invoice_pct + 0.1*responsiveness
		Updates supplier.overall_score to the rolling average across all periods.
		Emits SupplierPerformanceRatedEvent.
		Returns the SupplierPerformanceCard.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierProfile, SupplierPerformanceCard,
		)
		from pgappforge.plugins.erp.procurement.supplier_portal.events import (
			SupplierPerformanceRatedEvent,
		)

		supplier = session.get(SupplierProfile, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		ot = _dec(on_time_pct)
		qa = _dec(quality_pct)
		ia = _dec(invoice_pct)
		rs = _dec(responsiveness)

		composite = (
			_dec("0.4") * ot
			+ _dec("0.3") * qa
			+ _dec("0.2") * ia
			+ _dec("0.1") * rs
		).quantize(_dec("0.01"), rounding=ROUND_HALF_UP)

		# Upsert the performance card
		stmt = sa.select(SupplierPerformanceCard).where(
			SupplierPerformanceCard.supplier_id == supplier_id,
			SupplierPerformanceCard.period == period,
		)
		card: Any = session.execute(stmt).scalar_one_or_none()

		if card is None:
			card = SupplierPerformanceCard(
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				period=period,
			)
			session.add(card)

		card.on_time_delivery_pct = ot
		card.quality_acceptance_pct = qa
		card.invoice_accuracy_pct = ia
		card.responsiveness_score = rs
		card.composite_score = composite
		card.po_count = po_count
		card.grn_count = grn_count
		session.flush()

		# Update rolling overall_score on supplier profile
		supplier.overall_score = _compute_overall_score(supplier_id, session)
		session.flush()

		_emit(
			SupplierPerformanceRatedEvent(
				aggregate_id=supplier.id,
				aggregate_type="SupplierProfile",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				period=period,
				score=str(composite),
			),
			session,
		)

		log.info(
			"Supplier %s rated for period %s: composite=%s overall=%s",
			supplier.supplier_ref, period, composite, supplier.overall_score,
		)
		return card

	# ------------------------------------------------------------------
	# 6. suspend_supplier
	# ------------------------------------------------------------------

	@classmethod
	def suspend_supplier(
		cls,
		supplier_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Transition a supplier's kyc_status to SUSPENDED.

		Valid from APPROVED status.
		Emits SupplierSuspendedEvent.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		from pgappforge.plugins.erp.procurement.supplier_portal.events import SupplierSuspendedEvent

		supplier = session.get(SupplierProfile, supplier_id)
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")
		if supplier.kyc_status == "SUSPENDED":
			return supplier  # idempotent
		if supplier.kyc_status != "APPROVED":
			raise InvalidStatusTransitionError(
				f"suspend_supplier() requires APPROVED status, got {supplier.kyc_status!r}"
			)

		supplier.kyc_status = "SUSPENDED"
		session.flush()

		_emit(
			SupplierSuspendedEvent(
				aggregate_id=supplier.id,
				aggregate_type="SupplierProfile",
				tenant_id=supplier.tenant_id,
				supplier_id=supplier_id,
				reason=reason,
			),
			session,
		)

		log.info("Supplier %s suspended: %s", supplier.supplier_ref, reason)
		return supplier

	# ------------------------------------------------------------------
	# 7. get_approved_suppliers
	# ------------------------------------------------------------------

	@classmethod
	def get_approved_suppliers(
		cls,
		tenant_id: str,
		session: Any,
		*,
		category: str | None = None,
	) -> list[Any]:
		"""Return all APPROVED suppliers for a tenant, optionally filtered by category.

		Returns list sorted by company_name ascending.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile

		stmt = (
			sa.select(SupplierProfile)
			.where(
				SupplierProfile.tenant_id == tenant_id,
				SupplierProfile.kyc_status == "APPROVED",
			)
			.order_by(SupplierProfile.company_name.asc())
		)
		if category:
			stmt = stmt.where(SupplierProfile.primary_category == category)

		return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"procurement.supplier_portal.approve_kyc",
	"Approve a supplier's KYC documents (PENDING → APPROVED)",
)
def _bpm_approve_kyc(
	record_ctx: dict,
	session: Any,
	supplier_id: str = "",
	approver_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.supplier_portal.services import SupplierPortalService
	except ImportError:
		return {"status": "error", "message": "supplier_portal plugin not installed"}
	try:
		supplier = SupplierPortalService.approve_kyc(
			supplier_id=supplier_id,
			approver_id=approver_id,
			session=session,
		)
		return {
			"status": "ok",
			"supplier_id": supplier.id,
			"supplier_ref": supplier.supplier_ref,
			"kyc_status": supplier.kyc_status,
		}
	except Exception as exc:
		log.warning("bpm supplier_portal.approve_kyc failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"procurement.supplier_portal.rate",
	"Record a periodic performance rating for a supplier",
)
def _bpm_rate_supplier(
	record_ctx: dict,
	session: Any,
	supplier_id: str = "",
	period: str = "",
	on_time_pct: Any = 0,
	quality_pct: Any = 0,
	invoice_pct: Any = 0,
	responsiveness: Any = 0,
	po_count: int = 0,
	grn_count: int = 0,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.supplier_portal.services import SupplierPortalService
	except ImportError:
		return {"status": "error", "message": "supplier_portal plugin not installed"}
	try:
		card = SupplierPortalService.rate_supplier(
			supplier_id=supplier_id,
			period=period,
			on_time_pct=on_time_pct,
			quality_pct=quality_pct,
			invoice_pct=invoice_pct,
			responsiveness=responsiveness,
			session=session,
			po_count=po_count,
			grn_count=grn_count,
		)
		return {
			"status": "ok",
			"card_id": card.id,
			"period": card.period,
			"composite_score": str(card.composite_score),
		}
	except Exception as exc:
		log.warning("bpm supplier_portal.rate failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"SupplierPortalService",
	"SupplierPortalServiceError",
	"SupplierNotFoundError",
	"InvalidStatusTransitionError",
	"PerformanceCardNotFoundError",
]
