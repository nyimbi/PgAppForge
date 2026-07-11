"""
tests/ci/test_crm_sales_analytics.py

Focused tests for CRM sales advanced analytics.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import Column, Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Session, declarative_base


def _uid() -> str:
	return str(uuid.uuid4())


TENANT = _uid()
OTHER_TENANT = _uid()
OWNER = _uid()
Base = declarative_base()


class _SalesAccount(Base):
	__tablename__ = "crm_sales_account"
	__table_args__ = {"extend_existing": True}

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	name = Column(String(255), nullable=False)
	account_type = Column(String(30), nullable=False, default="CUSTOMER")
	owner_id = Column(String(36), nullable=True)
	annual_revenue_cents = Column(Integer, nullable=True)
	health_score = Column(Float, nullable=True)
	churn_risk_score = Column(Float, nullable=True)
	lifetime_value_cents = Column(Integer, nullable=True)
	nps_score = Column(Integer, nullable=True)
	status = Column(String(20), nullable=False, default="ACTIVE")
	updated_at = Column(DateTime, nullable=True)


class _SalesContact(Base):
	__tablename__ = "crm_sales_contact"
	__table_args__ = {"extend_existing": True}

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	account_id = Column(String(36), nullable=True)
	first_name = Column(String(100), nullable=False, default="Test")
	last_name = Column(String(100), nullable=False, default="Contact")
	engagement_score = Column(Float, nullable=True)


class _Opportunity(Base):
	__tablename__ = "crm_opportunity"
	__table_args__ = {"extend_existing": True}

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	account_id = Column(String(36), nullable=False)
	contact_id = Column(String(36), nullable=True)
	opportunity_name = Column(String(255), nullable=False)
	stage = Column(String(50), nullable=False)
	amount_cents = Column(Integer, nullable=True)
	currency_code = Column(String(3), nullable=False, default="USD")
	probability = Column(Integer, nullable=False, default=0)
	forecast_category = Column(String(20), nullable=True)
	expected_close_date = Column(Date, nullable=True)
	owner_id = Column(String(36), nullable=True)
	lead_source = Column(String(50), nullable=True)
	type = Column(String(30), nullable=True)
	reason_won = Column(String(255), nullable=True)
	reason_lost = Column(String(255), nullable=True)
	competitor = Column(String(200), nullable=True)
	closed_at = Column(DateTime, nullable=True)
	einstein_score = Column(Float, nullable=True)
	created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
	updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _Activity(Base):
	__tablename__ = "crm_activity"
	__table_args__ = {"extend_existing": True}

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	activity_type = Column(String(30), nullable=False, default="CALL")
	subject = Column(String(255), nullable=False, default="Touchpoint")
	status = Column(String(20), nullable=False, default="COMPLETED")
	activity_date = Column(DateTime, nullable=False)
	account_id = Column(String(36), nullable=True)
	opportunity_id = Column(String(36), nullable=True)
	contact_id = Column(String(36), nullable=True)
	owner_id = Column(String(36), nullable=True)


@pytest.fixture
def session():
	engine = sa.create_engine("sqlite:///:memory:", echo=False)
	Base.metadata.create_all(engine)
	connection = engine.connect()
	transaction = connection.begin()
	sess = Session(bind=connection)
	yield sess
	sess.close()
	transaction.rollback()
	connection.close()
	engine.dispose()


@pytest.fixture
def svc(monkeypatch):
	import pgappforge.plugins.erp.crm.sales.models as sales_models
	from pgappforge.plugins.erp.crm.sales.services import SalesService

	monkeypatch.setattr(sales_models, "SalesAccount", _SalesAccount)
	monkeypatch.setattr(sales_models, "SalesContact", _SalesContact)
	monkeypatch.setattr(sales_models, "Opportunity", _Opportunity)
	monkeypatch.setattr(sales_models, "Activity", _Activity)
	return SalesService()


def test_customer_health_score_updates_account(session, svc):
	account = _SalesAccount(
		id=_uid(),
		tenant_id=TENANT,
		name="Acme Ltd",
		lifetime_value_cents=15_000_000,
		nps_score=60,
	)
	session.add(account)
	session.add_all([
		_SalesContact(
			tenant_id=TENANT,
			account_id=account.id,
			first_name="Ada",
			last_name="Buyer",
			engagement_score=8.0,
		),
		_SalesContact(
			tenant_id=TENANT,
			account_id=account.id,
			first_name="Ben",
			last_name="Sponsor",
			engagement_score=7.0,
		),
		_Opportunity(
			tenant_id=TENANT,
			account_id=account.id,
			opportunity_name="Expansion",
			stage="CLOSED_WON",
			amount_cents=2_500_000,
			probability=100,
			forecast_category="CLOSED",
			closed_at=datetime.now(timezone.utc) - timedelta(days=20),
			created_at=datetime.now(timezone.utc) - timedelta(days=60),
		),
		_Activity(
			tenant_id=TENANT,
			account_id=account.id,
			status="COMPLETED",
			activity_date=datetime.now(timezone.utc) - timedelta(days=5),
		),
	])
	session.flush()

	result = svc.calculate_customer_health_score(account.id, session)

	assert result["band"] == "HEALTHY"
	assert result["health_score"] >= 8.0
	assert result["churn_risk_score"] <= 2.0
	assert account.health_score == result["health_score"]
	assert account.churn_risk_score == result["churn_risk_score"]
	assert result["signals"]["completed_activity_count"] == 1


def test_pipeline_forecast_filters_scope_and_weights_deals(session, svc):
	account_id = _uid()
	other_account_id = _uid()
	today = date.today()
	session.add_all([
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Best case deal",
			stage="PROPOSAL",
			amount_cents=10_000,
			probability=60,
			forecast_category="BEST_CASE",
			expected_close_date=today + timedelta(days=20),
			owner_id=OWNER,
		),
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Commit deal",
			stage="NEGOTIATION",
			amount_cents=20_000,
			probability=80,
			forecast_category="COMMIT",
			expected_close_date=today + timedelta(days=30),
			owner_id=OWNER,
			einstein_score=9.0,
		),
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Overdue pipeline",
			stage="PROSPECTING",
			amount_cents=5_000,
			probability=10,
			forecast_category="PIPELINE",
			expected_close_date=today - timedelta(days=3),
			owner_id=OWNER,
		),
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Closed loss",
			stage="CLOSED_LOST",
			amount_cents=500_000,
			probability=0,
			forecast_category="CLOSED",
			expected_close_date=today + timedelta(days=10),
			owner_id=OWNER,
		),
		_Opportunity(
			tenant_id=OTHER_TENANT,
			account_id=other_account_id,
			opportunity_name="Other tenant",
			stage="NEGOTIATION",
			amount_cents=900_000,
			probability=90,
			forecast_category="COMMIT",
			expected_close_date=today + timedelta(days=10),
			owner_id=OWNER,
		),
	])
	session.flush()

	result = svc.get_pipeline_forecast(
		session,
		tenant_id=TENANT,
		owner_id=OWNER,
		period_start=today,
		period_end=today + timedelta(days=60),
	)

	assert result["deal_count"] == 3
	assert result["total_open_pipeline_cents"] == 35_000
	assert result["weighted_pipeline_cents"] == 22_500
	assert result["ai_weighted_pipeline_cents"] == 24_500
	assert result["category_forecast_cents"] == 25_250
	assert result["closing_this_period_cents"] == 30_000
	assert result["overdue_deal_count"] == 1
	assert result["overdue_pipeline_cents"] == 5_000
	assert {row["stage"] for row in result["by_stage"]} == {
		"PROPOSAL",
		"NEGOTIATION",
		"PROSPECTING",
	}


def test_win_loss_analysis_groups_reasons_and_competitors(session, svc):
	account_id = _uid()
	now = datetime.now(timezone.utc)
	session.add_all([
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Won deal",
			stage="CLOSED_WON",
			amount_cents=10_000,
			probability=100,
			forecast_category="CLOSED",
			reason_won="Trusted relationship",
			lead_source="REFERRAL",
			closed_at=now - timedelta(days=10),
			created_at=now - timedelta(days=40),
			owner_id=OWNER,
		),
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_id,
			opportunity_name="Lost deal",
			stage="CLOSED_LOST",
			amount_cents=20_000,
			probability=0,
			forecast_category="CLOSED",
			reason_lost="Price",
			competitor="CompetitorX",
			lead_source="WEB",
			closed_at=now - timedelta(days=5),
			created_at=now - timedelta(days=25),
			owner_id=OWNER,
		),
		_Opportunity(
			tenant_id=OTHER_TENANT,
			account_id=account_id,
			opportunity_name="Other tenant win",
			stage="CLOSED_WON",
			amount_cents=90_000,
			probability=100,
			forecast_category="CLOSED",
			closed_at=now - timedelta(days=2),
			created_at=now - timedelta(days=20),
			owner_id=OWNER,
		),
	])
	session.flush()

	result = svc.get_win_loss_analysis(
		session,
		tenant_id=TENANT,
		owner_id=OWNER,
		since=date.today() - timedelta(days=30),
	)

	assert result["closed_deal_count"] == 2
	assert result["won_deal_count"] == 1
	assert result["lost_deal_count"] == 1
	assert result["win_rate_pct"] == 50.0
	assert result["won_revenue_cents"] == 10_000
	assert result["lost_revenue_cents"] == 20_000
	assert result["top_loss_reasons"][0]["label"] == "Price"
	assert result["losses_by_competitor"][0]["label"] == "CompetitorX"
	assert result["average_sales_cycle_days"] == 25.0


def test_analytics_dashboard_includes_forecast_health_and_win_loss(session, svc):
	account_one = _SalesAccount(
		id=_uid(),
		tenant_id=TENANT,
		name="Healthy Co",
		health_score=9.0,
		churn_risk_score=1.0,
		status="ACTIVE",
	)
	account_two = _SalesAccount(
		id=_uid(),
		tenant_id=TENANT,
		name="Risky Co",
		health_score=3.5,
		churn_risk_score=8.0,
		lifetime_value_cents=50_000,
		status="ACTIVE",
	)
	session.add_all([account_one, account_two])
	session.add(
		_Opportunity(
			tenant_id=TENANT,
			account_id=account_one.id,
			opportunity_name="Dashboard pipeline",
			stage="NEGOTIATION",
			amount_cents=100_000,
			probability=80,
			forecast_category="COMMIT",
			expected_close_date=date.today() + timedelta(days=15),
			owner_id=OWNER,
		)
	)
	session.flush()

	result = svc.get_analytics_dashboard(session, tenant_id=TENANT, owner_id=OWNER)

	assert set(result.keys()) == {
		"generated_at",
		"scope",
		"kpis",
		"pipeline_forecast",
		"win_loss_analysis",
		"customer_health",
	}
	assert result["kpis"]["open_pipeline_cents"] == 100_000
	assert result["kpis"]["forecast_cents"] == 90_000
	assert result["customer_health"]["distribution"]["healthy"] == 1
	assert result["customer_health"]["distribution"]["at_risk"] == 1
	assert result["kpis"]["at_risk_customer_count"] == 1
