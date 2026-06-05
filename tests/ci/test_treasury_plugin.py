"""
tests/ci/test_treasury_plugin.py

CI tests for the Treasury Management plugin.

Tests cover:
  - Model instantiation and repr
  - TreasuryService.create_bank_account()
  - TreasuryService.book_fx_deal() and settle_fx_deal()
  - TreasuryService.cash_flow_forecast()
  - TreasuryService.mark_to_market_hedges()
  - TreasuryService._generate_deal_reference()
  - Event dataclasses
  - Plugin class metadata, events, subscribe_to
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------

def test_bank_account_instantiation():
	from pgappforge.plugins.erp.finance.treasury.models import BankAccount
	acct = BankAccount(
		tenant_id="t-001",
		account_number="0123456789",
		bank_name="GTBank",
		bank_bic="GTBINGLA",
		currency_code="NGN",
		account_type="CURRENT",
		gl_account="1100",
		balance_cents=0,
		available_balance_cents=0,
	)
	assert acct.account_type == "CURRENT"
	assert "GTBank" in repr(acct)


def test_cash_position_instantiation():
	from pgappforge.plugins.erp.finance.treasury.models import CashPosition
	cp = CashPosition(
		tenant_id="t-001",
		bank_account_id="acct-001",
		position_date=date(2026, 1, 31),
		opening_balance_cents=1_000_000,
		receipts_cents=500_000,
		payments_cents=300_000,
		closing_balance_cents=1_200_000,
	)
	assert cp.closing_balance_cents == 1_200_000
	assert "1200000" in repr(cp)


def test_fx_deal_instantiation():
	from pgappforge.plugins.erp.finance.treasury.models import FXDeal
	deal = FXDeal(
		tenant_id="t-001",
		deal_reference="FX-2026-00001",
		deal_type="SPOT",
		buy_currency="NGN",
		sell_currency="USD",
		buy_amount_cents=1_620_000_00,
		sell_amount_cents=100_000_00,
		contracted_rate=Decimal("1620.00000000"),
		settlement_date=date(2026, 1, 17),
		hedge_designation="NONE",
		status="OPEN",
	)
	assert deal.status == "OPEN"
	assert "FX-2026-00001" in repr(deal)


def test_bank_statement_instantiation():
	from pgappforge.plugins.erp.finance.treasury.models import BankStatement
	stmt = BankStatement(
		tenant_id="t-001",
		bank_account_id="acct-001",
		statement_date=date(2026, 1, 31),
		opening_balance_cents=1_000_000,
		closing_balance_cents=1_200_000,
		status="IMPORTED",
	)
	assert stmt.status == "IMPORTED"
	assert "IMPORTED" in repr(stmt)


def test_bank_statement_line_instantiation():
	from pgappforge.plugins.erp.finance.treasury.models import BankStatementLine
	line = BankStatementLine(
		statement_id="stmt-001",
		transaction_date=date(2026, 1, 15),
		description="POS Purchase",
		amount_cents=50_000,
		is_debit=True,
		match_status="UNMATCHED",
	)
	assert line.is_debit is True
	assert "DR" in repr(line)


# ---------------------------------------------------------------------------
# Service: create_bank_account
# ---------------------------------------------------------------------------

def test_create_bank_account():
	from pgappforge.plugins.erp.finance.treasury.services import (
		BankAccountDetails, TreasuryService,
	)
	session = MagicMock()
	session.add = MagicMock()
	session.flush = MagicMock()

	details = BankAccountDetails(
		tenant_id="t-001",
		account_number="0123456789",
		bank_name="GTBank",
		currency_code="NGN",
		gl_account="1100",
		account_type="CURRENT",
	)
	with patch("pgappforge.plugins.erp.finance.treasury.events.emit_event"):
		acct = TreasuryService().create_bank_account(details, session)

	session.add.assert_called_once()
	session.flush.assert_called_once()
	assert acct.balance_cents == 0
	assert acct.currency_code == "NGN"


def test_create_bank_account_invalid_type_raises():
	from pgappforge.plugins.erp.finance.treasury.services import (
		BankAccountDetails, TreasuryService,
	)
	session = MagicMock()
	details = BankAccountDetails(
		tenant_id="t-001",
		account_number="111",
		bank_name="X",
		currency_code="USD",
		gl_account="1100",
		account_type="INVALID",
	)
	with pytest.raises(AssertionError):
		TreasuryService().create_bank_account(details, session)


# ---------------------------------------------------------------------------
# Service: FX deal
# ---------------------------------------------------------------------------

def test_book_fx_deal():
	from pgappforge.plugins.erp.finance.treasury.services import FXDealDetails, TreasuryService

	session = MagicMock()
	session.add = MagicMock()
	session.flush = MagicMock()
	session.execute.return_value.scalar_one.return_value = 3  # 3 existing deals

	details = FXDealDetails(
		tenant_id="t-001",
		deal_type="SPOT",
		buy_currency="NGN",
		sell_currency="USD",
		buy_amount_cents=162_000_000,
		sell_amount_cents=100_000_00,
		contracted_rate=Decimal("1620.00000000"),
		settlement_date=date(2026, 1, 17),
	)
	with patch("pgappforge.plugins.erp.finance.treasury.events.emit_event"):
		deal = TreasuryService().book_fx_deal(details, session)

	session.add.assert_called_once()
	assert deal.status == "OPEN"
	assert deal.deal_reference == "FX-2026-00004"
	assert deal.buy_currency == "NGN"


def test_book_fx_deal_invalid_type_raises():
	from pgappforge.plugins.erp.finance.treasury.services import FXDealDetails, TreasuryService

	session = MagicMock()
	details = FXDealDetails(
		tenant_id="t-001",
		deal_type="OPTIONS",   # invalid
		buy_currency="NGN",
		sell_currency="USD",
		buy_amount_cents=100,
		sell_amount_cents=100,
		contracted_rate=Decimal("1.0"),
		settlement_date=date(2026, 1, 17),
	)
	with pytest.raises(AssertionError):
		TreasuryService().book_fx_deal(details, session)


def test_settle_fx_deal():
	from pgappforge.plugins.erp.finance.treasury.models import FXDeal
	from pgappforge.plugins.erp.finance.treasury.services import TreasuryService

	deal = MagicMock(spec=FXDeal)
	deal.status = "OPEN"
	deal.deal_reference = "FX-2026-00001"
	deal.tenant_id = "t-001"
	deal.settlement_date = date(2026, 1, 17)
	deal.buy_amount_cents = 162_000_000
	deal.sell_amount_cents = 10_000_000

	session = MagicMock()
	session.get.return_value = deal

	with patch("pgappforge.plugins.erp.finance.treasury.events.emit_event"):
		result = TreasuryService().settle_fx_deal("deal-001", session)

	assert result.status == "SETTLED"


def test_settle_already_settled_raises():
	from pgappforge.plugins.erp.finance.treasury.models import FXDeal
	from pgappforge.plugins.erp.finance.treasury.services import FXDealStatusError, TreasuryService

	deal = MagicMock(spec=FXDeal)
	deal.status = "SETTLED"
	deal.deal_reference = "FX-2026-00001"

	session = MagicMock()
	session.get.return_value = deal

	with pytest.raises(FXDealStatusError):
		TreasuryService().settle_fx_deal("deal-001", session)


def test_settle_not_found_raises():
	from pgappforge.plugins.erp.finance.treasury.services import FXDealNotFoundError, TreasuryService
	session = MagicMock()
	session.get.return_value = None
	with pytest.raises(FXDealNotFoundError):
		TreasuryService().settle_fx_deal("nonexistent", session)


# ---------------------------------------------------------------------------
# Service: cash flow forecast
# ---------------------------------------------------------------------------

def test_cash_flow_forecast_returns_correct_days():
	from pgappforge.plugins.erp.finance.treasury.models import BankAccount
	from pgappforge.plugins.erp.finance.treasury.services import TreasuryService

	account = MagicMock(spec=BankAccount)
	account.id = "acct-001"
	account.balance_cents = 5_000_000
	account.tenant_id = "t-001"

	session = MagicMock()
	session.get.return_value = account
	# No latest cash position
	session.execute.return_value.scalar_one_or_none.return_value = None
	# No pending FX deals
	session.execute.return_value.scalars.return_value.all.return_value = []

	result = TreasuryService().cash_flow_forecast("acct-001", 7, session)

	assert len(result) == 7
	assert result[0]["opening_cents"] == 5_000_000
	# All receipts/payments zero with no FX deals
	assert all(r["expected_receipts_cents"] == 0 for r in result)
	assert all(r["forecast_closing_cents"] == 5_000_000 for r in result)


def test_cash_flow_forecast_not_found_raises():
	from pgappforge.plugins.erp.finance.treasury.services import BankAccountNotFoundError, TreasuryService
	session = MagicMock()
	session.get.return_value = None
	with pytest.raises(BankAccountNotFoundError):
		TreasuryService().cash_flow_forecast("nonexistent", 5, session)


# ---------------------------------------------------------------------------
# Service: mark-to-market
# ---------------------------------------------------------------------------

def test_mark_to_market_updates_deals():
	from pgappforge.plugins.erp.finance.treasury.models import FXDeal
	from pgappforge.plugins.erp.finance.treasury.services import TreasuryService

	deal = MagicMock(spec=FXDeal)
	deal.id = "deal-001"
	deal.deal_reference = "FX-2026-00001"
	deal.tenant_id = "t-001"
	deal.sell_currency = "USD"
	deal.buy_currency = "NGN"
	deal.contracted_rate = Decimal("1600.00000000")
	deal.sell_amount_cents = 10_000_000   # 100,000 USD
	deal.hedge_designation = "NONE"

	rate_row = MagicMock()
	rate_row.rate = Decimal("1620.00000000")  # market moved +20 NGN/USD

	# session.execute().scalars().all() -> [deal]
	# session.execute().scalar_one_or_none() -> rate_row
	mock_exec = MagicMock()
	call_count = [0]

	def execute_side_effect(q):
		call_count[0] += 1
		m = MagicMock()
		if call_count[0] == 1:
			m.scalars.return_value.all.return_value = [deal]
		else:
			m.scalar_one_or_none.return_value = rate_row
		return m

	session = MagicMock()
	session.execute.side_effect = execute_side_effect
	session.flush = MagicMock()

	results = TreasuryService().mark_to_market_hedges(session, tenant_id="t-001")

	assert len(results) == 1
	# MTM = (1620 - 1600) * 10,000,000 = 200,000,000 cents
	assert results[0]["mtm_value_cents"] == 200_000_000
	assert deal.mtm_value_cents == 200_000_000


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_fx_deal_booked_event_payload():
	from pgappforge.plugins.erp.finance.treasury.events import FXDealBookedEvent
	evt = FXDealBookedEvent(
		aggregate_id="deal-001",
		aggregate_type="FXDeal",
		tenant_id="t-001",
		deal_id="deal-001",
		deal_reference="FX-2026-00001",
		deal_type="SPOT",
		buy_currency="NGN",
		sell_currency="USD",
		buy_amount_cents=162_000_000,
		sell_amount_cents=10_000_000,
		contracted_rate="1620.00000000",  # string — no float
		settlement_date="2026-01-17",
		hedge_designation="NONE",
	)
	payload = evt.build_payload()
	assert payload["contracted_rate"] == "1620.00000000"
	assert isinstance(payload["buy_amount_cents"], int)


def test_all_treasury_events_have_correct_types():
	from pgappforge.plugins.erp.finance.treasury.events import (
		BankAccountCreatedEvent,
		BankReconciliationDoneEvent,
		CashPositionUpdatedEvent,
		FXDealBookedEvent,
		FXDealSettledEvent,
	)
	assert BankAccountCreatedEvent().event_type == "treasury.bank_account_created"
	assert FXDealBookedEvent().event_type == "treasury.fx_deal_booked"
	assert FXDealSettledEvent().event_type == "treasury.fx_deal_settled"
	assert BankReconciliationDoneEvent().event_type == "treasury.bank_reconciliation_done"
	assert CashPositionUpdatedEvent().event_type == "treasury.cash_position_updated"


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

def test_treasury_plugin_metadata():
	from pgappforge.plugins.erp.finance.treasury import TreasuryPlugin
	plugin = TreasuryPlugin(MagicMock())
	assert plugin.name == "treasury"
	assert plugin.domain == "finance"
	assert "foundation" in plugin.depends_on
	meta = plugin.metadata
	assert "can_treasury_fx_book" in meta.permissions


def test_treasury_plugin_events():
	from pgappforge.plugins.erp.finance.treasury import TreasuryPlugin
	plugin = TreasuryPlugin(MagicMock())
	events = plugin.get_events()
	assert "treasury.fx_deal_booked" in events
	assert "treasury.bank_reconciliation_done" in events
	subs = plugin.subscribe_to()
	assert "exchange_rate.updated" in subs
	assert "party.created" in subs


def test_treasury_plugin_register_models():
	from pgappforge.plugins.erp.finance.treasury import TreasuryPlugin
	from pgappforge.plugins.erp.finance.treasury.models import (
		BankAccount, BankStatement, BankStatementLine, CashPosition, FXDeal,
	)
	plugin = TreasuryPlugin(MagicMock())
	models = plugin.register_models()
	assert BankAccount in models
	assert FXDeal in models
	assert CashPosition in models
	assert BankStatement in models
	assert BankStatementLine in models


# ---------------------------------------------------------------------------
# No-float invariant
# ---------------------------------------------------------------------------

def test_contracted_rate_is_decimal_not_float():
	from pgappforge.plugins.erp.finance.treasury.models import FXDeal
	deal = FXDeal(
		tenant_id="t-001",
		deal_reference="FX-TEST",
		deal_type="FORWARD",
		buy_currency="EUR",
		sell_currency="GBP",
		buy_amount_cents=100_000,
		sell_amount_cents=85_000,
		contracted_rate=Decimal("1.17500000"),
		settlement_date=date(2026, 6, 30),
		hedge_designation="CASH_FLOW",
		status="OPEN",
	)
	assert not isinstance(deal.contracted_rate, float)
	assert isinstance(deal.contracted_rate, Decimal)
