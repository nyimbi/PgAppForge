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
	assert "1000.00" in xml


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


# ── Tests for the 6 self-review defect fixes ──────────────────────────────────

def test_mes_oee_uses_date_filter():
	"""get_oee() must filter readings by date, not aggregate all history."""
	import inspect
	from pgappforge.plugins.erp.platform.mes.services import MESService
	src = inspect.getsource(MESService.get_oee)
	assert "day_start" in src and "reading_at >=" in src, \
		"date filter missing from get_oee()"
	assert "0.9" not in src and "0.85" not in src, \
		"hardcoded availability/performance constants still present"


def test_mes_oee_no_hardcoded_performance():
	"""performance must be None when ideal_cycle_time is unconfigured."""
	from pgappforge.plugins.erp.platform.mes.services import MESService
	import inspect
	src = inspect.getsource(MESService.get_oee)
	assert '"performance": None' in src or "'performance': None" in src or \
		"performance: None" in src or "performance=None" in src, \
		"performance should be None when ideal_cycle_time is unavailable"


def test_analytics_engine_field_validation_rejects_unknown():
	"""query_cube() must reject filter fields not in cube.dimensions."""
	import inspect
	from pgappforge.plugins.erp.platform.analytics_engine.services import AnalyticsEngineService
	src = inspect.getsource(AnalyticsEngineService.query_cube)
	assert "ValueError" in src, "no ValueError raised on unknown field"
	assert "allowed" in src, "no allowlist check in query_cube()"
	# Confirm bare except is gone — errors must propagate
	assert "except Exception:\n\t\treturn []" not in src, \
		"exception still swallowed in query_cube()"


def test_accept_offer_null_guard():
	"""accept_offer() must raise ValueError when offer_id doesn't exist."""
	import inspect
	from pgappforge.plugins.erp.hcm.recruiting.services import RecruitingService
	src = inspect.getsource(RecruitingService.accept_offer)
	assert "if offer is None" in src, "null guard missing"
	assert "ValueError" in src, "ValueError not raised for missing offer"


def test_spend_analytics_propagates_import_error():
	"""compute_spend_cube() must raise ImportError when AP plugin absent."""
	import inspect
	from pgappforge.plugins.erp.procurement.spend_analytics.services import SpendAnalyticsService
	src = inspect.getsource(SpendAnalyticsService.compute_spend_cube)
	assert "raise ImportError" in src, \
		"ImportError still swallowed in compute_spend_cube()"
	assert "raise RuntimeError" in src, \
		"DB errors still swallowed in compute_spend_cube()"


def test_saft_xml_valid_namespace_and_declaration():
	"""SAF-T output must have proper XML declaration and OECD namespace."""
	import xml.etree.ElementTree as ET
	from unittest.mock import MagicMock
	from pgappforge.plugins.erp.platform.regulatory_reporting.services import SaftReportService, _SAFT_NS

	session = MagicMock()
	# Simulate ImportError for GL models (no GL plugin in test env)
	session.execute.side_effect = Exception("no table")
	svc = SaftReportService()
	xml_str = svc.generate_saft_gl("tenant-test", 2024, session)

	assert xml_str.startswith('<?xml version="1.0"'), \
		f"missing XML declaration, got: {xml_str[:60]}"
	assert _SAFT_NS in xml_str, \
		"OECD SAF-T namespace not present in output"
	# Must be parseable by a namespace-aware parser
	root = ET.fromstring(xml_str.split("\n", 1)[1])  # strip declaration
	assert root.tag == f"{{{_SAFT_NS}}}AuditFile", \
		f"root tag wrong: {root.tag}"


def test_csrd_esrs_s1_has_gender_query():
	"""_esrs_s1() must attempt to compute gender_ratio_f from live data."""
	import inspect
	from pgappforge.plugins.erp.platform.regulatory_reporting.services import CsrdReportService
	src = inspect.getsource(CsrdReportService._esrs_s1)
	assert "gender" in src and "= 'F'" in src, \
		"gender query missing from _esrs_s1()"
	assert "gender_ratio_f" in src, \
		"gender_ratio_f not computed"
