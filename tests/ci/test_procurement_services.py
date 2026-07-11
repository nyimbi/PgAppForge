"""Tests for procurement service methods added in reverse auction wave."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

pgappforge_module = sys.modules.get("pgappforge")
if pgappforge_module is not None and getattr(pgappforge_module, "__file__", None) is None:
	for module_name in list(sys.modules):
		if module_name == "pgappforge" or module_name.startswith("pgappforge."):
			sys.modules.pop(module_name, None)

from pgappforge.models.sqla import Model
from pgappforge.plugins.erp.finance.ap.models import APInvoice, APInvoiceLine, APSupplier
from pgappforge.plugins.erp.procurement.sourcing.models import (
	ProcurementSavings,
	RFQ,
	RFQAward,
	SupplierBid,
)
from pgappforge.plugins.erp.procurement.sourcing.services import SourcingService
from pgappforge.plugins.erp.procurement.spend_analytics.services import SpendAnalyticsService
from pgappforge.plugins.erp.procurement.supplier_portal.models import (
	SupplierPerformanceCard,
	SupplierProfile,
	SupplierRisk,
	SupplierScorecard,
)
from pgappforge.plugins.erp.procurement.supplier_portal.services import SupplierPortalService


DB_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
TENANT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def db_engine():
	engine = sa.create_engine(DB_URI)
	yield engine
	engine.dispose()


@pytest.fixture(autouse=True)
def _procurement_tables(pg_isolation, db_engine):
	ap_tables = [
		table
		for name, table in Model.metadata.tables.items()
		if name.startswith("ap_")
	]
	tables = [
		RFQ.__table__,
		SupplierBid.__table__,
		RFQAward.__table__,
		ProcurementSavings.__table__,
		SupplierProfile.__table__,
		SupplierPerformanceCard.__table__,
		SupplierScorecard.__table__,
		SupplierRisk.__table__,
		*ap_tables,
	]
	with db_engine.begin() as conn:
		Model.metadata.create_all(conn, tables=tables, checkfirst=True)
	yield


@pytest.fixture
def db_session(db_engine):
	conn = db_engine.connect()
	tx = conn.begin()
	session = Session(bind=conn)
	yield session
	session.close()
	tx.rollback()
	conn.close()


def _uuid() -> str:
	return str(uuid.uuid4())


def _rfq(db_session, **kwargs) -> RFQ:
	defaults = {
		"id": _uuid(),
		"tenant_id": TENANT_ID,
		"title": "Reverse auction RFQ",
		"rfq_ref": f"RFQ-{uuid.uuid4().hex[:8]}",
		"rfq_type": "COMPETITIVE",
		"status": "PUBLISHED",
		"evaluation_criteria": {"price_weight": 60, "quality_weight": 20, "delivery_weight": 20},
		"items": [{"item_code": "MAT-001", "qty": 1, "unit": "EA", "category": "INDIRECT"}],
		"invited_suppliers": [],
		"auction_mode": False,
		"auction_bids": [],
	}
	defaults.update(kwargs)
	rfq = RFQ(**defaults)
	db_session.add(rfq)
	db_session.flush()
	return rfq


def _supplier(db_session, name: str = "Acme Supplies") -> SupplierProfile:
	supplier = SupplierProfile(
		id=_uuid(),
		tenant_id=TENANT_ID,
		company_name=name,
		supplier_ref=f"SUP-{uuid.uuid4().hex[:8]}",
		country_code="KE",
		contact_email=f"{uuid.uuid4().hex[:8]}@example.com",
		primary_category="GOODS",
		kyc_status="APPROVED",
		kyc_documents=[],
		bank_verified=False,
		is_preferred=False,
	)
	db_session.add(supplier)
	db_session.flush()
	return supplier


def _ap_supplier(db_session, name: str) -> APSupplier:
	supplier = APSupplier(
		id=_uuid(),
		tenant_id=TENANT_ID,
		account_number=f"AP-{uuid.uuid4().hex[:8]}",
		name=name,
		status="active",
		payment_terms_days=30,
		currency_code="KES",
		bank_details={},
		approved_supplier=True,
		early_payment_discount_pct=Decimal("0"),
		early_payment_days=0,
		address={},
	)
	db_session.add(supplier)
	db_session.flush()
	return supplier


def _invoice_with_line(db_session, supplier: APSupplier, number: str, unit_cents: int) -> None:
	invoice = APInvoice(
		id=_uuid(),
		tenant_id=TENANT_ID,
		invoice_number_supplier=number,
		supplier_id=supplier.id,
		invoice_date=date.today(),
		due_date=date.today() + timedelta(days=30),
		currency_code="KES",
		exchange_rate=Decimal("1"),
		subtotal_cents=unit_cents,
		total_cents=unit_cents,
		paid_cents=0,
		status="RECEIVED",
		match_status="UNMATCHED",
		approval_status="PENDING",
		metadata_={},
	)
	db_session.add(invoice)
	db_session.flush()
	db_session.add(
		APInvoiceLine(
			id=_uuid(),
			tenant_id=TENANT_ID,
			invoice_id=invoice.id,
			line_number=1,
			description="Benchmark item",
			quantity=Decimal("1"),
			uom="EA",
			unit_cost_cents=unit_cents,
			line_amount_cents=unit_cents,
			tax_rate=Decimal("0"),
			tax_cents=0,
			gl_expense_account="INDIRECT",
		)
	)
	db_session.flush()


def test_start_reverse_auction_sets_auction_mode(db_session):
	rfq = _rfq(db_session)

	result = SourcingService.start_reverse_auction(
		rfq.id,
		duration_minutes=30,
		reserve_price_cents=50000,
		session=db_session,
		tenant_id=TENANT_ID,
	)

	assert result["auction_mode"] is True
	assert rfq.auction_mode is True
	assert rfq.reserve_price_cents == 50000


def test_place_bid_must_be_lower_than_current_best(db_session):
	rfq = _rfq(
		db_session,
		auction_mode=True,
		reserve_price_cents=50000,
		auction_end_time=datetime.now(timezone.utc) + timedelta(days=1),
	)

	SourcingService.place_auction_bid(rfq.id, "supplier-1", 100000, db_session, tenant_id=TENANT_ID)

	with pytest.raises(ValueError, match="lower than the current best"):
		SourcingService.place_auction_bid(rfq.id, "supplier-2", 120000, db_session, tenant_id=TENANT_ID)


def test_place_bid_below_reserve_raises(db_session):
	rfq = _rfq(
		db_session,
		auction_mode=True,
		reserve_price_cents=50000,
		auction_end_time=datetime.now(timezone.utc) + timedelta(days=1),
	)

	with pytest.raises(ValueError, match="below reserve"):
		SourcingService.place_auction_bid(rfq.id, "supplier-1", 30000, db_session, tenant_id=TENANT_ID)


def test_close_auction_selects_lowest_bid(db_session):
	rfq = _rfq(
		db_session,
		auction_mode=True,
		reserve_price_cents=100000,
		auction_bids=[
			{"supplier_id": "supplier-1", "bid_cents": 90000, "ts": "2026-01-01T00:00:00+00:00"},
			{"supplier_id": "supplier-2", "bid_cents": 75000, "ts": "2026-01-01T00:01:00+00:00"},
			{"supplier_id": "supplier-3", "bid_cents": 82000, "ts": "2026-01-01T00:02:00+00:00"},
		],
	)

	result = SourcingService.close_auction(rfq.id, db_session, tenant_id=TENANT_ID)

	assert result["winner_supplier_id"] == "supplier-2"
	assert result["winning_bid_cents"] == 75000
	assert rfq.status == "AWARDED"
	assert rfq.auction_mode is False


def test_record_savings_calculates_pct(db_session):
	rfq = _rfq(db_session)

	result = SourcingService.record_savings(
		rfq.id,
		baseline_price_cents=100000,
		awarded_price_cents=80000,
		session=db_session,
		tenant_id=TENANT_ID,
	)

	assert result["savings_cents"] == 20000
	assert result["savings_pct"] == Decimal("20.00")


def test_score_supplier_weighted_average(db_session):
	supplier = _supplier(db_session)

	scorecard = SupplierPortalService.score_supplier(
		supplier.id,
		"2026-01",
		{
			"OTD": 100,
			"quality": 80,
			"price": 60,
			"responsiveness": 40,
		},
		db_session,
		tenant_id=TENANT_ID,
	)

	assert scorecard.overall_score == Decimal("80.00")


def test_get_savings_opportunities_finds_overpriced_suppliers(db_session):
	target = _ap_supplier(db_session, "Overpriced Supplier")
	benchmark = _ap_supplier(db_session, "Benchmark Supplier")
	for idx in range(4):
		_invoice_with_line(db_session, benchmark, f"BASE-{idx}", 10000)
	for idx in range(3):
		_invoice_with_line(db_session, target, f"TARGET-{idx}", 12000)

	opportunities = SpendAnalyticsService().get_savings_opportunities(TENANT_ID, db_session)

	assert any(
		row["supplier_id"] == target.id
		and row["median_price_cents"] == 10000
		and row["opportunity_pct"] == Decimal("20.00")
		for row in opportunities
	)
