from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	EmissionRecordedEvent,
	EmissionReportGeneratedEvent,
	OffsetAppliedEvent,
)
from .models import CarbonOffset, EmissionFactor, EmissionRecord, GHGReport

__all__ = ["CarbonTrackingService", "CarbonValidationError"]

log = logging.getLogger(__name__)

_DEFAULT_EFFECTIVE_FROM = date(2024, 1, 1)
_PERIOD_RE = re.compile(
	r"^(?P<year>\d{4})(?:-(?P<month>0[1-9]|1[0-2])|-Q(?P<quarter>[1-4]))?$"
)

# (source_type, scope, co2e_per_unit, unit, source_note)
_KENYA_DEFAULT_FACTORS: list[tuple[str, int, Decimal, str, str]] = [
	("ELECTRICITY_KWH", 2, Decimal("0.390"), "KWH", "Kenya grid 2024 KETRACO"),
	("FUEL_DIESEL_LITRES", 1, Decimal("2.68"), "LITRES", "IPCC AR6"),
	("FUEL_PETROL_LITRES", 1, Decimal("2.31"), "LITRES", "IPCC AR6"),
	("FUEL_LPG_KG", 1, Decimal("2.98"), "KG", "IPCC AR6"),
	("FLEET_KM", 1, Decimal("0.170"), "KM", "BEIS 2024"),
	("BUSINESS_TRAVEL_KM_ECONOMY", 3, Decimal("0.133"), "KM", "BEIS 2024"),
	("WASTE_LANDFILL_KG", 3, Decimal("0.587"), "KG", "BEIS 2024"),
]


class CarbonValidationError(ValueError):
	"""Raised when carbon accounting inputs violate the service contract."""


def _emit(event: Any, session: Session | None = None) -> None:
	try:
		_emit_event(event, session)
	except Exception:
		log.debug("Event emission skipped: %s", type(event).__name__, exc_info=True)


def _decimal(value: Any) -> Decimal:
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError):
		return Decimal("0")


def _new_id() -> str:
	return str(uuid.uuid4())


def _period_to_date(period: str) -> date:
	"""Convert 'YYYY-MM' or 'YYYY-QN' or 'YYYY' to a date for factor lookup."""
	match = _PERIOD_RE.fullmatch(period)
	if not match:
		raise CarbonValidationError("period must use YYYY, YYYY-MM, or YYYY-QN")
	year = int(match.group("year"))
	if match.group("month"):
		return date(year, int(match.group("month")), 1)
	if match.group("quarter"):
		return date(year, (int(match.group("quarter")) - 1) * 3 + 1, 1)
	return date(year, 1, 1)


def _require_text(
	value: Any,
	field_name: str,
	*,
	max_length: int,
	uppercase: bool = False,
) -> str:
	if not isinstance(value, str):
		raise CarbonValidationError(f"{field_name} must be a string")
	text = value.strip()
	if not text:
		raise CarbonValidationError(f"{field_name} is required")
	if "\x00" in text:
		raise CarbonValidationError(f"{field_name} cannot contain NUL bytes")
	if len(text) > max_length:
		raise CarbonValidationError(f"{field_name} cannot exceed {max_length} characters")
	return text.upper() if uppercase else text


def _optional_text(
	value: Any,
	field_name: str,
	*,
	max_length: int,
	uppercase: bool = False,
) -> str | None:
	if value is None:
		return None
	return _require_text(value, field_name, max_length=max_length, uppercase=uppercase)


def _require_scope(value: Any) -> int:
	if isinstance(value, bool) or not isinstance(value, int):
		raise CarbonValidationError("scope must be an integer")
	if value not in {1, 2, 3}:
		raise CarbonValidationError("scope must be one of 1, 2, or 3")
	return value


def _require_decimal(value: Any, field_name: str) -> Decimal:
	if isinstance(value, bool):
		raise CarbonValidationError(f"{field_name} must be numeric")
	try:
		number = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError) as exc:
		raise CarbonValidationError(f"{field_name} must be numeric") from exc
	if not number.is_finite():
		raise CarbonValidationError(f"{field_name} must be finite")
	return number


def _require_positive_decimal(value: Any, field_name: str) -> Decimal:
	number = _require_decimal(value, field_name)
	if number <= Decimal("0"):
		raise CarbonValidationError(f"{field_name} must be positive")
	return number


def _require_int(value: Any, field_name: str, *, minimum: int | None = None) -> int:
	if isinstance(value, bool) or not isinstance(value, int):
		raise CarbonValidationError(f"{field_name} must be an integer")
	if minimum is not None and value < minimum:
		raise CarbonValidationError(f"{field_name} must be at least {minimum}")
	return value


def _normalize_period(value: Any) -> str:
	period = _require_text(value, "period", max_length=20, uppercase=True)
	_period_to_date(period)
	return period


class CarbonTrackingService:
	"""GHG emission recording, reporting, and offset management."""

	@BPMActionRegistry.register(
		"platform.carbon.record_emission",
		"Record GHG emission from activity",
	)
	def record_emission(
		self,
		scope: int,
		source_type: str,
		activity_data: Decimal | float | int | str,
		unit: str,
		period: str,
		tenant_id: str,
		session: Session,
		*,
		entity_id: str | None = None,
		country_code: str = "KEN",
		source_module: str | None = None,
		source_record_id: str | None = None,
		description: str | None = None,
	) -> EmissionRecord:
		scope = _require_scope(scope)
		source_type = _require_text(
			source_type, "source_type", max_length=100, uppercase=True
		)
		activity = _require_positive_decimal(activity_data, "activity_data")
		unit = _require_text(unit, "unit", max_length=30, uppercase=True)
		period = _normalize_period(period)
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		country_code = _require_text(
			country_code, "country_code", max_length=3, uppercase=True
		)
		if len(country_code) != 3:
			raise CarbonValidationError("country_code must be an ISO 3166-1 alpha-3 code")
		entity_id = _optional_text(entity_id, "entity_id", max_length=50)
		source_module = _optional_text(source_module, "source_module", max_length=100)
		source_record_id = _optional_text(source_record_id, "source_record_id", max_length=50)
		description = _optional_text(description, "description", max_length=5000)

		period_date = _period_to_date(period)

		# Find best matching emission factor: source_type + country_code, within effective date range
		_not_expired = (EmissionFactor.effective_to.is_(None)) | (
			EmissionFactor.effective_to >= period_date
		)
		factor_stmt = (
			select(EmissionFactor)
			.where(EmissionFactor.tenant_id == tenant_id)
			.where(EmissionFactor.source_type == source_type)
			.where(EmissionFactor.country_code == country_code)
			.where(EmissionFactor.effective_from <= period_date)
			.where(_not_expired)
			.order_by(EmissionFactor.effective_from.desc())
		)
		factor = session.execute(factor_stmt).scalars().first()

		if factor is not None:
			co2e_per_unit = _decimal(factor.co2e_per_unit)
			emission_factor_id: str | None = str(factor.id)
		else:
			# Fallback: try any country with same date constraints
			_not_expired_any = (EmissionFactor.effective_to.is_(None)) | (
				EmissionFactor.effective_to >= period_date
			)
			factor_stmt_any = (
				select(EmissionFactor)
				.where(EmissionFactor.tenant_id == tenant_id)
				.where(EmissionFactor.source_type == source_type)
				.where(EmissionFactor.effective_from <= period_date)
				.where(_not_expired_any)
				.order_by(EmissionFactor.effective_from.desc())
			)
			factor_any = session.execute(factor_stmt_any).scalars().first()
			if factor_any is not None:
				co2e_per_unit = _decimal(factor_any.co2e_per_unit)
				emission_factor_id = str(factor_any.id)
			else:
				log.warning(
					"No emission factor found for source_type=%s country=%s; co2e_kg=0",
					source_type,
					country_code,
				)
				co2e_per_unit = Decimal("0")
				emission_factor_id = None

		co2e_kg = activity * co2e_per_unit

		record = EmissionRecord(
			id=_new_id(),
			scope=scope,
			source_type=source_type,
			description=description,
			activity_data=activity,
			unit=unit,
			emission_factor_id=emission_factor_id,
			co2e_kg=co2e_kg,
			period=period,
			entity_id=entity_id,
			source_module=source_module,
			source_record_id=source_record_id,
			tenant_id=tenant_id,
		)
		session.add(record)
		session.flush()

		_emit(
			EmissionRecordedEvent(
				record_id=record.id,
				scope=scope,
				source_type=source_type,
				co2e_kg=str(co2e_kg),
				tenant_id=tenant_id,
			),
			session,
		)
		return record

	@BPMActionRegistry.register(
		"platform.carbon.generate_report",
		"Generate GHG report for period",
	)
	def generate_ghg_report(
		self,
		tenant_id: str,
		period: str,
		session: Session,
		*,
		entity_id: str | None = None,
		methodology: str | None = None,
	) -> GHGReport:
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		period = _normalize_period(period)
		entity_id = _optional_text(entity_id, "entity_id", max_length=50)
		methodology = _optional_text(methodology, "methodology", max_length=5000)

		stmt = (
			select(EmissionRecord)
			.where(EmissionRecord.tenant_id == tenant_id)
			.where(EmissionRecord.period == period)
		)
		if entity_id:
			stmt = stmt.where(EmissionRecord.entity_id == entity_id)

		records = list(session.execute(stmt).scalars())

		scope1 = sum(
			(_decimal(r.co2e_kg) for r in records if r.scope == 1), Decimal("0")
		)
		scope2 = sum(
			(_decimal(r.co2e_kg) for r in records if r.scope == 2), Decimal("0")
		)
		scope3 = sum(
			(_decimal(r.co2e_kg) for r in records if r.scope == 3), Decimal("0")
		)
		total = scope1 + scope2 + scope3

		report = GHGReport(
			id=_new_id(),
			period=period,
			scope1_co2e_kg=scope1,
			scope2_co2e_kg=scope2,
			scope3_co2e_kg=scope3,
			total_co2e_kg=total,
			methodology=methodology,
			entity_id=entity_id,
			tenant_id=tenant_id,
		)
		session.add(report)
		session.flush()

		_emit(
			EmissionReportGeneratedEvent(
				report_id=report.id,
				period=period,
				total_co2e_kg=str(total),
			),
			session,
		)
		return report

	def compute_emission_intensity(
		self,
		tenant_id: str,
		period: str,
		revenue_cents: int,
		session: Session,
	) -> dict[str, Any]:
		"""kgCO2e per currency unit of revenue for a period.

		Returns:
		    total_co2e_kg: str  — Decimal string
		    revenue_currency: str  — revenue expressed in whole currency units
		    intensity_co2e_per_unit_revenue: str  — kgCO2e / currency unit
		"""
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		period = _normalize_period(period)
		revenue_cents = _require_int(revenue_cents, "revenue_cents", minimum=1)

		rec_stmt = (
			select(EmissionRecord)
			.where(EmissionRecord.tenant_id == tenant_id)
			.where(EmissionRecord.period == period)
		)
		records = list(session.execute(rec_stmt).scalars())
		total_co2e = sum((_decimal(r.co2e_kg) for r in records), Decimal("0"))

		revenue = _decimal(revenue_cents) / Decimal("100")
		intensity = total_co2e / revenue if revenue > Decimal("0") else Decimal("0")

		return {
			"total_co2e_kg": str(total_co2e),
			"revenue_currency": str(revenue),
			"intensity_co2e_per_unit_revenue": str(intensity),
			"period": period,
		}

	def apply_offset(
		self,
		period: str,
		co2e_kg: Decimal | float | int | str,
		offset_type: str,
		provider: str | None,
		cost_cents: int,
		tenant_id: str,
		session: Session,
		*,
		certificate_ref: str | None = None,
		currency_code: str = "USD",
	) -> CarbonOffset:
		period = _normalize_period(period)
		co2e = _require_positive_decimal(co2e_kg, "co2e_kg")
		offset_type = _require_text(
			offset_type, "offset_type", max_length=50, uppercase=True
		)
		provider = _optional_text(provider, "provider", max_length=200)
		cost_cents = _require_int(cost_cents, "cost_cents", minimum=0)
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		certificate_ref = _optional_text(
			certificate_ref, "certificate_ref", max_length=100
		)
		currency_code = _require_text(
			currency_code, "currency_code", max_length=3, uppercase=True
		)
		if len(currency_code) != 3:
			raise CarbonValidationError("currency_code must be an ISO 4217 alpha-3 code")

		offset = CarbonOffset(
			id=_new_id(),
			period=period,
			co2e_kg=co2e,
			offset_type=offset_type,
			provider=provider,
			certificate_ref=certificate_ref,
			cost_cents=cost_cents,
			currency_code=currency_code,
			tenant_id=tenant_id,
		)
		session.add(offset)
		session.flush()

		_emit(
			OffsetAppliedEvent(
				offset_id=offset.id,
				co2e_kg=str(co2e),
				provider=provider or "",
				cost_cents=cost_cents,
			),
			session,
		)
		return offset

	def get_net_emissions(
		self,
		tenant_id: str,
		period: str,
		session: Session,
	) -> dict[str, Any]:
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)
		period = _normalize_period(period)

		rec_stmt = (
			select(EmissionRecord)
			.where(EmissionRecord.tenant_id == tenant_id)
			.where(EmissionRecord.period == period)
		)
		records = list(session.execute(rec_stmt).scalars())
		gross = sum((_decimal(r.co2e_kg) for r in records), Decimal("0"))

		off_stmt = (
			select(CarbonOffset)
			.where(CarbonOffset.tenant_id == tenant_id)
			.where(CarbonOffset.period == period)
		)
		offsets = list(session.execute(off_stmt).scalars())
		offsets_total = sum((_decimal(o.co2e_kg) for o in offsets), Decimal("0"))

		net = gross - offsets_total

		return {
			"gross_co2e_kg": str(gross),
			"offsets_co2e_kg": str(offsets_total),
			"net_co2e_kg": str(net),
			"period": period,
		}

	def seed_default_factors(self, tenant_id: str, session: Session) -> None:
		"""Seed Kenya-specific emission factors if none exist for the tenant."""
		tenant_id = _require_text(tenant_id, "tenant_id", max_length=64)

		count_stmt = (
			select(EmissionFactor)
			.where(EmissionFactor.tenant_id == tenant_id)
		)
		existing = list(session.execute(count_stmt).scalars())
		if existing:
			log.debug(
				"Emission factors already seeded for tenant %s (%d found)",
				tenant_id,
				len(existing),
			)
			return

		for source_type, scope, co2e_per_unit, unit, source_note in _KENYA_DEFAULT_FACTORS:
			factor = EmissionFactor(
				id=_new_id(),
				source_type=source_type,
				country_code="KEN",
				co2e_per_unit=co2e_per_unit,
				unit=unit,
				scope=scope,
				source=source_note,
				effective_from=_DEFAULT_EFFECTIVE_FROM,
				effective_to=None,
				tenant_id=tenant_id,
			)
			session.add(factor)

		session.flush()
		log.info(
			"Seeded %d default Kenya emission factors for tenant %s",
			len(_KENYA_DEFAULT_FACTORS),
			tenant_id,
		)
