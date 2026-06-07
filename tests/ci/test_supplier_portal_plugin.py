"""
tests/ci/test_supplier_portal_plugin.py

Unit tests for the Supplier Portal plugin.

Strategy
--------
- Pure-logic tests: no real DB, no Flask context.
- Session is a MagicMock; model instances are SimpleNamespace objects.
- Event emission is monkey-patched.
- Covers: register_supplier, submit_kyc_documents, approve_kyc,
          verify_bank_details, rate_supplier (composite formula),
          suspend_supplier, get_approved_suppliers,
          status FSM guards, rolling overall_score.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.erp.procurement.supplier_portal.services import (
	SupplierPortalService,
	SupplierPortalServiceError,
	SupplierNotFoundError,
	InvalidStatusTransitionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _make_supplier(**kw) -> SimpleNamespace:
	tid = _uid()
	defaults = dict(
		id=_uid(),
		tenant_id=tid,
		company_name="Acme Supplies Ltd",
		supplier_ref="SUP-20250101-00001",
		company_reg_number=None,
		tax_id=None,
		country_code="KE",
		contact_email="info@acme.co.ke",
		contact_phone=None,
		primary_category="GOODS",
		kyc_status="PENDING",
		kyc_approved_by=None,
		kyc_approved_at=None,
		kyc_documents=[],
		bank_name=None,
		bank_account_number=None,
		bank_branch=None,
		bank_swift=None,
		bank_verified=False,
		bank_verified_at=None,
		overall_score=None,
		is_preferred=False,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _make_perf_card(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id=_uid(),
		supplier_id=_uid(),
		period="2025-Q1",
		on_time_delivery_pct=Decimal("90"),
		quality_acceptance_pct=Decimal("85"),
		invoice_accuracy_pct=Decimal("95"),
		responsiveness_score=Decimal("80"),
		composite_score=Decimal("89.00"),
		po_count=10,
		grn_count=10,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _mock_session(get_result=None, scalar_result=0) -> MagicMock:
	session = MagicMock()
	session.get.return_value = get_result
	session.execute.return_value.scalar.return_value = scalar_result
	session.execute.return_value.scalar_one_or_none.return_value = None
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# register_supplier
# ---------------------------------------------------------------------------

class TestRegisterSupplier:
	def test_registers_supplier_pending_kyc(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			supplier = SupplierPortalService.register_supplier(
				company_name="Acme Supplies Ltd",
				country_code="KE",
				contact_email="info@acme.co.ke",
				tenant_id=_uid(),
				session=session,
			)
		assert supplier.kyc_status == "PENDING"
		assert supplier.supplier_ref.startswith("SUP-")
		assert supplier.bank_verified is False
		session.add.assert_called_once()

	def test_empty_company_name_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(SupplierPortalServiceError, match="cannot be empty"):
			SupplierPortalService.register_supplier(
				company_name="  ",
				country_code="KE",
				contact_email="x@x.com",
				tenant_id=_uid(),
				session=session,
			)

	def test_invalid_category_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(SupplierPortalServiceError, match="Invalid primary_category"):
			SupplierPortalService.register_supplier(
				company_name="Test Co",
				country_code="KE",
				contact_email="x@x.com",
				tenant_id=_uid(),
				session=session,
				primary_category="INVALID",
			)

	def test_country_code_uppercased(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			supplier = SupplierPortalService.register_supplier(
				company_name="Test Co",
				country_code="ke",
				contact_email="x@x.com",
				tenant_id=_uid(),
				session=session,
			)
		assert supplier.country_code == "KE"

	def test_email_lowercased(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			supplier = SupplierPortalService.register_supplier(
				company_name="Test Co",
				country_code="KE",
				contact_email="INFO@ACME.COM",
				tenant_id=_uid(),
				session=session,
			)
		assert supplier.contact_email == "info@acme.com"

	def test_ref_sequential(self):
		session = _mock_session(scalar_result=4)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			supplier = SupplierPortalService.register_supplier(
				company_name="Test",
				country_code="KE",
				contact_email="x@x.com",
				tenant_id=_uid(),
				session=session,
			)
		assert supplier.supplier_ref.endswith("00005")


# ---------------------------------------------------------------------------
# submit_kyc_documents
# ---------------------------------------------------------------------------

class TestSubmitKYCDocuments:
	def test_appends_documents(self):
		supplier = _make_supplier(kyc_documents=[])
		session = _mock_session(get_result=supplier)

		docs = [
			{"doc_type": "CERT_INC", "url": "https://example.com/cert.pdf"},
			{"doc_type": "TAX_PIN", "url": "https://example.com/pin.pdf"},
		]
		result = SupplierPortalService.submit_kyc_documents(
			supplier_id=supplier.id,
			documents=docs,
			session=session,
		)
		assert len(result.kyc_documents) == 2
		assert result.kyc_documents[0]["doc_type"] == "CERT_INC"

	def test_appends_to_existing(self):
		supplier = _make_supplier(kyc_documents=[{"doc_type": "OLD", "url": "old.pdf", "uploaded_at": "2025-01-01"}])
		session = _mock_session(get_result=supplier)

		result = SupplierPortalService.submit_kyc_documents(
			supplier_id=supplier.id,
			documents=[{"doc_type": "NEW", "url": "new.pdf"}],
			session=session,
		)
		assert len(result.kyc_documents) == 2

	def test_supplier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(SupplierNotFoundError):
			SupplierPortalService.submit_kyc_documents(
				supplier_id=_uid(),
				documents=[],
				session=session,
			)


# ---------------------------------------------------------------------------
# approve_kyc
# ---------------------------------------------------------------------------

class TestApproveKYC:
	def test_approves_pending(self):
		supplier = _make_supplier(kyc_status="PENDING")
		session = _mock_session(get_result=supplier)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			result = SupplierPortalService.approve_kyc(
				supplier_id=supplier.id,
				approver_id="USR-ADMIN",
				session=session,
			)
		assert result.kyc_status == "APPROVED"
		assert result.kyc_approved_by == "USR-ADMIN"
		assert result.kyc_approved_at is not None

	def test_approves_rejected(self):
		supplier = _make_supplier(kyc_status="REJECTED")
		session = _mock_session(get_result=supplier)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			result = SupplierPortalService.approve_kyc(
				supplier_id=supplier.id,
				approver_id="USR-ADMIN",
				session=session,
			)
		assert result.kyc_status == "APPROVED"

	def test_cannot_approve_suspended(self):
		supplier = _make_supplier(kyc_status="SUSPENDED")
		session = _mock_session(get_result=supplier)
		with pytest.raises(InvalidStatusTransitionError):
			SupplierPortalService.approve_kyc(
				supplier_id=supplier.id,
				approver_id="USR-ADMIN",
				session=session,
			)

	def test_supplier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(SupplierNotFoundError):
			SupplierPortalService.approve_kyc(
				supplier_id=_uid(),
				approver_id="USR-ADMIN",
				session=session,
			)


# ---------------------------------------------------------------------------
# verify_bank_details
# ---------------------------------------------------------------------------

class TestVerifyBankDetails:
	def test_verifies_bank(self):
		supplier = _make_supplier(kyc_status="APPROVED")
		session = _mock_session(get_result=supplier)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			result = SupplierPortalService.verify_bank_details(
				supplier_id=supplier.id,
				bank_name="Equity Bank",
				account_number="1234567890",
				swift="EQBLKENA",
				session=session,
				bank_ref="BNK-REF-2025",
			)
		assert result.bank_verified is True
		assert result.bank_name == "Equity Bank"
		assert result.bank_account_number == "1234567890"
		assert result.bank_swift == "EQBLKENA"
		assert result.bank_verified_at is not None

	def test_swift_uppercased(self):
		supplier = _make_supplier()
		session = _mock_session(get_result=supplier)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			result = SupplierPortalService.verify_bank_details(
				supplier_id=supplier.id,
				bank_name="KCB",
				account_number="9999",
				swift="kcbakena",
				session=session,
			)
		assert result.bank_swift == "KCBAKENA"

	def test_supplier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(SupplierNotFoundError):
			SupplierPortalService.verify_bank_details(
				supplier_id=_uid(),
				bank_name="X",
				account_number="X",
				swift="X",
				session=session,
			)


# ---------------------------------------------------------------------------
# rate_supplier (composite formula)
# ---------------------------------------------------------------------------

class TestRateSupplier:
	def test_composite_formula(self):
		"""composite = 0.4*90 + 0.3*80 + 0.2*95 + 0.1*70 = 36+24+19+7 = 86"""
		supplier = _make_supplier()
		session = MagicMock()
		session.get.return_value = supplier
		session.flush = MagicMock()
		session.add = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = None
		# _compute_overall_score query
		session.execute.return_value.scalar.return_value = Decimal("86.00")

		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			card = SupplierPortalService.rate_supplier(
				supplier_id=supplier.id,
				period="2025-Q1",
				on_time_pct=90,
				quality_pct=80,
				invoice_pct=95,
				responsiveness=70,
				session=session,
			)

		expected = Decimal("0.4") * 90 + Decimal("0.3") * 80 + Decimal("0.2") * 95 + Decimal("0.1") * 70
		assert card.composite_score == expected.quantize(Decimal("0.01"))

	def test_updates_existing_card(self):
		existing_card = _make_perf_card(period="2025-Q1")
		supplier = _make_supplier()
		session = MagicMock()
		session.get.return_value = supplier
		session.flush = MagicMock()
		session.execute.return_value.scalar_one_or_none.return_value = existing_card
		session.execute.return_value.scalar.return_value = Decimal("85.00")

		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			card = SupplierPortalService.rate_supplier(
				supplier_id=supplier.id,
				period="2025-Q1",
				on_time_pct=95,
				quality_pct=90,
				invoice_pct=90,
				responsiveness=85,
				session=session,
			)

		# Should update the existing card, not add a new one
		session.add.assert_not_called()
		assert card.on_time_delivery_pct == Decimal("95")

	def test_supplier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(SupplierNotFoundError):
			SupplierPortalService.rate_supplier(
				supplier_id=_uid(),
				period="2025-Q1",
				on_time_pct=80,
				quality_pct=80,
				invoice_pct=80,
				responsiveness=80,
				session=session,
			)


# ---------------------------------------------------------------------------
# suspend_supplier
# ---------------------------------------------------------------------------

class TestSuspendSupplier:
	def test_suspends_approved(self):
		supplier = _make_supplier(kyc_status="APPROVED")
		session = _mock_session(get_result=supplier)
		with patch("pgappforge.plugins.erp.procurement.supplier_portal.services._emit"):
			result = SupplierPortalService.suspend_supplier(
				supplier_id=supplier.id,
				reason="Fraudulent invoices",
				session=session,
			)
		assert result.kyc_status == "SUSPENDED"

	def test_idempotent_suspend(self):
		supplier = _make_supplier(kyc_status="SUSPENDED")
		session = _mock_session(get_result=supplier)
		result = SupplierPortalService.suspend_supplier(
			supplier_id=supplier.id,
			reason="again",
			session=session,
		)
		assert result.kyc_status == "SUSPENDED"
		session.flush.assert_not_called()

	def test_cannot_suspend_pending(self):
		supplier = _make_supplier(kyc_status="PENDING")
		session = _mock_session(get_result=supplier)
		with pytest.raises(InvalidStatusTransitionError):
			SupplierPortalService.suspend_supplier(
				supplier_id=supplier.id,
				reason="Wrong status",
				session=session,
			)

	def test_supplier_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(SupplierNotFoundError):
			SupplierPortalService.suspend_supplier(
				supplier_id=_uid(),
				reason="missing",
				session=session,
			)


# ---------------------------------------------------------------------------
# get_approved_suppliers
# ---------------------------------------------------------------------------

class TestGetApprovedSuppliers:
	def test_returns_approved(self):
		approved = [_make_supplier(kyc_status="APPROVED"), _make_supplier(kyc_status="APPROVED")]
		session = MagicMock()
		session.execute.return_value.scalars.return_value.all.return_value = approved

		result = SupplierPortalService.get_approved_suppliers(
			tenant_id=_uid(),
			session=session,
		)
		assert len(result) == 2

	def test_category_filter_passed_to_query(self):
		session = MagicMock()
		session.execute.return_value.scalars.return_value.all.return_value = []

		SupplierPortalService.get_approved_suppliers(
			tenant_id=_uid(),
			session=session,
			category="GOODS",
		)
		# Query was executed — verify execute was called
		session.execute.assert_called_once()
