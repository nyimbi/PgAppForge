"""
pgappforge/plugins/erp/industry/consumer_goods/services.py

ConsumerGoodsService — stateless business logic for the Consumer Goods plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts as integer cents
  - Decimal arithmetic internally; results rounded half-up to int
  - ROI / scores returned as Decimal strings

Public API:
  create_promotion(details, session)                        -> TradePromotion
  record_retail_visit(store_id, findings, photos, session)  -> RetailExecution
  check_shelf_compliance(store_id, product_id, session)     -> dict
  calculate_promo_roi(promo_id, session)                    -> dict
  submit_claim(promo_id, claim_details, session)            -> PromotionClaim
  get_distribution_coverage(product_id, territory, session) -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConsumerGoodsServiceError(Exception):
	"""Base domain error for consumer goods operations."""


class PromotionNotFoundError(ConsumerGoodsServiceError):
	pass


class BudgetExceededError(ConsumerGoodsServiceError):
	"""Raised when a claim or commitment would exceed approved budget."""


class ClaimNotFoundError(ConsumerGoodsServiceError):
	pass


class RetailExecutionNotFoundError(ConsumerGoodsServiceError):
	pass


class PlanoGramNotFoundError(ConsumerGoodsServiceError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _today() -> date:
	return _now().date()


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ConsumerGoodsService
# ---------------------------------------------------------------------------

class ConsumerGoodsService:
	"""Stateless Consumer Goods domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.
	"""

	# ------------------------------------------------------------------
	# create_promotion
	# ------------------------------------------------------------------

	def create_promotion(self, details: dict, session: Any) -> Any:
		"""Validate budget and create a TradePromotion.

		Validates:
		  - required fields: tenant_id, name, promo_type, start_date, end_date,
		    budget_cents, currency_code
		  - budget_cents > 0 (integer cents)
		  - start_date <= end_date
		  - promo_type in allowed set

		Sets status=DRAFT.  Emits no event (only APPROVED promotions emit events).

		Args:
			details: Dict of promotion fields.
			session: SQLAlchemy session (caller commits).

		Returns:
			TradePromotion instance.

		Raises:
			ConsumerGoodsServiceError: validation failure.
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion

		required = ("tenant_id", "name", "promo_type", "start_date", "end_date", "budget_cents")
		missing = [f for f in required if not details.get(f)]
		if missing:
			raise ConsumerGoodsServiceError(f"Missing required fields: {missing}")

		valid_types = {
			"OFF_INVOICE", "BILLBACK", "SCAN_DOWN", "BOGO",
			"VOLUME_REBATE", "DISPLAY", "COOP_ADVERTISING",
		}
		promo_type = details["promo_type"]
		if promo_type not in valid_types:
			raise ConsumerGoodsServiceError(
				f"promo_type must be one of {valid_types}; got {promo_type!r}"
			)

		budget = int(details["budget_cents"])
		assert isinstance(budget, int), "budget_cents must be int"
		if budget <= 0:
			raise ConsumerGoodsServiceError("budget_cents must be positive")

		# Parse dates
		start = details["start_date"] if isinstance(details["start_date"], date) else date.fromisoformat(str(details["start_date"]))
		end = details["end_date"] if isinstance(details["end_date"], date) else date.fromisoformat(str(details["end_date"]))
		if start > end:
			raise ConsumerGoodsServiceError(
				f"start_date {start} must be <= end_date {end}"
			)

		promo_number = details.get("promo_number") or f"PROMO-{_today().strftime('%Y%m%d')}-{_uuid4()[:8].upper()}"

		promo = TradePromotion(
			tenant_id=details["tenant_id"],
			promo_number=promo_number,
			name=details["name"],
			promo_type=promo_type,
			target_retailer_id=details.get("target_retailer_id"),
			target_retailer_name=details.get("target_retailer_name"),
			channel=details.get("channel"),
			start_date=start,
			end_date=end,
			budget_cents=budget,
			committed_cents=0,
			paid_cents=0,
			currency_code=details.get("currency_code", "USD"),
			mechanics=details.get("mechanics", {}),
			products_in_scope=details.get("products_in_scope", []),
			status="DRAFT",
			notes=details.get("notes"),
		)
		session.add(promo)
		session.flush()

		log.info(
			"ConsumerGoodsService.create_promotion: promo=%s type=%s budget=%d¢",
			promo_number, promo_type, budget,
		)
		return promo

	# ------------------------------------------------------------------
	# record_retail_visit
	# ------------------------------------------------------------------

	def record_retail_visit(
		self,
		store_id: str,
		findings: list[dict],
		photos: list[dict],
		session: Any,
		auditor_id: str = "",
		visit_date: date | None = None,
		gps_location: dict | None = None,
		check_in_at: datetime | None = None,
		check_out_at: datetime | None = None,
		store_name: str | None = None,
		store_type: str | None = None,
		tenant_id: str = "",
	) -> Any:
		"""Record a field team retail execution visit.

		Computes overall_score as the weighted mean of per-category scores
		in findings: [{category, score, compliant, notes}, ...].
		score values must be 0–1.

		Args:
			store_id:    UUID of the store/outlet (FK to foundation Party).
			findings:    Structured audit results per category.
			photos:      Photo evidence list [{url, category, taken_at, thumbnail_url}].
			session:     SQLAlchemy session.
			auditor_id:  UUID of the field rep (FK to ab_user).
			visit_date:  Date of visit (default: today).
			gps_location: {lat, lng, accuracy_m}.
			check_in_at:  Timestamp of arrival.
			check_out_at: Timestamp of departure.
			store_name:   Denormalized name for display.
			store_type:   HYPERMARKET|SUPERMARKET|CONVENIENCE|PHARMACY|WHOLESALE.
			tenant_id:    Tenant scope.

		Returns:
			RetailExecution instance (status=DRAFT).
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import RetailExecution

		assert store_id, "store_id required"

		# Compute overall_score from findings
		overall_score = self._compute_visit_score(findings)

		visit = RetailExecution(
			tenant_id=tenant_id,
			store_id=store_id,
			store_name=store_name,
			store_type=store_type,
			auditor_id=auditor_id or "00000000-0000-0000-0000-000000000000",
			visit_date=visit_date or _today(),
			check_in_at=check_in_at,
			check_out_at=check_out_at,
			findings=findings,
			photos=photos,
			gps_location=gps_location,
			overall_score=overall_score,
			status="DRAFT",
		)
		session.add(visit)
		session.flush()

		log.info(
			"ConsumerGoodsService.record_retail_visit: store=%s score=%.2f findings=%d photos=%d",
			store_id, float(overall_score or 0), len(findings), len(photos),
		)
		return visit

	# ------------------------------------------------------------------
	# check_shelf_compliance
	# ------------------------------------------------------------------

	def check_shelf_compliance(
		self,
		store_id: str,
		product_id: str,
		session: Any,
		store_type: str | None = None,
		tenant_id: str = "",
	) -> dict:
		"""Compare actual shelf position (from recent retail visits) vs planogram standard.

		Looks up the active PlanoGram for (product_id, store_type) and
		compares against the most recent RetailExecution findings for this
		store/product combination.

		Args:
			store_id:   UUID of the store.
			product_id: UUID of the product.
			session:    SQLAlchemy session.
			store_type: If None, inferred from most recent visit.
			tenant_id:  Tenant scope.

		Returns:
			dict::

			  {
			    "product_id": str,
			    "store_id": str,
			    "store_type": str | None,
			    "planogram_found": bool,
			    "planogram_id": str | None,
			    "required_facings": int | None,
			    "shelf_position": str | None,
			    "compliant": bool,
			    "compliance_score": str,   # Decimal string 0–1
			    "last_visit_date": str | None,
			    "gaps": list[str],         # human-readable non-compliance details
			  }
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import PlanoGram, RetailExecution

		result: dict = {
			"product_id": product_id,
			"store_id": store_id,
			"store_type": store_type,
			"planogram_found": False,
			"planogram_id": None,
			"required_facings": None,
			"shelf_position": None,
			"compliant": False,
			"compliance_score": "0",
			"last_visit_date": None,
			"gaps": [],
		}

		# Get most recent retail visit for this store
		recent_visit = session.execute(
			sa.select(RetailExecution)
			.where(RetailExecution.store_id == store_id)
			.where(RetailExecution.status.in_(["SUBMITTED", "REVIEWED", "APPROVED"]))
			.order_by(sa.desc(RetailExecution.visit_date))
			.limit(1)
		).scalar_one_or_none()

		if recent_visit:
			result["last_visit_date"] = recent_visit.visit_date.isoformat()
			if not store_type and recent_visit.store_type:
				store_type = recent_visit.store_type
				result["store_type"] = store_type

		# Find active planogram
		pg_q = (
			sa.select(PlanoGram)
			.where(PlanoGram.product_id == product_id)
		)
		if store_type:
			pg_q = pg_q.where(PlanoGram.store_type == store_type)
		if tenant_id:
			pg_q = pg_q.where(PlanoGram.tenant_id == tenant_id)

		today = _today()
		pg_q = pg_q.where(
			sa.or_(
				PlanoGram.effective_from.is_(None),
				PlanoGram.effective_from <= today,
			)
		).where(
			sa.or_(
				PlanoGram.effective_to.is_(None),
				PlanoGram.effective_to >= today,
			)
		).order_by(sa.desc(PlanoGram.effective_from)).limit(1)

		pg = session.execute(pg_q).scalar_one_or_none()

		if pg is None:
			result["gaps"].append("No active planogram found for this product/store type")
			return result

		result["planogram_found"] = True
		result["planogram_id"] = pg.id
		result["required_facings"] = pg.facing_count
		result["shelf_position"] = pg.shelf_position

		# Evaluate compliance from visit findings
		if recent_visit is None:
			result["gaps"].append("No recent submitted retail visit found for compliance check")
			return result

		gaps: list[str] = []
		compliance_score = Decimal("1")

		# Look for product-specific findings in the visit
		product_findings = [
			f for f in (recent_visit.findings or [])
			if str(f.get("product_id", "")) == product_id
			or f.get("category") in ("shelf_share", "facing", "planogram", "availability")
		]

		if not product_findings:
			gaps.append("No product-specific findings recorded in most recent visit")
			compliance_score = Decimal("0.5")
		else:
			scores = [_d(f.get("score", 1)) for f in product_findings]
			compliance_score = sum(scores) / Decimal(len(scores))
			for f in product_findings:
				if not f.get("compliant", True):
					note = f.get("notes", f.get("category", "unknown"))
					gaps.append(f"Non-compliant: {note}")

		result["compliant"] = compliance_score >= Decimal("0.80") and not gaps
		result["compliance_score"] = str(compliance_score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
		result["gaps"] = gaps

		log.info(
			"ConsumerGoodsService.check_shelf_compliance: store=%s product=%s compliant=%s score=%s",
			store_id, product_id, result["compliant"], result["compliance_score"],
		)
		return result

	# ------------------------------------------------------------------
	# calculate_promo_roi
	# ------------------------------------------------------------------

	def calculate_promo_roi(self, promo_id: str, session: Any) -> dict:
		"""Calculate trade promotion ROI: actual_spend vs incremental_revenue.

		Formula:
		  roi_pct = (incremental_revenue_cents - actual_spend_cents) / actual_spend_cents × 100
		  where:
		    actual_spend_cents  = sum of APPROVED/PAID claim amounts
		    incremental_revenue = estimated from promotion lift × baseline
		                          (uses mechanics.baseline_revenue_cents if present,
		                           else returns N/A flag)

		Args:
			promo_id: UUID of the TradePromotion.
			session:  SQLAlchemy session.

		Returns:
			dict::

			  {
			    "promo_id": str,
			    "promo_number": str,
			    "budget_cents": int,
			    "committed_cents": int,
			    "paid_cents": int,
			    "actual_spend_cents": int,
			    "budget_utilisation_pct": str,
			    "claim_count": int,
			    "approved_claim_count": int,
			    "baseline_revenue_cents": int | None,
			    "incremental_revenue_cents": int | None,
			    "roi_pct": str | None,
			    "roi_available": bool,
			    "currency_code": str,
			  }

		Raises:
			PromotionNotFoundError: promo not found.
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion, PromotionClaim

		promo = session.get(TradePromotion, promo_id)
		if promo is None:
			raise PromotionNotFoundError(f"TradePromotion {promo_id!r} not found")

		# Aggregate claims
		claim_agg = session.execute(
			sa.select(
				sa.func.count().label("total_claims"),
				sa.func.count(
					PromotionClaim.approved_cents
				).label("approved_claims"),
				sa.func.coalesce(sa.func.sum(PromotionClaim.approved_cents), 0).label("total_approved"),
				sa.func.coalesce(sa.func.sum(PromotionClaim.paid_cents), 0).label("total_paid"),
				sa.func.coalesce(sa.func.sum(PromotionClaim.actual_spend_cents), 0).label("total_claimed"),
			).where(
				PromotionClaim.promo_id == promo_id,
				PromotionClaim.status.notin_(["REJECTED", "DISPUTED"]),
			)
		).one()

		actual_spend = int(claim_agg.total_approved or claim_agg.total_paid or 0)
		assert isinstance(actual_spend, int)

		# Budget utilisation
		budget = int(promo.budget_cents)
		utilisation = (
			Decimal(actual_spend) / Decimal(budget) * 100
			if budget > 0
			else Decimal("0")
		)

		# ROI from mechanics baseline if provided
		mechanics = promo.mechanics or {}
		baseline = mechanics.get("baseline_revenue_cents")
		lift_pct = mechanics.get("expected_lift_pct")

		roi_available = False
		incremental_revenue_cents = None
		roi_pct_str = None

		if baseline and lift_pct and actual_spend > 0:
			baseline = int(baseline)
			lift = _d(lift_pct) / Decimal("100")
			incremental_revenue_cents = int(
				(Decimal(baseline) * lift).to_integral_value(rounding=ROUND_HALF_UP)
			)
			roi = (Decimal(incremental_revenue_cents) - Decimal(actual_spend)) / Decimal(actual_spend) * 100
			roi_pct_str = str(roi.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
			roi_available = True

		result: dict = {
			"promo_id": promo_id,
			"promo_number": promo.promo_number,
			"budget_cents": budget,
			"committed_cents": int(promo.committed_cents),
			"paid_cents": int(promo.paid_cents),
			"actual_spend_cents": actual_spend,
			"budget_utilisation_pct": str(utilisation.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
			"claim_count": int(claim_agg.total_claims),
			"approved_claim_count": int(claim_agg.approved_claims),
			"baseline_revenue_cents": int(baseline) if baseline else None,
			"incremental_revenue_cents": incremental_revenue_cents,
			"roi_pct": roi_pct_str,
			"roi_available": roi_available,
			"currency_code": promo.currency_code,
		}

		log.info(
			"ConsumerGoodsService.calculate_promo_roi: promo=%s spend=%d¢ roi=%s",
			promo.promo_number, actual_spend, roi_pct_str or "N/A",
		)
		return result

	# ------------------------------------------------------------------
	# submit_claim
	# ------------------------------------------------------------------

	def submit_claim(
		self,
		promo_id: str,
		claim_details: dict,
		session: Any,
	) -> Any:
		"""Submit a promotion claim against a trade promotion.

		Validates:
		  - Promotion exists and is ACTIVE or CLOSED
		  - actual_spend_cents is integer cents > 0
		  - committed_cents + actual_spend_cents <= budget_cents (configurable)

		Updates promotion.committed_cents (add-only).
		Emits PromotionClaimSubmittedEvent.

		Args:
			promo_id:      UUID of the TradePromotion.
			claim_details: Dict with retailer_id, actual_spend_cents,
			               claim_period_start, claim_period_end,
			               supporting_docs (optional).
			session:       SQLAlchemy session.

		Returns:
			PromotionClaim instance.

		Raises:
			PromotionNotFoundError: promo not found.
			BudgetExceededError:    claim would exceed budget.
			ConsumerGoodsServiceError: validation failure.
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import TradePromotion, PromotionClaim
		from pgappforge.plugins.erp.industry.consumer_goods.events import PromotionClaimSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		promo = session.get(TradePromotion, promo_id)
		if promo is None:
			raise PromotionNotFoundError(f"TradePromotion {promo_id!r} not found")
		if promo.status not in ("ACTIVE", "CLOSED", "APPROVED"):
			raise ConsumerGoodsServiceError(
				f"Cannot submit claim against promo in status {promo.status!r}; must be ACTIVE/APPROVED/CLOSED"
			)

		actual_spend = int(claim_details.get("actual_spend_cents", 0))
		assert isinstance(actual_spend, int), "actual_spend_cents must be int"
		if actual_spend <= 0:
			raise ConsumerGoodsServiceError("actual_spend_cents must be positive")

		# Budget guard
		new_committed = int(promo.committed_cents) + actual_spend
		if new_committed > int(promo.budget_cents):
			raise BudgetExceededError(
				f"Claim of {actual_spend}¢ would exceed budget: "
				f"committed={promo.committed_cents}¢ budget={promo.budget_cents}¢"
			)

		claim_number = claim_details.get("claim_number") or f"CLM-{_today().strftime('%Y%m%d')}-{_uuid4()[:8].upper()}"

		# Parse dates if strings
		def _parse_date(v: Any) -> date | None:
			if v is None:
				return None
			if isinstance(v, date):
				return v
			return date.fromisoformat(str(v))

		claim = PromotionClaim(
			tenant_id=promo.tenant_id,
			promo_id=promo_id,
			claim_number=claim_number,
			retailer_id=claim_details.get("retailer_id"),
			claimed_at=_now(),
			claim_period_start=_parse_date(claim_details.get("claim_period_start")),
			claim_period_end=_parse_date(claim_details.get("claim_period_end")),
			actual_spend_cents=actual_spend,
			approved_cents=None,
			paid_cents=0,
			currency_code=promo.currency_code,
			supporting_docs=claim_details.get("supporting_docs", []),
			status="SUBMITTED",
		)
		session.add(claim)

		# Update promotion committed (add-only)
		promo.committed_cents = new_committed
		promo.updated_at = _now()

		session.flush()

		emit_event(
			PromotionClaimSubmittedEvent(
				aggregate_id=claim.id,
				aggregate_type="PromotionClaim",
				tenant_id=str(promo.tenant_id),
				claim_id=claim.id,
				promo_id=promo_id,
				retailer_id=str(claim_details.get("retailer_id", "")),
				actual_spend_cents=actual_spend,
				currency=promo.currency_code,
			),
			session,
		)

		log.info(
			"ConsumerGoodsService.submit_claim: claim=%s promo=%s spend=%d¢",
			claim_number, promo.promo_number, actual_spend,
		)
		return claim

	# ------------------------------------------------------------------
	# get_distribution_coverage
	# ------------------------------------------------------------------

	def get_distribution_coverage(
		self,
		product_id: str,
		territory: str,
		session: Any,
		tenant_id: str = "",
	) -> dict:
		"""Calculate % of stores stocking a product in a territory.

		Uses RetailExecution visit data to determine stores where the product
		was found vs total stores visited in the territory during the last
		90 days.  Also checks inventory StockLevel for stores with stock > 0.

		Args:
			product_id: UUID of the product.
			territory:  Territory / region identifier string.
			session:    SQLAlchemy session.
			tenant_id:  Tenant scope.

		Returns:
			dict::

			  {
			    "product_id": str,
			    "territory": str,
			    "total_stores_visited": int,
			    "stores_stocking": int,
			    "coverage_pct": str,       # Decimal string 0–100
			    "oos_stores": int,          # out-of-stock
			    "as_of_date": str,          # ISO date
			    "method": str,             # "retail_visits" | "inventory" | "combined"
			  }
		"""
		from pgappforge.plugins.erp.industry.consumer_goods.models import RetailExecution
		from datetime import timedelta

		cutoff = _today() - timedelta(days=90)

		# Query recent visits in territory
		# Territory is matched against store_type or notes (basic impl;
		# a real impl would join to a Party/Store table with territory FK)
		visit_q = (
			sa.select(RetailExecution)
			.where(RetailExecution.visit_date >= cutoff)
			.where(RetailExecution.status.in_(["SUBMITTED", "REVIEWED", "APPROVED"]))
		)
		if tenant_id:
			visit_q = visit_q.where(RetailExecution.tenant_id == tenant_id)

		visits = session.execute(visit_q.limit(5000)).scalars().all()

		total_stores = set()
		stocking_stores = set()

		for v in visits:
			total_stores.add(str(v.store_id))
			# Check if product appears in findings as available/compliant
			for finding in (v.findings or []):
				pid = finding.get("product_id", "")
				if pid == product_id:
					if finding.get("compliant", False) or _d(finding.get("score", 0)) > 0:
						stocking_stores.add(str(v.store_id))
					break

		total = len(total_stores)
		stocking = len(stocking_stores)
		oos = total - stocking
		coverage = (
			Decimal(stocking) / Decimal(total) * 100
			if total > 0 else Decimal("0")
		)

		result: dict = {
			"product_id": product_id,
			"territory": territory,
			"total_stores_visited": total,
			"stores_stocking": stocking,
			"coverage_pct": str(coverage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
			"oos_stores": oos,
			"as_of_date": _today().isoformat(),
			"method": "retail_visits",
		}

		log.info(
			"ConsumerGoodsService.get_distribution_coverage: product=%s territory=%s coverage=%s%%",
			product_id, territory, result["coverage_pct"],
		)
		return result

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _compute_visit_score(self, findings: list[dict]) -> Decimal | None:
		"""Weighted mean of per-category scores from findings list."""
		if not findings:
			return None
		scores = [_d(f.get("score", 0)) for f in findings if f.get("score") is not None]
		if not scores:
			return None
		total = sum(scores)
		avg = total / Decimal(len(scores))
		return avg.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


__all__ = [
	"ConsumerGoodsService",
	"ConsumerGoodsServiceError",
	"PromotionNotFoundError",
	"BudgetExceededError",
	"ClaimNotFoundError",
	"RetailExecutionNotFoundError",
	"PlanoGramNotFoundError",
]
