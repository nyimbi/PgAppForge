"""
tests/ci/test_tax_gap_close.py

Tests for gap-closed Finance Tax methods:
  - WHTCertificate model
  - TaxService.apply_tax
  - TaxService.generate_wht_return
  - TaxService.issue_wht_certificate
  - TaxService.file_tax_return
  - TaxService.get_tax_calendar
  - TaxService.get_tax_dashboard
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


def _make_jurisdiction(jur_id: str, tenant_id: str, tax_type: str = "VAT") -> MagicMock:
	j = MagicMock()
	j.id = jur_id
	j.tenant_id = tenant_id
	j.code = f"KE-{tax_type}"
	j.tax_type = tax_type
	j.is_active = True
	return j


def _make_tax_code(
	code_id: str,
	tenant_id: str,
	jurisdiction_id: str,
	code: str = "STD",
	rate: str = "16.0000",
	is_output: bool = True,
	is_input: bool = False,
	is_exempt: bool = False,
	is_zero_rated: bool = False,
	gl_account: str = "2100-VAT",
) -> MagicMock:
	tc = MagicMock()
	tc.id = code_id
	tc.tenant_id = tenant_id
	tc.jurisdiction_id = jurisdiction_id
	tc.code = code
	tc.rate = Decimal(rate)
	tc.is_output_tax = is_output
	tc.is_input_tax = is_input
	tc.is_exempt = is_exempt
	tc.is_zero_rated = is_zero_rated
	tc.gl_account = gl_account
	tc.is_active = True
	tc.effective_from = date(2020, 1, 1)
	tc.effective_to = None
	return tc


def _make_session(tax_code: MagicMock | None = None) -> MagicMock:
	"""Return a mock SQLAlchemy session with sensible defaults."""
	session = MagicMock()
	# session.get returns tax_code for TaxCode lookups, None otherwise
	def _get(model, pk):
		from pgappforge.plugins.erp.finance.tax.models import TaxCode
		if model is TaxCode and tax_code and pk == tax_code.id:
			return tax_code
		return None
	session.get.side_effect = _get
	session.flush.return_value = None
	# execute().scalar_one() chain — return 0 by default
	exec_result = MagicMock()
	exec_result.scalar_one.return_value = 0
	exec_result.scalar_one_or_none.return_value = None
	exec_result.scalars.return_value.all.return_value = []
	exec_result.all.return_value = []
	session.execute.return_value = exec_result
	return session


# ---------------------------------------------------------------------------
# WHTCertificate model
# ---------------------------------------------------------------------------

class TestWHTCertificateModel:
	def test_instantiation(self):
		from pgappforge.plugins.erp.finance.tax.models import WHTCertificate
		tenant_id = _uuid()
		payee_id = _uuid()
		cert = WHTCertificate(
			tenant_id=tenant_id,
			cert_number="WHT-2026-000001",
			payee_id=payee_id,
			payee_pin="P051234567A",
			payment_date=date(2026, 5, 15),
			gross_amount_cents=1_000_000,
			wht_rate_pct=Decimal("5.0000"),
			wht_amount_cents=50_000,
			net_amount_cents=950_000,
			income_type="PROFESSIONAL_FEES",
			issued_by=_uuid(),
		)
		assert cert.cert_number == "WHT-2026-000001"
		assert cert.wht_amount_cents == 50_000
		assert cert.net_amount_cents == 950_000

	def test_repr(self):
		from pgappforge.plugins.erp.finance.tax.models import WHTCertificate
		cert = WHTCertificate(
			tenant_id=_uuid(),
			cert_number="WHT-2026-000042",
			payee_id=_uuid(),
			payee_pin="P999",
			payment_date=date(2026, 6, 1),
			gross_amount_cents=500_000,
			wht_rate_pct=Decimal("3.0000"),
			wht_amount_cents=15_000,
			net_amount_cents=485_000,
			income_type="RENT",
			issued_by=_uuid(),
		)
		r = repr(cert)
		assert "WHT-2026-000042" in r
		assert "15000" in r

	def test_in_all_export(self):
		from pgappforge.plugins.erp.finance.tax import models
		assert "WHTCertificate" in models.__all__


# ---------------------------------------------------------------------------
# TaxService.apply_tax
# ---------------------------------------------------------------------------

class TestApplyTax:
	def setup_method(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		self.svc = TaxService()
		self.tenant_id = _uuid()
		self.code_id = _uuid()
		self.jur_id = _uuid()

	def _make_session_with_code(self, code: MagicMock) -> MagicMock:
		"""Session where execute().scalar_one_or_none() returns the code."""
		session = MagicMock()
		session.flush.return_value = None
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = code
		exec_result.scalar_one.return_value = 0
		exec_result.scalars.return_value.all.return_value = []
		session.execute.return_value = exec_result
		# session.add captures adds
		session.add.return_value = None
		return session

	def test_apply_tax_computes_and_creates_transaction(self):
		from pgappforge.plugins.erp.finance.tax.models import TaxTransaction
		tc = _make_tax_code(
			self.code_id, self.tenant_id, self.jur_id,
			code="STD", rate="16.0000",
		)
		session = self._make_session_with_code(tc)

		txn = self.svc.apply_tax(
			session=session,
			taxable_amount_cents=100_000,
			tax_code="STD",
			source_doc_type="INVOICE",
			source_doc_id=_uuid(),
			period_month=date(2026, 6, 1),
			tenant_id=self.tenant_id,
		)
		assert txn.tax_amount_cents == 16_000
		assert txn.taxable_amount_cents == 100_000
		session.add.assert_called_once()
		session.flush.assert_called_once()

	def test_apply_tax_exempt_code_returns_zero(self):
		tc = _make_tax_code(
			self.code_id, self.tenant_id, self.jur_id,
			code="EXM", rate="0.0000", is_exempt=True,
		)
		session = self._make_session_with_code(tc)

		txn = self.svc.apply_tax(
			session=session,
			taxable_amount_cents=200_000,
			tax_code="EXM",
			source_doc_type="INVOICE",
			source_doc_id=_uuid(),
			period_month=date(2026, 6, 1),
			tenant_id=self.tenant_id,
		)
		assert txn.tax_amount_cents == 0

	def test_apply_tax_code_not_found_raises(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxCodeNotFoundError
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		session.execute.return_value = exec_result

		with pytest.raises(TaxCodeNotFoundError):
			self.svc.apply_tax(
				session=session,
				taxable_amount_cents=100_000,
				tax_code="MISSING",
				source_doc_type="INVOICE",
				source_doc_id=_uuid(),
				period_month=date(2026, 6, 1),
				tenant_id=self.tenant_id,
			)

	def test_apply_tax_rounding(self):
		"""16% of 100001 cents = 16000.16 → rounds to 16000."""
		tc = _make_tax_code(
			self.code_id, self.tenant_id, self.jur_id,
			code="STD", rate="16.0000",
		)
		session = self._make_session_with_code(tc)
		txn = self.svc.apply_tax(
			session=session,
			taxable_amount_cents=100_001,
			tax_code="STD",
			source_doc_type="INVOICE",
			source_doc_id=_uuid(),
			period_month=date(2026, 6, 1),
			tenant_id=self.tenant_id,
		)
		# 100001 * 0.16 = 16000.16 → ROUND_HALF_UP → 16000
		assert txn.tax_amount_cents == 16000

	def test_apply_tax_period_derived_from_date(self):
		tc = _make_tax_code(
			self.code_id, self.tenant_id, self.jur_id,
			code="STD", rate="5.0000",
		)
		session = self._make_session_with_code(tc)
		txn = self.svc.apply_tax(
			session=session,
			taxable_amount_cents=50_000,
			tax_code="STD",
			source_doc_type="PURCHASE",
			source_doc_id=_uuid(),
			period_month=date(2026, 3, 15),
			tenant_id=self.tenant_id,
		)
		assert txn.tax_period == "2026-03"


# ---------------------------------------------------------------------------
# TaxService.issue_wht_certificate
# ---------------------------------------------------------------------------

class TestIssueWHTCertificate:
	def setup_method(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		self.svc = TaxService()
		self.tenant_id = _uuid()

	def _make_session(self, existing_count: int = 0) -> MagicMock:
		session = MagicMock()
		session.flush.return_value = None
		session.add.return_value = None
		exec_result = MagicMock()
		exec_result.scalar_one.return_value = existing_count
		session.execute.return_value = exec_result
		return session

	def test_cert_number_format(self):
		session = self._make_session(existing_count=0)
		cert = self.svc.issue_wht_certificate(
			session=session,
			payee_id=_uuid(),
			payment_date=date(2026, 5, 20),
			gross_amount_cents=1_000_000,
			wht_rate_pct=Decimal("5.0000"),
			income_type="PROFESSIONAL_FEES",
			issued_by=_uuid(),
			tenant_id=self.tenant_id,
		)
		assert cert.cert_number == "WHT-2026-000001"

	def test_cert_number_sequential(self):
		session = self._make_session(existing_count=41)
		cert = self.svc.issue_wht_certificate(
			session=session,
			payee_id=_uuid(),
			payment_date=date(2026, 5, 20),
			gross_amount_cents=500_000,
			wht_rate_pct=Decimal("10.0000"),
			income_type="DIVIDEND",
			issued_by=_uuid(),
			tenant_id=self.tenant_id,
		)
		assert cert.cert_number == "WHT-2026-000042"

	def test_wht_amount_computed_correctly(self):
		session = self._make_session()
		cert = self.svc.issue_wht_certificate(
			session=session,
			payee_id=_uuid(),
			payment_date=date(2026, 6, 1),
			gross_amount_cents=2_000_000,
			wht_rate_pct=Decimal("15.0000"),
			income_type="MANAGEMENT_FEES",
			issued_by=_uuid(),
			tenant_id=self.tenant_id,
		)
		assert cert.wht_amount_cents == 300_000   # 15% of 2_000_000
		assert cert.net_amount_cents == 1_700_000  # gross - wht

	def test_gross_zero_raises(self):
		session = self._make_session()
		with pytest.raises(AssertionError):
			self.svc.issue_wht_certificate(
				session=session,
				payee_id=_uuid(),
				payment_date=date(2026, 6, 1),
				gross_amount_cents=0,
				wht_rate_pct=Decimal("5.0000"),
				income_type="RENT",
				issued_by=_uuid(),
				tenant_id=self.tenant_id,
			)

	def test_payee_pin_stored(self):
		session = self._make_session()
		cert = self.svc.issue_wht_certificate(
			session=session,
			payee_id=_uuid(),
			payment_date=date(2026, 6, 1),
			gross_amount_cents=100_000,
			wht_rate_pct=Decimal("5.0000"),
			income_type="INTEREST",
			issued_by=_uuid(),
			tenant_id=self.tenant_id,
			payee_pin="A000112345Z",
		)
		assert cert.payee_pin == "A000112345Z"


# ---------------------------------------------------------------------------
# TaxService.file_tax_return
# ---------------------------------------------------------------------------

class TestFileTaxReturn:
	def setup_method(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		self.svc = TaxService()
		self.tenant_id = _uuid()

	def _make_return(self, status: str = "DRAFT", net: int = 50_000) -> MagicMock:
		r = MagicMock()
		r.id = _uuid()
		r.tenant_id = self.tenant_id
		r.status = status
		r.net_tax_cents = net
		r.filing_date = None
		r.reference_number = None
		r.updated_at = None
		return r

	def _make_session(self, ret: MagicMock) -> MagicMock:
		session = MagicMock()
		session.flush.return_value = None
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn
		def _get(model, pk):
			if model is TaxReturn and pk == ret.id:
				return ret
			return None
		session.get.side_effect = _get
		exec_result = MagicMock()
		exec_result.scalar_one.return_value = 0
		exec_result.scalar_one_or_none.return_value = None
		session.execute.return_value = exec_result
		return session

	def test_draft_return_gets_filed(self):
		ret = self._make_return(status="DRAFT", net=100_000)
		session = self._make_session(ret)
		result = self.svc.file_tax_return(
			session=session,
			return_id=ret.id,
			kra_reference="KRA-2026-001",
			filed_by=_uuid(),
			tenant_id=self.tenant_id,
		)
		assert result.status == "FILED"
		assert result.reference_number == "KRA-2026-001"

	def test_non_draft_raises(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxReturnStatusError
		ret = self._make_return(status="FILED")
		session = self._make_session(ret)
		with pytest.raises(TaxReturnStatusError):
			self.svc.file_tax_return(
				session=session,
				return_id=ret.id,
				kra_reference="KRA-X",
				filed_by=_uuid(),
				tenant_id=self.tenant_id,
			)

	def test_wrong_tenant_raises(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxReturnStatusError
		ret = self._make_return(status="DRAFT")
		session = self._make_session(ret)
		with pytest.raises(TaxReturnStatusError):
			self.svc.file_tax_return(
				session=session,
				return_id=ret.id,
				kra_reference="KRA-X",
				filed_by=_uuid(),
				tenant_id=_uuid(),  # different tenant
			)

	def test_not_found_raises(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxReturnNotFoundError
		session = MagicMock()
		session.get.return_value = None
		with pytest.raises(TaxReturnNotFoundError):
			self.svc.file_tax_return(
				session=session,
				return_id=_uuid(),
				kra_reference="KRA-X",
				filed_by=_uuid(),
				tenant_id=self.tenant_id,
			)


# ---------------------------------------------------------------------------
# TaxService.get_tax_calendar
# ---------------------------------------------------------------------------

class TestGetTaxCalendar:
	def setup_method(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		self.svc = TaxService()

	def test_returns_60_entries(self):
		"""5 obligations × 12 months = 60."""
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		assert len(entries) == 60

	def test_each_entry_has_required_keys(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		required = {"obligation", "period", "due_date", "status", "days_until"}
		for e in entries:
			assert required == set(e.keys()), f"Missing keys in {e}"

	def test_obligations_present(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		obligations = {e["obligation"] for e in entries}
		assert obligations == {"VAT", "WHT", "PAYE", "NSSF", "NHIF"}

	def test_vat_due_20th_following_month(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		jan_vat = next(
			e for e in entries
			if e["obligation"] == "VAT" and e["period"] == "2026-01"
		)
		assert jan_vat["due_date"] == date(2026, 2, 20)

	def test_paye_due_9th_following_month(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		jan_paye = next(
			e for e in entries
			if e["obligation"] == "PAYE" and e["period"] == "2026-01"
		)
		assert jan_paye["due_date"] == date(2026, 2, 9)

	def test_status_values_are_valid(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		valid_statuses = {"OVERDUE", "DUE_SOON", "UPCOMING"}
		for e in entries:
			assert e["status"] in valid_statuses

	def test_sorted_by_due_date(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		dates = [e["due_date"] for e in entries]
		assert dates == sorted(dates)

	def test_dec_obligations_roll_to_next_year(self):
		session = MagicMock()
		entries = self.svc.get_tax_calendar(session, fiscal_year=2026, tenant_id=_uuid())
		dec_vat = next(
			e for e in entries
			if e["obligation"] == "VAT" and e["period"] == "2026-12"
		)
		# VAT for Dec 2026 is due 20 Jan 2027
		assert dec_vat["due_date"] == date(2027, 1, 20)


# ---------------------------------------------------------------------------
# TaxService.get_tax_dashboard
# ---------------------------------------------------------------------------

class TestGetTaxDashboard:
	def setup_method(self):
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		self.svc = TaxService()
		self.tenant_id = _uuid()

	def _make_session(
		self,
		pending: int = 2,
		overdue: int = 1,
		ytd_output: int = 500_000,
		ytd_input: int = 100_000,
		ytd_wht: int = 80_000,
	) -> MagicMock:
		session = MagicMock()

		call_count = [0]
		def _exec(q):
			result = MagicMock()
			c = call_count[0]
			# Order of calls: pending, overdue, vat_output, vat_input, wht
			values = [pending, overdue, ytd_output, ytd_input, ytd_wht]
			result.scalar_one.return_value = values[c] if c < len(values) else 0
			call_count[0] += 1
			return result

		session.execute.side_effect = _exec
		return session

	def test_dashboard_keys(self):
		session = self._make_session()
		dashboard = self.svc.get_tax_dashboard(session, tenant_id=self.tenant_id)
		assert set(dashboard.keys()) == {
			"pending_returns",
			"overdue_returns",
			"ytd_vat_payable_cents",
			"ytd_wht_withheld_cents",
			"next_filing_deadline",
		}

	def test_vat_payable_is_output_minus_input(self):
		session = self._make_session(ytd_output=500_000, ytd_input=100_000)
		dashboard = self.svc.get_tax_dashboard(session, tenant_id=self.tenant_id)
		assert dashboard["ytd_vat_payable_cents"] == 400_000

	def test_pending_and_overdue_counts(self):
		session = self._make_session(pending=3, overdue=1)
		dashboard = self.svc.get_tax_dashboard(session, tenant_id=self.tenant_id)
		assert dashboard["pending_returns"] == 3
		assert dashboard["overdue_returns"] == 1

	def test_next_deadline_is_dict_or_none(self):
		session = self._make_session()
		dashboard = self.svc.get_tax_dashboard(session, tenant_id=self.tenant_id)
		nd = dashboard["next_filing_deadline"]
		assert nd is None or isinstance(nd, dict)

	def test_generate_wht_return_structure(self):
		"""generate_wht_return returns expected keys."""
		from pgappforge.plugins.erp.finance.tax.services import TaxService
		svc = TaxService()
		session = MagicMock()
		exec_result = MagicMock()
		exec_result.scalars.return_value.all.return_value = []
		exec_result.scalar_one_or_none.return_value = None
		session.execute.return_value = exec_result
		session.flush.return_value = None

		result = svc.generate_wht_return(
			session=session,
			period_month=date(2026, 5, 1),
			tenant_id=_uuid(),
		)
		assert "period" in result
		assert "total_gross_cents" in result
		assert "total_wht_cents" in result
		assert "payee_count" in result
		assert "by_income_type" in result
		assert "wht_certificates" in result
		assert result["total_gross_cents"] == 0
		assert result["total_wht_cents"] == 0
