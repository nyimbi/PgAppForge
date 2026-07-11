"""Tests for ERP projects EVM and portfolio reporting."""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.models.sqla import Model
from pgappforge.plugins.erp.projects.models import Program, Project, WBSElement
from pgappforge.plugins.erp.projects.services import ProjectService


DB_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
TENANT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def db_engine():
	engine = sa.create_engine(DB_URI)
	yield engine
	engine.dispose()


@pytest.fixture(autouse=True)
def _project_tables(pg_isolation, db_engine):
	with db_engine.begin() as conn:
		Model.metadata.create_all(
			conn,
			tables=[Program.__table__, Project.__table__, WBSElement.__table__],
			checkfirst=True,
		)
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


def _project(db_session, status: str = "ACTIVE", code: str | None = None) -> Project:
	project = Project(
		id=_uuid(),
		tenant_id=TENANT_ID,
		code=code or f"PRJ-{uuid.uuid4().hex[:8]}",
		name="ERP rollout",
		project_type="T_AND_M",
		customer_id=_uuid(),
		owner_id=_uuid(),
		start_date=date(2026, 1, 1),
		end_date=date(2026, 12, 31),
		status=status,
		original_budget_cents=10000,
		revised_budget_cents=10000,
		forecast_at_completion_cents=10000,
		billed_to_date_cents=0,
		recognised_revenue_cents=0,
		percent_complete=Decimal("0"),
		risk_level="LOW",
		currency_code="KES",
		metadata_={},
	)
	db_session.add(project)
	db_session.flush()
	return project


def _wbs(
	db_session,
	project: Project,
	planned_cost_cents: int,
	actual_cost_cents: int,
	planned_hours: Decimal,
	actual_hours: Decimal,
) -> WBSElement:
	wbs = WBSElement(
		id=_uuid(),
		tenant_id=TENANT_ID,
		project_id=project.id,
		code=f"WBS-{uuid.uuid4().hex[:8]}",
		name="Build",
		element_type="TASK",
		planned_start=date(2026, 1, 1),
		planned_end=date.today() - timedelta(days=1),
		planned_hours=planned_hours,
		actual_hours=actual_hours,
		planned_cost_cents=planned_cost_cents,
		actual_cost_cents=actual_cost_cents,
		status="IN_PROGRESS",
		predecessor_ids=[],
	)
	db_session.add(wbs)
	db_session.flush()
	return wbs


def test_evm_cpi_above_one_is_under_budget(db_session):
	project = _project(db_session)
	_wbs(
		db_session,
		project,
		planned_cost_cents=110,
		actual_cost_cents=100,
		planned_hours=Decimal("100"),
		actual_hours=Decimal("100"),
	)

	evm = ProjectService.calculate_evm(db_session, project.id, date.today(), TENANT_ID)

	assert evm["EV"] == 110
	assert evm["AC"] == 100
	assert Decimal(evm["CPI"]) == Decimal("1.1")


def test_evm_spi_below_one_is_behind_schedule(db_session):
	project = _project(db_session)
	_wbs(
		db_session,
		project,
		planned_cost_cents=100,
		actual_cost_cents=90,
		planned_hours=Decimal("100"),
		actual_hours=Decimal("90"),
	)

	evm = ProjectService.calculate_evm(db_session, project.id, date.today(), TENANT_ID)

	assert evm["EV"] == 90
	assert evm["PV"] == 100
	assert Decimal(evm["SPI"]) == Decimal("0.9")


def test_portfolio_report_counts_by_status(db_session):
	for idx in range(3):
		_project(db_session, status="ACTIVE", code=f"ACTIVE-{idx}")
	for idx in range(2):
		_project(db_session, status="COMPLETED", code=f"DONE-{idx}")

	portfolio = ProjectService.get_project_portfolio(db_session, tenant_id=TENANT_ID)
	counts = {
		"ACTIVE": sum(1 for row in portfolio if row["status"] == "ACTIVE"),
		"COMPLETED": sum(1 for row in portfolio if row["status"] == "COMPLETED"),
	}

	assert counts == {"ACTIVE": 3, "COMPLETED": 2}
