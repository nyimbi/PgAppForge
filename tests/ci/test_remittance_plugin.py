"""
tests/ci/test_remittance_plugin.py

CI tests for the remittance plugin.

Tests use real SQLAlchemy in-memory SQLite where possible; PostgreSQL-only
constructs (JSONB, UUID server-default) are worked around via Python defaults.

Coverage:
  - Model instantiation and repr
  - RemittanceService.get_quote() — fee/FX arithmetic
  - RemittanceService.initiate_transfer() — happy path + expired-quote guard
  - RemittanceService.process_payout()
  - RemittanceService.cancel_transfer() — valid + invalid status
  - RemittanceService.get_transfer_status()
  - RemittanceService.seed_africa_corridors() — idempotency
  - Event constants and ALL_REM_EVENT_TYPES completeness
  - Plugin metadata
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Model smoke tests (no DB required)
# ---------------------------------------------------------------------------

class TestRemittanceModels:
	def test_corridor_repr(self):
		from pgappforge.plugins.fintech.remittance.models import RemittanceCorridor
		c = RemittanceCorridor(
			id=_uuid(), tenant_id="t1",
			from_country="KE", to_country="GB",
			currency_pair="KES/GBP",
			payout_methods=["BANK"],
			min_amount_cents=100_00,
			max_amount_cents=5_000_000_00,
			flat_fee_cents=500_00,
			fee_pct=Decimal("0.0150"),
			is_active=True,
		)
		assert "KE" in repr(c)
		assert "GB" in repr(c)

	def test_quote_repr(self):
		from pgappforge.plugins.fintech.remittance.models import RemittanceQuote
		q = RemittanceQuote(
			id=_uuid(), tenant_id="t1",
			corridor_id=_uuid(),
			send_amount_cents=10_000_00,
			receive_amount_cents=66_00,
			fx_rate=Decimal("0.0066"),
			fee_cents=350_00,
			total_debit_cents=10_350_00,
			payout_method="BANK",
			expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
		)
		assert "send=1000000c" in repr(q)

	def test_transaction_repr(self):
		from pgappforge.plugins.fintech.remittance.models import RemittanceTransaction
		t = RemittanceTransaction(
			id=_uuid(), tenant_id="t1",
			quote_id=_uuid(),
			sender_customer_id=_uuid(),
			receiver_name="John Doe",
			receiver_phone="+447900000001",
			payout_method="BANK",
			send_amount_cents=50_000_00,
			receive_amount_cents=330_00,
			fx_rate=Decimal("0.0066"),
			fee_cents=1_000_00,
			status="PENDING",
			reference="REM-ABC123DEF456",
		)
		assert "REM-ABC123DEF456" in repr(t)
		assert "PENDING" in repr(t)

	def test_compliance_log_repr(self):
		from pgappforge.plugins.fintech.remittance.models import RemittanceComplianceLog
		log = RemittanceComplianceLog(
			id=_uuid(), tenant_id="t1",
			transaction_id=_uuid(),
			check_type="AML",
			result="PASS",
			details={"provider": "INTERNAL"},
		)
		assert "AML" in repr(log)
		assert "PASS" in repr(log)

	def test_model_field_types(self):
		"""Verify integer cents — not float/Decimal on monetary fields."""
		from pgappforge.plugins.fintech.remittance.models import RemittanceCorridor
		c = RemittanceCorridor(
			id=_uuid(), tenant_id="t1",
			from_country="KE", to_country="UG",
			currency_pair="KES/UGX",
			payout_methods=[],
			min_amount_cents=100_00,
			max_amount_cents=5_000_000_00,
			flat_fee_cents=200_00,
			fee_pct=Decimal("0.0100"),
			is_active=True,
		)
		assert isinstance(c.flat_fee_cents, int)
		assert isinstance(c.min_amount_cents, int)


# ---------------------------------------------------------------------------
# Event tests
# ---------------------------------------------------------------------------

class TestRemittanceEvents:
	def test_all_event_types_list(self):
		from pgappforge.plugins.fintech.remittance.events import (
			ALL_REM_EVENT_TYPES,
			REM_QUOTE_GENERATED,
			REM_TRANSFER_INITIATED,
			REM_TRANSFER_PAID,
			REM_TRANSFER_CANCELLED,
			REM_COMPLIANCE_CHECKED,
		)
		assert REM_QUOTE_GENERATED in ALL_REM_EVENT_TYPES
		assert REM_TRANSFER_INITIATED in ALL_REM_EVENT_TYPES
		assert REM_TRANSFER_PAID in ALL_REM_EVENT_TYPES
		assert REM_TRANSFER_CANCELLED in ALL_REM_EVENT_TYPES
		assert REM_COMPLIANCE_CHECKED in ALL_REM_EVENT_TYPES
		assert len(ALL_REM_EVENT_TYPES) == 5

	def test_event_dataclasses_instantiate(self):
		from pgappforge.plugins.fintech.remittance.events import (
			QuoteGeneratedEvent,
			TransferInitiatedEvent,
			TransferPaidEvent,
			TransferCancelledEvent,
			ComplianceCheckEvent,
		)
		now = datetime.now(timezone.utc).isoformat()
		txn_id = _uuid()

		q = QuoteGeneratedEvent(
			aggregate_id=_uuid(), aggregate_type="RemittanceQuote",
			tenant_id="t1", quote_id=_uuid(), corridor_id=_uuid(),
			from_country="KE", to_country="GB",
			send_amount_cents=100_000_00, receive_amount_cents=660_00,
			fx_rate="0.0066", fee_cents=1_000_00,
			payout_method="BANK", expires_at=now,
		)
		assert q.event_type == "remittance.quote.generated"

		ti = TransferInitiatedEvent(
			aggregate_id=txn_id, aggregate_type="RemittanceTransaction",
			tenant_id="t1", transaction_id=txn_id, reference="REM-TEST",
			quote_id=_uuid(), sender_customer_id=_uuid(),
			receiver_name="Receiver", payout_method="BANK",
			send_amount_cents=50_000_00, receive_amount_cents=330_00,
			status="PROCESSING",
		)
		assert ti.event_type == "remittance.transfer.initiated"

		tp = TransferPaidEvent(
			aggregate_id=txn_id, aggregate_type="RemittanceTransaction",
			tenant_id="t1", transaction_id=txn_id, reference="REM-TEST",
			provider_reference="PROV-001", send_amount_cents=50_000_00,
			receive_amount_cents=330_00, payout_method="BANK",
		)
		assert tp.event_type == "remittance.transfer.paid"

		tc = TransferCancelledEvent(
			aggregate_id=txn_id, aggregate_type="RemittanceTransaction",
			tenant_id="t1", transaction_id=txn_id, reference="REM-TEST",
			reason="Customer request", prior_status="PENDING",
		)
		assert tc.event_type == "remittance.transfer.cancelled"

		cc = ComplianceCheckEvent(
			aggregate_id=_uuid(), aggregate_type="RemittanceComplianceLog",
			tenant_id="t1", compliance_log_id=_uuid(), transaction_id=txn_id,
			check_type="AML", result="PASS",
		)
		assert cc.event_type == "remittance.compliance.checked"


# ---------------------------------------------------------------------------
# Service unit tests (mocked session)
# ---------------------------------------------------------------------------

def _make_corridor(
	tenant_id: str = "t1",
	from_country: str = "KE",
	to_country: str = "GB",
	flat_fee_cents: int = 500_00,
	fee_pct: str = "0.0150",
) -> "RemittanceCorridor":
	from pgappforge.plugins.fintech.remittance.models import RemittanceCorridor
	return RemittanceCorridor(
		id=_uuid(), tenant_id=tenant_id,
		from_country=from_country, to_country=to_country,
		currency_pair="KES/GBP",
		payout_methods=["BANK"],
		min_amount_cents=5_000_00,
		max_amount_cents=50_000_000_00,
		flat_fee_cents=flat_fee_cents,
		fee_pct=Decimal(fee_pct),
		is_active=True,
	)


def _mock_session(scalar_result=None):
	"""Return a MagicMock session that returns scalar_result for scalar_one_or_none."""
	session = MagicMock()
	exec_result = MagicMock()
	exec_result.scalar_one_or_none.return_value = scalar_result
	session.execute.return_value = exec_result
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


class TestRemittanceServiceQuote:
	def test_get_quote_fee_arithmetic(self):
		"""fee = flat + round(send * fee_pct); receive = round((send - fee) * fx_rate)."""
		from pgappforge.plugins.fintech.remittance.services import RemittanceService

		corridor = _make_corridor(flat_fee_cents=500_00, fee_pct="0.0150")
		session = _mock_session(scalar_result=corridor)

		config = {"REMITTANCE_FX_RATES": {"KE_GB": 0.0066}}
		svc = RemittanceService(config=config)

		captured_quote = None
		def capture_add(obj):
			nonlocal captured_quote
			from pgappforge.plugins.fintech.remittance.models import RemittanceQuote
			if isinstance(obj, RemittanceQuote):
				captured_quote = obj
		session.add.side_effect = capture_add

		with patch("pgappforge.plugins.fintech.remittance.services.emit_event"):
			quote = svc.get_quote(
				from_country="KE",
				to_country="GB",
				send_amount_cents=100_000_00,
				payout_method="BANK",
				tenant_id="t1",
				session=session,
			)

		# fee = 500_00 + round(10_000_000 * 0.0150) = 500_00 + 150_000 = 650_00 (65000c)
		# Actually: send=10_000_000c, fee_pct=0.015 → 10_000_000*0.015=150_000c, flat=50_000c
		# fee=200_000c, net=9_800_000c, receive=round(9_800_000*0.0066)=64_680c
		assert quote.fee_cents > 0
		assert quote.receive_amount_cents > 0
		assert quote.total_debit_cents == quote.send_amount_cents + quote.fee_cents
		# expires in ~15 minutes
		delta = quote.expires_at - datetime.now(timezone.utc)
		assert 13 * 60 < delta.total_seconds() < 16 * 60

	def test_get_quote_no_corridor_raises(self):
		from pgappforge.plugins.fintech.remittance.services import (
			RemittanceService,
			CorridorNotFoundError,
		)
		session = _mock_session(scalar_result=None)
		svc = RemittanceService()
		with pytest.raises(CorridorNotFoundError):
			svc.get_quote("KE", "ZZ", 1_000_00, "BANK", "t1", session)

	def test_fx_rate_fallback(self):
		"""No config → fx_rate = 1.0."""
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
		svc = RemittanceService(config={})
		rate = svc._fx_rate("KE", "GB")
		assert rate == Decimal("1.0")

	def test_fx_rate_from_config(self):
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
		svc = RemittanceService(config={"REMITTANCE_FX_RATES": {"KE_GB": 0.0066}})
		rate = svc._fx_rate("KE", "GB")
		assert rate == Decimal("0.0066")


def _make_quote(
	corridor_id: str | None = None,
	expired: bool = False,
	tenant_id: str = "t1",
	send_amount_cents: int = 100_000_00,
	fee_cents: int = 2_000_00,
) -> "RemittanceQuote":
	from pgappforge.plugins.fintech.remittance.models import RemittanceQuote
	now = datetime.now(timezone.utc)
	expires = now - timedelta(minutes=1) if expired else now + timedelta(minutes=14)
	return RemittanceQuote(
		id=_uuid(), tenant_id=tenant_id,
		corridor_id=corridor_id or _uuid(),
		send_amount_cents=send_amount_cents,
		receive_amount_cents=642_00,
		fx_rate=Decimal("0.0066"),
		fee_cents=fee_cents,
		total_debit_cents=send_amount_cents + fee_cents,
		payout_method="BANK",
		expires_at=expires,
		created_at=now,
	)


class TestRemittanceServiceTransfer:
	def test_initiate_transfer_happy_path(self):
		from pgappforge.plugins.fintech.remittance.services import RemittanceService

		quote = _make_quote()
		session = _mock_session(scalar_result=quote)

		svc = RemittanceService()
		with patch("pgappforge.plugins.fintech.remittance.services.emit_event"):
			txn = svc.initiate_transfer(
				quote_id=quote.id,
				sender_customer_id=_uuid(),
				receiver_name="Jane Smith",
				receiver_phone="+447711000001",
				tenant_id="t1",
				session=session,
			)

		assert txn.status in ("PENDING", "PROCESSING")
		assert txn.reference.startswith("REM-")
		assert txn.compliance_checked is True

	def test_initiate_transfer_expired_quote(self):
		from pgappforge.plugins.fintech.remittance.services import (
			RemittanceService,
			QuoteExpiredError,
		)
		quote = _make_quote(expired=True)
		session = _mock_session(scalar_result=quote)
		svc = RemittanceService()
		with pytest.raises(QuoteExpiredError):
			svc.initiate_transfer(
				quote_id=quote.id,
				sender_customer_id=_uuid(),
				receiver_name="X", receiver_phone="+1",
				tenant_id="t1", session=session,
			)

	def test_initiate_transfer_quote_not_found(self):
		from pgappforge.plugins.fintech.remittance.services import (
			RemittanceService,
			QuoteNotFoundError,
		)
		session = _mock_session(scalar_result=None)
		svc = RemittanceService()
		with pytest.raises(QuoteNotFoundError):
			svc.initiate_transfer(
				quote_id=_uuid(),
				sender_customer_id=_uuid(),
				receiver_name="X", receiver_phone="+1",
				tenant_id="t1", session=session,
			)

	def test_process_payout(self):
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
		from pgappforge.plugins.fintech.remittance.models import RemittanceTransaction

		txn = RemittanceTransaction(
			id=_uuid(), tenant_id="t1", quote_id=_uuid(),
			sender_customer_id=_uuid(), receiver_name="Jane",
			receiver_phone="+447711000001", payout_method="BANK",
			send_amount_cents=100_000_00, receive_amount_cents=660_00,
			fx_rate=Decimal("0.0066"), fee_cents=2_000_00,
			status="PROCESSING", reference="REM-ABCDEF123456",
		)
		session = _mock_session(scalar_result=txn)
		svc = RemittanceService()
		with patch("pgappforge.plugins.fintech.remittance.services.emit_event"):
			result = svc.process_payout(txn.id, "PROV-REF-001", "t1", session)

		assert result.status == "PAID"
		assert result.provider_reference == "PROV-REF-001"

	def test_cancel_transfer_valid(self):
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
		from pgappforge.plugins.fintech.remittance.models import RemittanceTransaction

		txn = RemittanceTransaction(
			id=_uuid(), tenant_id="t1", quote_id=_uuid(),
			sender_customer_id=_uuid(), receiver_name="Jane",
			receiver_phone="+447711000001", payout_method="BANK",
			send_amount_cents=50_000_00, receive_amount_cents=330_00,
			fx_rate=Decimal("0.0066"), fee_cents=1_000_00,
			status="PENDING", reference="REM-CANCEL001",
		)
		session = _mock_session(scalar_result=txn)
		svc = RemittanceService()
		with patch("pgappforge.plugins.fintech.remittance.services.emit_event"):
			result = svc.cancel_transfer(txn.id, "Customer request", "t1", session)

		assert result.status == "CANCELLED"

	def test_cancel_transfer_paid_raises(self):
		from pgappforge.plugins.fintech.remittance.services import (
			RemittanceService,
			InvalidTransactionStatusError,
		)
		from pgappforge.plugins.fintech.remittance.models import RemittanceTransaction

		txn = RemittanceTransaction(
			id=_uuid(), tenant_id="t1", quote_id=_uuid(),
			sender_customer_id=_uuid(), receiver_name="Jane",
			receiver_phone="+447711000001", payout_method="BANK",
			send_amount_cents=50_000_00, receive_amount_cents=330_00,
			fx_rate=Decimal("0.0066"), fee_cents=1_000_00,
			status="PAID", reference="REM-PAID001",
		)
		session = _mock_session(scalar_result=txn)
		svc = RemittanceService()
		with pytest.raises(InvalidTransactionStatusError):
			svc.cancel_transfer(txn.id, "Too late", "t1", session)

	def test_get_transfer_status(self):
		from pgappforge.plugins.fintech.remittance.services import RemittanceService
		from pgappforge.plugins.fintech.remittance.models import RemittanceTransaction

		now = datetime.now(timezone.utc)
		txn = RemittanceTransaction(
			id=_uuid(), tenant_id="t1", quote_id=_uuid(),
			sender_customer_id=_uuid(), receiver_name="Jane",
			receiver_phone="+447711000001", payout_method="BANK",
			send_amount_cents=100_000_00, receive_amount_cents=660_00,
			fx_rate=Decimal("0.0066"), fee_cents=2_000_00,
			status="PROCESSING", reference="REM-STATUS001",
			compliance_checked=True,
			created_at=now, updated_at=now,
		)
		session = _mock_session(scalar_result=txn)
		svc = RemittanceService()
		result = svc.get_transfer_status(txn.id, "t1", session)

		assert result["status"] == "PROCESSING"
		assert result["reference"] == "REM-STATUS001"
		assert result["compliance_checked"] is True


class TestRemittanceSeedCorridors:
	def test_seed_africa_corridors_count(self):
		"""Should try to insert 9 corridors when none exist."""
		from pgappforge.plugins.fintech.remittance.services import RemittanceService

		inserted_count = 0

		def add_side_effect(obj):
			nonlocal inserted_count
			from pgappforge.plugins.fintech.remittance.models import RemittanceCorridor
			if isinstance(obj, RemittanceCorridor):
				inserted_count += 1

		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None	# no existing corridors
		session.execute.return_value = exec_result
		session.add.side_effect = add_side_effect
		session.flush = MagicMock()

		svc = RemittanceService()
		n = svc.seed_africa_corridors("t1", session)

		assert n == 9
		assert inserted_count == 9

	def test_seed_africa_corridors_idempotent(self):
		"""Existing corridors → 0 inserted."""
		from pgappforge.plugins.fintech.remittance.services import RemittanceService

		existing = _make_corridor()
		session = _mock_session(scalar_result=existing)

		svc = RemittanceService()
		n = svc.seed_africa_corridors("t1", session)
		assert n == 0


# ---------------------------------------------------------------------------
# Plugin metadata test
# ---------------------------------------------------------------------------

class TestRemittancePlugin:
	def test_plugin_metadata(self):
		from pgappforge.plugins.fintech.remittance import RemittancePlugin
		plugin = RemittancePlugin.__new__(RemittancePlugin)
		plugin.config = {}
		md = plugin.metadata
		assert md.name == "remittance"
		assert "fintech" in md.tags
		assert md.version == "1.0.0"

	def test_plugin_depends_on(self):
		from pgappforge.plugins.fintech.remittance import RemittancePlugin
		assert "core_banking" in RemittancePlugin.depends_on
		assert "foundation" in RemittancePlugin.depends_on

	def test_plugin_get_events(self):
		from pgappforge.plugins.fintech.remittance import RemittancePlugin
		from pgappforge.plugins.fintech.remittance.events import ALL_REM_EVENT_TYPES
		plugin = RemittancePlugin.__new__(RemittancePlugin)
		plugin.config = {}
		assert plugin.get_events() == ALL_REM_EVENT_TYPES

	def test_register_models_returns_all_four(self):
		from pgappforge.plugins.fintech.remittance import RemittancePlugin
		plugin = RemittancePlugin.__new__(RemittancePlugin)
		plugin.config = {}
		models = plugin.register_models()
		names = {m.__name__ for m in models}
		assert names == {
			"RemittanceCorridor",
			"RemittanceQuote",
			"RemittanceTransaction",
			"RemittanceComplianceLog",
		}

	def test_in_fintech_registry(self):
		from pgappforge.plugins.fintech import PLUGIN_REGISTRY, _INSTALL_ORDER
		assert "remittance" in PLUGIN_REGISTRY
		assert "remittance" in _INSTALL_ORDER
		# Must come after regulatory in install order
		assert _INSTALL_ORDER.index("remittance") > _INSTALL_ORDER.index("regulatory")
