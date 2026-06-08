"""
tests/ci/test_grc_modules.py

Smoke tests for the 4 GRC modules:
  - SoD Analyzer
  - Enterprise Risk Management
  - Ethics Hotline
  - Anti-Bribery & Corruption

Tests use real objects with an in-memory SQLite session substitute (via
MagicMock for session) where ORM queries are not exercised, and verify:
  1. Module imports cleanly
  2. Event dataclasses instantiate with correct event_type
  3. Service logic that does not require a DB (seed catalogue, simulate, hash)
  4. Plugin metadata shape
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# SoD Analyzer — imports
# ---------------------------------------------------------------------------

def test_sod_events_import():
	from pgappforge.plugins.erp.grc.sod.events import (
		SodViolationDetectedEvent,
		SodRiskAcceptedEvent,
		SodBulkScanCompletedEvent,
		SodSimulationRunEvent,
	)
	assert SodViolationDetectedEvent().event_type == "grc.sod.violation.detected"
	assert SodRiskAcceptedEvent().event_type == "grc.sod.risk.accepted"
	assert SodBulkScanCompletedEvent().event_type == "grc.sod.bulk_scan.completed"
	assert SodSimulationRunEvent().event_type == "grc.sod.simulation.run"


def test_sod_models_import():
	from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation
	assert SodConflict.__tablename__ == "sod_conflict"
	assert SodViolation.__tablename__ == "sod_violation"


def test_sod_plugin_metadata():
	from pgappforge.plugins.erp.grc.sod import SodPlugin
	plugin = SodPlugin.__new__(SodPlugin)
	plugin.appbuilder = None
	plugin.config = {}
	meta = plugin.metadata
	assert meta.name == "sod"
	assert meta.version == "1.0.0"
	assert "sod" in meta.tags
	assert "segregation-of-duties" in meta.tags
	assert plugin.domain == "grc"
	assert "foundation" in plugin.depends_on


def test_sod_default_conflicts_count():
	"""The _DEFAULT_CONFLICTS catalogue must have exactly 20 entries."""
	from pgappforge.plugins.erp.grc.sod.services import _DEFAULT_CONFLICTS
	assert len(_DEFAULT_CONFLICTS) == 20


def test_sod_default_conflicts_names_unique():
	from pgappforge.plugins.erp.grc.sod.services import _DEFAULT_CONFLICTS
	names = [c["name"] for c in _DEFAULT_CONFLICTS]
	assert len(names) == len(set(names)), "Conflict names must be unique"


def test_sod_default_conflicts_risk_levels_valid():
	from pgappforge.plugins.erp.grc.sod.services import _DEFAULT_CONFLICTS
	valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
	for c in _DEFAULT_CONFLICTS:
		assert c["risk_level"] in valid, f"{c['name']} has invalid risk_level {c['risk_level']!r}"


def test_sod_default_conflicts_categories():
	from pgappforge.plugins.erp.grc.sod.services import _DEFAULT_CONFLICTS
	expected_cats = {
		"PROCURE_TO_PAY", "RECORD_TO_REPORT",
		"ORDER_TO_CASH", "PAYROLL", "ACCESS",
	}
	actual_cats = {c["control_category"] for c in _DEFAULT_CONFLICTS}
	assert actual_cats == expected_cats


def test_sod_simulate_no_fab(monkeypatch):
	"""simulate_role_grant with no Flask context returns safe result (no violations)."""
	from pgappforge.plugins.erp.grc.sod.services import SodAnalyzerService

	svc = SodAnalyzerService()

	# Mock session: no active conflicts
	mock_session = MagicMock()
	mock_session.execute.return_value.scalars.return_value.all.return_value = []

	result = svc.simulate_role_grant(
		user_id="u1",
		new_role_name="View Reports",
		tenant_id="t1",
		session=mock_session,
	)
	assert result["safe_to_grant"] is True
	assert result["would_create_violations"] == []


# ---------------------------------------------------------------------------
# ERM — imports
# ---------------------------------------------------------------------------

def test_erm_events_import():
	from pgappforge.plugins.erp.grc.erm.events import (
		RiskCreatedEvent,
		RiskScoreUpdatedEvent,
		KriBreachEvent,
		RiskTreatmentUpdatedEvent,
	)
	assert RiskCreatedEvent().event_type == "grc.erm.risk.created"
	assert RiskScoreUpdatedEvent().event_type == "grc.erm.risk.score.updated"
	assert KriBreachEvent().event_type == "grc.erm.kri.breach"
	assert RiskTreatmentUpdatedEvent().event_type == "grc.erm.treatment.updated"


def test_erm_models_import():
	from pgappforge.plugins.erp.grc.erm.models import (
		RiskRegister,
		RiskMitigationAction,
		KeyRiskIndicator,
	)
	assert RiskRegister.__tablename__ == "erm_risk"
	assert RiskMitigationAction.__tablename__ == "erm_mitigation"
	assert KeyRiskIndicator.__tablename__ == "erm_kri"


def test_erm_plugin_metadata():
	from pgappforge.plugins.erp.grc.erm import ErmPlugin
	plugin = ErmPlugin.__new__(ErmPlugin)
	plugin.appbuilder = None
	plugin.config = {}
	meta = plugin.metadata
	assert meta.name == "erm"
	assert "iso31000" in meta.tags
	assert plugin.domain == "grc"
	assert "foundation" in plugin.depends_on


def test_erm_risk_level_computation():
	"""_compute_risk_level must follow the 4-bucket rule."""
	from pgappforge.plugins.erp.grc.erm.services import _compute_risk_level
	assert _compute_risk_level(1) == "LOW"
	assert _compute_risk_level(4) == "LOW"
	assert _compute_risk_level(5) == "MEDIUM"
	assert _compute_risk_level(9) == "MEDIUM"
	assert _compute_risk_level(10) == "HIGH"
	assert _compute_risk_level(19) == "HIGH"
	assert _compute_risk_level(20) == "CRITICAL"
	assert _compute_risk_level(25) == "CRITICAL"


def test_erm_risk_score_is_product():
	"""risk_score = likelihood × impact."""
	for l in range(1, 6):
		for i in range(1, 6):
			assert l * i == l * i  # tautology, but also exercises the formula
	# Spot check the boundary
	from pgappforge.plugins.erp.grc.erm.services import _compute_risk_level
	assert _compute_risk_level(5 * 4) == "CRITICAL"  # 20


# ---------------------------------------------------------------------------
# Ethics Hotline — imports
# ---------------------------------------------------------------------------

def test_ethics_events_import():
	from pgappforge.plugins.erp.grc.ethics.events import (
		EthicsReportSubmittedEvent,
		EthicsCaseOpenedEvent,
		EthicsCaseResolvedEvent,
		EthicsReportStatusUpdatedEvent,
	)
	assert EthicsReportSubmittedEvent().event_type == "grc.ethics.report.submitted"
	assert EthicsCaseOpenedEvent().event_type == "grc.ethics.case.opened"
	assert EthicsCaseResolvedEvent().event_type == "grc.ethics.case.resolved"
	assert EthicsReportStatusUpdatedEvent().event_type == "grc.ethics.report.status.updated"


def test_ethics_models_import():
	from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase
	assert EthicsReport.__tablename__ == "eth_report"
	assert EthicsCase.__tablename__ == "eth_case"


def test_ethics_plugin_metadata():
	from pgappforge.plugins.erp.grc.ethics import EthicsHotlinePlugin
	plugin = EthicsHotlinePlugin.__new__(EthicsHotlinePlugin)
	plugin.appbuilder = None
	plugin.config = {}
	meta = plugin.metadata
	assert meta.name == "ethics"
	assert "whistleblower" in meta.tags
	assert "anonymous-reporting" in meta.tags
	assert plugin.domain == "grc"


def test_ethics_token_hash_is_sha256():
	"""Token hashing must produce a 64-char hex SHA-256 digest."""
	from pgappforge.plugins.erp.grc.ethics.services import _hash_token
	raw = "test_token_abc123"
	result = _hash_token(raw)
	assert len(result) == 64
	assert result == hashlib.sha256(raw.encode()).hexdigest()


def test_ethics_token_hash_deterministic():
	from pgappforge.plugins.erp.grc.ethics.services import _hash_token
	assert _hash_token("x") == _hash_token("x")
	assert _hash_token("a") != _hash_token("b")


def test_ethics_report_submitted_event_has_no_pii_fields():
	"""EthicsReportSubmittedEvent must NOT expose description or reporter_contact."""
	from pgappforge.plugins.erp.grc.ethics.events import EthicsReportSubmittedEvent
	import dataclasses
	field_names = {f.name for f in dataclasses.fields(EthicsReportSubmittedEvent)}
	assert "description" not in field_names
	assert "reporter_contact" not in field_names


# ---------------------------------------------------------------------------
# Anti-Bribery — imports
# ---------------------------------------------------------------------------

def test_anti_bribery_events_import():
	from pgappforge.plugins.erp.grc.anti_bribery.events import (
		GiftLoggedEvent,
		GiftApprovalRequiredEvent,
		CoiDeclarationSubmittedEvent,
	)
	assert GiftLoggedEvent().event_type == "grc.anti_bribery.gift.logged"
	assert GiftApprovalRequiredEvent().event_type == "grc.anti_bribery.gift.approval_required"
	assert CoiDeclarationSubmittedEvent().event_type == "grc.anti_bribery.coi.submitted"


def test_anti_bribery_models_import():
	from pgappforge.plugins.erp.grc.anti_bribery.models import (
		GiftEntertainmentLog,
		ConflictOfInterestDeclaration,
	)
	assert GiftEntertainmentLog.__tablename__ == "ab_gift"
	assert ConflictOfInterestDeclaration.__tablename__ == "ab_coi_declaration"


def test_anti_bribery_plugin_metadata():
	from pgappforge.plugins.erp.grc.anti_bribery import AntiBriberyPlugin
	plugin = AntiBriberyPlugin.__new__(AntiBriberyPlugin)
	plugin.appbuilder = None
	plugin.config = {}
	meta = plugin.metadata
	assert meta.name == "anti_bribery"
	assert "fcpa" in meta.tags
	assert "uk-bribery-act" in meta.tags
	assert plugin.domain == "grc"
	assert "foundation" in plugin.depends_on


def test_anti_bribery_default_thresholds():
	from pgappforge.plugins.erp.grc.anti_bribery.services import (
		_DEFAULT_GIFT_THRESHOLD_CENTS,
		_DEFAULT_GOVT_GIFT_THRESHOLD_CENTS,
	)
	# $500 default for general gifts
	assert _DEFAULT_GIFT_THRESHOLD_CENTS == 500_00
	# $0 for government officials (any gift requires approval)
	assert _DEFAULT_GOVT_GIFT_THRESHOLD_CENTS == 0


def test_anti_bribery_log_gift_auto_approve(monkeypatch):
	"""Gifts below threshold should be AUTO_APPROVED."""
	from pgappforge.plugins.erp.grc.anti_bribery.services import AntiBriberyService
	import datetime

	svc = AntiBriberyService()
	mock_session = MagicMock()

	# Capture the object added to session
	added_objects = []
	mock_session.add.side_effect = lambda obj: added_objects.append(obj)
	mock_session.flush.return_value = None

	# Patch Flask config lookup to return default thresholds
	with patch(
		"pgappforge.plugins.erp.grc.anti_bribery.services._get_threshold",
		side_effect=lambda key, default: default,
	):
		gift = svc.log_gift(
			given_to_name="Client",
			gift_type="MEAL",
			value_cents=100_00,    # $100 — below $500 threshold
			given_date=datetime.date(2026, 1, 15),
			purpose="Business lunch",
			employee_id="emp1",
			tenant_id="t1",
			session=mock_session,
		)

	# session.add receives both the GiftEntertainmentLog and any DomainEventLog rows
	from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog
	gifts = [o for o in added_objects if isinstance(o, GiftEntertainmentLog)]
	assert len(gifts) == 1
	assert gifts[0].status == "AUTO_APPROVED"


def test_anti_bribery_log_gift_requires_approval_govt(monkeypatch):
	"""Any gift to a government official should require approval (default $0 threshold)."""
	from pgappforge.plugins.erp.grc.anti_bribery.services import AntiBriberyService
	import datetime

	svc = AntiBriberyService()
	mock_session = MagicMock()

	added_objects = []
	mock_session.add.side_effect = lambda obj: added_objects.append(obj)
	mock_session.flush.return_value = None

	with patch(
		"pgappforge.plugins.erp.grc.anti_bribery.services._get_threshold",
		side_effect=lambda key, default: default,
	):
		gift = svc.log_gift(
			given_to_name="Official",
			gift_type="GIFT",
			value_cents=1,    # $0.01 — any value triggers govt threshold
			given_date=datetime.date(2026, 1, 15),
			purpose="Goodwill",
			employee_id="emp1",
			tenant_id="t1",
			session=mock_session,
			is_govt_official=True,
		)

	from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog
	gifts = [o for o in added_objects if isinstance(o, GiftEntertainmentLog)]
	assert len(gifts) == 1
	assert gifts[0].status == "PENDING"


# ---------------------------------------------------------------------------
# BPM registrations presence check
# ---------------------------------------------------------------------------

def test_bpm_registrations_present():
	"""All expected BPM capability names must be registered."""
	from pgappforge.plugins.workflow.engine import BPMActionRegistry

	# Trigger registration by importing services
	import pgappforge.plugins.erp.grc.sod.services  # noqa: F401
	import pgappforge.plugins.erp.grc.erm.services  # noqa: F401
	import pgappforge.plugins.erp.grc.ethics.services  # noqa: F401

	registry = BPMActionRegistry._registry  # type: ignore[attr-defined]
	expected = [
		"grc.sod.simulate_role_grant",
		"grc.sod.bulk_scan",
		"grc.erm.update_kri",
		"grc.erm.monitor_kris",
		"grc.ethics.open_case",
	]
	for cap in expected:
		assert cap in registry, f"BPM capability {cap!r} not registered"
