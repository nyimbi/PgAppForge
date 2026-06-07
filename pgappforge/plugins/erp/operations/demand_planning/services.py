"""
pgappforge/plugins/erp/operations/demand_planning/services.py

DemandPlanningService — stateless business logic for demand forecasting.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Quantity arithmetic uses Decimal throughout — never float.
Holt-Winters implementation uses pure Decimal arithmetic with no numpy/scipy
dependency, making it portable to any deployment target.

Public API:
  record_actual(product_id, period, actual_qty, tenant_id, session)
    -> DemandHistory

  generate_forecast(product_id, tenant_id, session, *, method, horizon_periods,
                    lookback_periods)
    -> DemandForecast

  approve_forecast(forecast_id, approver_id, session)
    -> DemandForecast

  compute_accuracy(product_id, from_period, to_period, tenant_id, session)
    -> dict

  get_approved_forecast(product_id, period, tenant_id, session)
    -> Decimal | None

BPM actions registered:
  ops.demand_planning.generate_forecast — Generate demand forecast for product
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	ForecastAccuracyComputedEvent,
	ForecastApprovedEvent,
	ForecastCreatedEvent,
)
from .models import DemandForecast, DemandHistory

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Holt-Winters smoothing parameters
# ---------------------------------------------------------------------------

_HW_ALPHA = Decimal("0.3")		# level smoothing
_HW_BETA  = Decimal("0.1")		# trend smoothing
_HW_GAMMA = Decimal("0.2")		# seasonal smoothing
_HW_SEASON_LEN = 12			# monthly seasonality
_ES_ALPHA = Decimal("0.3")		# exponential smoothing alpha
_PI_Z = Decimal("1.96")		# 95 % prediction interval z-score


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DemandPlanningError(Exception):
	"""Base error for demand planning service layer."""


class ForecastNotFoundError(DemandPlanningError):
	pass


class InsufficientHistoryError(DemandPlanningError):
	"""Raised when not enough history exists to compute the requested method."""


class InvalidForecastStatusError(DemandPlanningError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _mean(values: list[Decimal]) -> Decimal:
	if not values:
		return Decimal("0")
	return sum(values, Decimal("0")) / Decimal(len(values))


def _std_dev(values: list[Decimal], mean: Decimal | None = None) -> Decimal:
	"""Population standard deviation using Decimal arithmetic."""
	if len(values) < 2:
		return Decimal("0")
	mu = mean if mean is not None else _mean(values)
	variance = sum((v - mu) ** 2 for v in values) / Decimal(len(values))
	# Newton-Raphson sqrt for Decimal — converges in < 20 iterations
	x = variance
	if x == 0:
		return Decimal("0")
	guess = Decimal(str(float(x) ** 0.5))
	for _ in range(25):
		next_guess = (guess + x / guess) / 2
		if abs(next_guess - guess) < Decimal("1e-10"):
			guess = next_guess
			break
		guess = next_guess
	return guess


def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: non-fatal event emit failure for %s: %s", type(event).__name__, exc)


def _build_period_label(base_period: str, offset: int) -> str:
	"""Compute period label offset months from base_period (YYYY-MM format).

	Handles year rollover correctly.
	"""
	try:
		year, month = int(base_period[:4]), int(base_period[5:7])
		month += offset
		while month > 12:
			month -= 12
			year += 1
		return f"{year:04d}-{month:02d}"
	except (ValueError, IndexError):
		# Fallback: append offset as suffix for non-standard period formats
		return f"{base_period}+{offset}"


# ---------------------------------------------------------------------------
# Forecast algorithm implementations
# ---------------------------------------------------------------------------

def _moving_average(
	history: list[Decimal],
	horizon: int,
	lookback: int,
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
	"""Simple moving average forecast.

	Returns (forecasts, lower_bounds, upper_bounds) — all as Decimal lists.
	forecast_qty = mean of last `lookback` periods, constant across horizon.
	Prediction interval: ±1.96 * std_dev of last `lookback` actuals.
	"""
	window = history[-lookback:] if len(history) >= lookback else history
	mu = _mean(window)
	sigma = _std_dev(window, mean=mu)
	half_width = _PI_Z * sigma

	forecasts = [mu] * horizon
	lower = [mu - half_width] * horizon
	upper = [mu + half_width] * horizon
	return forecasts, lower, upper


def _exponential_smoothing(
	history: list[Decimal],
	horizon: int,
	alpha: Decimal = _ES_ALPHA,
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
	"""Single exponential smoothing (SES).

	S_t = alpha * y_{t-1} + (1 - alpha) * S_{t-1}
	Initialised with the mean of the first half of history (or first value).
	Residuals used to compute prediction intervals.
	"""
	if not history:
		return ([Decimal("0")] * horizon, [Decimal("0")] * horizon, [Decimal("0")] * horizon)

	# Initialise with mean of first half
	init_len = max(1, len(history) // 2)
	s = _mean(history[:init_len])

	residuals: list[Decimal] = []
	for actual in history[init_len:]:
		forecast = s
		s = alpha * actual + (Decimal("1") - alpha) * s
		residuals.append(actual - forecast)

	sigma = _std_dev(residuals) if residuals else Decimal("0")
	half_width = _PI_Z * sigma

	# All future periods get the last smoothed value
	forecasts = [s] * horizon
	lower = [s - half_width] * horizon
	upper = [s + half_width] * horizon
	return forecasts, lower, upper


def _holt_winters_additive(
	history: list[Decimal],
	horizon: int,
	alpha: Decimal = _HW_ALPHA,
	beta:  Decimal = _HW_BETA,
	gamma: Decimal = _HW_GAMMA,
	m: int = _HW_SEASON_LEN,
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
	"""Holt-Winters additive triple exponential smoothing (monthly seasonality).

	Equations (additive):
	  Level:    L_t = alpha * (y_t - S_{t-m}) + (1-alpha) * (L_{t-1} + T_{t-1})
	  Trend:    T_t = beta  * (L_t - L_{t-1}) + (1-beta)  * T_{t-1}
	  Seasonal: S_t = gamma * (y_t - L_t)     + (1-gamma) * S_{t-m}
	  Forecast: (L + h*T) + S_{t-m + ((h-1) mod m) + 1}

	Initialisation:
	  Requires at least 2 full seasons (2*m observations) for seasonal indices.
	  Falls back to exponential smoothing when history is insufficient.

	All arithmetic is Decimal — no float intermediates.
	"""
	if len(history) < 2 * m:
		# Not enough history for Holt-Winters — fall back to ES
		log.debug(
			"_holt_winters_additive: insufficient history (%d < %d) — falling back to ES",
			len(history), 2 * m,
		)
		return _exponential_smoothing(history, horizon, alpha=alpha)

	# --- Initialisation ---
	# Level: mean of first season
	L = _mean(history[:m])

	# Trend: mean of (season 2 means - season 1 means) / m
	season1_means = [_mean(history[i * m:(i + 1) * m]) for i in range(len(history) // m)]
	if len(season1_means) >= 2:
		T = (season1_means[-1] - season1_means[0]) / Decimal(max(1, len(season1_means) - 1)) / Decimal(m)
	else:
		T = Decimal("0")

	# Seasonal indices: average deviation per period within a season
	# Use first two complete seasons
	S: list[Decimal] = []
	for i in range(m):
		vals = [history[i + j * m] for j in range(len(history) // m) if i + j * m < len(history)]
		avg = _mean(vals)
		S.append(avg - L if L != 0 else Decimal("0"))

	# Extend S buffer to cover full history
	# We need a circular buffer of length m; replicate initial S to cover training
	S_buf: list[Decimal] = list(S)

	residuals: list[Decimal] = []

	# --- Training pass ---
	for t, y in enumerate(history):
		s_idx = t % m
		forecast_t = L + T + S_buf[s_idx]
		residuals.append(y - forecast_t)

		L_prev = L
		L = alpha * (y - S_buf[s_idx]) + (Decimal("1") - alpha) * (L + T)
		T = beta * (L - L_prev) + (Decimal("1") - beta) * T
		# Update seasonal for this period
		S_buf[s_idx] = gamma * (y - L) + (Decimal("1") - gamma) * S_buf[s_idx]

	# --- Forecast ---
	sigma = _std_dev(residuals) if residuals else Decimal("0")
	half_width = _PI_Z * sigma

	forecasts: list[Decimal] = []
	lower: list[Decimal] = []
	upper: list[Decimal] = []
	n = len(history)

	for h in range(1, horizon + 1):
		s_idx = (n - m + ((h - 1) % m)) % m
		f = L + Decimal(h) * T + S_buf[s_idx]
		# Clamp negative forecasts to 0 — demand cannot be negative
		f = max(f, Decimal("0"))
		forecasts.append(f)
		lower.append(max(f - half_width, Decimal("0")))
		upper.append(f + half_width)

	return forecasts, lower, upper


# ---------------------------------------------------------------------------
# DemandPlanningService
# ---------------------------------------------------------------------------

class DemandPlanningService:
	"""Demand planning and forecasting service.

	Stateless — all state lives in the database.  Session is always passed
	explicitly; never stored on the instance.
	"""

	# -----------------------------------------------------------------------
	# record_actual
	# -----------------------------------------------------------------------

	@staticmethod
	def record_actual(
		product_id: str,
		period: str,
		actual_qty: Any,
		tenant_id: str,
		session: Any,
		*,
		source: str = "SALES_ORDER",
		notes: str | None = None,
	) -> DemandHistory:
		"""Upsert actual demand for a product/period.

		If a record already exists for (tenant_id, product_id, period), it is
		updated in-place (actual_qty and source).  Otherwise a new row is created.

		Returns the DemandHistory record (not yet committed).
		"""
		assert product_id, "product_id must be non-empty"
		assert period, "period must be non-empty"
		assert tenant_id, "tenant_id must be non-empty"
		qty = _d(actual_qty)
		assert qty >= 0, "actual_qty must be non-negative"

		existing: DemandHistory | None = session.execute(
			sa.select(DemandHistory).where(
				DemandHistory.tenant_id == tenant_id,
				DemandHistory.product_id == product_id,
				DemandHistory.period == period,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.actual_qty = qty
			existing.source = source
			if notes is not None:
				existing.notes = notes
			session.flush()
			log.debug(
				"DemandPlanningService.record_actual: updated product=%s period=%s qty=%s",
				product_id, period, qty,
			)
			return existing

		record = DemandHistory(
			tenant_id=tenant_id,
			product_id=product_id,
			period=period,
			actual_qty=qty,
			source=source,
			notes=notes,
		)
		session.add(record)
		session.flush()
		log.debug(
			"DemandPlanningService.record_actual: created product=%s period=%s qty=%s",
			product_id, period, qty,
		)
		return record

	# -----------------------------------------------------------------------
	# generate_forecast
	# -----------------------------------------------------------------------

	@staticmethod
	@BPMActionRegistry.register(
		"ops.demand_planning.generate_forecast",
		"Generate demand forecast for product",
	)
	def generate_forecast(
		product_id: str,
		tenant_id: str,
		session: Any,
		*,
		method: str = "MOVING_AVERAGE",
		horizon_periods: int = 12,
		lookback_periods: int = 6,
	) -> DemandForecast:
		"""Generate a demand forecast for a product using the specified method.

		Supported methods:
		  MOVING_AVERAGE        — constant forecast = mean of last N periods
		  EXPONENTIAL_SMOOTHING — SES with alpha=0.3
		  HOLT_WINTERS          — additive triple ES with monthly seasonality
		  MANUAL                — creates an empty DRAFT forecast for manual fill

		Steps:
		  1. Load DemandHistory ordered by period ascending.
		  2. Apply algorithm to produce per-period forecast, lower, upper.
		  3. Supersede any existing DRAFT/APPROVED forecasts for same product.
		  4. Persist DemandForecast with periods JSONB.
		  5. Emit ForecastCreatedEvent.

		Returns:
		  DemandForecast — not yet committed; caller commits.

		Raises:
		  InsufficientHistoryError — fewer than 2 history records for non-MANUAL
		"""
		assert product_id, "product_id must be non-empty"
		assert tenant_id, "tenant_id must be non-empty"
		assert horizon_periods > 0, "horizon_periods must be positive"
		valid_methods = {"MOVING_AVERAGE", "EXPONENTIAL_SMOOTHING", "HOLT_WINTERS", "MANUAL"}
		assert method in valid_methods, f"method must be one of {valid_methods}"

		# Load history, ordered by period
		history_rows: list[DemandHistory] = session.execute(
			sa.select(DemandHistory)
			.where(
				DemandHistory.tenant_id == tenant_id,
				DemandHistory.product_id == product_id,
			)
			.order_by(DemandHistory.period.asc())
		).scalars().all()

		if method != "MANUAL" and len(history_rows) < 2:
			raise InsufficientHistoryError(
				f"Product {product_id!r} has {len(history_rows)} history record(s); "
				f"at least 2 required for method {method!r}"
			)

		# Determine base period — last period with actual data
		base_period = history_rows[-1].period if history_rows else "MANUAL"

		# Build history as Decimal list
		history_vals: list[Decimal] = [_d(r.actual_qty) for r in history_rows]

		# Compute forecasts
		if method == "MOVING_AVERAGE":
			fq, fl, fu = _moving_average(history_vals, horizon_periods, lookback_periods)
		elif method == "EXPONENTIAL_SMOOTHING":
			fq, fl, fu = _exponential_smoothing(history_vals, horizon_periods)
		elif method == "HOLT_WINTERS":
			fq, fl, fu = _holt_winters_additive(history_vals, horizon_periods)
		else:
			# MANUAL — empty periods for planner to fill
			fq = [Decimal("0")] * horizon_periods
			fl = [Decimal("0")] * horizon_periods
			fu = [Decimal("0")] * horizon_periods

		# Build periods list
		periods_data: list[dict] = []
		for h in range(horizon_periods):
			period_label = _build_period_label(base_period, h + 1)
			periods_data.append({
				"period": period_label,
				"forecast_qty": str(fq[h].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
				"lower_bound": str(fl[h].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
				"upper_bound": str(fu[h].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
			})

		# Supersede existing active forecasts for this product
		existing_active: list[DemandForecast] = session.execute(
			sa.select(DemandForecast).where(
				DemandForecast.tenant_id == tenant_id,
				DemandForecast.product_id == product_id,
				DemandForecast.status.in_(["DRAFT", "APPROVED"]),
			)
		).scalars().all()

		for old in existing_active:
			old.status = "SUPERSEDED"

		# Create new forecast
		forecast = DemandForecast(
			tenant_id=tenant_id,
			product_id=product_id,
			forecast_method=method,
			base_period=base_period,
			horizon_periods=horizon_periods,
			status="DRAFT",
			periods=periods_data,
		)
		session.add(forecast)
		session.flush()

		_emit(
			ForecastCreatedEvent(
				aggregate_id=forecast.id,
				aggregate_type="DemandForecast",
				tenant_id=tenant_id,
				forecast_id=forecast.id,
				product_id=product_id,
				periods=horizon_periods,
				forecast_method=method,
				base_period=base_period,
			),
			session,
		)

		log.info(
			"DemandPlanningService.generate_forecast: product=%s method=%s "
			"base=%s horizon=%d forecast_id=%s",
			product_id, method, base_period, horizon_periods, forecast.id,
		)

		return forecast

	# -----------------------------------------------------------------------
	# approve_forecast
	# -----------------------------------------------------------------------

	@staticmethod
	def approve_forecast(forecast_id: str, approver_id: str, session: Any) -> DemandForecast:
		"""Approve a DRAFT demand forecast.

		Only DRAFT forecasts can be approved.  Sets status=APPROVED, records
		approver and timestamp, emits ForecastApprovedEvent.

		Raises:
		  ForecastNotFoundError       — forecast not found
		  InvalidForecastStatusError  — forecast is not in DRAFT status
		"""
		assert forecast_id, "forecast_id must be non-empty"
		assert approver_id, "approver_id must be non-empty"

		forecast: DemandForecast | None = session.execute(
			sa.select(DemandForecast).where(DemandForecast.id == forecast_id)
		).scalar_one_or_none()

		if forecast is None:
			raise ForecastNotFoundError(f"DemandForecast {forecast_id!r} not found")

		if forecast.status != "DRAFT":
			raise InvalidForecastStatusError(
				f"DemandForecast {forecast_id!r} is in status {forecast.status!r}; "
				"only DRAFT forecasts can be approved"
			)

		forecast.status = "APPROVED"
		forecast.approved_by = approver_id
		forecast.approved_at = datetime.now(timezone.utc)
		session.flush()

		_emit(
			ForecastApprovedEvent(
				aggregate_id=forecast.id,
				aggregate_type="DemandForecast",
				tenant_id=forecast.tenant_id,
				forecast_id=forecast.id,
				approved_by=approver_id,
				product_id=forecast.product_id,
				base_period=forecast.base_period,
			),
			session,
		)

		log.info(
			"DemandPlanningService.approve_forecast: forecast=%s product=%s approved_by=%s",
			forecast_id, forecast.product_id, approver_id,
		)

		return forecast

	# -----------------------------------------------------------------------
	# compute_accuracy
	# -----------------------------------------------------------------------

	@staticmethod
	def compute_accuracy(
		product_id: str,
		from_period: str,
		to_period: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Compute forecast accuracy KPIs for a product over a period range.

		Loads actual vs the most-recent non-SUPERSEDED forecast for each period
		in [from_period, to_period].

		KPIs:
		  MAPE = mean(|actual - forecast| / actual * 100)  [only where actual > 0]
		  Bias = mean((forecast - actual) / actual * 100)  [only where actual > 0]

		Returns:
		  {
		    product_id, from_period, to_period,
		    mape_pct, bias_pct,
		    periods_evaluated, periods_skipped,
		    per_period: [{period, actual, forecast, error_pct, bias_pct}]
		  }
		  All qty/pct values are Decimal strings.

		Emits ForecastAccuracyComputedEvent.
		"""
		assert product_id, "product_id must be non-empty"
		assert from_period, "from_period must be non-empty"
		assert to_period, "to_period must be non-empty"
		assert tenant_id, "tenant_id must be non-empty"

		# Load actuals in range (lexicographic period ordering works for YYYY-MM)
		actuals: list[DemandHistory] = session.execute(
			sa.select(DemandHistory).where(
				DemandHistory.tenant_id == tenant_id,
				DemandHistory.product_id == product_id,
				DemandHistory.period >= from_period,
				DemandHistory.period <= to_period,
			).order_by(DemandHistory.period)
		).scalars().all()

		# Load best available forecasts for this product
		forecasts: list[DemandForecast] = session.execute(
			sa.select(DemandForecast).where(
				DemandForecast.tenant_id == tenant_id,
				DemandForecast.product_id == product_id,
				DemandForecast.status.in_(["APPROVED", "DRAFT"]),
			).order_by(DemandForecast.approved_at.desc().nullslast(), DemandForecast.created_at.desc())
		).scalars().all()

		# Build period -> forecast_qty lookup from periods JSONB
		forecast_by_period: dict[str, Decimal] = {}
		for fc in forecasts:
			for p_entry in (fc.periods or []):
				pkey = p_entry.get("period", "")
				if pkey and pkey not in forecast_by_period:
					try:
						forecast_by_period[pkey] = _d(p_entry["forecast_qty"])
					except (KeyError, Exception):
						pass

		error_pcts: list[Decimal] = []
		bias_pcts: list[Decimal] = []
		per_period: list[dict] = []
		skipped = 0

		for actual_row in actuals:
			period = actual_row.period
			actual = _d(actual_row.actual_qty)
			forecast_qty = forecast_by_period.get(period)

			if forecast_qty is None or actual <= 0:
				skipped += 1
				per_period.append({
					"period": period,
					"actual": str(actual),
					"forecast": str(forecast_qty) if forecast_qty is not None else None,
					"error_pct": None,
					"bias_pct": None,
					"note": "skipped — no forecast or zero actual",
				})
				continue

			error = abs(actual - forecast_qty) / actual * Decimal("100")
			bias = (forecast_qty - actual) / actual * Decimal("100")
			error_pcts.append(error)
			bias_pcts.append(bias)
			per_period.append({
				"period": period,
				"actual": str(actual),
				"forecast": str(forecast_qty),
				"error_pct": str(error.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
				"bias_pct": str(bias.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
			})

		mape = _mean(error_pcts) if error_pcts else Decimal("0")
		bias_mean = _mean(bias_pcts) if bias_pcts else Decimal("0")
		mape_str = str(mape.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
		bias_str = str(bias_mean.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
		period_label = f"{from_period}:{to_period}"

		_emit(
			ForecastAccuracyComputedEvent(
				aggregate_id=product_id,
				aggregate_type="Product",
				tenant_id=tenant_id,
				product_id=product_id,
				mape_pct=mape_str,
				bias_pct=bias_str,
				period=period_label,
				periods_evaluated=len(error_pcts),
			),
			session,
		)

		log.info(
			"DemandPlanningService.compute_accuracy: product=%s range=%s:%s "
			"mape=%s%% bias=%s%% evaluated=%d skipped=%d",
			product_id, from_period, to_period, mape_str, bias_str,
			len(error_pcts), skipped,
		)

		return {
			"product_id": product_id,
			"from_period": from_period,
			"to_period": to_period,
			"mape_pct": mape_str,
			"bias_pct": bias_str,
			"periods_evaluated": len(error_pcts),
			"periods_skipped": skipped,
			"per_period": per_period,
		}

	# -----------------------------------------------------------------------
	# get_approved_forecast
	# -----------------------------------------------------------------------

	@staticmethod
	def get_approved_forecast(
		product_id: str,
		period: str,
		tenant_id: str,
		session: Any,
	) -> Decimal | None:
		"""Return the forecast_qty for a product/period from the latest APPROVED forecast.

		Searches APPROVED forecasts in descending approved_at order.  Falls back
		to DRAFT if no APPROVED forecast covers the period.

		Returns:
		  Decimal forecast_qty, or None if no forecast covers this period.
		"""
		assert product_id, "product_id must be non-empty"
		assert period, "period must be non-empty"
		assert tenant_id, "tenant_id must be non-empty"

		# Prefer APPROVED, then DRAFT; newest first
		forecasts: list[DemandForecast] = session.execute(
			sa.select(DemandForecast).where(
				DemandForecast.tenant_id == tenant_id,
				DemandForecast.product_id == product_id,
				DemandForecast.status.in_(["APPROVED", "DRAFT"]),
			).order_by(
				# APPROVED rows first (status alphabetic: APPROVED < DRAFT)
				DemandForecast.status.asc(),
				DemandForecast.approved_at.desc().nullslast(),
				DemandForecast.created_at.desc(),
			)
		).scalars().all()

		for fc in forecasts:
			for p_entry in (fc.periods or []):
				if p_entry.get("period") == period:
					try:
						return _d(p_entry["forecast_qty"])
					except (KeyError, Exception):
						pass

		return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"DemandPlanningService",
	"DemandPlanningError",
	"ForecastNotFoundError",
	"InsufficientHistoryError",
	"InvalidForecastStatusError",
]
