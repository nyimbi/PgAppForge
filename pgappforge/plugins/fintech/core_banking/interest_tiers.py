"""
pgappforge/plugins/fintech/core_banking/interest_tiers.py

Tiered interest rate support for core banking.

InterestRateTier model
----------------------
Each row defines one tier within a product's rate schedule, keyed by
(tenant_id, product_code, tier_order, effective_from).  Tiers are
open-ended at the top (max_balance_cents IS NULL) and may overlap time
ranges only if effective_from differs — the service always resolves the
*latest effective_from* set as the active one.

InterestRateTierService
-----------------------
  set_tiers()          — atomically replace the current tier schedule.
  get_active_tiers()   — fetch tiers in effect on a given date.
  compute_tiered_rate() — blended weighted-average annual rate for a balance.

Money conventions match the rest of the core banking module:
  - balances are integer cent amounts
  - rates are Decimal percent p.a. (e.g. Decimal("5.25") = 5.25 %)
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	Index,
	Integer,
	Numeric,
	String,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# InterestRateTier — model
# ---------------------------------------------------------------------------

class InterestRateTier(AuditMixin, Model):
	"""One tier within a product's tiered interest-rate schedule.

	Tier boundaries are in integer cents (same unit as all balance fields).
	A NULL max_balance_cents means the tier extends to infinity.

	Example — three-tier SAVINGS schedule:
	  tier 1: 0 – 1_000_000c   → 3.00 % p.a.
	  tier 2: 1_000_000 – 10_000_000c → 5.00 % p.a.
	  tier 3: 10_000_000+ c → 7.00 % p.a.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_interest_tier"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "product_code", "tier_order", "effective_from",
			name="uq_cb_interest_tier_key",
		),
		Index("ix_cb_interest_tier_product", "tenant_id", "product_code"),
		Index("ix_cb_interest_tier_effective", "effective_from", "effective_to"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	product_code = Column(String(30), nullable=False)
	tier_order = Column(Integer, nullable=False)          # 1, 2, 3 … ascending
	min_balance_cents = Column(Integer, nullable=False, default=0)
	max_balance_cents = Column(Integer, nullable=True)    # NULL = unbounded upper
	annual_rate_pct = Column(Numeric(8, 4), nullable=False)
	effective_from = Column(Date, nullable=False)
	effective_to = Column(Date, nullable=True)             # NULL = currently active
	is_promotional = Column(Boolean, nullable=False, default=False)
	promotion_name = Column(String(100), nullable=True)


# ---------------------------------------------------------------------------
# InterestRateTierService
# ---------------------------------------------------------------------------

class InterestRateTierService:
	"""Manage and evaluate tiered interest rate schedules.

	All methods accept an explicit ``session`` (SQLAlchemy Session).
	The service never commits — callers control transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# set_tiers
	# ------------------------------------------------------------------

	def set_tiers(
		self,
		product_code: str,
		tiers: list[dict[str, Any]],
		tenant_id: str,
		session: Session,
		*,
		effective_from: date | None = None,
	) -> list[InterestRateTier]:
		"""Atomically replace the active tier schedule for a product.

		Steps:
		  1. Deactivate current active tiers by setting effective_to = today − 1.
		  2. Insert new tier rows with effective_from = today (or the provided date).

		Parameters
		----------
		product_code : str
		tiers : list of dicts with keys:
		    tier_order         int
		    min_balance_cents  int
		    max_balance_cents  int | None
		    annual_rate_pct    str | Decimal | float
		    is_promotional     bool (optional, default False)
		    promotion_name     str | None (optional)
		tenant_id : str
		session : SQLAlchemy Session
		effective_from : date | None — defaults to today

		Returns
		-------
		list[InterestRateTier] — newly created tier rows (added to session, not committed)
		"""
		from datetime import timedelta

		eff_from = effective_from or date.today()
		deactivate_on = eff_from - timedelta(days=1)

		# Deactivate all currently open tiers for this product+tenant
		session.execute(
			sa.update(InterestRateTier)
			.where(InterestRateTier.tenant_id == tenant_id)
			.where(InterestRateTier.product_code == product_code)
			.where(InterestRateTier.effective_to.is_(None))
			.values(effective_to=deactivate_on)
			.execution_options(synchronize_session="fetch")
		)

		created: list[InterestRateTier] = []
		for t in tiers:
			tier = InterestRateTier(
				tenant_id=tenant_id,
				product_code=product_code,
				tier_order=int(t["tier_order"]),
				min_balance_cents=int(t["min_balance_cents"]),
				max_balance_cents=(
					int(t["max_balance_cents"])
					if t.get("max_balance_cents") is not None
					else None
				),
				annual_rate_pct=Decimal(str(t["annual_rate_pct"])),
				effective_from=eff_from,
				effective_to=None,
				is_promotional=bool(t.get("is_promotional", False)),
				promotion_name=t.get("promotion_name"),
			)
			session.add(tier)
			created.append(tier)

		session.flush()
		log.info(
			"InterestRateTierService.set_tiers: %d tier(s) created for "
			"product=%r tenant=%r effective_from=%s",
			len(created), product_code, tenant_id, eff_from,
		)
		return created

	# ------------------------------------------------------------------
	# get_active_tiers
	# ------------------------------------------------------------------

	def get_active_tiers(
		self,
		product_code: str,
		tenant_id: str,
		session: Session,
		*,
		as_of_date: date | None = None,
	) -> list[InterestRateTier]:
		"""Return tiers in effect on *as_of_date* (defaults to today), ordered by tier_order.

		A tier is active when:
		  effective_from <= as_of_date AND (effective_to IS NULL OR effective_to >= as_of_date)
		"""
		as_of = as_of_date or date.today()
		rows = session.execute(
			select(InterestRateTier)
			.where(InterestRateTier.tenant_id == tenant_id)
			.where(InterestRateTier.product_code == product_code)
			.where(InterestRateTier.effective_from <= as_of)
			.where(
				sa.or_(
					InterestRateTier.effective_to.is_(None),
					InterestRateTier.effective_to >= as_of,
				)
			)
			.order_by(InterestRateTier.tier_order)
		).scalars().all()
		return list(rows)

	# ------------------------------------------------------------------
	# compute_tiered_rate
	# ------------------------------------------------------------------

	def compute_tiered_rate(
		self,
		product_code: str,
		balance_cents: int,
		tenant_id: str,
		session: Session,
	) -> Decimal:
		"""Blended weighted-average annual interest rate for *balance_cents*.

		Algorithm
		---------
		For a balance B and tiers T1, T2, … Tn (each with min_i, max_i, rate_i):
		  portion_i = amount of B that falls within [min_i, max_i]
		  weighted  = sum(portion_i * rate_i)
		  blended   = weighted / B  (if B > 0)

		Example (B = 1_500_000c, 3 tiers):
		  tier1: 0 – 1_000_000c at 3.00 % → portion = 1_000_000c
		  tier2: 1_000_000 – 10_000_000c at 5.00 % → portion = 500_000c
		  blended = (1_000_000*3 + 500_000*5) / 1_500_000
		          = (3_000_000 + 2_500_000) / 1_500_000
		          = 5_500_000 / 1_500_000
		          ≈ 3.6667 %

		Falls back to Decimal("0") for a zero balance (avoids ZeroDivisionError).

		Returns
		-------
		Decimal — blended annual rate in percent (e.g. Decimal("3.6667"))
		"""
		tiers = self.get_active_tiers(product_code, tenant_id, session)
		if not tiers:
			return Decimal("0")

		balance = Decimal(str(balance_cents))
		if balance <= 0:
			# Zero or negative balance: return the rate of the first tier
			return Decimal(str(tiers[0].annual_rate_pct))

		weighted_sum = Decimal("0")
		remaining = balance

		for tier in tiers:
			if remaining <= 0:
				break

			tier_min = Decimal(str(tier.min_balance_cents))
			tier_max = (
				Decimal(str(tier.max_balance_cents))
				if tier.max_balance_cents is not None
				else None
			)
			rate = Decimal(str(tier.annual_rate_pct))

			# Amount of the balance that falls inside this tier
			if tier_max is not None:
				tier_capacity = tier_max - tier_min
				portion = min(remaining, tier_capacity)
			else:
				# Unbounded upper — absorbs all remaining balance
				portion = remaining

			weighted_sum += portion * rate
			remaining -= portion

		blended = (weighted_sum / balance).quantize(
			Decimal("0.0001"), rounding=ROUND_HALF_UP
		)
		return blended


__all__ = [
	"InterestRateTier",
	"InterestRateTierService",
]
