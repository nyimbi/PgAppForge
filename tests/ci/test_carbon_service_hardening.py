"""Regression tests for carbon accounting service input contracts."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from pgappforge.plugins.erp.platform.carbon.services import (
	CarbonTrackingService,
	CarbonValidationError,
	_period_to_date,
)


class _ScalarResult:
	def __init__(self, rows: list[object]) -> None:
		self._rows = rows

	def scalars(self) -> "_ScalarResult":
		return self

	def first(self) -> object | None:
		return self._rows[0] if self._rows else None

	def __iter__(self):
		return iter(self._rows)


class _Session:
	def __init__(self, *results: list[object]) -> None:
		self._results = list(results)
		self.executed: list[object] = []
		self.added: list[object] = []
		self.flushed = False

	def execute(self, statement: object) -> _ScalarResult:
		self.executed.append(statement)
		rows = self._results.pop(0) if self._results else []
		return _ScalarResult(rows)

	def add(self, value: object) -> None:
		self.added.append(value)

	def flush(self) -> None:
		self.flushed = True


def test_period_to_date_supports_year_month_and_quarter() -> None:
	assert _period_to_date("2025").isoformat() == "2025-01-01"
	assert _period_to_date("2025-09").isoformat() == "2025-09-01"
	assert _period_to_date("2025-Q3").isoformat() == "2025-07-01"

	with pytest.raises(CarbonValidationError):
		_period_to_date("2025-W01")


@pytest.mark.parametrize(
	"kwargs, message",
	[
		({"scope": 4}, "scope"),
		({"activity_data": "not-a-number"}, "activity_data"),
		({"activity_data": 0}, "activity_data"),
		({"period": "2025-W01"}, "period"),
		({"country_code": "KE"}, "country_code"),
		({"source_type": ""}, "source_type"),
	],
)
def test_record_emission_rejects_invalid_inputs_before_database(
	kwargs: dict,
	message: str,
) -> None:
	service = CarbonTrackingService()
	session = _Session()
	params = {
		"scope": 2,
		"source_type": "electricity_kwh",
		"activity_data": "10",
		"unit": "kwh",
		"period": "2025-Q1",
		"tenant_id": "tenant-a",
		"session": session,
		"country_code": "KEN",
	}
	params.update(kwargs)

	with pytest.raises(CarbonValidationError, match=message):
		service.record_emission(**params)

	assert session.executed == []
	assert session.added == []


def test_record_emission_normalizes_inputs_and_uses_matching_factor() -> None:
	factor = SimpleNamespace(id="factor-1", co2e_per_unit=Decimal("0.390"))
	session = _Session([factor])

	record = CarbonTrackingService().record_emission(
		scope=2,
		source_type="electricity_kwh",
		activity_data="10.5",
		unit="kwh",
		period="2025-q2",
		tenant_id="tenant-a",
		session=session,
		country_code="ken",
		description=" grid electricity ",
	)

	assert record.scope == 2
	assert record.source_type == "ELECTRICITY_KWH"
	assert record.unit == "KWH"
	assert record.period == "2025-Q2"
	assert record.description == "grid electricity"
	assert record.emission_factor_id == "factor-1"
	assert record.co2e_kg == Decimal("4.0950")
	assert session.added[0] is record
	assert session.flushed is True


def test_compute_emission_intensity_validates_revenue_and_normalizes_period() -> None:
	service = CarbonTrackingService()

	with pytest.raises(CarbonValidationError, match="revenue_cents"):
		service.compute_emission_intensity("tenant-a", "2025-Q1", 0, _Session())

	session = _Session([
		SimpleNamespace(co2e_kg=Decimal("25")),
		SimpleNamespace(co2e_kg="5"),
	])
	result = service.compute_emission_intensity("tenant-a", "2025-q1", 1000, session)

	assert result["total_co2e_kg"] == "30"
	assert result["revenue_currency"] == "10"
	assert result["intensity_co2e_per_unit_revenue"] == "3"
	assert result["period"] == "2025-Q1"


def test_apply_offset_validates_and_normalizes_fields() -> None:
	service = CarbonTrackingService()

	with pytest.raises(CarbonValidationError, match="cost_cents"):
		service.apply_offset("2025-Q4", "10", "verified", None, -1, "tenant-a", _Session())

	session = _Session()
	offset = service.apply_offset(
		"2025-q4",
		"12.5",
		"verified",
		" Gold Standard ",
		1500,
		"tenant-a",
		session,
		certificate_ref=" CERT-1 ",
		currency_code="kes",
	)

	assert offset.period == "2025-Q4"
	assert offset.co2e_kg == Decimal("12.5")
	assert offset.offset_type == "VERIFIED"
	assert offset.provider == "Gold Standard"
	assert offset.certificate_ref == "CERT-1"
	assert offset.currency_code == "KES"
	assert session.added[0] is offset
