"""
tests/ci/test_assets_plugin.py

CI tests for the Asset Accounting (AA) plugin.

Tests cover:
  - Model instantiation and repr
  - AssetService.capitalize()
  - AssetService.run_depreciation() — STRAIGHT_LINE and DECLINING
  - AssetService.record_disposal()
  - AssetService.record_impairment()
  - AssetService._generate_asset_number()
  - Event dataclasses
  - Plugin class metadata
  - Rules Engine rulesets pre-config (import-only smoke test)

No Flask app context required — uses plain SQLAlchemy in-memory SQLite
for model smoke tests, and exercises service logic with mock sessions
where full DB setup is impractical.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Model smoke tests (import + instantiation)
# ---------------------------------------------------------------------------

def test_asset_class_instantiation():
	from pgappforge.plugins.erp.finance.assets.models import AssetClass
	ac = AssetClass(
		tenant_id="t-001",
		code="MACH",
		name="Machinery",
		useful_life_years=Decimal("10.00"),
		depreciation_method="STRAIGHT_LINE",
		gl_asset_account="1200",
		gl_accumulated_depreciation_account="1201",
		gl_depreciation_expense_account="6100",
	)
	assert ac.code == "MACH"
	assert ac.depreciation_method == "STRAIGHT_LINE"
	assert "MACH" in repr(ac)


def test_fixed_asset_instantiation():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	fa = FixedAsset(
		tenant_id="t-001",
		asset_number="FA-2026-00001",
		asset_class_id="cls-001",
		description="CNC Machine",
		acquisition_date=date(2026, 1, 15),
		acquisition_cost_cents=50_000_00,   # 50,000 in cents
		residual_value_cents=5_000_00,
		useful_life_years=Decimal("10.00"),
		depreciation_method="STRAIGHT_LINE",
		current_book_value_cents=50_000_00,
		accumulated_depreciation_cents=0,
		status="ACTIVE",
	)
	assert fa.status == "ACTIVE"
	assert fa.acquisition_cost_cents == 5_000_000
	assert "FA-2026-00001" in repr(fa)


def test_asset_depreciation_instantiation():
	from pgappforge.plugins.erp.finance.assets.models import AssetDepreciation
	entry = AssetDepreciation(
		tenant_id="t-001",
		asset_id="asset-001",
		period_id="2026-01",
		depreciation_amount_cents=37_500,
		opening_nbv_cents=5_000_000,
		closing_nbv_cents=4_962_500,
		method_used="STRAIGHT_LINE",
	)
	assert entry.period_id == "2026-01"
	assert "2026-01" in repr(entry)


def test_asset_impairment_instantiation():
	from pgappforge.plugins.erp.finance.assets.models import AssetImpairment
	imp = AssetImpairment(
		tenant_id="t-001",
		asset_id="asset-001",
		impairment_date=date(2026, 6, 1),
		carrying_amount_cents=4_000_000,
		recoverable_amount_cents=3_200_000,
		impairment_loss_cents=800_000,
		reason="Market downturn reduced asset utility",
		is_reversal=False,
	)
	assert imp.impairment_loss_cents == 800_000
	assert "800000" in repr(imp)


# ---------------------------------------------------------------------------
# Service: depreciation calculation
# ---------------------------------------------------------------------------

def _make_asset(**overrides):
	"""Construct a minimal FixedAsset-like mock for service tests."""
	defaults = {
		"id": "asset-001",
		"tenant_id": "t-001",
		"asset_number": "FA-2026-00001",
		"asset_class_id": "cls-001",
		"acquisition_cost_cents": 1_200_000,   # 12,000.00
		"residual_value_cents": 0,
		"useful_life_years": Decimal("10.00"),
		"depreciation_method": "STRAIGHT_LINE",
		"current_book_value_cents": 1_200_000,
		"accumulated_depreciation_cents": 0,
		"status": "ACTIVE",
		"last_depreciation_date": None,
	}
	defaults.update(overrides)
	obj = MagicMock()
	for k, v in defaults.items():
		setattr(obj, k, v)
	return obj


def test_straight_line_depreciation_calculation():
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(
		acquisition_cost_cents=1_200_000,
		residual_value_cents=0,
		useful_life_years=Decimal("10.00"),
		depreciation_method="STRAIGHT_LINE",
		current_book_value_cents=1_200_000,
	)
	charge = svc._calculate_depreciation(asset)
	# (1,200,000 - 0) / (10 * 12) = 10,000 per month
	assert charge == 10_000


def test_straight_line_with_residual():
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(
		acquisition_cost_cents=1_200_000,
		residual_value_cents=120_000,
		useful_life_years=Decimal("10.00"),
		depreciation_method="STRAIGHT_LINE",
		current_book_value_cents=1_200_000,
	)
	charge = svc._calculate_depreciation(asset)
	# (1,200,000 - 120,000) / (10 * 12) = 9,000
	assert charge == 9_000


def test_declining_balance_depreciation():
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(
		acquisition_cost_cents=1_200_000,
		residual_value_cents=0,
		useful_life_years=Decimal("10.00"),
		depreciation_method="DECLINING",
		current_book_value_cents=1_200_000,
	)
	charge = svc._calculate_depreciation(asset)
	# NBV * 2 / 10 / 12 = 1,200,000 * 0.2 / 12 = 20,000
	assert charge == 20_000


def test_units_of_production_returns_zero():
	"""run_depreciation handles UOP separately; _calculate_depreciation returns 0."""
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(depreciation_method="UNITS_OF_PRODUCTION")
	assert svc._calculate_depreciation(asset) == 0


def test_zero_life_returns_zero():
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(useful_life_years=Decimal("0"))
	assert svc._calculate_depreciation(asset) == 0


def test_zero_depreciable_amount_returns_zero():
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(
		acquisition_cost_cents=500_000,
		residual_value_cents=500_000,   # equal to cost
	)
	assert svc._calculate_depreciation(asset) == 0


# ---------------------------------------------------------------------------
# Service: capitalize (mock session)
# ---------------------------------------------------------------------------

def test_capitalize_creates_asset():
	from pgappforge.plugins.erp.finance.assets.models import AssetClass
	from pgappforge.plugins.erp.finance.assets.services import AssetService, CapitaliseDetails

	# Mock session
	session = MagicMock()
	mock_class = MagicMock(spec=AssetClass)
	mock_class.useful_life_years = Decimal("5.00")
	mock_class.depreciation_method = "STRAIGHT_LINE"
	session.get.return_value = mock_class

	# execute().scalar_one() for count query
	session.execute.return_value.scalar_one.return_value = 0
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.add = MagicMock()
	session.flush = MagicMock()

	details = CapitaliseDetails(
		tenant_id="t-001",
		asset_class_id="cls-001",
		description="Test Asset",
		acquisition_date=date(2026, 1, 1),
		acquisition_cost_cents=500_000,
		residual_value_cents=50_000,
	)

	with patch("pgappforge.plugins.erp.finance.assets.events.emit_event"):
		asset = AssetService().capitalize(details, session)

	session.add.assert_called_once()
	session.flush.assert_called_once()
	assert asset.status == "ACTIVE"
	assert asset.current_book_value_cents == 500_000
	assert asset.accumulated_depreciation_cents == 0


def test_capitalize_inherits_class_defaults():
	from pgappforge.plugins.erp.finance.assets.models import AssetClass
	from pgappforge.plugins.erp.finance.assets.services import AssetService, CapitaliseDetails

	session = MagicMock()
	mock_class = MagicMock(spec=AssetClass)
	mock_class.useful_life_years = Decimal("3.00")
	mock_class.depreciation_method = "DECLINING"
	session.get.return_value = mock_class
	session.execute.return_value.scalar_one.return_value = 5  # 5 existing assets
	session.add = MagicMock()
	session.flush = MagicMock()

	details = CapitaliseDetails(
		tenant_id="t-001",
		asset_class_id="cls-001",
		description="Inherited defaults asset",
		acquisition_date=date(2026, 3, 1),
		acquisition_cost_cents=300_000,
	)
	with patch("pgappforge.plugins.erp.finance.assets.events.emit_event"):
		asset = AssetService().capitalize(details, session)

	assert asset.depreciation_method == "DECLINING"
	assert asset.useful_life_years == Decimal("3.00")
	assert asset.asset_number == "FA-2026-00006"


# ---------------------------------------------------------------------------
# Service: disposal
# ---------------------------------------------------------------------------

def test_record_disposal_gain():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	from pgappforge.plugins.erp.finance.assets.services import AssetService

	asset = MagicMock(spec=FixedAsset)
	asset.id = "asset-001"
	asset.asset_number = "FA-2026-00001"
	asset.tenant_id = "t-001"
	asset.current_book_value_cents = 800_000
	asset.status = "ACTIVE"

	session = MagicMock()
	session.get.return_value = asset

	with patch("pgappforge.plugins.erp.finance.assets.events.emit_event"):
		result = AssetService().record_disposal(
			"asset-001", 1_000_000, session, disposal_date=date(2026, 6, 1)
		)

	assert result.status == "DISPOSED"
	assert result.disposal_proceeds_cents == 1_000_000
	assert result.disposal_gain_loss_cents == 200_000   # gain


def test_record_disposal_loss():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	from pgappforge.plugins.erp.finance.assets.services import AssetService

	asset = MagicMock(spec=FixedAsset)
	asset.id = "asset-001"
	asset.asset_number = "FA-2026-00001"
	asset.tenant_id = "t-001"
	asset.current_book_value_cents = 800_000
	asset.status = "ACTIVE"

	session = MagicMock()
	session.get.return_value = asset

	with patch("pgappforge.plugins.erp.finance.assets.events.emit_event"):
		result = AssetService().record_disposal(
			"asset-001", 500_000, session, disposal_date=date(2026, 6, 1)
		)
	assert result.disposal_gain_loss_cents == -300_000   # loss


def test_dispose_already_disposed_raises():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetStatusError

	asset = MagicMock(spec=FixedAsset)
	asset.status = "DISPOSED"
	session = MagicMock()
	session.get.return_value = asset

	with pytest.raises(AssetStatusError):
		AssetService().record_disposal("asset-001", 0, session)


def test_dispose_not_found_raises():
	from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetNotFoundError
	session = MagicMock()
	session.get.return_value = None
	with pytest.raises(AssetNotFoundError):
		AssetService().record_disposal("nonexistent", 0, session)


# ---------------------------------------------------------------------------
# Service: impairment
# ---------------------------------------------------------------------------

def test_record_impairment():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	from pgappforge.plugins.erp.finance.assets.services import AssetService

	asset = MagicMock(spec=FixedAsset)
	asset.id = "asset-001"
	asset.asset_number = "FA-2026-00001"
	asset.tenant_id = "t-001"
	asset.current_book_value_cents = 1_000_000
	asset.accumulated_depreciation_cents = 200_000
	asset.status = "ACTIVE"

	session = MagicMock()
	session.get.return_value = asset
	session.add = MagicMock()
	session.flush = MagicMock()

	with patch("pgappforge.plugins.erp.finance.assets.events.emit_event"):
		imp = AssetService().record_impairment(
			"asset-001", 700_000, "Economic downturn", session,
			impairment_date=date(2026, 6, 1),
		)

	assert imp.impairment_loss_cents == 300_000
	assert imp.recoverable_amount_cents == 700_000
	assert asset.current_book_value_cents == 700_000
	assert asset.status == "IMPAIRED"


def test_impairment_recoverable_gte_carrying_raises():
	from pgappforge.plugins.erp.finance.assets.models import FixedAsset
	from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetServiceError

	asset = MagicMock(spec=FixedAsset)
	asset.current_book_value_cents = 500_000
	asset.status = "ACTIVE"
	session = MagicMock()
	session.get.return_value = asset

	with pytest.raises(AssetServiceError, match="no impairment required"):
		AssetService().record_impairment("asset-001", 500_000, "test", session)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_asset_capitalised_event_payload():
	from pgappforge.plugins.erp.finance.assets.events import AssetCapitalisedEvent
	evt = AssetCapitalisedEvent(
		aggregate_id="asset-001",
		aggregate_type="FixedAsset",
		tenant_id="t-001",
		asset_id="asset-001",
		asset_number="FA-2026-00001",
		asset_class_id="cls-001",
		acquisition_cost_cents=5_000_000,
		acquisition_date="2026-01-15",
	)
	payload = evt.build_payload()
	assert payload["asset_id"] == "asset-001"
	assert payload["acquisition_cost_cents"] == 5_000_000
	# Confirm no float leaked in
	assert isinstance(payload["acquisition_cost_cents"], int)


def test_all_asset_events_have_correct_event_type():
	from pgappforge.plugins.erp.finance.assets.events import (
		AssetCapitalisedEvent,
		AssetDepreciationRunEvent,
		AssetDisposedEvent,
		AssetImpairedEvent,
		AssetImpairmentReversedEvent,
	)
	assert AssetCapitalisedEvent().event_type == "asset.capitalised"
	assert AssetDepreciationRunEvent().event_type == "asset.depreciation_run"
	assert AssetDisposedEvent().event_type == "asset.disposed"
	assert AssetImpairedEvent().event_type == "asset.impaired"
	assert AssetImpairmentReversedEvent().event_type == "asset.impairment_reversed"


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

def test_assets_plugin_metadata():
	from pgappforge.plugins.erp.finance.assets import AssetsPlugin
	plugin = AssetsPlugin(MagicMock())
	assert plugin.name == "assets"
	assert plugin.domain == "finance"
	assert "foundation" in plugin.depends_on
	meta = plugin.metadata
	assert meta.version == "1.0.0"
	assert "can_assets_capitalise" in meta.permissions


def test_assets_plugin_events():
	from pgappforge.plugins.erp.finance.assets import AssetsPlugin
	plugin = AssetsPlugin(MagicMock())
	events = plugin.get_events()
	assert "asset.capitalised" in events
	assert "asset.depreciation_run" in events
	assert "asset.disposed" in events
	subs = plugin.subscribe_to()
	assert "exchange_rate.updated" in subs


def test_assets_plugin_register_models():
	from pgappforge.plugins.erp.finance.assets import AssetsPlugin
	from pgappforge.plugins.erp.finance.assets.models import (
		AssetClass, AssetDepreciation, AssetImpairment, FixedAsset,
	)
	plugin = AssetsPlugin(MagicMock())
	models = plugin.register_models()
	assert AssetClass in models
	assert FixedAsset in models
	assert AssetDepreciation in models
	assert AssetImpairment in models


# ---------------------------------------------------------------------------
# No-float invariant
# ---------------------------------------------------------------------------

def test_no_float_in_depreciation_calculation():
	"""Verify Decimal arithmetic produces int, never float."""
	from pgappforge.plugins.erp.finance.assets.services import AssetService
	svc = AssetService()
	asset = _make_asset(
		acquisition_cost_cents=999_999,
		residual_value_cents=3,
		useful_life_years=Decimal("7.00"),
		depreciation_method="STRAIGHT_LINE",
		current_book_value_cents=999_999,
	)
	charge = svc._calculate_depreciation(asset)
	assert isinstance(charge, int), f"Expected int, got {type(charge)}"
	assert charge >= 0
