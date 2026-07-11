"""Tests for HCM travel request and expense report totals."""
from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.models.sqla import Model
from pgappforge.plugins.erp.foundation.models import DomainEventLog
from pgappforge.plugins.erp.hcm.travel_expense.models import (
	CashAdvance,
	ExpenseLine,
	ExpensePolicy,
	ExpenseReport,
	MileageLog,
	PerDiemRate,
)
from pgappforge.plugins.erp.hcm.travel_expense.services import ExpenseService


DB_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
TENANT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def db_engine():
	engine = sa.create_engine(DB_URI)
	yield engine
	engine.dispose()


@pytest.fixture(autouse=True)
def _travel_expense_tables(pg_isolation, db_engine):
	with db_engine.begin() as conn:
		Model.metadata.create_all(
			conn,
			tables=[
				DomainEventLog.__table__,
				ExpensePolicy.__table__,
				PerDiemRate.__table__,
				ExpenseReport.__table__,
				ExpenseLine.__table__,
				CashAdvance.__table__,
				MileageLog.__table__,
			],
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


def _report(db_session) -> ExpenseReport:
	report = ExpenseReport(
		id=_uuid(),
		tenant_id=TENANT_ID,
		employee_id=_uuid(),
		title="Field visit",
		trip_purpose="Client implementation",
		destination="Nairobi",
		trip_start=date(2026, 3, 1),
		trip_end=date(2026, 3, 3),
		currency_code="KES",
		total_claimed_cents=0,
		total_approved_cents=0,
		advance_received_cents=0,
		reimbursement_due_cents=0,
		status="DRAFT",
		metadata_={},
	)
	db_session.add(report)
	db_session.flush()
	return report


def _line(db_session, report: ExpenseReport, amount_cents: int, category: str) -> ExpenseLine:
	line = ExpenseLine(
		id=_uuid(),
		tenant_id=TENANT_ID,
		report_id=report.id,
		expense_date=date(2026, 3, 1),
		expense_category=category,
		description=f"{category.title()} expense",
		amount_cents=amount_cents,
		currency_code="KES",
		exchange_rate=Decimal("1"),
		base_amount_cents=amount_cents,
		is_billable_to_client=False,
		is_paye_bik=False,
		policy_breach=False,
	)
	db_session.add(line)
	db_session.flush()
	return line


def test_travel_request_creation(db_session):
	request = ExpenseService.request_advance(
		db_session,
		employee_id=_uuid(),
		amount_cents=50000,
		currency_code="KES",
		trip_purpose="Regional sales visit",
		tenant_id=TENANT_ID,
	)
	db_session.flush()

	assert request.id is not None
	assert request.status == "REQUESTED"
	assert request.request_date == date.today()
	assert request.outstanding_cents == 50000


def test_expense_report_totals(db_session):
	report = _report(db_session)
	_line(db_session, report, 12000, "MEALS")
	_line(db_session, report, 35000, "ACCOMMODATION")
	_line(db_session, report, 8000, "TRANSPORT")

	submitted = ExpenseService.submit_report(db_session, report.id, TENANT_ID)

	assert submitted.total_claimed_cents == 55000
	assert submitted.reimbursement_due_cents == 55000
	assert submitted.status == "SUBMITTED"
