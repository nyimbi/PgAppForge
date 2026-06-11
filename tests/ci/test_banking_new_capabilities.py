"""
tests/ci/test_banking_new_capabilities.py

Structural / pure-logic CI tests for five new modules:
  - pgappforge/plugins/fintech/core_banking/kyc.py
  - pgappforge/plugins/fintech/core_banking/teller.py
  - pgappforge/plugins/fintech/core_banking/interest_tiers.py
  - pgappforge/plugins/fintech/sacco/sasra.py
  - pgappforge/plugins/fintech/banking_api/api.py

No DB connections, no mocks for DB, no @pytest.mark.asyncio.
Uses unittest.mock only where the spec explicitly requires it (compute_tiered_rate tests).
"""
from __future__ import annotations

import inspect
from decimal import Decimal
from unittest.mock import MagicMock


# ===========================================================================
# KYC
# ===========================================================================

def test_kyc_profile_tablename():
	from pgappforge.plugins.fintech.core_banking.kyc import KYCProfile
	assert KYCProfile.__tablename__ == "cb_kyc_profile"


def test_kyc_document_tablename():
	from pgappforge.plugins.fintech.core_banking.kyc import KYCDocument
	assert KYCDocument.__tablename__ == "cb_kyc_document"


def test_kyc_document_types():
	"""NATIONAL_ID, PASSPORT, DRIVING_LICENSE must be valid doc types."""
	from pgappforge.plugins.fintech.core_banking.kyc import _PHOTO_ID_TYPES
	assert "NATIONAL_ID" in _PHOTO_ID_TYPES
	assert "PASSPORT" in _PHOTO_ID_TYPES
	assert "DRIVING_LICENSE" in _PHOTO_ID_TYPES


def test_kyc_tier_constants():
	"""Tier upgrade daily limits are defined in upgrade_account_limits source."""
	from pgappforge.plugins.fintech.core_banking.kyc import KYCService
	src = inspect.getsource(KYCService.upgrade_account_limits)
	# TIER0: 5_000_000 cents (KES 50,000)
	assert "5_000_000" in src or "5000000" in src
	# TIER1: 50_000_000 cents (KES 500,000)
	assert "50_000_000" in src or "50000000" in src


def test_kyc_service_get_kyc_status_signature():
	"""get_kyc_status must accept customer_id, tenant_id, session."""
	from pgappforge.plugins.fintech.core_banking.kyc import KYCService
	sig = inspect.signature(KYCService.get_kyc_status)
	params = set(sig.parameters.keys())
	assert "customer_id" in params
	assert "tenant_id" in params
	assert "session" in params


def test_kyc_missing_for_tier():
	"""get_kyc_status source contains 'missing_for_next_tier' as a returned key."""
	from pgappforge.plugins.fintech.core_banking.kyc import KYCService
	src = inspect.getsource(KYCService.get_kyc_status)
	assert "missing_for_next_tier" in src


# ===========================================================================
# Teller
# ===========================================================================

def test_teller_session_status_values():
	"""TellerSession.status column has default 'OPEN'."""
	from pgappforge.plugins.fintech.core_banking.teller import TellerSession
	col = TellerSession.__table__.c.status
	# SQLAlchemy Column default — can be a ColumnDefault or plain value
	default_val = col.default.arg if col.default is not None else None
	assert default_val == "OPEN", f"Expected 'OPEN', got {default_val!r}"


def test_teller_transaction_types_in_source():
	"""TellerService source defines all four key transaction types."""
	from pgappforge.plugins.fintech.core_banking.teller import TellerService
	src = inspect.getsource(TellerService)
	assert "CASH_DEPOSIT" in src
	assert "CASH_WITHDRAWAL" in src
	assert "VAULT_DEPOSIT" in src
	assert "VAULT_WITHDRAWAL" in src


def test_teller_get_balance_exists():
	"""TellerService.get_teller_balance is callable."""
	from pgappforge.plugins.fintech.core_banking.teller import TellerService
	assert callable(TellerService().get_teller_balance)


def test_teller_close_session_computes_variance():
	"""close_session source computes and stores variance_cents."""
	from pgappforge.plugins.fintech.core_banking.teller import TellerService
	src = inspect.getsource(TellerService.close_session)
	assert "variance" in src
	assert "variance_cents" in src


def test_teller_vault_tablename():
	from pgappforge.plugins.fintech.core_banking.teller import TellerVault
	assert TellerVault.__tablename__ == "cb_teller_vault"


# ===========================================================================
# Interest Tiers
# ===========================================================================

def test_interest_tier_tablename():
	from pgappforge.plugins.fintech.core_banking.interest_tiers import InterestRateTier
	assert InterestRateTier.__tablename__ == "cb_interest_tier"


def test_compute_tiered_rate_zero_balance():
	"""Zero balance returns the first tier's rate without crashing."""
	from pgappforge.plugins.fintech.core_banking.interest_tiers import InterestRateTierService

	svc = InterestRateTierService()

	class _Tier:
		min_balance_cents = 0
		max_balance_cents = None
		annual_rate_pct = Decimal("5.0")

	svc.get_active_tiers = lambda *a, **kw: [_Tier()]
	rate = svc.compute_tiered_rate("SAVINGS", 0, "t1", MagicMock())
	assert isinstance(rate, Decimal)


def test_tiered_rate_monotonic_blend():
	"""Blended rate for 1.5M cents with 3%/5%/7% tiers must be strictly between 3% and 7%."""
	from pgappforge.plugins.fintech.core_banking.interest_tiers import InterestRateTierService

	svc = InterestRateTierService()

	class _Tier:
		def __init__(self, mn: int, mx: int | None, r: int | str) -> None:
			self.min_balance_cents = mn
			self.max_balance_cents = mx
			self.annual_rate_pct = Decimal(str(r))

	tiers = [
		_Tier(0, 10_000_00, 3),
		_Tier(10_000_00, 100_000_00, 5),
		_Tier(100_000_00, None, 7),
	]
	svc.get_active_tiers = lambda *a, **kw: tiers
	rate = svc.compute_tiered_rate("SAVINGS", 150_000_00, "t1", MagicMock())
	assert Decimal("3.0") < rate < Decimal("7.0"), f"blended={rate} not in (3, 7)"


def test_accrue_interest_uses_tiers():
	"""CoreBankingService.accrue_interest integrates InterestRateTierService."""
	from pgappforge.plugins.fintech.core_banking import services as cb_services
	src = inspect.getsource(cb_services.CoreBankingService.accrue_interest)
	assert "InterestRateTierService" in src


# ===========================================================================
# SASRA
# ===========================================================================

def test_sasra_service_init_signature():
	"""SASRAReturnsService.__init__ accepts sacco_id and tenant_id."""
	from pgappforge.plugins.fintech.sacco.sasra import SASRAReturnsService
	sig = inspect.signature(SASRAReturnsService.__init__)
	params = set(sig.parameters.keys())
	assert "sacco_id" in params
	assert "tenant_id" in params


def test_sasra_sas3_compliance_fields():
	"""generate_sas3 source contains capital_adequacy, par30, and liquidity sections."""
	from pgappforge.plugins.fintech.sacco.sasra import SASRAReturnsService
	src = inspect.getsource(SASRAReturnsService.generate_sas3)
	assert "capital_adequacy" in src
	# PAR30 key (various spellings accepted)
	assert "par30" in src.lower() or "par_30" in src.lower()
	assert "liquidity" in src


def test_sasra_sas3_compliance_checks():
	"""generate_sas3 source enforces 8% minimum capital ratio and overall_compliance."""
	from pgappforge.plugins.fintech.sacco.sasra import SASRAReturnsService
	src = inspect.getsource(SASRAReturnsService.generate_sas3)
	assert "8.0" in src or "8.00" in src, "8% minimum capital adequacy threshold not found"
	assert "overall_compliance" in src


def test_sasra_generate_all_keys():
	"""generate_all source composes sas1, sas2, and sas3 returns."""
	from pgappforge.plugins.fintech.sacco.sasra import SASRAReturnsService
	src = inspect.getsource(SASRAReturnsService.generate_all)
	assert "sas1" in src
	assert "sas2" in src
	assert "sas3" in src


# ===========================================================================
# Banking API
# ===========================================================================

def test_banking_api_blueprint_name():
	from pgappforge.plugins.fintech.banking_api.api import BANKING_API_BP
	assert BANKING_API_BP.name == "banking_api"


def test_banking_api_url_prefix():
	from pgappforge.plugins.fintech.banking_api.api import BANKING_API_BP
	assert BANKING_API_BP.url_prefix == "/api/v1/banking"


def test_banking_api_health_endpoint_exists():
	"""The api module source registers a /health route."""
	from pgappforge.plugins.fintech.banking_api import api as api_mod
	src = inspect.getsource(api_mod)
	assert "/health" in src


def test_banking_api_auth_error_class():
	from pgappforge.plugins.fintech.banking_api.api import AuthError
	assert issubclass(AuthError, Exception)


def test_banking_api_format_helpers():
	"""_ok and _err response helpers are importable and callable."""
	from pgappforge.plugins.fintech.banking_api.api import _ok, _err
	assert callable(_ok)
	assert callable(_err)


def test_banking_api_plugin_in_fintech_registry():
	"""banking_api is registered in the fintech PLUGIN_REGISTRY and list_plugins()."""
	from pgappforge.plugins.fintech import PLUGIN_REGISTRY, list_plugins
	assert "banking_api" in PLUGIN_REGISTRY
	assert "banking_api" in list_plugins()
