"""
tests/ci/test_position_management_plugin.py

CI tests for the HCM Position Management plugin.

Uses real objects + pytest fixtures; no mocks.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal in-memory session stub
# ---------------------------------------------------------------------------

class _Store:
	def __init__(self) -> None:
		self._objects: dict[str, Any] = {}
		self._added: list[Any] = []

	def add(self, obj: Any) -> None:
		self._added.append(obj)

	def flush(self) -> None:
		for obj in self._added:
			if not getattr(obj, "id", None):
				import uuid
				obj.id = str(uuid.uuid4())
			self._objects[obj.id] = obj
		self._added.clear()

	def get(self, model: Any, pk: str) -> Any | None:
		return self._objects.get(pk)

	def execute(self, stmt: Any) -> Any:
		return _CountResult(self._objects)


class _CountResult:
	def __init__(self, objects: dict) -> None:
		self._objects = objects

	def scalars(self) -> "_CountResult":
		return self

	def all(self) -> list:
		return []

	def scalar_one_or_none(self) -> Any:
		return None

	def scalar_one(self) -> Any:
		# For headcount variance tests, return 0
		return 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session() -> _Store:
	return _Store()


@pytest.fixture
def tenant_id() -> str:
	return "tenant-pos-test-0001"


@pytest.fixture
def svc():
	from pgappforge.plugins.erp.hcm.position_management.services import PositionManagementService
	return PositionManagementService()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_event_types_are_correct() -> None:
	from pgappforge.plugins.erp.hcm.position_management.events import (
		PositionCreatedEvent,
		PositionFilledEvent,
		PositionVacatedEvent,
		HeadcountVarianceAlertEvent,
	)
	assert PositionCreatedEvent.event_type == "hcm.positions.created"
	assert PositionFilledEvent.event_type == "hcm.positions.filled"
	assert PositionVacatedEvent.event_type == "hcm.positions.vacated"
	assert HeadcountVarianceAlertEvent.event_type == "hcm.positions.headcount.variance"


# ---------------------------------------------------------------------------
# Models import
# ---------------------------------------------------------------------------

def test_models_importable() -> None:
	from pgappforge.plugins.erp.hcm.position_management.models import (
		Position,
		HeadcountRequest,
	)
	assert Position.__tablename__ == "pos_position"
	assert HeadcountRequest.__tablename__ == "pos_headcount_request"


# ---------------------------------------------------------------------------
# create_position
# ---------------------------------------------------------------------------

def test_create_position_creates_vacant(svc, session, tenant_id) -> None:
	pos = svc.create_position(
		"ENG-001",
		"Senior Software Engineer",
		tenant_id,
		session,
		entity_id="entity-nairobi",
		grade_level="G5",
		employment_type="FULL_TIME",
		budget_salary_cents=8_000_000,
	)
	assert pos.status == "VACANT"
	assert pos.position_code == "ENG-001"
	assert pos.title == "Senior Software Engineer"
	assert pos.budget_salary_cents == 8_000_000
	assert pos.headcount_budget == Decimal("1.0")
	assert pos.incumbent_employee_id is None


def test_create_position_fractional_fte(svc, session, tenant_id) -> None:
	pos = svc.create_position(
		"PT-001",
		"Part-Time Analyst",
		tenant_id,
		session,
		employment_type="PART_TIME",
		headcount_budget=0.5,
	)
	assert pos.headcount_budget == Decimal("0.5")
	assert pos.employment_type == "PART_TIME"


# ---------------------------------------------------------------------------
# fill_position
# ---------------------------------------------------------------------------

def test_fill_position_sets_filled_status(svc, session, tenant_id) -> None:
	pos = svc.create_position("MGR-001", "Engineering Manager", tenant_id, session)
	pos = svc.fill_position(pos.id, "emp-abc-123", session)
	assert pos.status == "FILLED"
	assert pos.incumbent_employee_id == "emp-abc-123"


def test_fill_non_vacant_position_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.position_management.services import PositionStateError

	pos = svc.create_position("MGR-002", "Product Manager", tenant_id, session)
	pos = svc.fill_position(pos.id, "emp-111", session)

	with pytest.raises(PositionStateError, match="VACANT"):
		svc.fill_position(pos.id, "emp-222", session)


def test_fill_nonexistent_position_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.position_management.services import PositionNotFoundError

	with pytest.raises(PositionNotFoundError):
		svc.fill_position("nonexistent-id", "emp-999", session)


# ---------------------------------------------------------------------------
# vacate_position
# ---------------------------------------------------------------------------

def test_vacate_position_clears_incumbent(svc, session, tenant_id) -> None:
	pos = svc.create_position("DEV-001", "Developer", tenant_id, session)
	pos = svc.fill_position(pos.id, "emp-dev-001", session)
	assert pos.status == "FILLED"

	pos = svc.vacate_position(pos.id, "RESIGNATION", session)
	assert pos.status == "VACANT"
	assert pos.incumbent_employee_id is None


def test_vacate_position_different_triggers(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.position_management.events import PositionVacatedEvent

	for trigger in ("RESIGNATION", "TERMINATION", "TRANSFER"):
		pos = svc.create_position(f"TRIG-{trigger[:3]}", f"Role {trigger}", tenant_id, session)
		svc.fill_position(pos.id, "emp-x", session)
		pos = svc.vacate_position(pos.id, trigger, session)
		assert pos.status == "VACANT"


def test_vacate_nonexistent_position_raises(svc, session, tenant_id) -> None:
	from pgappforge.plugins.erp.hcm.position_management.services import PositionNotFoundError

	with pytest.raises(PositionNotFoundError):
		svc.vacate_position("bad-id", "RESIGNATION", session)


# ---------------------------------------------------------------------------
# get_org_chart_positions
# ---------------------------------------------------------------------------

def test_get_org_chart_positions_returns_list(svc, session, tenant_id) -> None:
	entity = "entity-test-001"
	svc.create_position("ORG-001", "CTO", tenant_id, session, entity_id=entity)
	svc.create_position("ORG-002", "VP Engineering", tenant_id, session, entity_id=entity)

	# Stub session.execute to return the stored positions
	from pgappforge.plugins.erp.hcm.position_management.models import Position

	class _PosResult:
		def __init__(self, store, entity_id):
			self._positions = [
				v for v in store._objects.values()
				if isinstance(v, Position) and v.entity_id == entity_id
			]

		def scalars(self):
			return self

		def all(self):
			return self._positions

	original_execute = session.execute

	def _patched_execute(stmt):
		return _PosResult(session, entity)

	session.execute = _patched_execute

	positions = svc.get_org_chart_positions(entity, tenant_id, session)
	assert isinstance(positions, list)
	assert len(positions) == 2
	assert all("position_code" in p for p in positions)
	assert all("status" in p for p in positions)


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

def test_plugin_metadata() -> None:
	from pgappforge.plugins.erp.hcm.position_management import PositionManagementPlugin

	plugin = PositionManagementPlugin(None)
	meta = plugin.metadata
	assert meta.name == "position_management"
	assert meta.version == "1.0.0"
	assert "headcount" in meta.tags
	assert "workforce-planning" in meta.tags


def test_plugin_register_models() -> None:
	from pgappforge.plugins.erp.hcm.position_management import PositionManagementPlugin

	plugin = PositionManagementPlugin(None)
	models = plugin.register_models()
	names = [m.__tablename__ for m in models]
	assert "pos_position" in names
	assert "pos_headcount_request" in names


def test_plugin_subscribe_to_is_empty() -> None:
	from pgappforge.plugins.erp.hcm.position_management import PositionManagementPlugin

	plugin = PositionManagementPlugin(None)
	assert plugin.subscribe_to() == []
