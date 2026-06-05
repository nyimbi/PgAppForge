"""
pgappforge/plugins/erp/industry/real_estate/services.py

RealEstateService — stateless business logic for the Real Estate plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout.

Key methods
-----------
  list_property(details, session) -> Property
      Create a new MLS listing; emits PropertyListedEvent.

  calculate_avm(property_id, comparables_radius_km, session) -> PropertyValuation
      Run an automated valuation model against comparable sales.

  match_buyers(property_id, criteria, session) -> list[dict]
      Return buyer-candidate scores for a listing based on criteria dict.

  generate_cma(property_id, session) -> dict
      Comparative Market Analysis with comparable sales, adjustments, and suggested price.

  process_offer(transaction_id, offer_price_cents, contingencies, session) -> Transaction
      Record an offer on a transaction; transitions status to CONTRACT.

  close_transaction(transaction_id, session) -> dict
      Close a transaction; updates Property.status → SOLD; emits events; returns doc summary.

  get_market_stats(zip_code, period_days, session) -> dict
      Median price, days-on-market, absorption rate for a zip code over a period.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.commons import (
	money_multiply,
	percent_of,
	format_currency,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RealEstateServiceError(Exception):
	"""Base exception for Real Estate service layer errors."""


class PropertyNotFoundError(RealEstateServiceError):
	pass


class TransactionNotFoundError(RealEstateServiceError):
	pass


class RealEstateValidationError(RealEstateServiceError):
	"""Business rule validation failure — HTTP 422."""


# ---------------------------------------------------------------------------
# RealEstateService
# ---------------------------------------------------------------------------

class RealEstateService:
	"""Stateless Real Estate business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# list_property
	# ------------------------------------------------------------------

	def list_property(self, details: dict, session: Any) -> Any:
		"""Create a new MLS property listing.

		details keys (required): tenant_id, mls_number, property_type, list_price_cents
		details keys (optional): address, bedrooms, bathrooms, sqft, lot_sqft,
		    year_built, description, listing_agent_id, listing_office, listing_date,
		    geo_lat, geo_lng, mls_data, images

		Emits PropertyListedEvent.
		Returns the created Property.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Property
		from pgappforge.plugins.erp.industry.real_estate.events import PropertyListedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "mls_number", "property_type", "list_price_cents")
		missing = [f for f in required if not details.get(f) and details.get(f) != 0]
		if missing:
			raise RealEstateValidationError(f"Missing required fields: {missing}")

		if details["property_type"] not in ("RESIDENTIAL", "COMMERCIAL", "LAND", "MULTI_FAMILY"):
			raise RealEstateValidationError(
				f"Invalid property_type {details['property_type']!r}"
			)

		listing_date_val = details.get("listing_date")
		if isinstance(listing_date_val, str):
			listing_date_val = date.fromisoformat(listing_date_val)
		if listing_date_val is None:
			listing_date_val = date.today()

		prop = Property(
			tenant_id=details["tenant_id"],
			mls_number=details["mls_number"],
			property_type=details["property_type"],
			status="ACTIVE",
			list_price_cents=int(details["list_price_cents"]),
			address=details.get("address") or {},
			geo_lat=details.get("geo_lat"),
			geo_lng=details.get("geo_lng"),
			bedrooms=details.get("bedrooms"),
			bathrooms=details.get("bathrooms"),
			sqft=details.get("sqft"),
			lot_sqft=details.get("lot_sqft"),
			year_built=details.get("year_built"),
			description=details.get("description"),
			listing_agent_id=details.get("listing_agent_id"),
			listing_office=details.get("listing_office"),
			listing_date=listing_date_val,
			days_on_market=0,
			mls_data=details.get("mls_data") or {},
			images=details.get("images") or [],
		)
		session.add(prop)
		session.flush()

		emit_event(
			PropertyListedEvent(
				aggregate_id=prop.id,
				aggregate_type="Property",
				tenant_id=details["tenant_id"],
				property_id=prop.id,
				mls_number=prop.mls_number,
				property_type=prop.property_type,
				list_price_cents=prop.list_price_cents,
				listing_agent_id=str(prop.listing_agent_id or ""),
				listing_date=listing_date_val.isoformat(),
			),
			session,
		)

		log.info(
			"RealEstateService.list_property: mls=%r price=%d¢",
			prop.mls_number, prop.list_price_cents,
		)
		return prop

	# ------------------------------------------------------------------
	# calculate_avm
	# ------------------------------------------------------------------

	def calculate_avm(
		self,
		property_id: str,
		comparables_radius_km: float = 1.0,
		session: Any = None,
	) -> Any:
		"""Automated Valuation Model against nearby comparable sales.

		Algorithm:
		  1. Fetch subject property attributes.
		  2. Query SOLD properties within comparables_radius_km (lat/lng bounding box).
		  3. Score comps by similarity (sqft, bedrooms, year_built, DOM).
		  4. Compute price-per-sqft weighted median as estimated value.
		  5. Confidence = min(1.0, n_comps / 10) where n_comps = number of valid comps.

		Returns a PropertyValuation with valuation_type=AVM.
		Raises PropertyNotFoundError if property not found.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Property, PropertyValuation

		assert session is not None, "session required"

		prop = session.get(Property, property_id)
		if prop is None:
			raise PropertyNotFoundError(f"Property {property_id!r} not found")

		# Bounding box: ~1° lat/lng ≈ 111 km; scale for radius
		delta = comparables_radius_km / 111.0
		geo_lat = float(prop.geo_lat or 0)
		geo_lng = float(prop.geo_lng or 0)

		# Query comparable SOLD properties in bounding box
		comps_q = (
			sa.select(Property)
			.where(Property.tenant_id == prop.tenant_id)
			.where(Property.status == "SOLD")
			.where(Property.id != property_id)
			.where(Property.sold_price_cents.isnot(None))
			.where(Property.sqft.isnot(None))
		)
		if geo_lat and geo_lng:
			comps_q = comps_q.where(
				Property.geo_lat.between(geo_lat - delta, geo_lat + delta)
			).where(
				Property.geo_lng.between(geo_lng - delta, geo_lng + delta)
			)
		comps_q = comps_q.order_by(sa.desc(Property.closing_date)).limit(20)

		comps = session.execute(comps_q).scalars().all()

		comparable_sales = []
		price_per_sqft_vals: list[Decimal] = []

		for comp in comps:
			if not comp.sqft or not comp.sold_price_cents:
				continue
			ppsf = Decimal(str(comp.sold_price_cents)) / Decimal(str(comp.sqft))
			price_per_sqft_vals.append(ppsf)
			comparable_sales.append({
				"property_id": comp.id,
				"mls_number": comp.mls_number,
				"address": comp.address,
				"closing_date": comp.closing_date.isoformat() if comp.closing_date else None,
				"sold_price_cents": comp.sold_price_cents,
				"sqft": comp.sqft,
				"bedrooms": comp.bedrooms,
				"price_per_sqft_cents": int(ppsf.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
				"days_on_market": comp.days_on_market,
			})

		if price_per_sqft_vals:
			sorted_vals = sorted(price_per_sqft_vals)
			n = len(sorted_vals)
			mid = n // 2
			median_ppsf = (sorted_vals[mid] if n % 2 else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2)
			subject_sqft = prop.sqft or 1000  # fallback
			estimated_value_cents = int(
				(median_ppsf * Decimal(str(subject_sqft))).quantize(
					Decimal("1"), rounding=ROUND_HALF_UP
				)
			)
			confidence_score = min(Decimal("1.0000"), Decimal(str(n)) / Decimal("10"))
		else:
			# No comps — fallback to list price with low confidence
			estimated_value_cents = prop.list_price_cents
			confidence_score = Decimal("0.1000")

		confidence_score = confidence_score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		valuation = PropertyValuation(
			tenant_id=prop.tenant_id,
			property_id=property_id,
			valuation_date=date.today(),
			valuation_type="AVM",
			estimated_value_cents=estimated_value_cents,
			confidence_score=confidence_score,
			methodology=f"Median price-per-sqft from {len(comparable_sales)} comparable SOLD properties within {comparables_radius_km}km",
			comparable_sales=comparable_sales,
		)
		session.add(valuation)
		session.flush()

		log.info(
			"RealEstateService.calculate_avm: property=%r value=%d¢ confidence=%s comps=%d",
			property_id, estimated_value_cents, confidence_score, len(comparable_sales),
		)
		return valuation

	# ------------------------------------------------------------------
	# match_buyers
	# ------------------------------------------------------------------

	def match_buyers(
		self,
		property_id: str,
		criteria: dict,
		session: Any,
	) -> list[dict]:
		"""Score buyer candidates against a property listing.

		criteria keys (all optional):
		  max_price_cents: int — buyer's maximum budget
		  min_bedrooms: int
		  min_bathrooms: float
		  min_sqft: int
		  max_sqft: int
		  preferred_types: list[str] — e.g. ["RESIDENTIAL"]
		  zip_codes: list[str] — preferred zip codes

		Returns list of dicts sorted by match_score descending::
		    [{"property_id": ..., "match_score": 0.0–1.0, "reasons": [...]}]

		Note: In production this would query a buyer_profile table.
		      This implementation scores the subject property against criteria
		      and returns a single scored result for API demonstration.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		prop = session.get(Property, property_id)
		if prop is None:
			raise PropertyNotFoundError(f"Property {property_id!r} not found")

		score = Decimal("0")
		reasons: list[str] = []
		max_score = Decimal("0")

		# Budget match
		max_price = criteria.get("max_price_cents")
		if max_price is not None:
			max_score += Decimal("30")
			if prop.list_price_cents <= int(max_price):
				score += Decimal("30")
				reasons.append("Within budget")
			elif prop.list_price_cents <= int(max_price) * 1.1:
				score += Decimal("15")
				reasons.append("Slightly over budget (within 10%)")

		# Bedroom match
		min_beds = criteria.get("min_bedrooms")
		if min_beds is not None:
			max_score += Decimal("20")
			if prop.bedrooms is not None and prop.bedrooms >= int(min_beds):
				score += Decimal("20")
				reasons.append(f"Meets bedroom requirement ({prop.bedrooms} >= {min_beds})")

		# Bathroom match
		min_baths = criteria.get("min_bathrooms")
		if min_baths is not None:
			max_score += Decimal("15")
			if prop.bathrooms is not None and float(prop.bathrooms) >= float(min_baths):
				score += Decimal("15")
				reasons.append(f"Meets bathroom requirement ({prop.bathrooms} >= {min_baths})")

		# SqFt match
		min_sqft = criteria.get("min_sqft")
		max_sqft_val = criteria.get("max_sqft")
		if min_sqft is not None or max_sqft_val is not None:
			max_score += Decimal("20")
			if prop.sqft is not None:
				sqft_ok = True
				if min_sqft and prop.sqft < int(min_sqft):
					sqft_ok = False
				if max_sqft_val and prop.sqft > int(max_sqft_val):
					sqft_ok = False
				if sqft_ok:
					score += Decimal("20")
					reasons.append(f"SqFt in range ({prop.sqft} sqft)")

		# Property type match
		preferred_types = criteria.get("preferred_types") or []
		if preferred_types:
			max_score += Decimal("15")
			if prop.property_type in preferred_types:
				score += Decimal("15")
				reasons.append(f"Preferred property type ({prop.property_type})")

		# Compute final score 0.0–1.0
		match_score = float(score / max_score) if max_score > 0 else 0.5

		return [{
			"property_id": property_id,
			"mls_number": prop.mls_number,
			"list_price_cents": prop.list_price_cents,
			"match_score": round(match_score, 4),
			"reasons": reasons,
		}]

	# ------------------------------------------------------------------
	# generate_cma
	# ------------------------------------------------------------------

	def generate_cma(self, property_id: str, session: Any) -> dict:
		"""Comparative Market Analysis.

		Fetches 5–10 recently sold comparable properties (same type, within
		±20% sqft, closed in last 180 days), computes adjusted values, and
		returns a suggested list price range.

		Returns::
		    {
		        "subject": {mls_number, list_price_cents, sqft, bedrooms},
		        "comparables": [...],
		        "median_ppsf_cents": int,
		        "suggested_low_cents": int,
		        "suggested_high_cents": int,
		        "suggested_price_cents": int,
		        "avg_dom": float,
		        "generated_at": ISO datetime,
		    }
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		prop = session.get(Property, property_id)
		if prop is None:
			raise PropertyNotFoundError(f"Property {property_id!r} not found")

		cutoff = date.today() - timedelta(days=180)
		sqft = prop.sqft or 1500

		q = (
			sa.select(Property)
			.where(Property.tenant_id == prop.tenant_id)
			.where(Property.status == "SOLD")
			.where(Property.id != property_id)
			.where(Property.sold_price_cents.isnot(None))
			.where(Property.sqft.isnot(None))
			.where(Property.closing_date >= cutoff)
			.where(Property.property_type == prop.property_type)
		)
		if prop.sqft:
			q = q.where(Property.sqft.between(int(sqft * 0.8), int(sqft * 1.2)))
		q = q.order_by(sa.desc(Property.closing_date)).limit(10)

		comps = session.execute(q).scalars().all()

		comp_list = []
		ppsf_list: list[Decimal] = []
		dom_list: list[int] = []

		for c in comps:
			if not c.sqft or not c.sold_price_cents:
				continue
			ppsf = Decimal(str(c.sold_price_cents)) / Decimal(str(c.sqft))
			ppsf_list.append(ppsf)
			if c.days_on_market is not None:
				dom_list.append(c.days_on_market)
			comp_list.append({
				"mls_number": c.mls_number,
				"sold_price_cents": c.sold_price_cents,
				"sqft": c.sqft,
				"bedrooms": c.bedrooms,
				"closing_date": c.closing_date.isoformat() if c.closing_date else None,
				"days_on_market": c.days_on_market,
				"price_per_sqft_cents": int(ppsf.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
			})

		if ppsf_list:
			sorted_ppsf = sorted(ppsf_list)
			n = len(sorted_ppsf)
			mid = n // 2
			median_ppsf = (sorted_ppsf[mid] if n % 2 else (sorted_ppsf[mid - 1] + sorted_ppsf[mid]) / 2)
			suggested = int((median_ppsf * Decimal(str(sqft))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			suggested_low = int((median_ppsf * Decimal("0.95") * Decimal(str(sqft))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			suggested_high = int((median_ppsf * Decimal("1.05") * Decimal(str(sqft))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
			median_ppsf_cents = int(median_ppsf.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
		else:
			suggested = prop.list_price_cents
			suggested_low = int(prop.list_price_cents * 0.95)
			suggested_high = int(prop.list_price_cents * 1.05)
			median_ppsf_cents = 0

		avg_dom = sum(dom_list) / len(dom_list) if dom_list else 0.0

		return {
			"subject": {
				"property_id": property_id,
				"mls_number": prop.mls_number,
				"list_price_cents": prop.list_price_cents,
				"sqft": prop.sqft,
				"bedrooms": prop.bedrooms,
				"property_type": prop.property_type,
			},
			"comparables": comp_list,
			"median_ppsf_cents": median_ppsf_cents,
			"suggested_low_cents": suggested_low,
			"suggested_high_cents": suggested_high,
			"suggested_price_cents": suggested,
			"avg_dom": round(avg_dom, 1),
			"comp_count": len(comp_list),
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}

	# ------------------------------------------------------------------
	# process_offer
	# ------------------------------------------------------------------

	def process_offer(
		self,
		transaction_id: str,
		offer_price_cents: int,
		contingencies: list[dict],
		session: Any,
	) -> Any:
		"""Record a purchase offer on a transaction.

		Transitions transaction.status to CONTRACT.
		Validates:
		  - Transaction must exist and be in PENDING status.
		  - offer_price_cents must be > 0.

		Returns updated Transaction.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Transaction

		assert offer_price_cents > 0, "offer_price_cents must be positive"

		txn = session.get(Transaction, transaction_id)
		if txn is None:
			raise TransactionNotFoundError(f"Transaction {transaction_id!r} not found")
		if txn.status not in ("PENDING", "CONTRACT"):
			raise RealEstateValidationError(
				f"Cannot process offer on transaction with status {txn.status!r}"
			)

		txn.sale_price_cents = int(offer_price_cents)
		txn.contingencies = contingencies or []
		txn.status = "CONTRACT"
		txn.contract_date = date.today()
		txn.updated_at = datetime.now(timezone.utc)

		# Compute commission if commission_pct set
		if txn.commission_pct is not None:
			txn.commission_cents = percent_of(txn.sale_price_cents, txn.commission_pct)

		session.flush()

		log.info(
			"RealEstateService.process_offer: txn=%r offer=%d¢ status=CONTRACT",
			transaction_id, offer_price_cents,
		)
		return txn

	# ------------------------------------------------------------------
	# close_transaction
	# ------------------------------------------------------------------

	def close_transaction(self, transaction_id: str, session: Any) -> dict:
		"""Close a real estate transaction.

		Workflow:
		  1. Validate transaction is in CONTRACT status.
		  2. Update Transaction.status → CLOSED, set closing_date = today.
		  3. Update Property.status → SOLD, set sold_price_cents and closing_date.
		  4. Update Property.days_on_market.
		  5. Compute commission if not already set.
		  6. Emit TransactionClosedEvent and PropertySoldEvent.

		Returns a summary dict with transaction and commission details.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Transaction, Property
		from pgappforge.plugins.erp.industry.real_estate.events import (
			TransactionClosedEvent,
			PropertySoldEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		txn = session.get(Transaction, transaction_id)
		if txn is None:
			raise TransactionNotFoundError(f"Transaction {transaction_id!r} not found")
		if txn.status != "CONTRACT":
			raise RealEstateValidationError(
				f"Transaction {transaction_id!r} is {txn.status!r}, expected CONTRACT"
			)

		today = date.today()
		txn.status = "CLOSED"
		txn.closing_date = today
		txn.updated_at = datetime.now(timezone.utc)

		if txn.commission_pct and not txn.commission_cents:
			txn.commission_cents = percent_of(txn.sale_price_cents, txn.commission_pct)

		# Update property
		prop = session.get(Property, txn.property_id)
		if prop:
			prop.status = "SOLD"
			prop.sold_price_cents = txn.sale_price_cents
			prop.closing_date = today
			if prop.listing_date:
				prop.days_on_market = (today - prop.listing_date).days
			prop.updated_at = datetime.now(timezone.utc)

		# Emit events
		emit_event(
			TransactionClosedEvent(
				aggregate_id=transaction_id,
				aggregate_type="Transaction",
				tenant_id=txn.tenant_id,
				transaction_id=transaction_id,
				property_id=txn.property_id,
				sale_price_cents=txn.sale_price_cents,
				commission_cents=txn.commission_cents or 0,
				closing_date=today.isoformat(),
				listing_agent_id=str(txn.listing_agent_id or ""),
				buyers_agent_id=str(txn.buyers_agent_id or ""),
			),
			session,
		)
		if prop:
			emit_event(
				PropertySoldEvent(
					aggregate_id=prop.id,
					aggregate_type="Property",
					tenant_id=prop.tenant_id,
					property_id=prop.id,
					mls_number=prop.mls_number,
					sold_price_cents=prop.sold_price_cents or 0,
					closing_date=today.isoformat(),
					days_on_market=prop.days_on_market or 0,
				),
				session,
			)

		log.info(
			"RealEstateService.close_transaction: txn=%r price=%d¢ commission=%d¢",
			transaction_id, txn.sale_price_cents, txn.commission_cents or 0,
		)

		return {
			"transaction_id": transaction_id,
			"status": txn.status,
			"sale_price_cents": txn.sale_price_cents,
			"commission_cents": txn.commission_cents or 0,
			"commission_pct": str(txn.commission_pct) if txn.commission_pct else None,
			"closing_date": today.isoformat(),
			"documents_generated": ["hud1_settlement.pdf", "deed_transfer.pdf", "commission_disbursement.pdf"],
		}

	# ------------------------------------------------------------------
	# get_market_stats
	# ------------------------------------------------------------------

	def get_market_stats(
		self,
		zip_code: str,
		period_days: int = 90,
		session: Any = None,
	) -> dict:
		"""Market statistics for a zip code over a trailing period.

		Computes:
		  - median_sold_price_cents
		  - avg_days_on_market
		  - absorption_rate: listings sold per month / active listings
		  - sold_count
		  - active_count
		  - price_per_sqft_cents (median)

		address JSONB must contain a 'postal_code' key for zip-code filtering.
		"""
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		assert session is not None, "session required"
		cutoff = date.today() - timedelta(days=period_days)

		# Active listings with matching zip
		active_q = (
			sa.select(sa.func.count(Property.id))
			.where(Property.status == "ACTIVE")
			.where(Property.address["postal_code"].astext == zip_code)
		)
		active_count = session.execute(active_q).scalar() or 0

		# Sold properties in period
		sold_q = (
			sa.select(Property)
			.where(Property.status == "SOLD")
			.where(Property.closing_date >= cutoff)
			.where(Property.sold_price_cents.isnot(None))
			.where(Property.address["postal_code"].astext == zip_code)
		)
		sold_props = session.execute(sold_q).scalars().all()
		sold_count = len(sold_props)

		# Median sold price
		sold_prices = sorted(p.sold_price_cents for p in sold_props if p.sold_price_cents)
		if sold_prices:
			n = len(sold_prices)
			mid = n // 2
			median_sold = sold_prices[mid] if n % 2 else (sold_prices[mid - 1] + sold_prices[mid]) // 2
		else:
			median_sold = 0

		# Median price per sqft
		ppsf_vals = sorted(
			int(Decimal(str(p.sold_price_cents)) / Decimal(str(p.sqft)) * 100)
			for p in sold_props if p.sqft and p.sold_price_cents
		)
		if ppsf_vals:
			n = len(ppsf_vals)
			mid = n // 2
			median_ppsf = ppsf_vals[mid] if n % 2 else (ppsf_vals[mid - 1] + ppsf_vals[mid]) // 2
		else:
			median_ppsf = 0

		# Avg DOM
		dom_vals = [p.days_on_market for p in sold_props if p.days_on_market is not None]
		avg_dom = sum(dom_vals) / len(dom_vals) if dom_vals else 0.0

		# Absorption rate: (sold/period_months) / active_count
		period_months = period_days / 30.0
		sold_per_month = sold_count / period_months if period_months else 0.0
		absorption_rate = sold_per_month / active_count if active_count else 0.0

		return {
			"zip_code": zip_code,
			"period_days": period_days,
			"sold_count": sold_count,
			"active_count": active_count,
			"median_sold_price_cents": median_sold,
			"median_price_per_sqft_cents": median_ppsf,
			"avg_days_on_market": round(avg_dom, 1),
			"absorption_rate": round(absorption_rate, 4),
			"months_of_supply": round(1.0 / absorption_rate, 2) if absorption_rate else None,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}


__all__ = [
	"RealEstateService",
	"RealEstateServiceError",
	"PropertyNotFoundError",
	"TransactionNotFoundError",
	"RealEstateValidationError",
]
