"""
tests/ci/test_tax_plugin.py

CI tests for the Tax Management plugin.

Tests cover:
  - Model instantiation and repr
  - TaxService.determine_tax()
  - TaxService.post_tax_transaction()
  - TaxService.generate_vat_return()
  - TaxService.file_return() and pay_return()
  - TaxService.get_applicable_tax_code() (mock session)
  - Event dataclasses
  - Plugin class metadata, events, subscribe_to
  - No-float invariant for rates and amounts
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Model smoke tests
# ---------------------------------------------------------------------------

def test_tax_jurisdiction_instantiation():
	from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction
	jur = TaxJurisdiction(
		tenant_id="t-001",
		code="NG-FIRS",
		name="Nigeria Federal Inland Revenue Service",
		country_code="NG",
		tax_type="VAT",
		tax_authority_name="FIRS",
		filing_frequency="MONTHLY",
	)
	assert jur.tax_type == "VAT"
	assert "NG-FIRS" in repr(jur)


def test_tax_code_instantiation():
	from pgappforge.plugins.erp.finance.tax.models import TaxCode
	tc = TaxCode(
		tenant_id="t-001",
		jurisdiction_id="jur-001",
		code="STD",
		description="Standard Rate",
		rate=Decimal("7.5000"),
		effective_from=date(2020, 2, 1),
		effective_to=None,
		is_input_tax=True,
		is_output_tax=True,
		is_zero_rated=False,
		is_exempt=False,
		gl_account="2300",
	)
	assert str(tc.rate) == "7.5000"
	assert "STD" in repr(tc)


def test_tax_return_instantiation():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	ret = TaxReturn(
		tenant_id="t-001",
		jurisdiction_id="jur-001",
		period_start=date(2026, 1, 1),
		period_end=date(2026, 1, 31),
		output_tax_cents=1_500_000,
		input_tax_cents=600_000,
		net_tax_cents=900_000,
		status="DRAFT",
	)
	assert ret.net_tax_cents == 900_000
	assert "DRAFT" in repr(ret)


def test_tax_transaction_instantiation():
	from pgappforge.plugins.erp.finance.tax.models import TaxTransaction
	txn = TaxTransaction(
		tenant_id="t-001",
		tax_code_id="tc-001",
		source_document_type="SalesInvoice",
		source_document_id="inv-001",
		taxable_amount_cents=1_000_000,
		tax_amount_cents=75_000,
		is_recoverable=False,
		posting_date=date(2026, 1, 15),
		tax_period="2026-01",
	)
	assert txn.tax_amount_cents == 75_000
	assert "SalesInvoice" in repr(txn)


# ---------------------------------------------------------------------------
# Service: determine_tax
# ---------------------------------------------------------------------------

def _mock_tax_code(rate: str = "7.5000", is_exempt: bool = False, is_zero_rated: bool = False):
	tc = MagicMock()
	tc.rate = Decimal(rate)
	tc.is_exempt = is_exempt
	tc.is_zero_rated = is_zero_rated
	return tc


def test_determine_tax_standard_rate():
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	svc = TaxService()
	session = MagicMock()
	tc = _mock_tax_code("7.5000")

	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(1_000_000, "NG-FIRS", "STD", session, tenant_id="t-001")

	# 1,000,000 * 7.5% = 75,000
	assert tax == 75_000
	assert isinstance(tax, int)


def test_determine_tax_exempt_returns_zero():
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	svc = TaxService()
	session = MagicMock()
	tc = _mock_tax_code(is_exempt=True)

	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(500_000, "NG-FIRS", "EX", session)

	assert tax == 0


def test_determine_tax_zero_rated_returns_zero():
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	svc = TaxService()
	session = MagicMock()
	tc = _mock_tax_code("0.0000", is_zero_rated=True)

	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(500_000, "NG-FIRS", "ZR", session)

	assert tax == 0


def test_determine_tax_code_not_found_raises():
	from pgappforge.plugins.erp.finance.tax.services import TaxCodeNotFoundError, TaxService

	svc = TaxService()
	session = MagicMock()

	with patch.object(svc, "get_applicable_tax_code", return_value=None):
		with pytest.raises(TaxCodeNotFoundError):
			svc.determine_tax(100_000, "NG-FIRS", "NONEXISTENT", session)


def test_determine_tax_rounds_correctly():
	"""Tax on odd amounts should round half-up, never produce float."""
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	svc = TaxService()
	session = MagicMock()
	# 7.5% of 100,001 = 7,500.075 → rounds to 7,500
	tc = _mock_tax_code("7.5000")

	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(100_001, "NG-FIRS", "STD", session)

	assert isinstance(tax, int)
	assert tax == 7_500  # floor of 7500.075


def test_determine_tax_whichever_5_pct():
	from pgappforge.plugins.erp.finance.tax.services import TaxService
	svc = TaxService()
	session = MagicMock()
	tc = _mock_tax_code("5.0000")
	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(2_000_000, "NG-LIRS", "WHT5", session)
	# 5% of 2,000,000 = 100,000
	assert tax == 100_000


# ---------------------------------------------------------------------------
# Service: post_tax_transaction
# ---------------------------------------------------------------------------

def test_post_tax_transaction():
	from pgappforge.plugins.erp.finance.tax.models import TaxCode
	from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxTransactionDetails

	tc = MagicMock(spec=TaxCode)
	tc.rate = Decimal("7.5000")
	tc.is_exempt = False
	tc.is_zero_rated = False

	session = MagicMock()
	session.get.return_value = tc
	session.add = MagicMock()
	session.flush = MagicMock()

	details = TaxTransactionDetails(
		tenant_id="t-001",
		tax_code_id="tc-001",
		source_document_type="SalesInvoice",
		source_document_id="inv-001",
		taxable_amount_cents=1_000_000,
		posting_date=date(2026, 1, 15),
	)
	with patch("pgappforge.plugins.erp.finance.tax.events.emit_event"):
		txn = TaxService().post_tax_transaction(details, session)

	session.add.assert_called_once()
	assert txn.tax_amount_cents == 75_000
	assert txn.tax_period == "2026-01"
	assert txn.is_reversal is False


def test_post_tax_transaction_reversal():
	from pgappforge.plugins.erp.finance.tax.models import TaxCode
	from pgappforge.plugins.erp.finance.tax.services import TaxService, TaxTransactionDetails

	tc = MagicMock(spec=TaxCode)
	tc.rate = Decimal("7.5000")
	tc.is_exempt = False
	tc.is_zero_rated = False

	session = MagicMock()
	session.get.return_value = tc
	session.add = MagicMock()
	session.flush = MagicMock()

	details = TaxTransactionDetails(
		tenant_id="t-001",
		tax_code_id="tc-001",
		source_document_type="CreditNote",
		source_document_id="cn-001",
		taxable_amount_cents=-1_000_000,  # reversal
		posting_date=date(2026, 1, 20),
		is_reversal=True,
		reversal_of_id="txn-orig-001",
	)
	with patch("pgappforge.plugins.erp.finance.tax.events.emit_event"):
		txn = TaxService().post_tax_transaction(details, session)

	assert txn.is_reversal is True
	assert txn.tax_amount_cents == -75_000  # reversed


# ---------------------------------------------------------------------------
# Service: generate_vat_return
# ---------------------------------------------------------------------------

def test_generate_vat_return_creates_draft():
	from pgappforge.plugins.erp.finance.tax.models import TaxJurisdiction, TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	jurisdiction = MagicMock(spec=TaxJurisdiction)
	jurisdiction.id = "jur-001"
	jurisdiction.name = "Nigeria FIRS"

	session = MagicMock()
	session.get.return_value = jurisdiction

	# Simulate aggregate queries returning specific values
	call_seq = [1_500_000, 600_000, 20_000_000]  # output, input, taxable_supplies
	call_iter = iter(call_seq)

	def exec_side(*args, **kwargs):
		m = MagicMock()
		m.scalar_one.return_value = next(call_iter, 0)
		m.scalar_one_or_none.return_value = None  # no existing draft
		return m

	session.execute.side_effect = exec_side
	session.add = MagicMock()
	session.flush = MagicMock()

	with patch("pgappforge.plugins.erp.finance.tax.events.emit_event"):
		ret = TaxService().generate_vat_return(
			"jur-001",
			date(2026, 1, 1),
			date(2026, 1, 31),
			session,
			tenant_id="t-001",
		)

	assert ret.status == "DRAFT"
	assert ret.output_tax_cents == 1_500_000
	assert ret.input_tax_cents == 600_000
	assert ret.net_tax_cents == 900_000


# ---------------------------------------------------------------------------
# Service: file_return and pay_return
# ---------------------------------------------------------------------------

def test_file_return():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	ret = MagicMock(spec=TaxReturn)
	ret.id = "ret-001"
	ret.tenant_id = "t-001"
	ret.jurisdiction_id = "jur-001"
	ret.status = "DRAFT"
	ret.net_tax_cents = 900_000

	session = MagicMock()
	session.get.return_value = ret

	with patch("pgappforge.plugins.erp.finance.tax.events.emit_event"):
		result = TaxService().file_return("ret-001", "REF-2026-001", session)

	assert result.status == "FILED"
	assert result.reference_number == "REF-2026-001"


def test_file_return_not_draft_raises():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxReturnStatusError, TaxService

	ret = MagicMock(spec=TaxReturn)
	ret.status = "FILED"
	session = MagicMock()
	session.get.return_value = ret

	with pytest.raises(TaxReturnStatusError):
		TaxService().file_return("ret-001", "REF", session)


def test_pay_return():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxService

	ret = MagicMock(spec=TaxReturn)
	ret.id = "ret-001"
	ret.tenant_id = "t-001"
	ret.jurisdiction_id = "jur-001"
	ret.status = "FILED"
	ret.net_tax_cents = 900_000

	session = MagicMock()
	session.get.return_value = ret

	with patch("pgappforge.plugins.erp.finance.tax.events.emit_event"):
		result = TaxService().pay_return("ret-001", "PAY-REF-001", session)

	assert result.status == "PAID"
	assert result.payment_reference == "PAY-REF-001"


def test_pay_return_not_filed_raises():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxReturnStatusError, TaxService

	ret = MagicMock(spec=TaxReturn)
	ret.status = "DRAFT"  # must be FILED first
	session = MagicMock()
	session.get.return_value = ret

	with pytest.raises(TaxReturnStatusError):
		TaxService().pay_return("ret-001", "PAY", session)


def test_pay_return_refundable_raises():
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn
	from pgappforge.plugins.erp.finance.tax.services import TaxReturnStatusError, TaxService

	ret = MagicMock(spec=TaxReturn)
	ret.status = "FILED"
	ret.net_tax_cents = -100_000   # refund due
	session = MagicMock()
	session.get.return_value = ret

	with pytest.raises(TaxReturnStatusError, match="REFUND_CLAIMED"):
		TaxService().pay_return("ret-001", "PAY", session)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_tax_transaction_posted_event_payload():
	from pgappforge.plugins.erp.finance.tax.events import TaxTransactionPostedEvent
	evt = TaxTransactionPostedEvent(
		aggregate_id="txn-001",
		aggregate_type="TaxTransaction",
		tenant_id="t-001",
		tax_transaction_id="txn-001",
		tax_code_id="tc-001",
		source_document_type="SalesInvoice",
		source_document_id="inv-001",
		taxable_amount_cents=1_000_000,
		tax_amount_cents=75_000,
		posting_date="2026-01-15",
		is_recoverable=False,
	)
	payload = evt.build_payload()
	assert payload["tax_amount_cents"] == 75_000
	assert isinstance(payload["tax_amount_cents"], int)
	assert isinstance(payload["taxable_amount_cents"], int)


def test_all_tax_events_have_correct_types():
	from pgappforge.plugins.erp.finance.tax.events import (
		TaxRateExpiredEvent,
		TaxReturnFiledEvent,
		TaxReturnGeneratedEvent,
		TaxReturnPaidEvent,
		TaxTransactionPostedEvent,
	)
	assert TaxTransactionPostedEvent().event_type == "tax.transaction_posted"
	assert TaxReturnGeneratedEvent().event_type == "tax.return_generated"
	assert TaxReturnFiledEvent().event_type == "tax.return_filed"
	assert TaxReturnPaidEvent().event_type == "tax.return_paid"
	assert TaxRateExpiredEvent().event_type == "tax.rate_expired"


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

def test_tax_plugin_metadata():
	from pgappforge.plugins.erp.finance.tax import TaxPlugin
	plugin = TaxPlugin(MagicMock())
	assert plugin.name == "tax"
	assert plugin.domain == "finance"
	assert "foundation" in plugin.depends_on
	meta = plugin.metadata
	assert "can_tax_return_generate" in meta.permissions
	assert "can_tax_return_file" in meta.permissions
	assert "can_tax_return_pay" in meta.permissions


def test_tax_plugin_events():
	from pgappforge.plugins.erp.finance.tax import TaxPlugin
	plugin = TaxPlugin(MagicMock())
	events = plugin.get_events()
	assert "tax.transaction_posted" in events
	assert "tax.return_generated" in events
	assert "tax.return_filed" in events
	subs = plugin.subscribe_to()
	assert "invoice.posted" in subs
	assert "payment.posted" in subs
	assert "exchange_rate.updated" in subs


def test_tax_plugin_register_models():
	from pgappforge.plugins.erp.finance.tax import TaxPlugin
	from pgappforge.plugins.erp.finance.tax.models import (
		TaxCode, TaxJurisdiction, TaxReturn, TaxTransaction,
	)
	plugin = TaxPlugin(MagicMock())
	models = plugin.register_models()
	assert TaxJurisdiction in models
	assert TaxCode in models
	assert TaxReturn in models
	assert TaxTransaction in models


# ---------------------------------------------------------------------------
# No-float invariants
# ---------------------------------------------------------------------------

def test_tax_rate_is_decimal_not_float():
	from pgappforge.plugins.erp.finance.tax.models import TaxCode
	tc = TaxCode(
		tenant_id="t-001",
		jurisdiction_id="jur-001",
		code="STD",
		description="Standard Rate",
		rate=Decimal("7.5000"),
		effective_from=date(2020, 2, 1),
		gl_account="2300",
	)
	assert isinstance(tc.rate, Decimal)
	assert not isinstance(tc.rate, float)


def test_determine_tax_returns_int_not_float():
	from pgappforge.plugins.erp.finance.tax.services import TaxService
	svc = TaxService()
	session = MagicMock()
	tc = _mock_tax_code("7.5000")
	with patch.object(svc, "get_applicable_tax_code", return_value=tc):
		tax = svc.determine_tax(333_333, "NG-FIRS", "STD", session)
	assert isinstance(tax, int)
	# 333,333 * 7.5% = 24,999.975 → rounds to 25,000
	assert tax == 25_000


def test_tax_amount_cents_never_float():
	"""Tax amounts must always be int — never float. Check all model fields."""
	from pgappforge.plugins.erp.finance.tax.models import TaxReturn, TaxTransaction
	ret = TaxReturn(
		tenant_id="t-001",
		jurisdiction_id="jur-001",
		period_start=date(2026, 1, 1),
		period_end=date(2026, 1, 31),
		output_tax_cents=1_000_000,
		input_tax_cents=250_000,
		net_tax_cents=750_000,
	)
	assert isinstance(ret.output_tax_cents, int)
	assert isinstance(ret.net_tax_cents, int)

	txn = TaxTransaction(
		tenant_id="t-001",
		tax_code_id="tc-001",
		source_document_type="Invoice",
		source_document_id="inv-001",
		taxable_amount_cents=500_000,
		tax_amount_cents=37_500,
		posting_date=date(2026, 1, 15),
	)
	assert isinstance(txn.tax_amount_cents, int)
	assert isinstance(txn.taxable_amount_cents, int)
