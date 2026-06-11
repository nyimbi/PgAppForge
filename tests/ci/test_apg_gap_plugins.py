"""CI tests for 4 new fintech plugins: agency_banking, embedded_finance,
terminal_management, insurtech. Structural/import tests only."""
from __future__ import annotations
import inspect


# ── Agency Banking ─────────────────────────────────────────────────────────

def test_agency_models_import():
	from pgappforge.plugins.fintech.agency.models import (
		AgencyOutlet, AgencyAgent, AgencyTransaction, AgencyFloat, AgencyCommission
	)
	assert AgencyOutlet.__tablename__ == "ft_agency_outlet"
	assert AgencyAgent.__tablename__ == "ft_agency_agent"
	assert AgencyTransaction.__tablename__ == "ft_agency_transaction"

def test_agency_service_methods():
	from pgappforge.plugins.fintech.agency.services import AgencyService
	svc = AgencyService()
	for m in ("onboard_outlet","accredit_agent","process_transaction",
	          "top_up_float","check_float_level","settle_commissions",
	          "suspend_outlet"):
		assert callable(getattr(svc, m)), f"AgencyService.{m} missing"

def test_agency_plugin_metadata():
	from pgappforge.plugins.fintech.agency import AgencyPlugin
	p = AgencyPlugin.__new__(AgencyPlugin)
	assert p.name in ("agency_banking", "agency")
	assert "core_banking" in p.depends_on

def test_agency_outlet_types_in_source():
	from pgappforge.plugins.fintech.agency.models import AgencyOutlet
	src = inspect.getsource(AgencyOutlet)
	for t in ("RETAIL_SHOP", "PHARMACY", "MPESA_SHOP"):
		assert t in src

def test_agency_commission_cents_integer():
	from pgappforge.plugins.fintech.agency.models import AgencyCommission
	col = AgencyCommission.__table__.c.gross_commission_cents
	assert str(col.type) in ("INTEGER", "BIGINT", "BigInteger", "Integer")


# ── Embedded Finance ─────────────────────────────────────────────────────────

def test_embedded_models_import():
	from pgappforge.plugins.fintech.embedded_finance.models import (
		EmbeddedPartner, EmbeddedProduct, EmbeddedConsent, EmbeddedRevShareRecord
	)
	assert EmbeddedPartner.__tablename__ == "ft_emb_partner"
	assert EmbeddedProduct.__tablename__ == "ft_emb_product"

def test_embedded_service_methods():
	from pgappforge.plugins.fintech.embedded_finance.services import EmbeddedFinanceService
	svc = EmbeddedFinanceService()
	for m in ("register_partner","validate_api_key","enable_product",
	          "obtain_consent","check_consent","provision_account",
	          "calculate_revenue_share"):
		assert callable(getattr(svc, m)), f"EmbeddedFinanceService.{m} missing"

def test_embedded_api_key_never_stored():
	from pgappforge.plugins.fintech.embedded_finance.services import EmbeddedFinanceService
	src = inspect.getsource(EmbeddedFinanceService.register_partner)
	# Should hash the API key, not store plaintext
	assert "sha256" in src.lower() or "hash" in src.lower()

def test_embedded_plugin_metadata():
	from pgappforge.plugins.fintech.embedded_finance import EmbeddedFinancePlugin
	p = EmbeddedFinancePlugin.__new__(EmbeddedFinancePlugin)
	assert "core_banking" in p.depends_on

def test_embedded_product_types():
	from pgappforge.plugins.fintech.embedded_finance.models import EmbeddedProduct
	src = inspect.getsource(EmbeddedProduct)
	for pt in ("ACCOUNT", "WALLET", "LOANS", "BNPL"):
		assert pt in src


# ── Terminal Management ──────────────────────────────────────────────────────

def test_terminal_models_import():
	from pgappforge.plugins.fintech.terminal_management.models import (
		Terminal, TerminalKey, TerminalParameter, TerminalHealthEvent, TerminalBatch
	)
	assert Terminal.__tablename__ == "ft_terminal"
	assert TerminalKey.__tablename__ == "ft_terminal_key"
	assert TerminalHealthEvent.__tablename__ == "ft_terminal_health"

def test_terminal_health_event_immutable():
	from pgappforge.plugins.fintech.terminal_management.models import TerminalHealthEvent
	from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin
	assert issubclass(TerminalHealthEvent, ImmutableRecordMixin)

def test_terminal_service_methods():
	from pgappforge.plugins.fintech.terminal_management.services import TerminalManagementService
	svc = TerminalManagementService()
	for m in ("provision_terminal","activate_terminal","inject_key",
	          "deploy_parameters","record_health_event","record_heartbeat",
	          "get_compliance_status","open_batch","close_batch","decommission"):
		assert callable(getattr(svc, m)), f"TerminalManagementService.{m} missing"

def test_terminal_tamper_in_source():
	from pgappforge.plugins.fintech.terminal_management.services import TerminalManagementService
	src = inspect.getsource(TerminalManagementService.record_health_event)
	assert "TAMPER" in src

def test_terminal_heartbeat_uses_sa_update():
	from pgappforge.plugins.fintech.terminal_management.services import TerminalManagementService
	src = inspect.getsource(TerminalManagementService.record_heartbeat)
	assert "sa.update" in src or "update(" in src

def test_terminal_plugin_metadata():
	from pgappforge.plugins.fintech.terminal_management import TerminalManagementPlugin
	p = TerminalManagementPlugin.__new__(TerminalManagementPlugin)
	assert p.name == "terminal_management"


# ── InsurTech ────────────────────────────────────────────────────────────────

def test_insurtech_models_import():
	from pgappforge.plugins.fintech.insurtech.models import (
		InsuranceProduct, PolicyHolder, InsurancePolicy,
		InsurancePremium, InsuranceClaim
	)
	assert InsuranceProduct.__tablename__ == "ft_ins_product"
	assert InsurancePolicy.__tablename__ == "ft_ins_policy"
	assert InsuranceClaim.__tablename__ == "ft_ins_claim"

def test_insurtech_product_lines():
	from pgappforge.plugins.fintech.insurtech.models import InsuranceProduct
	src = inspect.getsource(InsuranceProduct)
	for line in ("LIFE", "HEALTH", "MOTOR", "CROP", "MICROINSURANCE"):
		assert line in src

def test_insurtech_service_methods():
	from pgappforge.plugins.fintech.insurtech.services import InsurTechService
	svc = InsurTechService()
	for m in ("get_quote","issue_policy","collect_premium","run_lapse_check",
	          "submit_claim","assess_claim","approve_claim","reject_claim",
	          "cancel_policy"):
		assert callable(getattr(svc, m)), f"InsurTechService.{m} missing"

def test_insurtech_get_quote_logic():
	from pgappforge.plugins.fintech.insurtech.services import InsurTechService
	src = inspect.getsource(InsurTechService.get_quote)
	assert "base_rate" in src or "premium" in src.lower()
	assert "sum_insured" in src

def test_insurtech_plugin_metadata():
	from pgappforge.plugins.fintech.insurtech import InsurTechPlugin
	p = InsurTechPlugin.__new__(InsurTechPlugin)
	assert p.name == "insurtech"
	assert "core_banking" in p.depends_on

def test_fintech_registry_has_all_20():
	from pgappforge.plugins.fintech import PLUGIN_REGISTRY, list_plugins
	order = list_plugins()
	assert len(order) == 20
	assert len(set(order)) == 20  # no duplicates
	for name in ("agency_banking","embedded_finance","terminal_management",
	             "insurtech","wealth_management","robo_advisory",
	             "remittance","bnpl"):
		assert name in PLUGIN_REGISTRY, f"{name} missing from PLUGIN_REGISTRY"

