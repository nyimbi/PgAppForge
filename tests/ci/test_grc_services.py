"""Tests for ERP GRC service methods."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.models.sqla import Model
from pgappforge.plugins.erp.foundation.models import Party
from pgappforge.plugins.erp.grc.erm.models import RiskRegister
from pgappforge.plugins.erp.grc.erm.services import ERMService
from pgappforge.plugins.erp.grc.privacy.models import DataSubjectRequest
from pgappforge.plugins.erp.grc.privacy.services import PrivacyService
from pgappforge.plugins.erp.grc.sod.models import SodConflict, SodViolation


DB_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
TENANT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(scope="module")
def db_engine():
	engine = sa.create_engine(DB_URI)
	yield engine
	engine.dispose()


@pytest.fixture(autouse=True)
def _grc_tables(pg_isolation, db_engine):
	with db_engine.begin() as conn:
		conn.execute(
			sa.text(
				"""
				CREATE TABLE IF NOT EXISTS erp_party (
					id uuid PRIMARY KEY,
					tenant_id uuid NOT NULL,
					party_type varchar(20) NOT NULL,
					name varchar(500) NOT NULL,
					is_active boolean NOT NULL DEFAULT true,
					created_at timestamptz DEFAULT now(),
					updated_at timestamptz DEFAULT now()
				)
				"""
			)
		)
		Model.metadata.create_all(
			conn,
			tables=[
				RiskRegister.__table__,
				SodConflict.__table__,
				SodViolation.__table__,
				DataSubjectRequest.__table__,
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


def _party(db_session) -> str:
	party_id = _uuid()
	db_session.execute(
		sa.insert(Party.__table__).values(
			id=party_id,
			tenant_id=TENANT_ID,
			party_type="INDIVIDUAL",
			name="Data Subject",
			is_active=True,
		)
	)
	db_session.flush()
	return party_id


def _conflict(db_session, risk_level: str = "HIGH") -> SodConflict:
	conflict = SodConflict(
		id=_uuid(),
		tenant_id=TENANT_ID,
		name=f"CONFLICT-{uuid.uuid4().hex[:8]}",
		function_a="Create Vendor",
		function_b="Approve Vendor",
		risk_level=risk_level,
		description="Conflicting procurement duties",
		control_category="PROCURE_TO_PAY",
		is_active=True,
	)
	db_session.add(conflict)
	db_session.flush()
	return conflict


def _violation(db_session, conflict: SodConflict, risk_level: str, status: str = "OPEN") -> SodViolation:
	violation = SodViolation(
		id=_uuid(),
		tenant_id=TENANT_ID,
		user_id=f"user-{uuid.uuid4().hex[:6]}",
		conflict_id=conflict.id,
		risk_level=risk_level,
		role_ids=["role-a", "role-b"],
		status=status,
	)
	db_session.add(violation)
	db_session.flush()
	return violation


def _dsr(db_session, party_id: str, due_at: datetime, status: str) -> DataSubjectRequest:
	dsr = DataSubjectRequest(
		id=_uuid(),
		tenant_id=TENANT_ID,
		dsr_number=f"DSR-{uuid.uuid4().hex[:8]}",
		party_id=party_id,
		request_type="ACCESS",
		status=status,
		received_at=due_at - timedelta(days=30),
		due_at=due_at,
	)
	db_session.add(dsr)
	db_session.flush()
	return dsr


def test_risk_heat_map_grid_correct_dimensions(db_session):
	service = ERMService()
	for likelihood in range(1, 6):
		for impact in range(1, 6):
			service.create_risk(
				TENANT_ID,
				name=f"L{likelihood} I{impact}",
				category="OPERATIONAL",
				likelihood=likelihood,
				impact=impact,
				session=db_session,
			)
	db_session.flush()

	heat_map = service.get_heat_map(TENANT_ID, db_session)
	grid = [
		[heat_map.get(f"L{likelihood}_I{impact}", []) for impact in range(1, 6)]
		for likelihood in range(1, 6)
	]

	assert len(grid) == 5
	assert all(len(row) == 5 for row in grid)
	assert all(len(cell) == 1 for row in grid for cell in row)


def test_sod_violation_severity_counts(db_session):
	high_conflict = _conflict(db_session, "HIGH")
	critical_conflict = _conflict(db_session, "CRITICAL")
	_violation(db_session, high_conflict, "HIGH")
	_violation(db_session, high_conflict, "HIGH")
	_violation(db_session, critical_conflict, "CRITICAL")

	rows = db_session.execute(
		sa.select(SodViolation.risk_level, sa.func.count(SodViolation.id).label("count"))
		.where(SodViolation.tenant_id == TENANT_ID)
		.group_by(SodViolation.risk_level)
	).all()
	counts = {row.risk_level: row.count for row in rows}

	assert counts == {"CRITICAL": 1, "HIGH": 2}


def test_compliance_overdue_returns_past_due_only(db_session):
	party_id = _party(db_session)
	now = datetime.now(timezone.utc)
	past_due = _dsr(db_session, party_id, now - timedelta(days=2), "IN_PROGRESS")
	_dsr(db_session, party_id, now + timedelta(days=2), "IN_PROGRESS")
	_dsr(db_session, party_id, now - timedelta(days=5), "COMPLETED")

	overdue = PrivacyService().get_overdue_dsrs(db_session, TENANT_ID)

	assert [row["dsr_id"] for row in overdue] == [past_due.id]
