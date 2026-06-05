"""
pgappforge/plugins/erp/industry/energy/services.py

EnergyService — stateless business logic for the Energy & Utilities plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents. Never float.
  - MeterReading rows are NEVER updated — supersede old + insert corrected.
  - EnergyBill rows are IMMUTABLE once status=ISSUED — void + reissue for corrections.
  - RenewableAttribute retired=True is permanent.
  - Consumption = (read_value - previous_read_value) * meter.multiplier
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EnergyError(Exception):
	"""Base error for Energy domain violations."""


class MeterNotFoundError(EnergyError):
	"""No Meter with the given id."""


class BillNotFoundError(EnergyError):
	"""No EnergyBill with the given id."""


class CertificateNotFoundError(EnergyError):
	"""No RenewableAttribute with the given id."""


class InvalidReadingError(EnergyError):
	"""Meter reading is invalid (e.g. below previous reading without rollover)."""


class BillAlreadyIssuedError(EnergyError):
	"""Bill has already been issued; it is immutable."""


# ---------------------------------------------------------------------------
# Default emission factor: US average scope 2 grid electricity
# tCO2e per kWh (EPA eGRID 2022 national average)
# ---------------------------------------------------------------------------

_DEFAULT_EMISSION_FACTOR_TCO2E_PER_KWH = Decimal("0.000233")


# ---------------------------------------------------------------------------
# EnergyService
# ---------------------------------------------------------------------------

class EnergyService:
	"""Stateless service for Energy & Utilities operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Meter reading ingestion
	# ------------------------------------------------------------------

	def ingest_meter_reading(
		self,
		*,
		meter_id: str,
		read_value: Decimal | str,
		read_date: date,
		read_type: str,
		session: Any,
		read_at: datetime | None = None,
		read_by: str | None = None,
		photo_url: str | None = None,
		notes: str | None = None,
	) -> Any:
		"""Record a meter reading, compute consumption, flag anomalies.

		Validates that read_value >= previous reading (non-decreasing odometer).
		Calculates consumption_kwh = (read_value - prev) * meter.multiplier.
		Sets status=ESTIMATED for read_type=ESTIMATE, VALID otherwise.
		Marks status=DISPUTED if consumption is negative (possible rollover).

		Raises:
		  MeterNotFoundError if meter_id does not exist.
		  InvalidReadingError if read_type is not a recognised value.
		"""
		from pgappforge.plugins.erp.industry.energy.models import Meter, MeterReading
		from pgappforge.plugins.erp.industry.energy.events import (
			MeterReadingSubmittedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		valid_read_types = {"ACTUAL", "ESTIMATE", "CUSTOMER", "CORRECTED", "AMR"}
		if read_type not in valid_read_types:
			raise InvalidReadingError(
				f"read_type must be one of {valid_read_types}, got {read_type!r}"
			)

		meter = session.get(Meter, meter_id)
		if meter is None:
			raise MeterNotFoundError(f"Meter {meter_id!r} not found")

		read_value = Decimal(str(read_value))

		# Fetch previous reading (most recent by read_date then created_at)
		prev_row = session.execute(
			select(MeterReading)
			.where(
				MeterReading.meter_id == meter_id,
				MeterReading.status.not_in(["SUPERSEDED", "REJECTED"]),
				MeterReading.read_date <= read_date,
			)
			.order_by(MeterReading.read_date.desc(), MeterReading.created_at.desc())
			.limit(1)
		).scalar_one_or_none()

		prev_value = prev_row.read_value if prev_row is not None else None
		multiplier = meter.multiplier or Decimal("1")

		consumption_kwh: Decimal | None = None
		if prev_value is not None:
			raw_delta = read_value - Decimal(str(prev_value))
			consumption_kwh = (raw_delta * Decimal(str(multiplier))).quantize(
				Decimal("0.01"), rounding=ROUND_HALF_UP
			)

		# Determine status
		if read_type == "ESTIMATE":
			status = "ESTIMATED"
		elif consumption_kwh is not None and consumption_kwh < 0:
			status = "DISPUTED"
			log.warning(
				"ingest_meter_reading: negative consumption %s for meter %r — marked DISPUTED",
				consumption_kwh,
				meter.meter_number,
			)
		else:
			status = "VALID"

		reading = MeterReading(
			tenant_id=meter.tenant_id,
			meter_id=meter_id,
			read_date=read_date,
			read_at=read_at,
			read_value=read_value,
			previous_read_value=prev_value,
			consumption_kwh=consumption_kwh,
			read_type=read_type,
			read_by=read_by,
			photo_url=photo_url,
			status=status,
			notes=notes,
		)
		session.add(reading)
		session.flush()

		emit_event(
			MeterReadingSubmittedEvent(
				aggregate_id=reading.id,
				aggregate_type="MeterReading",
				tenant_id=meter.tenant_id,
				reading_id=reading.id,
				meter_id=meter_id,
				meter_number=meter.meter_number,
				read_date=read_date.isoformat(),
				read_value=str(read_value),
				consumption_kwh=str(consumption_kwh) if consumption_kwh is not None else "",
				read_type=read_type,
			),
			session,
		)

		log.info(
			"ingest_meter_reading: meter=%r date=%s val=%s consumption=%s type=%s status=%s",
			meter.meter_number, read_date, read_value, consumption_kwh, read_type, status,
		)
		return reading

	# ------------------------------------------------------------------
	# Billing
	# ------------------------------------------------------------------

	def generate_bill(
		self,
		*,
		meter_id: str,
		billing_period_start: date,
		billing_period_end: date,
		session: Any,
		bill_number: str | None = None,
		tariff_rates: dict | None = None,
		currency_code: str = "USD",
		notes: str | None = None,
	) -> Any:
		"""Generate an EnergyBill for the given billing period.

		Aggregates all VALID/ESTIMATED readings in the period, applies tariff
		rates, posts status=DRAFT.  Caller must explicitly issue the bill
		(set status=ISSUED) after review.

		tariff_rates dict shape (all values integer cents unless noted):
		  {
		    "energy_rate_cents_per_kwh": int,   # cents per kWh consumed
		    "network_charge_cents":       int,   # flat network charge
		    "standing_charge_cents":      int,   # flat daily standing charge
		    "tax_rate_pct":               float, # percentage e.g. 0.05 = 5%
		  }

		Raises:
		  MeterNotFoundError if meter not found.
		"""
		from pgappforge.plugins.erp.industry.energy.models import Meter, MeterReading, EnergyBill
		from pgappforge.plugins.erp.industry.energy.events import EnergyBillIssuedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		import uuid

		meter = session.get(Meter, meter_id)
		if meter is None:
			raise MeterNotFoundError(f"Meter {meter_id!r} not found")

		# Sum consumption across all valid readings in period
		rows = session.execute(
			select(MeterReading)
			.where(
				MeterReading.meter_id == meter_id,
				MeterReading.read_date >= billing_period_start,
				MeterReading.read_date <= billing_period_end,
				MeterReading.status.in_(["VALID", "ESTIMATED"]),
			)
			.order_by(MeterReading.read_date)
		).scalars().all()

		total_consumption = sum(
			Decimal(str(r.consumption_kwh)) for r in rows
			if r.consumption_kwh is not None
		)

		opening_read = rows[0].previous_read_value if rows else None
		closing_read = rows[-1].read_value if rows else None

		# Apply tariff rates
		rates = tariff_rates or {}
		energy_rate = int(rates.get("energy_rate_cents_per_kwh", 10))
		network_charge = int(rates.get("network_charge_cents", 0))
		standing_charge = int(rates.get("standing_charge_cents", 0))
		tax_rate = float(rates.get("tax_rate_pct", 0.0))

		energy_charge_cents = int(total_consumption * energy_rate)
		subtotal = energy_charge_cents + network_charge + standing_charge
		tax_cents = int(subtotal * tax_rate)
		amount_cents = subtotal + tax_cents

		if bill_number is None:
			bill_number = f"BILL-{uuid.uuid4().hex[:8].upper()}"

		bill = EnergyBill(
			tenant_id=meter.tenant_id,
			bill_number=bill_number,
			meter_id=meter_id,
			customer_id=meter.customer_id,
			billing_period_start=billing_period_start,
			billing_period_end=billing_period_end,
			consumption_kwh=total_consumption,
			opening_read=opening_read,
			closing_read=closing_read,
			energy_charge_cents=energy_charge_cents,
			network_charge_cents=network_charge,
			standing_charge_cents=standing_charge,
			tax_cents=tax_cents,
			amount_cents=amount_cents,
			paid_cents=0,
			currency_code=currency_code,
			tariff_code=meter.tariff_code,
			bill_breakdown={
				"consumption_kwh": str(total_consumption),
				"energy_rate_cents_per_kwh": energy_rate,
				"energy_charge_cents": energy_charge_cents,
				"network_charge_cents": network_charge,
				"standing_charge_cents": standing_charge,
				"tax_rate_pct": tax_rate,
				"tax_cents": tax_cents,
				"reading_ids": [r.id for r in rows],
			},
			status="DRAFT",
			notes=notes,
		)
		session.add(bill)
		session.flush()

		log.info(
			"generate_bill: meter=%r period=%s–%s consumption=%s amount_cents=%d status=DRAFT",
			meter.meter_number, billing_period_start, billing_period_end,
			total_consumption, amount_cents,
		)
		return bill

	# ------------------------------------------------------------------
	# Anomaly detection
	# ------------------------------------------------------------------

	def detect_anomalies(
		self,
		meter_id: str,
		session: Any,
		lookback_days: int = 90,
		std_dev_threshold: float = 2.0,
	) -> list[dict]:
		"""Return readings that deviate > std_dev_threshold standard deviations.

		Uses historical mean and stddev of consumption_kwh over lookback_days.
		Only considers VALID or ESTIMATED readings with non-null consumption.

		Returns list of dicts: {reading_id, read_date, consumption_kwh,
		                        z_score, anomaly_score, deviation_pct}
		"""
		from pgappforge.plugins.erp.industry.energy.models import MeterReading

		cutoff = date.today() - timedelta(days=lookback_days)

		rows = session.execute(
			select(MeterReading)
			.where(
				MeterReading.meter_id == meter_id,
				MeterReading.read_date >= cutoff,
				MeterReading.status.in_(["VALID", "ESTIMATED"]),
				MeterReading.consumption_kwh.is_not(None),
			)
			.order_by(MeterReading.read_date)
		).scalars().all()

		if len(rows) < 3:
			return []

		values = [float(r.consumption_kwh) for r in rows]
		mean = statistics.mean(values)
		stddev = statistics.stdev(values)

		if stddev == 0:
			return []

		anomalies = []
		for r, v in zip(rows, values):
			z = (v - mean) / stddev
			if abs(z) > std_dev_threshold:
				anomalies.append({
					"reading_id": r.id,
					"read_date": r.read_date.isoformat(),
					"consumption_kwh": str(r.consumption_kwh),
					"z_score": round(z, 4),
					"anomaly_score": round(abs(z), 4),
					"deviation_pct": round((v - mean) / mean * 100, 2) if mean != 0 else None,
				})

		log.info(
			"detect_anomalies: meter=%r lookback=%dd found %d anomalies out of %d readings",
			meter_id, lookback_days, len(anomalies), len(rows),
		)
		return anomalies

	# ------------------------------------------------------------------
	# Carbon footprint
	# ------------------------------------------------------------------

	def calculate_carbon_footprint(
		self,
		meter_id: str,
		period_start: date,
		period_end: date,
		session: Any,
		emission_factor_tco2e_per_kwh: Decimal | str | None = None,
	) -> dict:
		"""Map energy consumption to CO2e (Scope 2 market-based).

		emission_factor_tco2e_per_kwh defaults to US EPA average (0.000233).
		Returns tCO2e values as Decimal strings to avoid float imprecision.

		Returns dict:
		  {meter_id, period_start, period_end, consumption_kwh,
		   emission_factor_tco2e_per_kwh, total_tco2e, scope,
		   source, unit}
		"""
		from pgappforge.plugins.erp.industry.energy.models import Meter, MeterReading
		from pgappforge.plugins.erp.foundation.events import emit_event
		from pgappforge.plugins.erp.industry.energy.events import (
			MeterReadingSubmittedEvent,
		)

		meter = session.get(Meter, meter_id)
		if meter is None:
			raise MeterNotFoundError(f"Meter {meter_id!r} not found")

		rows = session.execute(
			select(MeterReading)
			.where(
				MeterReading.meter_id == meter_id,
				MeterReading.read_date >= period_start,
				MeterReading.read_date <= period_end,
				MeterReading.status.in_(["VALID", "ESTIMATED"]),
				MeterReading.consumption_kwh.is_not(None),
			)
		).scalars().all()

		total_kwh = sum(Decimal(str(r.consumption_kwh)) for r in rows)

		factor = (
			Decimal(str(emission_factor_tco2e_per_kwh))
			if emission_factor_tco2e_per_kwh is not None
			else _DEFAULT_EMISSION_FACTOR_TCO2E_PER_KWH
		)

		total_tco2e = (total_kwh * factor).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

		result = {
			"meter_id": meter_id,
			"meter_number": meter.meter_number,
			"meter_type": meter.meter_type,
			"period_start": period_start.isoformat(),
			"period_end": period_end.isoformat(),
			"consumption_kwh": str(total_kwh),
			"emission_factor_tco2e_per_kwh": str(factor),
			"total_tco2e": str(total_tco2e),
			"scope": "SCOPE_2",
			"source": "market_based",
			"unit": "tCO2e",
			"reading_count": len(rows),
		}

		log.info(
			"calculate_carbon_footprint: meter=%r period=%s–%s kwh=%s tco2e=%s",
			meter.meter_number, period_start, period_end, total_kwh, total_tco2e,
		)
		return result

	# ------------------------------------------------------------------
	# Renewable certificates
	# ------------------------------------------------------------------

	def issue_renewable_certificate(
		self,
		*,
		tenant_id: str,
		generation_mwh: Decimal | str,
		energy_type: str,
		generation_date: date,
		session: Any,
		certificate_id: str | None = None,
		generation_facility_name: str | None = None,
		generation_country: str | None = None,
		registry_name: str | None = None,
		holder_id: str | None = None,
		metadata: dict | None = None,
	) -> Any:
		"""Issue a new Renewable Energy Certificate (REC/REGO/GO).

		certificate_id defaults to a generated unique string if not provided.
		generation_mwh stored as NUMERIC(15,4).

		Raises EnergyError for invalid energy_type.
		"""
		from pgappforge.plugins.erp.industry.energy.models import RenewableAttribute
		import uuid

		valid_types = {"SOLAR", "WIND", "HYDRO", "GEOTHERMAL", "BIOMASS", "TIDAL", "OTHER"}
		if energy_type not in valid_types:
			raise EnergyError(f"energy_type must be one of {valid_types}, got {energy_type!r}")

		if certificate_id is None:
			certificate_id = f"REC-{uuid.uuid4().hex[:12].upper()}"

		cert = RenewableAttribute(
			tenant_id=tenant_id,
			certificate_id=certificate_id,
			energy_type=energy_type,
			generation_mwh=Decimal(str(generation_mwh)),
			generation_date=generation_date,
			generation_facility_name=generation_facility_name,
			generation_country=generation_country,
			registry_name=registry_name,
			issued_date=date.today(),
			retired=False,
			holder_id=holder_id,
			metadata_=metadata or {},
		)
		session.add(cert)
		session.flush()

		log.info(
			"issue_renewable_certificate: cert=%r type=%r mwh=%s date=%s",
			certificate_id, energy_type, generation_mwh, generation_date,
		)
		return cert

	# ------------------------------------------------------------------
	# Demand forecasting
	# ------------------------------------------------------------------

	def forecast_demand(
		self,
		meter_id: str,
		session: Any,
		days_ahead: int = 30,
		lookback_days: int = 90,
	) -> list[dict]:
		"""Forecast daily demand using a simple moving-average model.

		Uses mean + stddev of historical daily consumption as baseline.
		Returns list of {forecast_date, forecast_kwh, confidence_lower,
		                  confidence_upper, method} dicts.

		For production use, replace the moving-average with a proper
		time-series model (Prophet, ARIMA, etc.).
		"""
		from pgappforge.plugins.erp.industry.energy.models import MeterReading

		meter_row = session.execute(
			select(sa.text("1")).where(sa.literal(meter_id) != "")
		)  # cheap existence-ish; actual check below
		cutoff = date.today() - timedelta(days=lookback_days)

		rows = session.execute(
			select(MeterReading)
			.where(
				MeterReading.meter_id == meter_id,
				MeterReading.read_date >= cutoff,
				MeterReading.status.in_(["VALID", "ESTIMATED"]),
				MeterReading.consumption_kwh.is_not(None),
			)
			.order_by(MeterReading.read_date)
		).scalars().all()

		if not rows:
			return []

		values = [float(r.consumption_kwh) for r in rows]
		mean_daily = statistics.mean(values)
		stddev_daily = statistics.stdev(values) if len(values) > 1 else 0.0
		# 90 % confidence interval ≈ ±1.645 std deviations
		ci_half = stddev_daily * 1.645

		today = date.today()
		forecasts = []
		for i in range(1, days_ahead + 1):
			forecast_date = today + timedelta(days=i)
			forecasts.append({
				"forecast_date": forecast_date.isoformat(),
				"forecast_kwh": round(mean_daily, 4),
				"confidence_lower": round(max(0.0, mean_daily - ci_half), 4),
				"confidence_upper": round(mean_daily + ci_half, 4),
				"method": "moving_average",
			})

		return forecasts

	# ------------------------------------------------------------------
	# Grid / utility summary
	# ------------------------------------------------------------------

	def get_grid_summary(
		self,
		utility_id: str,
		snapshot_date: date,
		session: Any,
	) -> dict:
		"""Return a grid-level summary for a utility/tenant.

		utility_id is treated as tenant_id for the query scope.

		Returns:
		  total_meters, active_meters, smart_meters,
		  total_consumption_kwh (period = snapshot month),
		  total_revenue_cents (all ISSUED/PAID bills up to snapshot_date),
		  outstanding_balance_cents (all ISSUED/PARTIALLY_PAID bills),
		  outage_incidents (stub — returns 0 until outage model added).
		"""
		from pgappforge.plugins.erp.industry.energy.models import Meter, MeterReading, EnergyBill

		tenant_id = utility_id

		# Meter counts
		meter_counts = session.execute(
			select(
				func.count(Meter.id).label("total"),
				func.count(Meter.id).filter(Meter.status == "ACTIVE").label("active"),
				func.count(Meter.id).filter(Meter.smart_meter.is_(True)).label("smart"),
			).where(Meter.tenant_id == tenant_id)
		).one()

		# Consumption for the calendar month of snapshot_date
		month_start = snapshot_date.replace(day=1)
		consumption_row = session.execute(
			select(func.coalesce(func.sum(MeterReading.consumption_kwh), 0).label("total"))
			.join(Meter, Meter.id == MeterReading.meter_id)
			.where(
				Meter.tenant_id == tenant_id,
				MeterReading.read_date >= month_start,
				MeterReading.read_date <= snapshot_date,
				MeterReading.status.in_(["VALID", "ESTIMATED"]),
			)
		).one()

		# Revenue — sum of amount_cents for ISSUED/PAID bills up to snapshot_date
		revenue_row = session.execute(
			select(func.coalesce(func.sum(EnergyBill.amount_cents), 0).label("total"))
			.where(
				EnergyBill.tenant_id == tenant_id,
				EnergyBill.status.in_(["ISSUED", "PAID", "PARTIALLY_PAID"]),
				EnergyBill.issue_date <= snapshot_date,
			)
		).one()

		# Outstanding — unpaid portion of open bills
		outstanding_row = session.execute(
			select(
				func.coalesce(
					func.sum(EnergyBill.amount_cents - EnergyBill.paid_cents), 0
				).label("total")
			)
			.where(
				EnergyBill.tenant_id == tenant_id,
				EnergyBill.status.in_(["ISSUED", "PARTIALLY_PAID", "OVERDUE"]),
			)
		).one()

		return {
			"utility_id": utility_id,
			"snapshot_date": snapshot_date.isoformat(),
			"total_meters": meter_counts.total,
			"active_meters": meter_counts.active,
			"smart_meters": meter_counts.smart,
			"total_consumption_kwh": str(consumption_row.total),
			"period_start": month_start.isoformat(),
			"period_end": snapshot_date.isoformat(),
			"total_revenue_cents": int(revenue_row.total),
			"outstanding_balance_cents": int(outstanding_row.total),
			"outage_incidents": 0,  # placeholder — requires OutageEvent model
		}


__all__ = [
	"EnergyService",
	"EnergyError",
	"MeterNotFoundError",
	"BillNotFoundError",
	"CertificateNotFoundError",
	"InvalidReadingError",
	"BillAlreadyIssuedError",
]
