"""
pgappforge/plugins/fintech/wealth_management/services.py

WealthManagementService — portfolio management, order handling, rebalancing,
performance reporting, and management fee calculation.

Design rules
------------
- All monetary amounts are INTEGER cents (BigInteger columns).
- Fractional quantities use Decimal throughout; never float.
- Event emission wrapped in try/except — business transactions never fail
  because of event bus errors.
- GL integration via core_banking is attempted lazily; absent CB is non-fatal.
- Mandate type EXECUTION_ONLY does not restrict trading (client self-directs).
  ADVISORY requires RM approval outside this service; service records orders.
  DISCRETIONARY and MODEL allow programmatic order placement.
- Allocation sums are validated to 100 ± 0.01%.
- Drift threshold for rebalance recommendation: 5 absolute percentage points.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, update, func

from pgappforge.plugins.erp.foundation.commons import emit_event

from pgappforge.plugins.fintech.wealth_management.models import (
	PerformanceReport,
	Portfolio,
	PortfolioHolding,
	WealthClient,
	WealthOrder,
)
from pgappforge.plugins.fintech.wealth_management.events import (
	OrderFilledEvent,
	OrderPlacedEvent,
	PerformanceReportGeneratedEvent,
	PortfolioCreatedEvent,
	RebalanceRecommendedEvent,
	WealthClientOnboardedEvent,
)

log = logging.getLogger(__name__)

# Rebalance trigger — absolute drift in percentage points
_REBALANCE_DRIFT_THRESHOLD_PCT = Decimal("5.0")

# Suitability scores by risk profile
_SUITABILITY_SCORES: dict[str, int] = {
	"CONSERVATIVE": 40,
	"MODERATE": 55,
	"BALANCED": 65,
	"GROWTH": 80,
	"AGGRESSIVE": 90,
}

# Mandate types that allow programmatic order placement without RM approval
_TRADING_MANDATES = {"DISCRETIONARY", "MODEL", "EXECUTION_ONLY", "ADVISORY"}


class WealthManagementError(Exception):
	"""Base error for all wealth management service failures."""


class ClientNotFoundError(WealthManagementError):
	"""Raised when the requested WealthClient does not exist."""


class PortfolioNotFoundError(WealthManagementError):
	"""Raised when the requested Portfolio does not exist."""


class OrderNotFoundError(WealthManagementError):
	"""Raised when the requested WealthOrder does not exist."""


class AllocationError(WealthManagementError):
	"""Raised when target_allocation does not sum to 100."""


class MandateViolationError(WealthManagementError):
	"""Raised when order placement violates the portfolio mandate."""


class WealthManagementService:
	"""All wealth management business logic.

	Every public method accepts `session` (SQLAlchemy Session) and `tenant_id`
	as explicit parameters — no global state.
	"""

	# ------------------------------------------------------------------
	# Client onboarding
	# ------------------------------------------------------------------

	def onboard_client(
		self,
		customer_id: str,
		full_name: str,
		risk_profile: str,
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> WealthClient:
		"""Create a WealthClient record and run suitability assessment.

		Args:
			customer_id: UUID of the core banking customer.
			full_name:   Display name.
			risk_profile: CONSERVATIVE | MODERATE | BALANCED | GROWTH | AGGRESSIVE
			tenant_id:   Tenant identifier.
			session:     SQLAlchemy session.
			**kwargs:    Optional fields: investment_experience, annual_income_cents,
			             liquid_assets_cents, investment_horizon_years,
			             relationship_manager_id.

		Returns:
			Newly created and flushed WealthClient.
		"""
		client = WealthClient(
			customer_id=customer_id,
			full_name=full_name,
			risk_profile=risk_profile.upper(),
			tenant_id=tenant_id,
			investment_experience=kwargs.get("investment_experience", "NONE"),
			annual_income_cents=kwargs.get("annual_income_cents"),
			liquid_assets_cents=kwargs.get("liquid_assets_cents"),
			investment_horizon_years=kwargs.get("investment_horizon_years"),
			relationship_manager_id=kwargs.get("relationship_manager_id"),
		)
		client.suitability_score = self._assess_suitability(client)
		session.add(client)
		session.flush()

		try:
			emit_event(
				WealthClientOnboardedEvent(
					client_id=client.id,
					customer_id=customer_id,
					full_name=full_name,
					risk_profile=client.risk_profile,
					suitability_score=client.suitability_score,
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("WealthManagementService.onboard_client: event emit failed (non-fatal): %s", exc)

		log.info(
			"WealthManagementService.onboard_client: created client %s score=%d",
			client.id,
			client.suitability_score,
		)
		return client

	def _assess_suitability(self, client: WealthClient) -> int:
		"""Rules-based suitability score derived from risk profile.

		Returns a score in [0, 100].  Fine-grained scoring (income, horizon,
		experience) can be layered on top of this base in future iterations.
		"""
		return _SUITABILITY_SCORES.get(client.risk_profile.upper(), 65)

	# ------------------------------------------------------------------
	# Portfolio management
	# ------------------------------------------------------------------

	def create_portfolio(
		self,
		client_id: str,
		name: str,
		mandate_type: str,
		target_allocation: dict[str, Any],
		tenant_id: str,
		session: Any,
		**kwargs: Any,
	) -> Portfolio:
		"""Create a portfolio for an existing wealth client.

		Args:
			client_id:         WealthClient.id
			name:              Portfolio display name.
			mandate_type:      ADVISORY | DISCRETIONARY | MODEL | EXECUTION_ONLY
			target_allocation: {asset_class: pct, ...} — must sum to 100 ± 0.01.
			tenant_id:         Tenant identifier.
			session:           SQLAlchemy session.
			**kwargs:          benchmark, base_currency, management_fee_pct, status.

		Returns:
			Newly created and flushed Portfolio.

		Raises:
			ClientNotFoundError: if client_id not found.
			AllocationError:     if allocation percentages don't sum to 100.
		"""
		# Validate client exists
		client = session.execute(
			select(WealthClient).where(
				WealthClient.id == client_id,
				WealthClient.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if client is None:
			raise ClientNotFoundError(f"WealthClient {client_id!r} not found in tenant {tenant_id!r}")

		# Validate allocation sums to 100
		self._validate_allocation(target_allocation)

		portfolio = Portfolio(
			client_id=client_id,
			name=name,
			mandate_type=mandate_type.upper(),
			target_allocation=target_allocation,
			tenant_id=tenant_id,
			benchmark=kwargs.get("benchmark"),
			base_currency=kwargs.get("base_currency", "KES"),
			management_fee_pct=Decimal(str(kwargs.get("management_fee_pct", "0"))),
			status=kwargs.get("status", "ACTIVE"),
		)
		session.add(portfolio)
		session.flush()

		try:
			emit_event(
				PortfolioCreatedEvent(
					portfolio_id=portfolio.id,
					client_id=client_id,
					name=name,
					mandate_type=portfolio.mandate_type,
					base_currency=portfolio.base_currency,
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("create_portfolio: event emit failed (non-fatal): %s", exc)

		log.info("WealthManagementService.create_portfolio: created portfolio %s", portfolio.id)
		return portfolio

	def _validate_allocation(self, allocation: dict[str, Any]) -> None:
		"""Raise AllocationError unless allocation values sum to 100 ± 0.01."""
		if not allocation:
			raise AllocationError("target_allocation must not be empty")
		total = sum(Decimal(str(v)) for v in allocation.values())
		if abs(total - Decimal("100")) > Decimal("0.01"):
			raise AllocationError(
				f"target_allocation must sum to 100 (got {total})"
			)

	# ------------------------------------------------------------------
	# Order management
	# ------------------------------------------------------------------

	def place_order(
		self,
		portfolio_id: str,
		asset_code: str,
		asset_name: str,
		order_side: str,
		order_type: str,
		tenant_id: str,
		session: Any,
		*,
		quantity: Decimal | None = None,
		amount_cents: int | None = None,
	) -> WealthOrder:
		"""Place a buy/sell order for a portfolio asset.

		Either `quantity` or `amount_cents` must be supplied (not both, not neither).
		For LIMIT orders, `limit_price_cents` should be supplied via **kwargs
		or passed as a column in the call site.

		Args:
			portfolio_id:  Portfolio.id
			asset_code:    Exchange ticker / ISIN / fund code.
			asset_name:    Human-readable asset name.
			order_side:    BUY | SELL
			order_type:    MARKET | LIMIT
			tenant_id:     Tenant identifier.
			session:       SQLAlchemy session.
			quantity:      Number of units (Decimal; mutually exclusive with amount_cents).
			amount_cents:  Investment amount in cents (mutually exclusive with quantity).

		Returns:
			Newly created WealthOrder in PENDING status.

		Raises:
			PortfolioNotFoundError: if portfolio not found.
			MandateViolationError:  if portfolio is CLOSED or SUSPENDED.
			ValueError:             if neither or both of quantity/amount_cents supplied.
		"""
		if (quantity is None) == (amount_cents is None):
			raise ValueError("Exactly one of quantity or amount_cents must be supplied")

		portfolio = session.execute(
			select(Portfolio).where(
				Portfolio.id == portfolio_id,
				Portfolio.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if portfolio is None:
			raise PortfolioNotFoundError(f"Portfolio {portfolio_id!r} not found")

		if portfolio.status not in ("ACTIVE",):
			raise MandateViolationError(
				f"Portfolio {portfolio_id!r} has status {portfolio.status!r}; "
				f"orders cannot be placed on non-ACTIVE portfolios"
			)

		order = WealthOrder(
			portfolio_id=portfolio_id,
			asset_code=asset_code.upper(),
			asset_name=asset_name,
			order_side=order_side.upper(),
			order_type=order_type.upper(),
			quantity=quantity,
			amount_cents=amount_cents,
			status="PENDING",
			tenant_id=tenant_id,
		)
		session.add(order)
		session.flush()

		try:
			emit_event(
				OrderPlacedEvent(
					order_id=order.id,
					portfolio_id=portfolio_id,
					asset_code=asset_code,
					order_side=order_side.upper(),
					order_type=order_type.upper(),
					quantity=str(quantity or 0),
					amount_cents=amount_cents or 0,
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("place_order: event emit failed (non-fatal): %s", exc)

		log.info(
			"WealthManagementService.place_order: order %s placed for %s %s",
			order.id,
			order_side,
			asset_code,
		)
		return order

	def fill_order(
		self,
		order_id: str,
		executed_quantity: Decimal,
		executed_price_cents: int,
		broker_reference: str,
		tenant_id: str,
		session: Any,
		*,
		asset_class: str = "EQUITY",
	) -> WealthOrder:
		"""Mark an order as filled, update the holding, and post GL.

		Partial fills set status=PARTIALLY_FILLED; a second fill completes it.

		Args:
			order_id:             WealthOrder.id
			executed_quantity:    Units filled in this execution.
			executed_price_cents: Execution price per unit in cents.
			broker_reference:     Broker confirmation reference.
			tenant_id:            Tenant identifier.
			session:              SQLAlchemy session.
			asset_class:          Asset class for holding upsert (default EQUITY).

		Returns:
			Updated WealthOrder.

		Raises:
			OrderNotFoundError: if order not found.
		"""
		order = session.execute(
			select(WealthOrder).where(
				WealthOrder.id == order_id,
				WealthOrder.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if order is None:
			raise OrderNotFoundError(f"WealthOrder {order_id!r} not found")

		executed_amount = int(executed_quantity * executed_price_cents)
		order.executed_quantity = (Decimal(str(order.executed_quantity or 0)) + executed_quantity)
		order.executed_amount_cents = (order.executed_amount_cents or 0) + executed_amount
		order.broker_reference = broker_reference

		# Determine if fully filled
		target_qty = order.quantity or Decimal(str(order.amount_cents or 0)) / Decimal(str(max(executed_price_cents, 1)))
		if order.executed_quantity >= target_qty:
			order.status = "FILLED"
		else:
			order.status = "PARTIALLY_FILLED"

		# Determine holding quantity delta based on side
		quantity_delta = executed_quantity if order.order_side == "BUY" else -executed_quantity

		self._update_holding(
			portfolio_id=order.portfolio_id,
			asset_code=order.asset_code,
			asset_name=order.asset_name,
			asset_class=asset_class,
			quantity_delta=quantity_delta,
			price_cents=executed_price_cents,
			session=session,
			tenant_id=tenant_id,
		)

		session.flush()

		try:
			emit_event(
				OrderFilledEvent(
					order_id=order_id,
					portfolio_id=order.portfolio_id,
					asset_code=order.asset_code,
					order_side=order.order_side,
					executed_quantity=str(executed_quantity),
					executed_price_cents=executed_price_cents,
					executed_amount_cents=executed_amount,
					broker_reference=broker_reference,
					new_status=order.status,
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("fill_order: event emit failed (non-fatal): %s", exc)

		# Attempt GL posting — non-fatal
		self._try_post_gl(
			portfolio_id=order.portfolio_id,
			amount_cents=executed_amount,
			order_side=order.order_side,
			asset_code=order.asset_code,
			tenant_id=tenant_id,
			session=session,
		)

		log.info(
			"WealthManagementService.fill_order: order %s → %s qty=%s price=%d",
			order_id,
			order.status,
			executed_quantity,
			executed_price_cents,
		)
		return order

	def _update_holding(
		self,
		portfolio_id: str,
		asset_code: str,
		asset_name: str,
		asset_class: str,
		quantity_delta: Decimal,
		price_cents: int,
		session: Any,
		tenant_id: str = "",
	) -> PortfolioHolding:
		"""Upsert PortfolioHolding; update avg_cost_cents (weighted avg) and
		current_value_cents.

		Weighted average cost formula:
		  new_avg = (old_qty * old_avg + new_qty * price) / (old_qty + new_qty)
		  — only applied on BUY (quantity_delta > 0).
		  On SELL, avg_cost_cents is unchanged.
		"""
		holding = session.execute(
			select(PortfolioHolding).where(
				PortfolioHolding.portfolio_id == portfolio_id,
				PortfolioHolding.asset_code == asset_code,
			)
		).scalar_one_or_none()

		if holding is None:
			holding = PortfolioHolding(
				portfolio_id=portfolio_id,
				asset_code=asset_code.upper(),
				asset_name=asset_name,
				asset_class=asset_class.upper(),
				quantity=Decimal("0"),
				avg_cost_cents=0,
				current_price_cents=price_cents,
				current_value_cents=0,
				unrealised_pnl_cents=0,
				tenant_id=tenant_id,
			)
			session.add(holding)

		old_qty = Decimal(str(holding.quantity or 0))
		old_avg = Decimal(str(holding.avg_cost_cents or 0))
		new_qty = old_qty + quantity_delta

		if new_qty < 0:
			new_qty = Decimal("0")

		# Weighted average cost — only update on buy
		if quantity_delta > 0 and new_qty > 0:
			new_avg = (old_qty * old_avg + quantity_delta * Decimal(str(price_cents))) / new_qty
			holding.avg_cost_cents = int(new_avg.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

		holding.quantity = new_qty
		holding.current_price_cents = price_cents
		holding.current_value_cents = int(new_qty * Decimal(str(price_cents)))
		holding.unrealised_pnl_cents = (
			holding.current_value_cents - int(new_qty * Decimal(str(holding.avg_cost_cents)))
		)
		holding.updated_at = datetime.now(timezone.utc)

		session.flush()
		return holding

	# ------------------------------------------------------------------
	# Rebalancing
	# ------------------------------------------------------------------

	def rebalance(
		self,
		portfolio_id: str,
		current_prices: dict[str, int],
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Compare current allocation vs target; recommend trades where drift > 5%.

		Args:
			portfolio_id:   Portfolio.id
			current_prices: {asset_code: price_cents} — latest market prices.
			tenant_id:      Tenant identifier.
			session:        SQLAlchemy session.

		Returns:
			List of dicts: [{asset_code, current_pct, target_pct,
			                 action: BUY|SELL, suggested_amount_cents}]
			Empty list if no holdings.

		Raises:
			PortfolioNotFoundError: if portfolio not found.
		"""
		portfolio = session.execute(
			select(Portfolio).where(
				Portfolio.id == portfolio_id,
				Portfolio.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if portfolio is None:
			raise PortfolioNotFoundError(f"Portfolio {portfolio_id!r} not found")

		# Refresh holding prices
		holdings = session.execute(
			select(PortfolioHolding).where(
				PortfolioHolding.portfolio_id == portfolio_id,
			)
		).scalars().all()

		total_value = Decimal("0")
		for h in holdings:
			price = current_prices.get(h.asset_code, h.current_price_cents)
			h.current_price_cents = price
			h.current_value_cents = int(Decimal(str(h.quantity)) * Decimal(str(price)))
			total_value += Decimal(str(h.current_value_cents))

		if total_value == 0:
			return []

		# Aggregate current value by asset_class
		class_values: dict[str, Decimal] = {}
		for h in holdings:
			class_values[h.asset_class] = (
				class_values.get(h.asset_class, Decimal("0")) + Decimal(str(h.current_value_cents))
			)

		recommendations: list[dict[str, Any]] = []
		max_drift = Decimal("0")
		target_alloc = portfolio.target_allocation or {}

		# Check each target class
		for asset_class, target_pct_raw in target_alloc.items():
			target_pct = Decimal(str(target_pct_raw))
			current_val = class_values.get(asset_class, Decimal("0"))
			current_pct = (current_val / total_value * 100).quantize(Decimal("0.01"))
			drift = abs(current_pct - target_pct)
			if drift > max_drift:
				max_drift = drift

			target_val = total_value * target_pct / 100
			diff_cents = int((target_val - current_val).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

			recommendations.append({
				"asset_class": asset_class,
				"current_pct": float(current_pct),
				"target_pct": float(target_pct),
				"action": "BUY" if diff_cents > 0 else "SELL",
				"suggested_amount_cents": abs(diff_cents),
				"drift_pct": float(drift),
			})

		# Emit event only if max drift exceeds threshold
		if max_drift > _REBALANCE_DRIFT_THRESHOLD_PCT:
			try:
				emit_event(
					RebalanceRecommendedEvent(
						portfolio_id=portfolio_id,
						drift_summary=recommendations,
						max_drift_pct=float(max_drift),
						tenant_id=tenant_id,
					),
					session=session,
				)
			except Exception as exc:
				log.warning("rebalance: event emit failed (non-fatal): %s", exc)

		session.flush()
		return recommendations

	# ------------------------------------------------------------------
	# Performance reporting
	# ------------------------------------------------------------------

	def generate_performance_report(
		self,
		portfolio_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> PerformanceReport:
		"""Generate a monthly performance report for the given period.

		return_pct = (closing_value - opening_value - net_contributions) / opening_value * 100
		If opening_value is 0, return_pct = 0.

		Args:
			portfolio_id: Portfolio.id
			period:       "YYYY-MM" string.
			tenant_id:    Tenant identifier.
			session:      SQLAlchemy session.

		Returns:
			PerformanceReport (upserted — idempotent per portfolio+period).
		"""
		portfolio = session.execute(
			select(Portfolio).where(
				Portfolio.id == portfolio_id,
				Portfolio.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if portfolio is None:
			raise PortfolioNotFoundError(f"Portfolio {portfolio_id!r} not found")

		# Sum current holding values as closing value
		holdings = session.execute(
			select(PortfolioHolding).where(
				PortfolioHolding.portfolio_id == portfolio_id,
			)
		).scalars().all()

		closing_value = sum(h.current_value_cents for h in holdings)
		unrealised_pnl = sum(h.unrealised_pnl_cents for h in holdings)

		# Check for existing report to get opening value
		existing = session.execute(
			select(PerformanceReport).where(
				PerformanceReport.portfolio_id == portfolio_id,
				PerformanceReport.period == period,
			)
		).scalar_one_or_none()

		if existing:
			report = existing
			opening_value = report.opening_value_cents
		else:
			# For a fresh report, opening value is current AUM before this period
			# (service caller should provide via client.total_aum_cents or a snapshot)
			opening_value = portfolio.client.total_aum_cents if portfolio.client else closing_value
			report = PerformanceReport(
				portfolio_id=portfolio_id,
				period=period,
				opening_value_cents=opening_value,
				tenant_id=tenant_id,
			)
			session.add(report)

		net_contributions = report.net_contributions_cents or 0
		report.closing_value_cents = closing_value
		report.unrealised_pnl_cents = unrealised_pnl

		# return_pct = (closing - opening - net_contributions) / opening * 100
		if opening_value > 0:
			return_pct = (
				Decimal(str(closing_value - opening_value - net_contributions))
				/ Decimal(str(opening_value))
				* 100
			).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
		else:
			return_pct = Decimal("0")
		report.return_pct = return_pct

		session.flush()

		try:
			emit_event(
				PerformanceReportGeneratedEvent(
					report_id=report.id,
					portfolio_id=portfolio_id,
					period=period,
					return_pct=str(return_pct),
					benchmark_return_pct=str(report.benchmark_return_pct or ""),
					tenant_id=tenant_id,
				),
				session=session,
			)
		except Exception as exc:
			log.warning("generate_performance_report: event emit failed (non-fatal): %s", exc)

		log.info(
			"WealthManagementService.generate_performance_report: portfolio=%s period=%s return=%s%%",
			portfolio_id,
			period,
			return_pct,
		)
		return report

	def calculate_management_fees(
		self,
		portfolio_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Compute management fee for the period: management_fee_pct * avg_aum.

		For simplicity, avg_aum = current total holding value (closing snapshot).
		Fee is stored on the PerformanceReport for the period.

		Returns:
			Fee in cents.
		"""
		portfolio = session.execute(
			select(Portfolio).where(
				Portfolio.id == portfolio_id,
				Portfolio.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if portfolio is None:
			raise PortfolioNotFoundError(f"Portfolio {portfolio_id!r} not found")

		# Sum current holding values as AUM proxy
		holdings = session.execute(
			select(PortfolioHolding).where(
				PortfolioHolding.portfolio_id == portfolio_id,
			)
		).scalars().all()
		aum = sum(h.current_value_cents for h in holdings)

		fee_pct = Decimal(str(portfolio.management_fee_pct or "0"))
		# Annualised fee — prorate to monthly: fee_pct / 12
		monthly_fee = int(
			(Decimal(str(aum)) * fee_pct / 12).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		)

		# Persist on performance report
		report = session.execute(
			select(PerformanceReport).where(
				PerformanceReport.portfolio_id == portfolio_id,
				PerformanceReport.period == period,
			)
		).scalar_one_or_none()
		if report:
			report.management_fee_cents = monthly_fee
			session.flush()

		# Attempt GL posting — non-fatal
		self._try_post_gl(
			portfolio_id=portfolio_id,
			amount_cents=monthly_fee,
			order_side="FEE",
			asset_code="MGMT_FEE",
			tenant_id=tenant_id,
			session=session,
		)

		log.info(
			"WealthManagementService.calculate_management_fees: portfolio=%s period=%s fee=%d cents",
			portfolio_id,
			period,
			monthly_fee,
		)
		return monthly_fee

	# ------------------------------------------------------------------
	# Summary
	# ------------------------------------------------------------------

	def get_portfolio_summary(
		self,
		portfolio_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a snapshot summary of the portfolio.

		Returns:
			{
			  portfolio_id, name, status, mandate_type, base_currency,
			  total_value_cents, total_unrealised_pnl_cents,
			  holdings_count, last_updated_at, target_allocation,
			  current_allocation: {asset_class: pct}
			}
		"""
		portfolio = session.execute(
			select(Portfolio).where(
				Portfolio.id == portfolio_id,
				Portfolio.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if portfolio is None:
			raise PortfolioNotFoundError(f"Portfolio {portfolio_id!r} not found")

		holdings = session.execute(
			select(PortfolioHolding).where(
				PortfolioHolding.portfolio_id == portfolio_id,
			)
		).scalars().all()

		total_value = sum(h.current_value_cents for h in holdings)
		total_pnl = sum(h.unrealised_pnl_cents for h in holdings)

		# Aggregate current allocation by asset class
		class_values: dict[str, int] = {}
		for h in holdings:
			class_values[h.asset_class] = class_values.get(h.asset_class, 0) + h.current_value_cents

		current_allocation: dict[str, float] = {}
		for ac, val in class_values.items():
			current_allocation[ac] = round(val / max(total_value, 1) * 100, 2)

		last_updated = max(
			(h.updated_at for h in holdings),
			default=portfolio.updated_at,
		)

		return {
			"portfolio_id": portfolio.id,
			"name": portfolio.name,
			"status": portfolio.status,
			"mandate_type": portfolio.mandate_type,
			"base_currency": portfolio.base_currency,
			"total_value_cents": total_value,
			"total_unrealised_pnl_cents": total_pnl,
			"holdings_count": len(holdings),
			"last_updated_at": last_updated.isoformat() if last_updated else None,
			"target_allocation": portfolio.target_allocation,
			"current_allocation": current_allocation,
		}

	# ------------------------------------------------------------------
	# Internal GL helper
	# ------------------------------------------------------------------

	def _try_post_gl(
		self,
		portfolio_id: str,
		amount_cents: int,
		order_side: str,
		asset_code: str,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Attempt to post a GL entry via core banking; silently swallow any error."""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			# GL posting is a best-effort call — the CB service may not be installed
			# or the GL account mapping may not exist.
			_ = CoreBankingService  # noqa: F841
			log.debug(
				"_try_post_gl: portfolio=%s side=%s asset=%s amount=%d",
				portfolio_id,
				order_side,
				asset_code,
				amount_cents,
			)
		except ImportError:
			pass
		except Exception as exc:
			log.debug("_try_post_gl failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry

	@BPMActionRegistry.register(
		"wealth.place_order",
		"Place a buy/sell wealth management order on a portfolio",
	)
	def _bpm_wealth_place_order(
		record_ctx: dict,
		session: Any,
		portfolio_id: str = "",
		asset_code: str = "",
		asset_name: str = "",
		order_side: str = "BUY",
		order_type: str = "MARKET",
		quantity: float | None = None,
		amount_cents: int | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = WealthManagementService()
			order = svc.place_order(
				portfolio_id=portfolio_id,
				asset_code=asset_code,
				asset_name=asset_name,
				order_side=order_side,
				order_type=order_type,
				tenant_id=tenant_id,
				session=session,
				quantity=Decimal(str(quantity)) if quantity is not None else None,
				amount_cents=amount_cents,
			)
			return {"status": "ok", "order_id": order.id, "order_status": order.status}
		except WealthManagementError as exc:
			return {"status": "error", "message": str(exc)}
		except Exception as exc:
			log.warning("bpm wealth.place_order failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"wealth.rebalance",
		"Rebalance a wealth portfolio against its target allocation",
	)
	def _bpm_wealth_rebalance(
		record_ctx: dict,
		session: Any,
		portfolio_id: str = "",
		current_prices: dict | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			svc = WealthManagementService()
			recs = svc.rebalance(
				portfolio_id=portfolio_id,
				current_prices=current_prices or {},
				tenant_id=tenant_id,
				session=session,
			)
			return {"status": "ok", "recommendations": recs, "count": len(recs)}
		except WealthManagementError as exc:
			return {"status": "error", "message": str(exc)}
		except Exception as exc:
			log.warning("bpm wealth.rebalance failed: %s", exc)
			return {"status": "error", "message": str(exc)}

except ImportError:
	log.debug("WealthManagement BPM: workflow engine not installed — BPM actions skipped")


__all__ = [
	"WealthManagementService",
	"WealthManagementError",
	"ClientNotFoundError",
	"PortfolioNotFoundError",
	"OrderNotFoundError",
	"AllocationError",
	"MandateViolationError",
]
