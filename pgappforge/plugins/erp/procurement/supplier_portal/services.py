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
from datetime import date, datetime, timezone
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


class PurchaseOrderNotFoundError(SupplierPortalServiceError):
	pass


class SupplierPortalAuthorizationError(SupplierPortalServiceError):
	pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dec(value: Any) -> Decimal:
	return Decimal(str(value))


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _as_date(value: Any, field_name: str) -> date:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if value is None:
		raise SupplierPortalServiceError(f"{field_name} is required")
	try:
		return date.fromisoformat(str(value))
	except ValueError as exc:
		raise SupplierPortalServiceError(f"{field_name} must be ISO date YYYY-MM-DD") from exc


def current_tenant_id() -> str | None:
	try:
		from pgappforge.multitenancy.middleware import get_current_tenant_id
		tenant_id = get_current_tenant_id()
	except Exception:
		tenant_id = None
	return str(tenant_id) if tenant_id else None


def _tenant_id(explicit_tenant_id: str | None = None) -> str:
	tenant_id = current_tenant_id()
	if tenant_id:
		if explicit_tenant_id and str(explicit_tenant_id) != tenant_id:
			raise ValueError("tenant_id does not match current tenant")
		return tenant_id
	if explicit_tenant_id:
		return str(explicit_tenant_id)
	raise ValueError("Tenant context required")


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


def _compute_overall_score(
	supplier_id: str,
	session: Any,
	tenant_id: str | None = None,
) -> Decimal:
	"""Rolling average composite_score across all SupplierPerformanceCard rows."""
	from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierPerformanceCard
	tenant_id = _tenant_id(tenant_id)
	stmt = sa.select(
		sa.func.avg(SupplierPerformanceCard.composite_score)
	).where(
		SupplierPerformanceCard.tenant_id == tenant_id,
		SupplierPerformanceCard.supplier_id == supplier_id,
	)
	avg = session.execute(stmt).scalar()
	if avg is None:
		return _dec(0)
	return _dec(avg).quantize(_dec("0.01"), rounding=ROUND_HALF_UP)


def _scorecard_dict(card: Any) -> dict[str, Any]:
	return {
		"id": card.id,
		"supplier_id": card.supplier_id,
		"period": card.period,
		"on_time_delivery_pct": card.on_time_delivery_pct,
		"quality_score": card.quality_score,
		"price_competitiveness": card.price_competitiveness,
		"responsiveness_score": card.responsiveness_score,
		"overall_score": card.overall_score,
		"notes": card.notes,
		"scored_by": card.scored_by,
		"scored_at": card.scored_at,
	}


def _purchase_order_candidates() -> list[dict[str, Any]]:
	candidates: list[dict[str, Any]] = []
	try:
		from pgappforge.plugins.erp.operations.scm.models import PurchaseOrder
		candidates.append({
			"source": "SCM",
			"model": PurchaseOrder,
			"total_field": "total_amount_cents",
			"delivery_field": "expected_delivery_date",
		})
	except Exception as exc:  # noqa: BLE001
		log.debug("SCM PurchaseOrder unavailable: %s", exc)
	try:
		from pgappforge.plugins.erp.finance.ap.models import APPurchaseOrder
		candidates.append({
			"source": "AP",
			"model": APPurchaseOrder,
			"total_field": "total_cents",
			"delivery_field": "delivery_date",
		})
	except Exception as exc:  # noqa: BLE001
		log.debug("AP PurchaseOrder unavailable: %s", exc)
	return candidates


def _record_tenant_id(record: Any) -> str | None:
	value = getattr(record, "tenant_id", None)
	return str(value) if value is not None else None


def _po_total_cents(po: Any, candidate: dict[str, Any]) -> int:
	for field_name in (candidate.get("total_field"), "total_cents", "total_amount_cents", "subtotal_cents"):
		if field_name and hasattr(po, field_name):
			return int(getattr(po, field_name) or 0)
	return 0


def _po_currency(po: Any) -> str:
	return str(getattr(po, "currency_code", "USD") or "USD")


def _date_to_json(value: Any) -> str | None:
	if isinstance(value, (datetime, date)):
		return value.isoformat()
	return str(value) if value is not None else None


def _set_record_value(record: Any, field_name: str, value: Any) -> None:
	is_mapped = False
	try:
		is_mapped = field_name in sa.inspect(record.__class__).attrs
	except Exception:  # noqa: BLE001
		is_mapped = hasattr(record, field_name)
	if is_mapped or hasattr(record, field_name):
		setattr(record, field_name, value)
	else:
		setattr(record, field_name, value)
	if hasattr(record, "metadata_"):
		metadata = dict(getattr(record, "metadata_", None) or {})
		metadata[field_name] = _date_to_json(value)
		record.metadata_ = metadata


def _find_purchase_order(
	po_id: str,
	supplier_id: str,
	session: Any,
	tenant_id: str | None = None,
) -> tuple[Any, dict[str, Any]]:
	for candidate in _purchase_order_candidates():
		po = session.get(candidate["model"], po_id)
		if po is None:
			continue
		if tenant_id and _record_tenant_id(po) != str(tenant_id):
			raise PurchaseOrderNotFoundError(f"Purchase order {po_id!r} not found for tenant {tenant_id!r}")
		if str(getattr(po, "supplier_id", "")) != str(supplier_id):
			raise SupplierPortalAuthorizationError("Purchase order does not belong to this supplier")
		return po, candidate
	raise PurchaseOrderNotFoundError(f"Purchase order {po_id!r} not found")


def _po_line_model_for_source(source: str) -> Any:
	if source == "SCM":
		from pgappforge.plugins.erp.operations.scm.models import POLine
		return POLine
	if source == "AP":
		from pgappforge.plugins.erp.finance.ap.models import APPOLine
		return APPOLine
	return None


def _validate_po_line(
	po: Any,
	candidate: dict[str, Any],
	po_line_id: str | None,
	session: Any,
) -> None:
	if not po_line_id:
		return
	try:
		line_model = _po_line_model_for_source(candidate["source"])
	except Exception as exc:  # noqa: BLE001
		log.debug("PO line model unavailable for %s: %s", candidate["source"], exc)
		return
	if line_model is None:
		return
	line = session.get(line_model, po_line_id)
	if line is None or str(getattr(line, "po_id", "")) != str(getattr(po, "id", "")):
		raise SupplierPortalServiceError(f"PO line {po_line_id!r} does not belong to PO {po.id!r}")


def _normalize_asn_line_items(
	po: Any,
	candidate: dict[str, Any],
	line_items: list[dict[str, Any]],
	session: Any,
) -> list[dict[str, Any]]:
	if not line_items:
		raise SupplierPortalServiceError("line_items cannot be empty")
	normalized: list[dict[str, Any]] = []
	for item in line_items:
		po_line_id = item.get("po_line_id")
		if not po_line_id:
			raise SupplierPortalServiceError("line item po_line_id is required")
		_validate_po_line(po, candidate, str(po_line_id), session)
		shipped_qty = _dec(item.get("shipped_qty"))
		if shipped_qty <= 0:
			raise SupplierPortalServiceError("shipped_qty must be positive")
		normalized.append({
			"po_line_id": str(po_line_id),
			"shipped_qty": str(shipped_qty),
		})
	return normalized


def _normalize_invoice_line_items(
	po: Any,
	candidate: dict[str, Any],
	line_items: list[dict[str, Any]],
	session: Any,
) -> list[dict[str, Any]]:
	if not line_items:
		raise SupplierPortalServiceError("line_items cannot be empty")
	normalized: list[dict[str, Any]] = []
	for index, item in enumerate(line_items, start=1):
		po_line_id = item.get("po_line_id")
		if po_line_id:
			_validate_po_line(po, candidate, str(po_line_id), session)
		row = dict(item)
		row["line_number"] = int(row.get("line_number") or index)
		if po_line_id:
			row["po_line_id"] = str(po_line_id)
		if "amount_cents" in row:
			row["amount_cents"] = int(row["amount_cents"])
		normalized.append(row)
	return normalized


def _latest_goods_receipt(
	po_id: str,
	tenant_id: str,
	po_source: str,
	session: Any,
) -> tuple[Any | None, str | None]:
	try:
		if po_source == "SCM":
			from pgappforge.plugins.erp.operations.scm.models import GoodsReceipt
			grn = session.execute(
				sa.select(GoodsReceipt)
				.where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.po_id == po_id)
				.order_by(sa.desc(GoodsReceipt.received_date), sa.desc(GoodsReceipt.created_at))
				.limit(1)
			).scalar_one_or_none()
			return grn, "SCM" if grn is not None else None
		if po_source == "AP":
			from pgappforge.plugins.erp.finance.ap.models import APGoodsReceipt
			grn = session.execute(
				sa.select(APGoodsReceipt)
				.where(APGoodsReceipt.tenant_id == tenant_id, APGoodsReceipt.po_id == po_id)
				.order_by(sa.desc(APGoodsReceipt.received_date), sa.desc(APGoodsReceipt.created_at))
				.limit(1)
			).scalar_one_or_none()
			return grn, "AP" if grn is not None else None
	except Exception as exc:  # noqa: BLE001
		log.debug("Latest goods receipt lookup skipped: %s", exc)
	return None, None


def _generate_asn_number(session: Any, tenant_id: str) -> str:
	from pgappforge.plugins.erp.procurement.supplier_portal.models import AdvanceShipmentNotice
	today_str = _now_utc().strftime("%Y%m%d")
	prefix = f"ASN-{today_str}-"
	count = int(session.execute(
		sa.select(sa.func.count(AdvanceShipmentNotice.id)).where(
			AdvanceShipmentNotice.tenant_id == tenant_id,
			AdvanceShipmentNotice.asn_number.like(f"{prefix}%"),
		)
	).scalar() or 0)
	return f"{prefix}{count + 1:05d}"


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

		tenant_id = _tenant_id(tenant_id)
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
		tenant_id: str | None = None,
	) -> Any:
		"""Append KYC documents to a supplier profile.

		documents is a list of {doc_type, url, uploaded_at} dicts.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
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
		tenant_id: str | None = None,
	) -> Any:
		"""Transition supplier KYC from PENDING → APPROVED.

		Sets kyc_approved_by and kyc_approved_at.
		Emits KYCApprovedEvent.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		from pgappforge.plugins.erp.procurement.supplier_portal.events import KYCApprovedEvent

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
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
		tenant_id: str | None = None,
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

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
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
		tenant_id: str | None = None,
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

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
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
			SupplierPerformanceCard.tenant_id == tenant_id,
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
		supplier.overall_score = _compute_overall_score(supplier_id, session, tenant_id)
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
		tenant_id: str | None = None,
	) -> Any:
		"""Transition a supplier's kyc_status to SUSPENDED.

		Valid from APPROVED status.
		Emits SupplierSuspendedEvent.
		Returns the updated SupplierProfile.
		"""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import SupplierProfile
		from pgappforge.plugins.erp.procurement.supplier_portal.events import SupplierSuspendedEvent

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
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

		tenant_id = _tenant_id(tenant_id)
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

	# ------------------------------------------------------------------
	# 8. acknowledge_po
	# ------------------------------------------------------------------

	@classmethod
	def acknowledge_po(
		cls,
		po_id: str,
		supplier_id: str,
		confirmed_delivery_date: Any,
		session: Any,
	) -> Any:
		"""Acknowledge a sent PO, recording the supplier's confirmed delivery date."""
		from pgappforge.plugins.erp.procurement.supplier_portal.events import POAcknowledgedEvent
		from pgappforge.plugins.erp.procurement.supplier_portal.models import POAcknowledgement

		confirmed_date = _as_date(confirmed_delivery_date, "confirmed_delivery_date")
		po, candidate = _find_purchase_order(po_id, supplier_id, session)
		tenant_id = _record_tenant_id(po)
		if tenant_id is None:
			raise SupplierPortalServiceError("Purchase order tenant_id is required")

		previous_status = str(getattr(po, "status", ""))
		po.status = "ACKNOWLEDGED"
		_set_record_value(po, "confirmed_delivery_date", confirmed_date)
		_set_record_value(po, "supplier_acknowledged_at", _now_utc())

		ack = session.execute(
			sa.select(POAcknowledgement).where(
				POAcknowledgement.tenant_id == tenant_id,
				POAcknowledgement.po_id == po_id,
			)
		).scalar_one_or_none()
		if ack is None:
			ack = POAcknowledgement(
				tenant_id=tenant_id,
				po_id=po_id,
				po_source=candidate["source"],
				supplier_id=supplier_id,
			)
			session.add(ack)

		ack.confirmed_delivery_date = confirmed_date
		ack.status = "ACKNOWLEDGED"
		ack.acknowledged_at = _now_utc()
		ack.metadata_ = {
			"po_number": str(getattr(po, "po_number", "")),
			"previous_status": previous_status,
		}
		session.flush()

		_emit(
			POAcknowledgedEvent(
				aggregate_id=po.id,
				aggregate_type=po.__class__.__name__,
				tenant_id=tenant_id,
				po_id=po_id,
				po_source=candidate["source"],
				supplier_id=supplier_id,
				acknowledgement_id=ack.id,
				confirmed_delivery_date=confirmed_date.isoformat(),
			),
			session,
		)
		log.info("PO %s acknowledged by supplier %s", po_id, supplier_id)
		return ack

	# ------------------------------------------------------------------
	# 9. get_open_pos_for_supplier
	# ------------------------------------------------------------------

	@classmethod
	def get_open_pos_for_supplier(
		cls,
		supplier_id: str,
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Return SENT purchase orders awaiting supplier acknowledgement."""
		tenant_id = _tenant_id(tenant_id)
		open_pos: list[Any] = []
		for candidate in _purchase_order_candidates():
			model = candidate["model"]
			rows = session.execute(
				sa.select(model)
				.where(
					model.tenant_id == tenant_id,
					model.supplier_id == supplier_id,
					model.status == "SENT",
				)
				.order_by(sa.desc(getattr(model, "order_date", model.id)))
			).scalars().all()
			open_pos.extend(rows)
		return open_pos

	# ------------------------------------------------------------------
	# 10. submit_asn
	# ------------------------------------------------------------------

	@classmethod
	def submit_asn(
		cls,
		po_id: str,
		supplier_id: str,
		ship_date: Any,
		expected_delivery_date: Any,
		tracking_number: str,
		line_items: list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Create an advance shipment notice and request GR preparation in operations."""
		from pgappforge.plugins.erp.procurement.supplier_portal.events import (
			AdvanceShipmentNoticeSubmittedEvent,
		)
		from pgappforge.plugins.erp.procurement.supplier_portal.models import AdvanceShipmentNotice

		po, candidate = _find_purchase_order(po_id, supplier_id, session)
		tenant_id = _record_tenant_id(po)
		if tenant_id is None:
			raise SupplierPortalServiceError("Purchase order tenant_id is required")

		ship_dt = _as_date(ship_date, "ship_date")
		expected_dt = _as_date(expected_delivery_date, "expected_delivery_date")
		normalized_lines = _normalize_asn_line_items(po, candidate, line_items, session)
		asn_number = _generate_asn_number(session, tenant_id)
		operations_payload = {
			"action": "prepare_goods_receipt",
			"po_id": str(po_id),
			"po_source": candidate["source"],
			"supplier_id": str(supplier_id),
			"tracking_number": tracking_number or "",
			"expected_delivery_date": expected_dt.isoformat(),
			"line_items": normalized_lines,
		}

		asn = AdvanceShipmentNotice(
			tenant_id=tenant_id,
			asn_number=asn_number,
			po_id=po_id,
			po_source=candidate["source"],
			supplier_id=supplier_id,
			ship_date=ship_dt,
			expected_delivery_date=expected_dt,
			tracking_number=(tracking_number or "").strip(),
			line_items=normalized_lines,
			status="IN_TRANSIT",
			operations_status="GR_PREPARATION_REQUESTED",
			operations_payload=operations_payload,
		)
		session.add(asn)

		po.status = "IN_TRANSIT"
		_set_record_value(po, "asn_tracking_number", tracking_number or "")
		_set_record_value(po, "asn_expected_delivery_date", expected_dt)
		session.flush()

		operations_payload["asn_id"] = str(asn.id)
		asn.operations_payload = operations_payload
		_emit(
			AdvanceShipmentNoticeSubmittedEvent(
				aggregate_id=asn.id,
				aggregate_type="AdvanceShipmentNotice",
				tenant_id=tenant_id,
				po_id=po_id,
				po_source=candidate["source"],
				supplier_id=supplier_id,
				asn_id=asn.id,
				asn_number=asn.asn_number,
				tracking_number=asn.tracking_number or "",
			),
			session,
		)
		log.info("ASN %s submitted for PO %s by supplier %s", asn.asn_number, po_id, supplier_id)
		return asn

	# ------------------------------------------------------------------
	# 11. submit_invoice
	# ------------------------------------------------------------------

	@classmethod
	def submit_invoice(
		cls,
		po_id: str,
		supplier_id: str,
		invoice_number: str,
		invoice_date: Any,
		amount_cents: int,
		line_items: list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Create a supplier-submitted invoice after validating against PO value."""
		from pgappforge.plugins.erp.procurement.supplier_portal.events import (
			VendorInvoiceSubmittedEvent,
		)
		from pgappforge.plugins.erp.procurement.supplier_portal.models import VendorInvoice

		if not str(invoice_number or "").strip():
			raise SupplierPortalServiceError("invoice_number is required")
		amount = int(amount_cents)
		if amount <= 0:
			raise SupplierPortalServiceError("amount_cents must be positive")

		po, candidate = _find_purchase_order(po_id, supplier_id, session)
		tenant_id = _record_tenant_id(po)
		if tenant_id is None:
			raise SupplierPortalServiceError("Purchase order tenant_id is required")
		po_total = _po_total_cents(po, candidate)
		if amount > po_total:
			raise SupplierPortalServiceError(
				f"invoice_amount {amount} exceeds PO value {po_total}"
			)

		normalized_lines = _normalize_invoice_line_items(po, candidate, line_items, session)
		grn, grn_source = _latest_goods_receipt(po_id, tenant_id, candidate["source"], session)
		invoice = VendorInvoice(
			tenant_id=tenant_id,
			po_id=po_id,
			po_source=candidate["source"],
			supplier_id=supplier_id,
			goods_receipt_id=getattr(grn, "id", None),
			goods_receipt_source=grn_source,
			invoice_number=invoice_number.strip(),
			invoice_date=_as_date(invoice_date, "invoice_date"),
			amount_cents=amount,
			currency_code=_po_currency(po),
			line_items=normalized_lines,
			match_status="PO_VALUE_VALIDATED",
			status="PENDING_APPROVAL",
			ap_notification_status="REQUESTED",
			metadata_={
				"po_number": str(getattr(po, "po_number", "")),
				"po_total_cents": po_total,
				"ap_team_notification": "requested",
			},
		)
		session.add(invoice)
		_set_record_value(po, "supplier_invoice_submitted_at", _now_utc())
		session.flush()

		_emit(
			VendorInvoiceSubmittedEvent(
				aggregate_id=invoice.id,
				aggregate_type="VendorInvoice",
				tenant_id=tenant_id,
				po_id=po_id,
				po_source=candidate["source"],
				supplier_id=supplier_id,
				invoice_id=invoice.id,
				invoice_number=invoice.invoice_number,
				amount_cents=invoice.amount_cents,
			),
			session,
		)
		log.info("Vendor invoice %s submitted for PO %s", invoice.invoice_number, po_id)
		return invoice

	# ------------------------------------------------------------------
	# 12. get_supplier_dashboard
	# ------------------------------------------------------------------

	@classmethod
	def get_supplier_dashboard(
		cls,
		supplier_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return supplier portal dashboard metrics for a supplier."""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			AdvanceShipmentNotice,
			SupplierScorecard,
			VendorInvoice,
		)

		tenant_id = _tenant_id(tenant_id)
		open_po_rows: list[tuple[Any, dict[str, Any]]] = []
		for candidate in _purchase_order_candidates():
			model = candidate["model"]
			rows = session.execute(
				sa.select(model)
				.where(
					model.tenant_id == tenant_id,
					model.supplier_id == supplier_id,
					model.status.notin_(["CLOSED", "CANCELLED"]),
				)
			).scalars().all()
			open_po_rows.extend((row, candidate) for row in rows)

		pending_ack_count = len(cls.get_open_pos_for_supplier(supplier_id, tenant_id, session))
		active_shipments = int(session.execute(
			sa.select(sa.func.count(AdvanceShipmentNotice.id)).where(
				AdvanceShipmentNotice.tenant_id == tenant_id,
				AdvanceShipmentNotice.supplier_id == supplier_id,
				AdvanceShipmentNotice.status == "IN_TRANSIT",
			)
		).scalar() or 0)
		invoice_rows = session.execute(
			sa.select(VendorInvoice.status, sa.func.count(VendorInvoice.id))
			.where(
				VendorInvoice.tenant_id == tenant_id,
				VendorInvoice.supplier_id == supplier_id,
			)
			.group_by(VendorInvoice.status)
		).all()
		invoice_counts = {
			"pending": 0,
			"approved": 0,
			"paid": 0,
		}
		for status, count in invoice_rows:
			normalized = str(status or "").lower()
			if normalized in ("pending", "pending_approval"):
				invoice_counts["pending"] += int(count or 0)
			elif normalized == "approved":
				invoice_counts["approved"] += int(count or 0)
			elif normalized == "paid":
				invoice_counts["paid"] += int(count or 0)

		scorecards = session.execute(
			sa.select(SupplierScorecard)
			.where(
				SupplierScorecard.tenant_id == tenant_id,
				SupplierScorecard.supplier_id == supplier_id,
			)
			.order_by(SupplierScorecard.period.desc())
			.limit(3)
		).scalars().all()

		return {
			"supplier_id": supplier_id,
			"tenant_id": tenant_id,
			"open_pos": {
				"count": len(open_po_rows),
				"total_value_cents": sum(_po_total_cents(po, candidate) for po, candidate in open_po_rows),
			},
			"pending_acknowledgments": pending_ack_count,
			"active_shipments": active_shipments,
			"submitted_invoices": invoice_counts,
			"performance_scorecard": [_scorecard_dict(card) for card in scorecards],
		}

	# ------------------------------------------------------------------
	# 13. score_supplier
	# ------------------------------------------------------------------

	@classmethod
	def score_supplier(
		cls,
		supplier_id: str,
		period: str,
		metrics: dict[str, Any],
		session: Any,
		tenant_id: str | None = None,
	) -> Any:
		"""Create a monthly SupplierScorecard using the requested weighted average."""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierProfile,
			SupplierScorecard,
		)

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")
		if len(period) != 7 or period[4] != "-":
			raise SupplierPortalServiceError("period must use YYYY-MM format")

		otd = _dec(metrics.get("OTD", metrics.get("otd", metrics.get("on_time_delivery_pct", 0))))
		quality = _dec(metrics.get("quality", metrics.get("quality_score", metrics.get("quality_score_1_5", 0))))
		price = _dec(metrics.get("price", metrics.get("price_competitiveness", metrics.get("price_competitiveness_1_5", 0))))
		responsiveness = _dec(metrics.get("responsiveness", metrics.get("responsiveness_score", metrics.get("responsiveness_1_5", 0))))
		for name, value in (
			("OTD", otd),
			("quality", quality),
			("price", price),
			("responsiveness", responsiveness),
		):
			if value < 0 or value > 100:
				raise SupplierPortalServiceError(f"{name} must be between 0 and 100")

		overall = (
			otd * _dec("0.4")
			+ quality * _dec("0.3")
			+ price * _dec("0.2")
			+ responsiveness * _dec("0.1")
		).quantize(_dec("0.01"), rounding=ROUND_HALF_UP)

		card = SupplierScorecard(
			tenant_id=supplier.tenant_id,
			supplier_id=supplier.id,
			period=period,
			on_time_delivery_pct=otd,
			quality_score=quality,
			price_competitiveness=price,
			responsiveness_score=responsiveness,
			overall_score=overall,
			notes=metrics.get("notes"),
			scored_by=str(metrics.get("scored_by", "")),
			scored_at=_now_utc(),
		)
		session.add(card)
		session.flush()
		return card

	# ------------------------------------------------------------------
	# 9. get_supplier_360
	# ------------------------------------------------------------------

	@classmethod
	def get_supplier_360(
		cls,
		supplier_id: str,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Return supplier profile, recent scorecards, PO count, spend, and compliance status."""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierProfile,
			SupplierScorecard,
		)

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")

		scorecards = session.execute(
			sa.select(SupplierScorecard)
			.where(
				SupplierScorecard.tenant_id == tenant_id,
				SupplierScorecard.supplier_id == supplier_id,
			)
			.order_by(SupplierScorecard.period.desc())
			.limit(3)
		).scalars().all()

		open_pos_count = 0
		total_spend_cents = 0
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice, APPurchaseOrder
			open_pos_count = int(session.execute(
				sa.select(sa.func.count(APPurchaseOrder.id)).where(
					APPurchaseOrder.tenant_id == tenant_id,
					APPurchaseOrder.supplier_id == supplier_id,
					APPurchaseOrder.status.notin_(["CLOSED", "CANCELLED"]),
				)
			).scalar() or 0)
			total_spend_cents = int(session.execute(
				sa.select(sa.func.coalesce(sa.func.sum(APInvoice.total_cents), 0)).where(
					APInvoice.tenant_id == tenant_id,
					APInvoice.supplier_id == supplier_id,
				)
			).scalar() or 0)
		except Exception:
			open_pos_count = 0
			total_spend_cents = 0

		return {
			"supplier": {
				"id": supplier.id,
				"supplier_ref": supplier.supplier_ref,
				"company_name": supplier.company_name,
				"country_code": supplier.country_code,
				"primary_category": supplier.primary_category,
				"risk_level": supplier.risk_level,
			},
			"last_3_scorecards": [_scorecard_dict(card) for card in scorecards],
			"open_pos_count": open_pos_count,
			"total_spend_cents": total_spend_cents,
			"compliance_status": supplier.kyc_status,
		}

	# ------------------------------------------------------------------
	# 10. flag_supplier_risk
	# ------------------------------------------------------------------

	@classmethod
	def flag_supplier_risk(
		cls,
		supplier_id: str,
		risk_type: str,
		severity: str,
		notes: str | None,
		session: Any,
		tenant_id: str | None = None,
	) -> dict[str, Any]:
		"""Create a risk flag and update SupplierProfile.risk_level."""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			RISK_TYPES,
			SupplierProfile,
			SupplierRisk,
		)

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")
		normalized_type = risk_type.upper().strip()
		if normalized_type not in RISK_TYPES:
			raise SupplierPortalServiceError(f"Invalid risk_type {risk_type!r}. Choose from {RISK_TYPES}")

		risk = SupplierRisk(
			tenant_id=supplier.tenant_id,
			supplier_id=supplier.id,
			risk_type=normalized_type,
			severity=severity,
			notes=notes,
			created_at=_now_utc(),
		)
		supplier.risk_level = severity
		session.add(risk)
		session.flush()

		return {
			"id": risk.id,
			"tenant_id": risk.tenant_id,
			"supplier_id": risk.supplier_id,
			"risk_type": risk.risk_type,
			"severity": risk.severity,
			"notes": risk.notes,
			"created_at": risk.created_at,
		}

	# ------------------------------------------------------------------
	# 11. get_supplier_performance_trend
	# ------------------------------------------------------------------

	@classmethod
	def get_supplier_performance_trend(
		cls,
		supplier_id: str,
		periods: int,
		session: Any,
		tenant_id: str | None = None,
	) -> list[dict[str, Any]]:
		"""Return the last N scorecards ordered by newest period first."""
		from pgappforge.plugins.erp.procurement.supplier_portal.models import (
			SupplierProfile,
			SupplierScorecard,
		)

		tenant_id = _tenant_id(tenant_id)
		supplier = session.execute(
			sa.select(SupplierProfile).where(
				SupplierProfile.id == supplier_id,
				SupplierProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if supplier is None:
			raise SupplierNotFoundError(f"Supplier {supplier_id!r} not found")
		limit = max(int(periods), 0)
		rows = session.execute(
			sa.select(SupplierScorecard)
			.where(
				SupplierScorecard.tenant_id == tenant_id,
				SupplierScorecard.supplier_id == supplier_id,
			)
			.order_by(SupplierScorecard.period.desc())
			.limit(limit)
		).scalars().all()
		return [_scorecard_dict(row) for row in rows]


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
			tenant_id=record_ctx.get("tenant_id"),
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
			tenant_id=record_ctx.get("tenant_id"),
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
	"PurchaseOrderNotFoundError",
	"SupplierPortalAuthorizationError",
]
