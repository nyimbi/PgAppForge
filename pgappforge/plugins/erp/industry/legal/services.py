"""
pgappforge/plugins/erp/industry/legal/services.py

LegalService — stateless business logic for the Legal Services plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - matter_number unique per tenant
  - invoice_number unique per tenant
  - Time entries: amount_cents computed from hours * rate_cents_per_hour
  - Invoice total = time_charges + disbursements + tax (no negative totals)
  - Precedent search uses PostgreSQL array overlap (&&) on legal_issues
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

from pgappforge.plugins.erp.foundation.commons import money_add, format_currency

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LegalServiceError(Exception):
	"""Base error for Legal Services domain violations."""


class MatterNotFoundError(LegalServiceError):
	"""No LegalMatter with the given id."""


class DocumentNotFoundError(LegalServiceError):
	"""No LegalDocument with the given id."""


class TimeEntryNotFoundError(LegalServiceError):
	"""No LegalTimeEntry with the given id."""


class DeadlineNotFoundError(LegalServiceError):
	"""No Deadline with the given id."""


class InvoiceNotFoundError(LegalServiceError):
	"""No LegalInvoice with the given id."""


class DuplicateMatterNumberError(LegalServiceError):
	"""matter_number already exists for this tenant."""


class DuplicateInvoiceNumberError(LegalServiceError):
	"""invoice_number already exists for this tenant."""


class MatterNotActiveError(LegalServiceError):
	"""Operation requires matter in ACTIVE status."""


# ---------------------------------------------------------------------------
# LegalService
# ---------------------------------------------------------------------------

class LegalService:
	"""Stateless service for Legal Services operations."""

	# ------------------------------------------------------------------
	# Matter
	# ------------------------------------------------------------------

	def open_matter(
		self,
		*,
		tenant_id: str,
		client_id: str,
		matter_type: str,
		lead_counsel_id: str,
		jurisdiction: str,
		details: dict[str, Any],
		session: Any,
	) -> "LegalMatter":
		"""Open a new legal matter.

		details may include: matter_number, description, opposing_party_id,
		court, filed_date, target_resolution_date, budget_cents.

		Raises DuplicateMatterNumberError if matter_number exists for tenant.
		"""
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter
		from pgappforge.plugins.erp.industry.legal.events import (
			MatterOpenedEvent, emit_event,
		)

		matter_number = details.get("matter_number") or _generate_matter_number(session)

		existing = session.execute(
			select(LegalMatter).where(
				LegalMatter.tenant_id == tenant_id,
				LegalMatter.matter_number == matter_number,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateMatterNumberError(
				f"matter_number {matter_number!r} already exists for tenant {tenant_id!r}"
			)

		matter = LegalMatter(
			tenant_id=tenant_id,
			matter_number=matter_number,
			matter_type=matter_type,
			client_id=client_id,
			lead_counsel_id=lead_counsel_id,
			opposing_party_id=details.get("opposing_party_id"),
			jurisdiction=jurisdiction,
			court=details.get("court"),
			status="INTAKE",
			description=details.get("description"),
			filed_date=details.get("filed_date"),
			target_resolution_date=details.get("target_resolution_date"),
			budget_cents=int(details.get("budget_cents", 0)),
			billed_cents=0,
		)
		session.add(matter)
		session.flush()

		emit_event(
			MatterOpenedEvent(
				aggregate_id=matter.id,
				aggregate_type="LegalMatter",
				tenant_id=tenant_id,
				matter_id=matter.id,
				matter_number=matter_number,
				matter_type=matter_type,
				client_id=client_id,
				lead_counsel_id=lead_counsel_id,
			),
			session,
		)

		log.info("open_matter: created %r type=%r", matter_number, matter_type)
		return matter

	def change_matter_status(
		self,
		matter_id: str,
		new_status: str,
		session: Any,
	) -> dict:
		"""Transition matter to a new status. Emits MatterStatusChangedEvent."""
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter
		from pgappforge.plugins.erp.industry.legal.events import (
			MatterStatusChangedEvent, MatterClosedEvent, emit_event,
		)

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		old_status = matter.status
		matter.status = new_status

		emit_event(
			MatterStatusChangedEvent(
				aggregate_id=matter_id,
				aggregate_type="LegalMatter",
				tenant_id=matter.tenant_id,
				matter_id=matter_id,
				matter_number=matter.matter_number,
				old_status=old_status,
				new_status=new_status,
			),
			session,
		)

		if new_status in ("SETTLED", "CLOSED"):
			emit_event(
				MatterClosedEvent(
					aggregate_id=matter_id,
					aggregate_type="LegalMatter",
					tenant_id=matter.tenant_id,
					matter_id=matter_id,
					matter_number=matter.matter_number,
					final_status=new_status,
				),
				session,
			)

		log.info(
			"change_matter_status: matter %r %r → %r",
			matter.matter_number, old_status, new_status,
		)
		return {
			"matter_id": matter_id,
			"old_status": old_status,
			"new_status": new_status,
		}

	# ------------------------------------------------------------------
	# Time entries
	# ------------------------------------------------------------------

	def record_time(
		self,
		*,
		tenant_id: str,
		matter_id: str,
		timekeeper_id: str,
		hours: float,
		description: str,
		activity_code: str,
		rate_cents_per_hour: int,
		work_date: date | None = None,
		is_billable: bool = True,
		session: Any,
	) -> "LegalTimeEntry":
		"""Record a time entry against a matter.

		amount_cents is computed as round_half_up(hours * rate_cents_per_hour).
		"""
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter, LegalTimeEntry
		from pgappforge.plugins.erp.industry.legal.events import (
			TimeEntryRecordedEvent, emit_event,
		)

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		amount_cents = int(
			(Decimal(str(hours)) * Decimal(str(rate_cents_per_hour))).quantize(
				Decimal("1"), rounding=ROUND_HALF_UP
			)
		)

		entry = LegalTimeEntry(
			tenant_id=tenant_id,
			matter_id=matter_id,
			timekeeper_id=timekeeper_id,
			work_date=work_date or date.today(),
			hours=Decimal(str(hours)),
			rate_cents_per_hour=rate_cents_per_hour,
			amount_cents=amount_cents,
			activity_code=activity_code,
			description=description,
			status="DRAFT",
			is_billable=is_billable,
		)
		session.add(entry)
		session.flush()

		emit_event(
			TimeEntryRecordedEvent(
				aggregate_id=entry.id,
				aggregate_type="LegalTimeEntry",
				tenant_id=tenant_id,
				time_entry_id=entry.id,
				matter_id=matter_id,
				timekeeper_id=timekeeper_id,
				amount_cents=amount_cents,
				is_billable=is_billable,
			),
			session,
		)

		log.info(
			"record_time: %s hours for matter %r amount=%d cents",
			hours, matter_id, amount_cents,
		)
		return entry

	# ------------------------------------------------------------------
	# Invoice
	# ------------------------------------------------------------------

	def generate_invoice(
		self,
		*,
		tenant_id: str,
		matter_id: str,
		billing_period_start: date,
		billing_period_end: date,
		disbursements_cents: int = 0,
		tax_cents: int = 0,
		session: Any,
	) -> "LegalInvoice":
		"""Generate an invoice from approved time entries in the billing period.

		Sums all APPROVED, billable time entries in the period. Sets them to
		BILLED status. Computes total = time_charges + disbursements + tax.

		Raises DuplicateInvoiceNumberError if a draft invoice already exists
		for the same matter and period.
		"""
		from pgappforge.plugins.erp.industry.legal.models import (
			LegalMatter, LegalTimeEntry, LegalInvoice,
		)
		from pgappforge.plugins.erp.industry.legal.events import (
			InvoiceGeneratedEvent, emit_event,
		)

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		# Fetch approved billable entries in period
		entries = session.execute(
			select(LegalTimeEntry).where(
				LegalTimeEntry.matter_id == matter_id,
				LegalTimeEntry.status == "APPROVED",
				LegalTimeEntry.is_billable.is_(True),
				LegalTimeEntry.work_date >= billing_period_start,
				LegalTimeEntry.work_date <= billing_period_end,
			)
		).scalars().all()

		time_charges_cents = sum(e.amount_cents for e in entries)
		total_cents = money_add(
			money_add(time_charges_cents, disbursements_cents),
			tax_cents,
		)

		invoice_number = _generate_invoice_number(tenant_id, matter.matter_number, session)

		invoice = LegalInvoice(
			tenant_id=tenant_id,
			matter_id=matter_id,
			invoice_number=invoice_number,
			billing_period_start=billing_period_start,
			billing_period_end=billing_period_end,
			time_charges_cents=time_charges_cents,
			disbursements_cents=disbursements_cents,
			tax_cents=tax_cents,
			total_cents=total_cents,
			status="DRAFT",
		)
		session.add(invoice)
		session.flush()

		# Mark time entries as BILLED
		for entry in entries:
			entry.status = "BILLED"

		# Update matter billed_cents
		matter.billed_cents = money_add(matter.billed_cents, total_cents)

		emit_event(
			InvoiceGeneratedEvent(
				aggregate_id=invoice.id,
				aggregate_type="LegalInvoice",
				tenant_id=tenant_id,
				invoice_id=invoice.id,
				matter_id=matter_id,
				invoice_number=invoice_number,
				total_cents=total_cents,
			),
			session,
		)

		log.info(
			"generate_invoice: %r for matter %r total=%d cents (%d entries)",
			invoice_number, matter_id, total_cents, len(entries),
		)
		return invoice

	# ------------------------------------------------------------------
	# Deadlines
	# ------------------------------------------------------------------

	def track_deadline(
		self,
		*,
		tenant_id: str,
		matter_id: str,
		deadline_type: str,
		deadline_date: date,
		description: str,
		is_hard_deadline: bool = True,
		responsible_id: str | None = None,
		session: Any,
	) -> "Deadline":
		"""Add a deadline to a matter and emit DeadlineTrackedEvent."""
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter, Deadline
		from pgappforge.plugins.erp.industry.legal.events import (
			DeadlineTrackedEvent, emit_event,
		)

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		dl = Deadline(
			tenant_id=tenant_id,
			matter_id=matter_id,
			deadline_type=deadline_type,
			deadline_date=deadline_date,
			description=description,
			is_hard_deadline=is_hard_deadline,
			status="PENDING",
			responsible_id=responsible_id,
		)
		session.add(dl)
		session.flush()

		emit_event(
			DeadlineTrackedEvent(
				aggregate_id=dl.id,
				aggregate_type="Deadline",
				tenant_id=tenant_id,
				deadline_id=dl.id,
				matter_id=matter_id,
				deadline_type=deadline_type,
				deadline_date=deadline_date.isoformat(),
				is_hard_deadline=is_hard_deadline,
			),
			session,
		)

		log.info(
			"track_deadline: %s on %s for matter %r hard=%s",
			deadline_type, deadline_date, matter_id, is_hard_deadline,
		)
		return dl

	# ------------------------------------------------------------------
	# Precedent research
	# ------------------------------------------------------------------

	def search_precedents(
		self,
		legal_issues: list[str],
		jurisdiction: str,
		session: Any,
		limit: int = 20,
	) -> list["Precedent"]:
		"""Find precedents matching given legal issues in a jurisdiction.

		Uses PostgreSQL array overlap (&&) operator on legal_issues column.
		Falls back to relevance_tags overlap if no legal_issues match is found.
		"""
		from pgappforge.plugins.erp.industry.legal.models import Precedent

		if not legal_issues:
			return []

		# Array overlap: find precedents with ANY matching issue
		q = (
			select(Precedent)
			.where(
				Precedent.jurisdiction.ilike(f"%{jurisdiction}%"),
				Precedent.legal_issues.overlap(legal_issues),
			)
			.order_by(Precedent.decided_date.desc())
			.limit(limit)
		)
		results = session.execute(q).scalars().all()

		if not results:
			# Fallback: relevance_tags overlap
			q2 = (
				select(Precedent)
				.where(
					Precedent.jurisdiction.ilike(f"%{jurisdiction}%"),
					Precedent.relevance_tags.overlap(legal_issues),
				)
				.order_by(Precedent.decided_date.desc())
				.limit(limit)
			)
			results = session.execute(q2).scalars().all()

		log.info(
			"search_precedents: %d results for issues=%r jurisdiction=%r",
			len(results), legal_issues, jurisdiction,
		)
		return list(results)

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def calculate_matter_profitability(
		self,
		matter_id: str,
		session: Any,
	) -> dict:
		"""Return profitability analysis for a matter.

		Returns:
		  budget_cents, billed_cents, unbilled_approved_cents,
		  total_hours, billable_hours, budget_utilization_pct,
		  profitability_cents (budget - billed - unbilled)
		"""
		from pgappforge.plugins.erp.industry.legal.models import LegalMatter, LegalTimeEntry

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		# All time entries for matter
		all_entries = session.execute(
			select(LegalTimeEntry).where(LegalTimeEntry.matter_id == matter_id)
		).scalars().all()

		total_hours = float(sum(e.hours for e in all_entries))
		billable_hours = float(sum(e.hours for e in all_entries if e.is_billable))
		unbilled_approved_cents = sum(
			e.amount_cents
			for e in all_entries
			if e.status == "APPROVED" and e.is_billable
		)
		billed_cents = matter.billed_cents
		budget_cents = matter.budget_cents

		budget_utilization_pct = (
			round(billed_cents / budget_cents * 100, 2)
			if budget_cents > 0
			else 0.0
		)
		profitability_cents = budget_cents - billed_cents - unbilled_approved_cents

		return {
			"matter_id": matter_id,
			"matter_number": matter.matter_number,
			"budget_cents": budget_cents,
			"budget_display": format_currency(budget_cents),
			"billed_cents": billed_cents,
			"billed_display": format_currency(billed_cents),
			"unbilled_approved_cents": unbilled_approved_cents,
			"unbilled_approved_display": format_currency(unbilled_approved_cents),
			"total_hours": total_hours,
			"billable_hours": billable_hours,
			"budget_utilization_pct": budget_utilization_pct,
			"profitability_cents": profitability_cents,
			"profitability_display": format_currency(profitability_cents),
		}

	def get_docket(self, matter_id: str, session: Any) -> list[dict]:
		"""Return a chronological docket — documents, deadlines, and invoices.

		Each entry has: date, event_type, title/description, status, id.
		Sorted ascending by date so the docket reads as a timeline.
		"""
		from pgappforge.plugins.erp.industry.legal.models import (
			LegalMatter, LegalDocument, Deadline, LegalInvoice,
		)

		matter = session.get(LegalMatter, matter_id)
		if matter is None:
			raise MatterNotFoundError(f"LegalMatter {matter_id!r} not found")

		entries: list[dict] = []

		# Documents
		docs = session.execute(
			select(LegalDocument).where(LegalDocument.matter_id == matter_id)
		).scalars().all()
		for doc in docs:
			dt = doc.executed_at or doc.created_at
			entries.append({
				"date": dt.date().isoformat() if dt else None,
				"event_type": "DOCUMENT",
				"document_type": doc.document_type,
				"title": doc.title,
				"version": doc.version,
				"status": doc.status,
				"id": doc.id,
			})

		# Deadlines
		dls = session.execute(
			select(Deadline).where(Deadline.matter_id == matter_id)
		).scalars().all()
		for dl in dls:
			entries.append({
				"date": dl.deadline_date.isoformat() if dl.deadline_date else None,
				"event_type": "DEADLINE",
				"deadline_type": dl.deadline_type,
				"title": dl.description,
				"is_hard_deadline": dl.is_hard_deadline,
				"status": dl.status,
				"id": dl.id,
			})

		# Invoices
		invs = session.execute(
			select(LegalInvoice).where(LegalInvoice.matter_id == matter_id)
		).scalars().all()
		for inv in invs:
			entries.append({
				"date": inv.billing_period_end.isoformat() if inv.billing_period_end else None,
				"event_type": "INVOICE",
				"invoice_number": inv.invoice_number,
				"title": f"Invoice {inv.invoice_number}",
				"total_cents": inv.total_cents,
				"total_display": format_currency(inv.total_cents),
				"status": inv.status,
				"id": inv.id,
			})

		# Sort by date ascending (None dates go last)
		entries.sort(key=lambda e: e.get("date") or "9999-99-99")
		return entries


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _generate_matter_number(session: Any) -> str:
	"""Generate next sequential matter number MAT-YYYY-NNN."""
	from pgappforge.plugins.erp.industry.legal.models import LegalMatter
	year = datetime.now(timezone.utc).year
	prefix = f"MAT-{year}-"
	count = session.execute(
		sa.select(func.count(LegalMatter.id)).where(
			LegalMatter.matter_number.like(f"{prefix}%")
		)
	).scalar() or 0
	return f"{prefix}{count + 1:04d}"


def _generate_invoice_number(
	tenant_id: str,
	matter_number: str,
	session: Any,
) -> str:
	"""Generate sequential invoice number INV-<matter_number>-NNN."""
	from pgappforge.plugins.erp.industry.legal.models import LegalInvoice
	prefix = f"INV-{matter_number}-"
	count = session.execute(
		sa.select(func.count(LegalInvoice.id)).where(
			LegalInvoice.invoice_number.like(f"{prefix}%"),
			LegalInvoice.tenant_id == tenant_id,
		)
	).scalar() or 0
	return f"{prefix}{count + 1:03d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LegalService",
	"LegalServiceError",
	"MatterNotFoundError",
	"DocumentNotFoundError",
	"TimeEntryNotFoundError",
	"DeadlineNotFoundError",
	"InvoiceNotFoundError",
	"DuplicateMatterNumberError",
	"DuplicateInvoiceNumberError",
	"MatterNotActiveError",
]
