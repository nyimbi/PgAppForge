"""
pgappforge/plugins/erp/industry/procurement/services.py

ProcurementService — stateless business logic for the Public Procurement plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - ContractPayments are immutable (insert-only)
  - Bid evaluation uses weighted criteria scores
  - OCDS release output is spec-compliant JSON (OCDS 1.1)
  - All monetary amounts are integer cents — never float
  - Tender must be ACTIVE before bids are evaluated
  - ProcurementContract awarded only to a bid in SUBMITTED/EVALUATED/SHORTLISTED status
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select

from pgappforge.plugins.erp.foundation.commons import format_currency

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ProcurementServiceError(Exception):
	"""Base error for Procurement domain violations."""


class TenderNotFoundError(ProcurementServiceError):
	"""No TenderNotice with the given id."""


class BidNotFoundError(ProcurementServiceError):
	"""No Bid with the given id."""


class ContractNotFoundError(ProcurementServiceError):
	"""No ProcurementContract with the given id."""


class EntityNotFoundError(ProcurementServiceError):
	"""No ProcuringEntity with the given id."""


class TenderNotActiveError(ProcurementServiceError):
	"""Tender must be ACTIVE to evaluate bids."""


class InvalidBidStatusError(ProcurementServiceError):
	"""Bid status does not permit this operation."""


# ---------------------------------------------------------------------------
# ProcurementService
# ---------------------------------------------------------------------------

class ProcurementService:
	"""Stateless service for Public Procurement OCDS operations."""

	# ------------------------------------------------------------------
	# publish_tender
	# ------------------------------------------------------------------

	def publish_tender(
		self,
		*,
		tenant_id: str,
		ocid: str,
		title: str,
		procuring_entity_id: str,
		procurement_method: str = "OPEN",
		main_procurement_category: str = "GOODS",
		description: str | None = None,
		tender_value_estimate_cents: int | None = None,
		currency_code: str = "USD",
		publication_date: datetime | None = None,
		deadline_date: datetime | None = None,
		eligibility_criteria: str | None = None,
		selection_criteria: str | None = None,
		lots: list | None = None,
		items: list | None = None,
		documents: list | None = None,
		session: Any,
	) -> Any:
		"""Create and publish a TenderNotice, emitting TenderPublishedEvent.

		Sets status=ACTIVE immediately (planning-phase tenders can be created
		with status=PLANNING by passing status explicitly via a direct model
		instantiation before calling this method).

		Returns the created TenderNotice.
		"""
		from pgappforge.plugins.erp.industry.procurement.models import TenderNotice
		from pgappforge.plugins.erp.industry.procurement.events import TenderPublishedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		pub_date = publication_date or datetime.now(timezone.utc)

		notice = TenderNotice(
			tenant_id=tenant_id,
			ocid=ocid,
			title=title,
			procuring_entity_id=procuring_entity_id,
			procurement_method=procurement_method,
			main_procurement_category=main_procurement_category,
			description=description,
			tender_value_estimate_cents=tender_value_estimate_cents,
			currency_code=currency_code,
			publication_date=pub_date,
			deadline_date=deadline_date,
			eligibility_criteria=eligibility_criteria,
			selection_criteria=selection_criteria,
			lots=lots or [],
			items=items or [],
			documents=documents or [],
			status="ACTIVE",
		)
		session.add(notice)
		session.flush()

		emit_event(
			TenderPublishedEvent(
				aggregate_id=notice.id,
				aggregate_type="TenderNotice",
				tenant_id=tenant_id,
				tender_id=notice.id,
				ocid=ocid,
				procuring_entity_id=procuring_entity_id,
				procurement_method=procurement_method,
				main_procurement_category=main_procurement_category,
				tender_value_estimate_cents=tender_value_estimate_cents or 0,
				currency_code=currency_code,
				deadline_date=deadline_date.isoformat() if deadline_date else "",
			),
			session,
		)

		log.info("publish_tender: ocid=%r tender=%r method=%r", ocid, notice.id, procurement_method)
		return notice

	# ------------------------------------------------------------------
	# evaluate_bids
	# ------------------------------------------------------------------

	def evaluate_bids(
		self,
		*,
		tender_id: str,
		criteria_weights: dict[str, float] | None = None,
		session: Any,
	) -> list[dict]:
		"""Score and rank all submitted bids for a tender.

		criteria_weights defaults to {'technical': 0.4, 'financial': 0.6}.
		technical_score is assumed pre-populated on each Bid row (by evaluators).
		financial_score is computed here as an inverse-price ratio:
		    financial_score = (min_price / bid_price) * 100

		Returns list of scored bid dicts sorted by overall_score desc.

		Side effects: updates each Bid.financial_score, .overall_score,
		.status=EVALUATED.

		Raises TenderNotFoundError, TenderNotActiveError.
		"""
		from pgappforge.plugins.erp.industry.procurement.models import Bid, TenderNotice
		from pgappforge.plugins.erp.industry.procurement.events import BidsEvaluatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tender = session.get(TenderNotice, tender_id)
		if tender is None:
			raise TenderNotFoundError(f"TenderNotice {tender_id!r} not found")
		if tender.status != "ACTIVE":
			raise TenderNotActiveError(
				f"Tender {tender_id!r} has status={tender.status!r}; must be ACTIVE to evaluate"
			)

		weights = criteria_weights or {"technical": 0.4, "financial": 0.6}
		tech_w = float(weights.get("technical", 0.4))
		fin_w = float(weights.get("financial", 0.6))

		# Normalise weights
		total_w = tech_w + fin_w
		if total_w > 0:
			tech_w /= total_w
			fin_w /= total_w

		bids = session.execute(
			select(Bid).where(
				Bid.tender_id == tender_id,
				Bid.status.in_(["SUBMITTED", "EVALUATED", "SHORTLISTED"]),
			)
		).scalars().all()

		if not bids:
			return []

		# Compute financial scores: lowest price = 100
		min_price = min(b.bid_price_cents for b in bids)

		results: list[dict] = []
		for bid in bids:
			fin_score = round((min_price / max(bid.bid_price_cents, 1)) * 100, 2)
			tech_score = float(bid.technical_score or 0)
			overall = round(tech_score * tech_w + fin_score * fin_w, 2)

			bid.financial_score = Decimal(str(fin_score))
			bid.overall_score = Decimal(str(overall))
			bid.status = "EVALUATED"

			results.append({
				"bid_id": bid.id,
				"tender_id": tender_id,
				"bidder_id": bid.bidder_id,
				"bid_price_cents": bid.bid_price_cents,
				"currency_code": bid.currency_code,
				"technical_score": float(bid.technical_score or 0),
				"financial_score": fin_score,
				"overall_score": overall,
				"status": "EVALUATED",
			})

		# Rank by overall_score descending
		results.sort(key=lambda r: r["overall_score"], reverse=True)
		for i, r in enumerate(results):
			r["rank"] = i + 1

		emit_event(
			BidsEvaluatedEvent(
				aggregate_id=tender_id,
				aggregate_type="TenderNotice",
				tenant_id=tender.tenant_id,
				tender_id=tender_id,
				ocid=tender.ocid,
				bid_count=len(results),
				ranked_bids=[
					{"bid_id": r["bid_id"], "overall_score": r["overall_score"], "rank": r["rank"]}
					for r in results
				],
			),
			session,
		)

		log.info("evaluate_bids: tender=%r bids=%d criteria_weights=%r", tender_id, len(results), weights)
		return results

	# ------------------------------------------------------------------
	# award_contract
	# ------------------------------------------------------------------

	def award_contract(
		self,
		*,
		bid_id: str,
		title: str | None = None,
		description: str | None = None,
		signed_date: date | None = None,
		start_date: date | None = None,
		end_date: date | None = None,
		performance_bond_pct: Decimal | float = 0,
		session: Any,
	) -> Any:
		"""Award a contract to the winning bid.

		Creates a ProcurementContract, marks the bid AWARDED, marks all other bids
		for the same tender REJECTED, and sets tender status=COMPLETE.

		Returns the created ProcurementContract.

		Raises BidNotFoundError, InvalidBidStatusError.
		"""
		from pgappforge.plugins.erp.industry.procurement.models import Bid, ProcurementContract, TenderNotice
		from pgappforge.plugins.erp.industry.procurement.events import ContractAwardedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		bid = session.get(Bid, bid_id)
		if bid is None:
			raise BidNotFoundError(f"Bid {bid_id!r} not found")
		if bid.status not in ("SUBMITTED", "EVALUATED", "SHORTLISTED"):
			raise InvalidBidStatusError(
				f"Bid {bid_id!r} has status={bid.status!r}; cannot award"
			)

		tender = session.get(TenderNotice, bid.tender_id)
		if tender is None:
			raise TenderNotFoundError(f"TenderNotice {bid.tender_id!r} not found")

		award_id = f"AWARD-{bid.id[:8].upper()}"

		contract = ProcurementContract(
			tenant_id=bid.tenant_id,
			tender_id=bid.tender_id,
			award_id=award_id,
			supplier_id=bid.bidder_id,
			title=title or tender.title,
			description=description or tender.description,
			contract_value_cents=bid.bid_price_cents,
			currency_code=bid.currency_code,
			signed_date=signed_date,
			start_date=start_date,
			end_date=end_date,
			status="PENDING",
			performance_bond_pct=Decimal(str(performance_bond_pct)),
		)
		session.add(contract)
		session.flush()

		# Mark winning bid
		bid.status = "AWARDED"

		# Reject all other bids for this tender
		other_bids = session.execute(
			select(Bid).where(
				Bid.tender_id == bid.tender_id,
				Bid.id != bid_id,
				Bid.status != "REJECTED",
			)
		).scalars().all()
		for other in other_bids:
			other.status = "REJECTED"
			other.disqualification_reason = "ProcurementContract awarded to another bidder"

		# Close tender
		tender.status = "COMPLETE"

		emit_event(
			ContractAwardedEvent(
				aggregate_id=contract.id,
				aggregate_type="ProcurementContract",
				tenant_id=bid.tenant_id,
				contract_id=contract.id,
				tender_id=bid.tender_id,
				ocid=tender.ocid,
				bid_id=bid_id,
				supplier_id=bid.bidder_id,
				contract_value_cents=bid.bid_price_cents,
				currency_code=bid.currency_code,
				award_id=award_id,
			),
			session,
		)

		log.info(
			"award_contract: contract=%r tender=%r supplier=%r value=%d¢",
			contract.id, bid.tender_id, bid.bidder_id, bid.bid_price_cents,
		)
		return contract

	# ------------------------------------------------------------------
	# track_contract_performance
	# ------------------------------------------------------------------

	def track_contract_performance(self, contract_id: str, session: Any) -> dict:
		"""Return performance summary for a contract.

		Returns::

		    {
		        "contract_id": "...",
		        "award_id": "...",
		        "contract_value_cents": 10000000,
		        "total_paid_cents": 4500000,
		        "remaining_cents": 5500000,
		        "spend_pct": 45.0,
		        "milestones": {
		            "total": 5, "met": 2, "missed": 1, "pending": 2
		        },
		        "milestone_detail": [...],
		        "payment_detail": [...],
		    }
		"""
		from pgappforge.plugins.erp.industry.procurement.models import ProcurementContract, ContractMilestone, ContractPayment

		contract = session.get(ProcurementContract, contract_id)
		if contract is None:
			raise ContractNotFoundError(f"ProcurementContract {contract_id!r} not found")

		milestones = session.execute(
			select(ContractMilestone)
			.where(ContractMilestone.contract_id == contract_id)
			.order_by(ContractMilestone.due_date)
		).scalars().all()

		payments = session.execute(
			select(ContractPayment)
			.where(ContractPayment.contract_id == contract_id)
			.order_by(ContractPayment.payment_date)
		).scalars().all()

		total_paid = sum(p.amount_cents for p in payments)
		remaining = max(0, (contract.contract_value_cents or 0) - total_paid)
		spend_pct = (
			round(total_paid / max(contract.contract_value_cents, 1) * 100, 1)
			if contract.contract_value_cents
			else 0.0
		)

		milestone_counts = {"total": len(milestones), "met": 0, "missed": 0, "extended": 0, "pending": 0}
		for m in milestones:
			key = m.status.lower() if m.status.lower() in milestone_counts else "pending"
			milestone_counts[key] = milestone_counts.get(key, 0) + 1

		return {
			"contract_id": contract_id,
			"award_id": contract.award_id,
			"supplier_id": contract.supplier_id,
			"status": contract.status,
			"contract_value_cents": contract.contract_value_cents,
			"currency_code": contract.currency_code,
			"total_paid_cents": total_paid,
			"remaining_cents": remaining,
			"spend_pct": spend_pct,
			"performance_bond_pct": float(contract.performance_bond_pct or 0),
			"milestones": milestone_counts,
			"milestone_detail": [
				{
					"milestone_id": m.id,
					"title": m.title,
					"milestone_type": m.milestone_type,
					"due_date": m.due_date.isoformat(),
					"achieved_date": m.achieved_date.isoformat() if m.achieved_date else None,
					"payment_pct": float(m.payment_pct),
					"status": m.status,
				}
				for m in milestones
			],
			"payment_detail": [
				{
					"payment_id": p.id,
					"payment_date": p.payment_date.isoformat(),
					"amount_cents": p.amount_cents,
					"invoice_reference": p.invoice_reference,
					"milestone_id": p.milestone_id,
				}
				for p in payments
			],
		}

	# ------------------------------------------------------------------
	# generate_ocds_release
	# ------------------------------------------------------------------

	def generate_ocds_release(self, tender_id: str, session: Any) -> dict:
		"""Generate an OCDS 1.1-compliant release JSON for a tender.

		Includes tender, awards (contracts), and parties blocks.
		The release is suitable for publication to a public contracting portal.
		"""
		from pgappforge.plugins.erp.industry.procurement.models import Bid, ProcurementContract, TenderNotice

		tender = session.get(TenderNotice, tender_id)
		if tender is None:
			raise TenderNotFoundError(f"TenderNotice {tender_id!r} not found")

		contracts_rows = session.execute(
			select(ProcurementContract).where(ProcurementContract.tender_id == tender_id)
		).scalars().all()

		bids_rows = session.execute(
			select(Bid).where(Bid.tender_id == tender_id)
		).scalars().all()

		def _money(cents: int | None, currency: str) -> dict:
			return {"amount": round((cents or 0) / 100, 2), "currency": currency}

		release: dict = {
			"ocid": tender.ocid,
			"id": f"{tender.ocid}-release-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
			"date": datetime.now(timezone.utc).isoformat(),
			"tag": ["tender"],
			"initiationType": "tender",
			"parties": [
				{
					"id": tender.procuring_entity_id,
					"roles": ["buyer", "procuringEntity"],
				},
				*[
					{"id": b.bidder_id, "roles": ["tenderer"]}
					for b in bids_rows
				],
			],
			"buyer": {"id": tender.procuring_entity_id},
			"tender": {
				"id": tender.ocid,
				"title": tender.title,
				"description": tender.description,
				"status": tender.status.lower(),
				"procurementMethod": tender.procurement_method.lower(),
				"mainProcurementCategory": tender.main_procurement_category.lower(),
				"value": _money(tender.tender_value_estimate_cents, tender.currency_code),
				"datePublished": tender.publication_date.isoformat() if tender.publication_date else None,
				"tenderPeriod": {
					"endDate": tender.deadline_date.isoformat() if tender.deadline_date else None,
				},
				"eligibilityCriteria": tender.eligibility_criteria,
				"lots": tender.lots or [],
				"items": tender.items or [],
				"documents": tender.documents or [],
				"numberOfTenderers": len(bids_rows),
				"tenderers": [{"id": b.bidder_id} for b in bids_rows],
			},
		}

		if contracts_rows:
			release["tag"] = ["contract"]
			release["awards"] = [
				{
					"id": c.award_id,
					"title": c.title,
					"status": "active",
					"date": c.signed_date.isoformat() if c.signed_date else None,
					"value": _money(c.contract_value_cents, c.currency_code),
					"suppliers": [{"id": c.supplier_id}],
				}
				for c in contracts_rows
			]
			release["contracts"] = [
				{
					"id": c.award_id,
					"awardID": c.award_id,
					"title": c.title,
					"description": c.description,
					"status": c.status.lower(),
					"period": {
						"startDate": c.start_date.isoformat() if c.start_date else None,
						"endDate": c.end_date.isoformat() if c.end_date else None,
					},
					"value": _money(c.contract_value_cents, c.currency_code),
					"dateSigned": c.signed_date.isoformat() if c.signed_date else None,
				}
				for c in contracts_rows
			]

		log.info("generate_ocds_release: ocid=%r", tender.ocid)
		return release

	# ------------------------------------------------------------------
	# calculate_spend_analytics
	# ------------------------------------------------------------------

	def calculate_spend_analytics(
		self,
		*,
		entity_id: str,
		period_year: int,
		session: Any,
	) -> dict:
		"""Aggregate spend analytics for a procuring entity in a calendar year.

		Returns::

		    {
		        "entity_id": "...",
		        "period_year": 2025,
		        "total_spend_cents": 12000000,
		        "by_category": {"GOODS": 5000000, "WORKS": 4000000, "SERVICES": 3000000},
		        "by_method": {"OPEN": 10000000, "DIRECT": 2000000},
		        "by_supplier": [{"supplier_id": "...", "total_cents": ...}, ...],
		        "contract_count": 12,
		        "tender_count": 15,
		    }
		"""
		from pgappforge.plugins.erp.industry.procurement.models import ProcurementContract, ContractPayment, TenderNotice

		year_start = date(period_year, 1, 1)
		year_end = date(period_year, 12, 31)

		# Tenders for this entity in the year
		tenders = session.execute(
			select(TenderNotice).where(
				TenderNotice.procuring_entity_id == entity_id,
				TenderNotice.publication_date >= datetime(period_year, 1, 1, tzinfo=timezone.utc),
				TenderNotice.publication_date <= datetime(period_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
			)
		).scalars().all()
		tender_ids = [t.id for t in tenders]

		# Contracts derived from those tenders
		contracts = []
		if tender_ids:
			contracts = session.execute(
				select(ProcurementContract).where(ProcurementContract.tender_id.in_(tender_ids))
			).scalars().all()
		contract_ids = [c.id for c in contracts]

		# Payments in the year against those contracts
		payments: list[Any] = []
		if contract_ids:
			payments = session.execute(
				select(ContractPayment).where(
					ContractPayment.contract_id.in_(contract_ids),
					ContractPayment.payment_date >= year_start,
					ContractPayment.payment_date <= year_end,
				)
			).scalars().all()

		# Build a lookup: contract_id → tender
		tender_by_id = {t.id: t for t in tenders}
		contract_by_id = {c.id: c for c in contracts}

		by_category: dict[str, int] = {}
		by_method: dict[str, int] = {}
		by_supplier: dict[str, int] = {}
		total_spend = 0

		for p in payments:
			amt = p.amount_cents
			total_spend += amt
			contract = contract_by_id.get(p.contract_id)
			if contract is None:
				continue
			tender = tender_by_id.get(contract.tender_id)
			if tender:
				cat = tender.main_procurement_category
				method = tender.procurement_method
				by_category[cat] = by_category.get(cat, 0) + amt
				by_method[method] = by_method.get(method, 0) + amt
			supplier = contract.supplier_id
			by_supplier[supplier] = by_supplier.get(supplier, 0) + amt

		supplier_list = sorted(
			[{"supplier_id": k, "total_cents": v} for k, v in by_supplier.items()],
			key=lambda x: x["total_cents"],
			reverse=True,
		)

		return {
			"entity_id": entity_id,
			"period_year": period_year,
			"total_spend_cents": total_spend,
			"by_category": by_category,
			"by_method": by_method,
			"by_supplier": supplier_list,
			"contract_count": len(contracts),
			"tender_count": len(tenders),
		}


__all__ = [
	"ProcurementService",
	"ProcurementServiceError",
	"TenderNotFoundError",
	"BidNotFoundError",
	"ContractNotFoundError",
	"EntityNotFoundError",
	"TenderNotActiveError",
	"InvalidBidStatusError",
]
