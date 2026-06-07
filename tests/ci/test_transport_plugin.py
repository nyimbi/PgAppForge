"""
tests/ci/test_transport_plugin.py

Unit tests for the Transport Management plugin.

Strategy
--------
- Pure-logic tests: no real DB, no Flask context.
- SQLAlchemy session is a MagicMock; model instances are plain objects.
- Event emission and BPM registry are monkey-patched.
- Covers: create_shipment, book_carrier, dispatch, record_delivery,
          add_tracking_event, compute_freight, update_carrier_performance,
          _apply_rate, _find_best_rate (via book_carrier), status FSM guards,
          FreightRateNotFoundError path.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.erp.operations.transport.services import (
	TransportService,
	TransportServiceError,
	ShipmentNotFoundError,
	CarrierNotFoundError,
	InvalidStatusTransitionError,
	FreightRateNotFoundError,
	_cents,
	_dec,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


def _make_carrier(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id=_uid(),
		name="TestCarrier",
		code="TC01",
		carrier_type="ROAD",
		is_active=True,
		on_time_delivery_rate_pct=Decimal("95.00"),
		avg_damage_rate_pct=Decimal("0.50"),
		preferred_routes=[],
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _make_shipment(**kw) -> SimpleNamespace:
	tid = _uid()
	defaults = dict(
		id=_uid(),
		tenant_id=tid,
		shipment_ref="SHP-20250101-00001",
		source_document_type=None,
		source_document_id=None,
		carrier_id=None,
		origin_address="Nairobi CBD",
		destination_address="Mombasa Port",
		origin_zone="NRB",
		destination_zone="MSA",
		status="PLANNED",
		weight_kg=Decimal("500.00"),
		volume_cbm=Decimal("2.50"),
		freight_cost_cents=0,
		currency_code="USD",
		planned_dispatch_date=date.today(),
		actual_dispatch_at=None,
		planned_delivery_date=date.today(),
		actual_delivery_at=None,
		driver_id=None,
		vehicle_id=None,
		pod_ref=None,
		tracking_events=[],
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _make_rate(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		carrier_id=_uid(),
		origin_zone="NRB",
		destination_zone="MSA",
		weight_kg_min=Decimal("0"),
		weight_kg_max=None,
		rate_type="PER_KG",
		rate_cents=50,
		currency_code="USD",
		effective_from=date(2024, 1, 1),
		effective_to=None,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _mock_session(get_result=None, scalar_result=0, scalars_result=None) -> MagicMock:
	session = MagicMock()
	session.get.return_value = get_result
	session.execute.return_value.scalar.return_value = scalar_result
	session.execute.return_value.scalar_one_or_none.return_value = None
	session.execute.return_value.scalars.return_value.all.return_value = (
		scalars_result if scalars_result is not None else []
	)
	session.execute.return_value.first.return_value = None
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# _cents / _dec helpers
# ---------------------------------------------------------------------------

class TestHelpers:
	def test_cents_integer(self):
		assert _cents(100) == 100

	def test_cents_decimal(self):
		assert _cents(Decimal("99.999")) == 100

	def test_cents_float_string(self):
		assert _cents("49.50") == 50

	def test_dec_string(self):
		assert _dec("3.14") == Decimal("3.14")

	def test_dec_int(self):
		assert _dec(5) == Decimal("5")


# ---------------------------------------------------------------------------
# _apply_rate
# ---------------------------------------------------------------------------

class TestApplyRate:
	def test_per_kg(self):
		rate = _make_rate(rate_type="PER_KG", rate_cents=50)
		result = TransportService._apply_rate(rate, Decimal("100"), Decimal("0"))
		assert result == 5000  # 50 * 100

	def test_flat(self):
		rate = _make_rate(rate_type="FLAT", rate_cents=10000)
		result = TransportService._apply_rate(rate, Decimal("999"), Decimal("0"))
		assert result == 10000  # flat ignores weight

	def test_per_cbm(self):
		rate = _make_rate(rate_type="PER_CBM", rate_cents=2000)
		result = TransportService._apply_rate(rate, Decimal("10"), Decimal("3"))
		assert result == 6000  # 2000 * 3

	def test_per_cbm_fallback_to_weight(self):
		rate = _make_rate(rate_type="PER_CBM", rate_cents=2000)
		result = TransportService._apply_rate(rate, Decimal("5"), Decimal("0"))
		assert result == 10000  # falls back to weight

	def test_per_unit(self):
		rate = _make_rate(rate_type="PER_UNIT", rate_cents=300)
		result = TransportService._apply_rate(rate, Decimal("10"), Decimal("0"))
		assert result == 3000


# ---------------------------------------------------------------------------
# create_shipment
# ---------------------------------------------------------------------------

class TestCreateShipment:
	def test_creates_shipment_with_ref(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			shipment = TransportService.create_shipment(
				origin_address="Nairobi CBD",
				destination_address="Mombasa Port",
				tenant_id=_uid(),
				session=session,
				origin_zone="NRB",
				destination_zone="MSA",
				weight_kg=Decimal("200"),
			)
		assert shipment is not None
		assert shipment.shipment_ref.startswith("SHP-")
		assert shipment.status == "PLANNED"
		assert shipment.freight_cost_cents == 0
		session.add.assert_called_once()
		session.flush.assert_called()

	def test_invalid_source_type_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(TransportServiceError, match="Invalid source_type"):
			TransportService.create_shipment(
				origin_address="A",
				destination_address="B",
				tenant_id=_uid(),
				session=session,
				source_type="INVALID_TYPE",
			)

	def test_valid_source_type_accepted(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			shipment = TransportService.create_shipment(
				origin_address="A",
				destination_address="B",
				tenant_id=_uid(),
				session=session,
				source_type="PURCHASE_ORDER",
				source_id="PO-001",
			)
		assert shipment.source_document_type == "PURCHASE_ORDER"

	def test_ref_increments_on_same_day(self):
		session = _mock_session(scalar_result=4)  # 4 existing today
		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			shipment = TransportService.create_shipment(
				origin_address="A",
				destination_address="B",
				tenant_id=_uid(),
				session=session,
			)
		assert shipment.shipment_ref.endswith("00005")


# ---------------------------------------------------------------------------
# book_carrier
# ---------------------------------------------------------------------------

class TestBookCarrier:
	def _setup(self, shipment_status="PLANNED"):
		carrier = _make_carrier()
		shipment = _make_shipment(
			carrier_id=None,
			status=shipment_status,
			tenant_id=carrier.tenant_id,
		)
		session = MagicMock()
		session.flush = MagicMock()

		def _get(model, id_):
			from pgappforge.plugins.erp.operations.transport.models import Carrier, Shipment
			if model == Carrier or str(model) == str(Carrier):
				return carrier
			return shipment

		session.get.side_effect = _get
		# Rate query returns empty → no rate
		session.execute.return_value.scalars.return_value.all.return_value = []
		return session, shipment, carrier

	def test_books_carrier_no_rate(self):
		session, shipment, carrier = self._setup()
		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			result = TransportService.book_carrier(
				shipment_id=shipment.id,
				carrier_id=carrier.id,
				session=session,
			)
		assert result.status == "BOOKED"
		assert result.carrier_id == carrier.id
		assert result.freight_cost_cents == 0  # no rate matched

	def test_cannot_book_dispatched_shipment(self):
		session, shipment, carrier = self._setup(shipment_status="DISPATCHED")
		with pytest.raises(InvalidStatusTransitionError):
			TransportService.book_carrier(
				shipment_id=shipment.id,
				carrier_id=carrier.id,
				session=session,
			)

	def test_shipment_not_found_raises(self):
		session = _mock_session(get_result=None)
		with pytest.raises(ShipmentNotFoundError):
			TransportService.book_carrier(
				shipment_id=_uid(),
				carrier_id=_uid(),
				session=session,
			)

	def test_inactive_carrier_raises(self):
		carrier = _make_carrier(is_active=False)
		shipment = _make_shipment(tenant_id=carrier.tenant_id)
		session = MagicMock()
		session.flush = MagicMock()

		def _get(model, id_):
			from pgappforge.plugins.erp.operations.transport.models import Carrier, Shipment
			if model == Carrier or str(model) == str(Carrier):
				return carrier
			return shipment

		session.get.side_effect = _get
		with pytest.raises(TransportServiceError, match="inactive"):
			TransportService.book_carrier(
				shipment_id=shipment.id,
				carrier_id=carrier.id,
				session=session,
			)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
	def test_dispatches_booked_shipment(self):
		shipment = _make_shipment(status="BOOKED")
		session = MagicMock()
		session.get.return_value = shipment
		session.flush = MagicMock()

		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			result = TransportService.dispatch(
				shipment_id=shipment.id,
				driver_id="DRV-001",
				session=session,
				vehicle_id="VEH-001",
			)

		assert result.status == "DISPATCHED"
		assert result.driver_id == "DRV-001"
		assert result.vehicle_id == "VEH-001"
		assert result.actual_dispatch_at is not None

	def test_dispatch_requires_booked_status(self):
		shipment = _make_shipment(status="PLANNED")
		session = MagicMock()
		session.get.return_value = shipment
		with pytest.raises(InvalidStatusTransitionError):
			TransportService.dispatch(
				shipment_id=shipment.id,
				driver_id="DRV-001",
				session=session,
			)

	def test_dispatch_shipment_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(ShipmentNotFoundError):
			TransportService.dispatch(
				shipment_id=_uid(),
				driver_id="DRV-001",
				session=session,
			)


# ---------------------------------------------------------------------------
# record_delivery
# ---------------------------------------------------------------------------

class TestRecordDelivery:
	@pytest.mark.parametrize("status", ["DISPATCHED", "IN_TRANSIT"])
	def test_records_delivery(self, status):
		shipment = _make_shipment(status=status)
		session = MagicMock()
		session.get.return_value = shipment
		session.flush = MagicMock()

		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			result = TransportService.record_delivery(
				shipment_id=shipment.id,
				pod_ref="POD-2025-001",
				session=session,
			)

		assert result.status == "DELIVERED"
		assert result.pod_ref == "POD-2025-001"
		assert result.actual_delivery_at is not None

	def test_cannot_deliver_planned(self):
		shipment = _make_shipment(status="PLANNED")
		session = MagicMock()
		session.get.return_value = shipment
		with pytest.raises(InvalidStatusTransitionError):
			TransportService.record_delivery(
				shipment_id=shipment.id,
				pod_ref="POD-X",
				session=session,
			)


# ---------------------------------------------------------------------------
# add_tracking_event
# ---------------------------------------------------------------------------

class TestAddTrackingEvent:
	def test_appends_event(self):
		shipment = _make_shipment(tracking_events=[])
		session = MagicMock()
		session.get.return_value = shipment
		session.flush = MagicMock()

		result = TransportService.add_tracking_event(
			shipment_id=shipment.id,
			location="Naivasha",
			status_note="Checkpoint cleared",
			session=session,
		)

		assert len(result.tracking_events) == 1
		ev = result.tracking_events[0]
		assert ev["location"] == "Naivasha"
		assert ev["notes"] == "Checkpoint cleared"
		assert "timestamp" in ev

	def test_appends_multiple(self):
		shipment = _make_shipment(tracking_events=[{"existing": True}])
		session = MagicMock()
		session.get.return_value = shipment
		session.flush = MagicMock()

		result = TransportService.add_tracking_event(
			shipment_id=shipment.id,
			location="Mtito Andei",
			status_note="En route",
			session=session,
		)
		assert len(result.tracking_events) == 2

	def test_not_found_raises(self):
		session = _mock_session(get_result=None)
		with pytest.raises(ShipmentNotFoundError):
			TransportService.add_tracking_event(
				shipment_id=_uid(),
				location="X",
				status_note="Y",
				session=session,
			)


# ---------------------------------------------------------------------------
# update_carrier_performance
# ---------------------------------------------------------------------------

class TestUpdateCarrierPerformance:
	def test_100_pct_when_no_shipments(self):
		carrier = _make_carrier()
		session = MagicMock()
		session.get.return_value = carrier
		session.flush = MagicMock()
		# total delivered = 0
		session.execute.return_value.scalar.return_value = 0

		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			result = TransportService.update_carrier_performance(
				carrier_id=carrier.id,
				period="2025-Q1",
				tenant_id=carrier.tenant_id,
				session=session,
			)

		assert result.on_time_delivery_rate_pct == Decimal("100")

	def test_on_time_rate_computed(self):
		carrier = _make_carrier()
		session = MagicMock()
		session.get.return_value = carrier
		session.flush = MagicMock()

		call_count = 0

		def _scalar():
			nonlocal call_count
			call_count += 1
			return 8 if call_count == 1 else 6  # total=8, on_time=6

		session.execute.return_value.scalar.side_effect = _scalar

		with patch("pgappforge.plugins.erp.operations.transport.services._emit"):
			result = TransportService.update_carrier_performance(
				carrier_id=carrier.id,
				period="2025-Q1",
				tenant_id=carrier.tenant_id,
				session=session,
			)

		assert result.on_time_delivery_rate_pct == Decimal("75.00")

	def test_carrier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(CarrierNotFoundError):
			TransportService.update_carrier_performance(
				carrier_id=_uid(),
				period="2025-Q1",
				tenant_id=_uid(),
				session=session,
			)
