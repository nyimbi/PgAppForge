"""Smoke-import tests for the 29 Tier-1 gap-closing modules."""
from __future__ import annotations
import importlib
import pytest


MODULES = [
	# Finance
	"pgappforge.plugins.erp.finance.lease_accounting",
	"pgappforge.plugins.erp.finance.lease_accounting.models",
	"pgappforge.plugins.erp.finance.lease_accounting.services",
	"pgappforge.plugins.erp.finance.hedge_accounting",
	"pgappforge.plugins.erp.finance.hedge_accounting.models",
	"pgappforge.plugins.erp.finance.hedge_accounting.services",
	"pgappforge.plugins.erp.finance.material_ledger",
	"pgappforge.plugins.erp.finance.material_ledger.models",
	"pgappforge.plugins.erp.finance.material_ledger.services",
	"pgappforge.plugins.erp.finance.joint_venture",
	"pgappforge.plugins.erp.finance.joint_venture.models",
	"pgappforge.plugins.erp.finance.joint_venture.services",
	# GRC
	"pgappforge.plugins.erp.grc.sod",
	"pgappforge.plugins.erp.grc.sod.models",
	"pgappforge.plugins.erp.grc.sod.services",
	"pgappforge.plugins.erp.grc.erm",
	"pgappforge.plugins.erp.grc.erm.models",
	"pgappforge.plugins.erp.grc.erm.services",
	"pgappforge.plugins.erp.grc.ethics",
	"pgappforge.plugins.erp.grc.ethics.models",
	"pgappforge.plugins.erp.grc.ethics.services",
	"pgappforge.plugins.erp.grc.anti_bribery",
	"pgappforge.plugins.erp.grc.anti_bribery.models",
	"pgappforge.plugins.erp.grc.anti_bribery.services",
	# Platform / EDI
	"pgappforge.plugins.erp.platform.edi",
	"pgappforge.plugins.erp.platform.edi.models",
	"pgappforge.plugins.erp.platform.edi.services",
	# Procurement
	"pgappforge.plugins.erp.procurement.trade_compliance",
	"pgappforge.plugins.erp.procurement.trade_compliance.models",
	"pgappforge.plugins.erp.procurement.trade_compliance.services",
	"pgappforge.plugins.erp.procurement.spend_analytics",
	"pgappforge.plugins.erp.procurement.spend_analytics.services",
	# Operations
	"pgappforge.plugins.erp.operations.process_manufacturing",
	"pgappforge.plugins.erp.operations.process_manufacturing.models",
	"pgappforge.plugins.erp.operations.process_manufacturing.services",
	"pgappforge.plugins.erp.operations.capacity_scheduling",
	"pgappforge.plugins.erp.operations.capacity_scheduling.models",
	"pgappforge.plugins.erp.operations.capacity_scheduling.services",
	"pgappforge.plugins.erp.operations.lean",
	"pgappforge.plugins.erp.operations.lean.models",
	"pgappforge.plugins.erp.operations.lean.services",
	# HCM
	"pgappforge.plugins.erp.hcm.recruiting",
	"pgappforge.plugins.erp.hcm.recruiting.models",
	"pgappforge.plugins.erp.hcm.recruiting.services",
	"pgappforge.plugins.erp.hcm.performance",
	"pgappforge.plugins.erp.hcm.performance.models",
	"pgappforge.plugins.erp.hcm.performance.services",
	"pgappforge.plugins.erp.hcm.position_management",
	"pgappforge.plugins.erp.hcm.position_management.models",
	"pgappforge.plugins.erp.hcm.position_management.services",
	# CRM
	"pgappforge.plugins.erp.crm.prm",
	"pgappforge.plugins.erp.crm.prm.models",
	"pgappforge.plugins.erp.crm.prm.services",
	"pgappforge.plugins.erp.crm.territory_management",
	"pgappforge.plugins.erp.crm.territory_management.models",
	"pgappforge.plugins.erp.crm.territory_management.services",
	"pgappforge.plugins.erp.crm.loyalty",
	"pgappforge.plugins.erp.crm.loyalty.models",
	"pgappforge.plugins.erp.crm.loyalty.services",
	# Platform analytics & infra
	"pgappforge.plugins.erp.platform.analytics_engine",
	"pgappforge.plugins.erp.platform.analytics_engine.models",
	"pgappforge.plugins.erp.platform.analytics_engine.services",
	"pgappforge.plugins.erp.platform.process_mining",
	"pgappforge.plugins.erp.platform.process_mining.services",
	"pgappforge.plugins.erp.platform.regulatory_reporting",
	"pgappforge.plugins.erp.platform.regulatory_reporting.services",
	"pgappforge.plugins.erp.platform.ipaas",
	"pgappforge.plugins.erp.platform.ipaas.models",
	"pgappforge.plugins.erp.platform.ipaas.services",
	"pgappforge.plugins.erp.platform.tenant_control",
	"pgappforge.plugins.erp.platform.tenant_control.models",
	"pgappforge.plugins.erp.platform.tenant_control.services",
	"pgappforge.plugins.erp.platform.mes",
	"pgappforge.plugins.erp.platform.mes.models",
	"pgappforge.plugins.erp.platform.mes.services",
]


@pytest.mark.parametrize("module_path", MODULES)
def test_module_imports(module_path):
	mod = importlib.import_module(module_path)
	assert mod is not None


def test_lease_service_npv():
	from pgappforge.plugins.erp.finance.lease_accounting.services import _npv
	from decimal import Decimal
	pv = _npv(Decimal("0.05"), [100_000, 100_000, 100_000])
	assert 270_000 < pv < 290_000


def test_jaro_winkler():
	from pgappforge.plugins.erp.procurement.trade_compliance.services import _jaro_winkler
	assert _jaro_winkler("ACME CORP", "ACME CORP") == 1.0
	assert _jaro_winkler("ACME CORP", "TOTALLY DIFFERENT") < 0.7
	assert _jaro_winkler("ACME CORPORATION", "ACME CORP") > 0.85


def test_sod_seed_structure():
	from pgappforge.plugins.erp.grc.sod.services import _DEFAULT_CONFLICTS
	assert len(_DEFAULT_CONFLICTS) >= 10
	for row in _DEFAULT_CONFLICTS:
		assert len(row) == 5


def test_ethics_token_hash():
	from pgappforge.plugins.erp.grc.ethics.services import _hash_token
	h1 = _hash_token("abc123")
	h2 = _hash_token("abc123")
	h3 = _hash_token("different")
	assert h1 == h2
	assert h1 != h3
	assert len(h1) == 64


def test_anti_bribery_flag_logic():
	from pgappforge.plugins.erp.grc.anti_bribery.services import AntiBriberyService, GOVT_OFFICIAL_THRESHOLD_CENTS
	from datetime import date
	svc = AntiBriberyService()
	log = svc.log_gift(
		"t1", "emp1", "Minister Smith", "GIFT",
		GOVT_OFFICIAL_THRESHOLD_CENTS + 1, date.today(),
		is_government_official=True,
	)
	assert log.status == "FLAGGED"
	ok_log = svc.log_gift(
		"t1", "emp1", "Client Johnson", "MEAL",
		100, date.today(),
		is_government_official=False,
	)
	assert ok_log.status == "PENDING"


def test_edi_x12_roundtrip():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	data = {"segments": {"BEG": [["00", "SA", "PO-001", "", "20240101"]]}}
	x12 = svc.format_x12(data, "850", "PARTNER1")
	parsed = svc.parse_x12(x12, "850")
	assert "ISA" in parsed["segments"] or "GS" in parsed["segments"]


def test_peppol_bis3_xml():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	xml = svc.format_peppol_bis3({"id": "INV-001", "date": "2024-01-01", "total_cents": 100000, "tax_cents": 16000, "supplier_name": "SupplierCo", "customer_name": "BuyerCo"})
	assert "Invoice" in xml
	assert "100.00" in xml


def test_tenant_plan_defaults():
	from pgappforge.plugins.erp.platform.tenant_control.services import _DEFAULT_LIMITS
	tiers = {row[0] for row in _DEFAULT_LIMITS}
	assert "STARTER" in tiers and "GROWTH" in tiers and "ENTERPRISE" in tiers


def test_plugin_metadata_all_new():
	plugins = [
		("pgappforge.plugins.erp.finance.lease_accounting", "LeaseAccountingPlugin"),
		("pgappforge.plugins.erp.grc.sod", "SodPlugin"),
		("pgappforge.plugins.erp.grc.ethics", "EthicsPlugin"),
		("pgappforge.plugins.erp.platform.edi", "EDIPlugin"),
		("pgappforge.plugins.erp.crm.loyalty", "LoyaltyPlugin"),
		("pgappforge.plugins.erp.platform.mes", "MESPlugin"),
	]
	for module_path, class_name in plugins:
		mod = importlib.import_module(module_path)
		cls = getattr(mod, class_name)
		inst = cls.__new__(cls)
		assert inst.name
		assert inst.domain
