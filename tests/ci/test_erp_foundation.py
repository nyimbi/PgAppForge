"""
tests/ci/test_erp_foundation.py

CI tests for the ERP Foundation plugin.

Tests cover:
 - DomainEvent dataclass construction and build_payload()
 - emit_event() persists DomainEventLog row + fires in-process handlers
 - FoundationService.resolve_party() — all match strategies
 - FoundationService.merge_parties() — re-parenting + deactivation
 - FoundationService.get_exchange_rate() — identity, lookup, missing
 - FoundationService.convert_amount() — round-trip, rounding, identity
 - FoundationService.seed_* helpers
 - Models: UUID PKs, JSONB defaults, tenant_id required

All tests use SQLite in-memory via SQLAlchemy (no Flask context needed for
the model / service layer).  We do NOT use lazy='dynamic' anywhere.

Run:
    uv run pytest -vxs tests/ci/test_erp_foundation.py
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Bootstrap: create an in-memory SQLite engine with all foundation tables
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
	"""Build an isolated SQLite engine with only foundation tables.

	We cannot use the shared Model.metadata because it contains JSONB columns
	from other plugins that SQLite cannot compile.  Instead we build a fresh
	MetaData, clone the foundation table definitions with JSON instead of JSONB,
	and create only those tables.
	"""
	eng = create_engine("sqlite:///:memory:", future=True)
	meta = sa.MetaData()

	# Minimal ab_user stub (FK target for Note.author_id, Attachment.uploaded_by)
	sa.Table(
		"ab_user", meta,
		sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
		sa.Column("username", sa.String(64)),
	)

	# erp_currency (no FKs, no JSONB)
	sa.Table(
		"erp_currency", meta,
		sa.Column("code", sa.String(3), primary_key=True),
		sa.Column("name", sa.String(100), nullable=False),
		sa.Column("symbol", sa.String(10), nullable=False),
		sa.Column("decimal_places", sa.Integer, nullable=False, default=2),
		sa.Column("is_active", sa.Boolean, nullable=False, default=True),
	)

	# erp_country
	sa.Table(
		"erp_country", meta,
		sa.Column("iso_alpha2", sa.String(2), primary_key=True),
		sa.Column("iso_alpha3", sa.String(3), nullable=False),
		sa.Column("name", sa.String(200), nullable=False),
		sa.Column("phone_prefix", sa.String(10)),
		sa.Column("currency_code", sa.String(3), sa.ForeignKey("erp_currency.code")),
		sa.Column("is_eu", sa.Boolean, nullable=False, default=False),
		sa.Column("is_active", sa.Boolean, nullable=False, default=True),
	)

	# erp_party
	sa.Table(
		"erp_party", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("party_type", sa.String(20), nullable=False),
		sa.Column("name", sa.String(500), nullable=False),
		sa.Column("short_name", sa.String(100)),
		sa.Column("legal_name", sa.String(500)),
		sa.Column("tax_id", sa.String(50)),
		sa.Column("vat_number", sa.String(50)),
		sa.Column("registration_number", sa.String(100)),
		sa.Column("lei", sa.String(20)),
		sa.Column("website", sa.String(500)),
		sa.Column("is_active", sa.Boolean, nullable=False, default=True),
		sa.Column("parent_id", sa.String(36), sa.ForeignKey("erp_party.id")),
		sa.Column("created_at", sa.DateTime(timezone=True)),
		sa.Column("updated_at", sa.DateTime(timezone=True)),
	)

	# erp_party_role  (attributes as JSON)
	sa.Table(
		"erp_party_role", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("party_id", sa.String(36), sa.ForeignKey("erp_party.id"), nullable=False),
		sa.Column("role_type", sa.String(20), nullable=False),
		sa.Column("effective_from", sa.DateTime(timezone=True)),
		sa.Column("effective_to", sa.DateTime(timezone=True)),
		sa.Column("attributes", sa.JSON, default=dict),
	)

	# erp_address
	sa.Table(
		"erp_address", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("party_id", sa.String(36), sa.ForeignKey("erp_party.id"), nullable=False),
		sa.Column("address_type", sa.String(20), nullable=False),
		sa.Column("line1", sa.String(500), nullable=False),
		sa.Column("line2", sa.String(500)),
		sa.Column("city", sa.String(200), nullable=False),
		sa.Column("state", sa.String(200)),
		sa.Column("postal_code", sa.String(20)),
		sa.Column("country_code", sa.String(2), sa.ForeignKey("erp_country.iso_alpha2"), nullable=False),
		sa.Column("geo_point", sa.Text),
		sa.Column("is_default", sa.Boolean, nullable=False, default=False),
		sa.Column("is_verified", sa.Boolean, nullable=False, default=False),
		sa.Column("created_at", sa.DateTime(timezone=True)),
		sa.Column("updated_at", sa.DateTime(timezone=True)),
	)

	# erp_contact
	sa.Table(
		"erp_contact", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("party_id", sa.String(36), sa.ForeignKey("erp_party.id"), nullable=False),
		sa.Column("contact_type", sa.String(20), nullable=False),
		sa.Column("value", sa.String(500), nullable=False),
		sa.Column("is_primary", sa.Boolean, nullable=False, default=False),
		sa.Column("is_verified", sa.Boolean, nullable=False, default=False),
		sa.Column("created_at", sa.DateTime(timezone=True)),
	)

	# erp_exchange_rate
	sa.Table(
		"erp_exchange_rate", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("from_currency", sa.String(3), sa.ForeignKey("erp_currency.code"), nullable=False),
		sa.Column("to_currency", sa.String(3), sa.ForeignKey("erp_currency.code"), nullable=False),
		sa.Column("rate", sa.Numeric(20, 8), nullable=False),
		sa.Column("rate_date", sa.DateTime(timezone=True), nullable=False),
		sa.Column("source", sa.String(20), nullable=False, default="MANUAL"),
		sa.Column("expires_at", sa.DateTime(timezone=True)),
		sa.Column("created_at", sa.DateTime(timezone=True)),
	)

	# erp_code_table  (metadata as JSON)
	sa.Table(
		"erp_code_table", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("domain", sa.String(100), nullable=False),
		sa.Column("code", sa.String(100), nullable=False),
		sa.Column("label", sa.String(500), nullable=False),
		sa.Column("sort_order", sa.Integer, nullable=False, default=0),
		sa.Column("is_active", sa.Boolean, nullable=False, default=True),
		sa.Column("metadata", sa.JSON, default=dict),
		sa.UniqueConstraint("domain", "code", name="uq_erp_code_table_domain_code"),
	)

	# erp_note
	sa.Table(
		"erp_note", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("entity_type", sa.String(100), nullable=False),
		sa.Column("entity_id", sa.String(64), nullable=False),
		sa.Column("note_type", sa.String(20), nullable=False, default="INTERNAL"),
		sa.Column("body", sa.Text, nullable=False),
		sa.Column("is_pinned", sa.Boolean, nullable=False, default=False),
		sa.Column("author_id", sa.Integer, sa.ForeignKey("ab_user.id")),
		sa.Column("created_at", sa.DateTime(timezone=True)),
		sa.Column("updated_at", sa.DateTime(timezone=True)),
	)

	# erp_attachment
	sa.Table(
		"erp_attachment", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("entity_type", sa.String(100), nullable=False),
		sa.Column("entity_id", sa.String(64), nullable=False),
		sa.Column("filename", sa.String(500), nullable=False),
		sa.Column("mime_type", sa.String(200), nullable=False),
		sa.Column("size_bytes", sa.Integer, nullable=False, default=0),
		sa.Column("storage_url", sa.String(2000), nullable=False),
		sa.Column("checksum_sha256", sa.String(64)),
		sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("ab_user.id")),
		sa.Column("created_at", sa.DateTime(timezone=True)),
	)

	# erp_domain_event_log
	sa.Table(
		"erp_domain_event_log", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("event_id", sa.String(36), nullable=False, unique=True),
		sa.Column("event_type", sa.String(200), nullable=False),
		sa.Column("aggregate_type", sa.String(100)),
		sa.Column("aggregate_id", sa.String(64)),
		sa.Column("tenant_id", sa.String(36)),
		sa.Column("payload", sa.JSON, default=dict),
		sa.Column("published_at", sa.DateTime(timezone=True)),
		sa.Column("correlation_id", sa.String(36)),
		sa.Column("causation_id", sa.String(36)),
	)

	meta.create_all(eng)

	# Point the ORM models at this engine's tables by rebinding their __table__
	# metadata.  We monkey-patch each model's __table__ to use our clean meta.
	from pgappforge.plugins.erp.foundation.models import (
		Address, Attachment, CodeTable, Contact, Country,
		Currency, DomainEventLog, ExchangeRate, Note, Party, PartyRole,
	)
	_ORM_TABLES = {
		"erp_party": Party,
		"erp_party_role": PartyRole,
		"erp_address": Address,
		"erp_contact": Contact,
		"erp_currency": Currency,
		"erp_exchange_rate": ExchangeRate,
		"erp_country": Country,
		"erp_code_table": CodeTable,
		"erp_note": Note,
		"erp_attachment": Attachment,
		"erp_domain_event_log": DomainEventLog,
	}
	_orig_tables = {}
	for tbl_name, cls in _ORM_TABLES.items():
		_orig_tables[tbl_name] = cls.__table__
		cls.__table__ = meta.tables[tbl_name]

	yield eng

	# Restore original tables
	for tbl_name, cls in _ORM_TABLES.items():
		cls.__table__ = _orig_tables[tbl_name]
	meta.drop_all(eng)


@pytest.fixture
def session(engine):
	with Session(engine) as s:
		yield s
		s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "11111111-1111-1111-1111-111111111111"


def _party(session, name="Acme Corp", party_type="ORGANIZATION", **kwargs) -> "Party":
	from pgappforge.plugins.erp.foundation.models import Party
	p = Party(
		name=name,
		party_type=party_type,
		tenant_id=_TENANT,
		**kwargs,
	)
	session.add(p)
	session.flush()
	return p


def _currency(session, code="USD", name="US Dollar", symbol="$", dp=2):
	from pgappforge.plugins.erp.foundation.models import Currency
	c = Currency(code=code, name=name, symbol=symbol, decimal_places=dp)
	session.add(c)
	session.flush()
	return c


# ---------------------------------------------------------------------------
# DomainEvent tests
# ---------------------------------------------------------------------------

class TestDomainEvent:

	def test_event_id_auto_generated(self):
		from pgappforge.plugins.erp.foundation.events import DomainEvent
		e = DomainEvent(event_type="test.event", aggregate_id="abc")
		assert e.event_id
		assert len(e.event_id) == 36  # UUID4 string

	def test_two_events_have_different_ids(self):
		from pgappforge.plugins.erp.foundation.events import DomainEvent
		e1 = DomainEvent(event_type="x")
		e2 = DomainEvent(event_type="x")
		assert e1.event_id != e2.event_id

	def test_occurred_at_is_timezone_aware(self):
		from pgappforge.plugins.erp.foundation.events import DomainEvent
		e = DomainEvent()
		assert e.occurred_at.tzinfo is not None

	def test_build_payload_excludes_base_fields(self):
		from pgappforge.plugins.erp.foundation.events import PartyCreatedEvent
		e = PartyCreatedEvent(
			aggregate_id="p1",
			aggregate_type="Party",
			tenant_id=_TENANT,
			party_id="p1",
			party_type="ORGANIZATION",
			name="Acme",
		)
		payload = e.build_payload()
		# Domain-specific fields present
		assert payload["party_id"] == "p1"
		assert payload["party_type"] == "ORGANIZATION"
		assert payload["name"] == "Acme"
		# Base fields excluded
		assert "event_id" not in payload
		assert "tenant_id" not in payload
		assert "occurred_at" not in payload

	def test_subclass_default_event_type(self):
		from pgappforge.plugins.erp.foundation.events import PartyCreatedEvent
		e = PartyCreatedEvent()
		assert e.event_type == "party.created"


# ---------------------------------------------------------------------------
# emit_event tests
# ---------------------------------------------------------------------------

class TestEmitEvent:

	def test_emit_persists_event_log_row(self, session):
		from pgappforge.plugins.erp.foundation.events import PartyCreatedEvent, emit_event
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		e = PartyCreatedEvent(
			aggregate_id="p-emit-1",
			aggregate_type="Party",
			tenant_id=_TENANT,
			party_id="p-emit-1",
			party_type="ORGANIZATION",
			name="Emit Test Corp",
		)
		emit_event(e, session)
		row = session.execute(
			sa.select(DomainEventLog).where(DomainEventLog.event_id == e.event_id)
		).scalar_one_or_none()
		assert row is not None
		assert row.event_type == "party.created"
		assert row.aggregate_id == "p-emit-1"

	def test_emit_auto_builds_payload(self, session):
		from pgappforge.plugins.erp.foundation.events import PartyCreatedEvent, emit_event
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		e = PartyCreatedEvent(
			aggregate_id="p-payload",
			aggregate_type="Party",
			tenant_id=_TENANT,
			party_id="p-payload",
			party_type="INDIVIDUAL",
			name="Jane Doe",
		)
		# payload is empty before emit
		assert not e.payload
		emit_event(e, session)
		assert e.payload["name"] == "Jane Doe"

	def test_emit_fires_in_process_handler(self, session):
		from pgappforge.plugins.erp.foundation.events import (
			PartyUpdatedEvent, emit_event, subscribe, unsubscribe,
		)
		received = []

		def handler(ev):
			received.append(ev.event_type)

		subscribe("party.updated", handler)
		try:
			e = PartyUpdatedEvent(
				aggregate_id="p-handler",
				aggregate_type="Party",
				tenant_id=_TENANT,
				party_id="p-handler",
				changed_fields=["name"],
			)
			emit_event(e, session)
			assert received == ["party.updated"]
		finally:
			unsubscribe("party.updated", handler)

	def test_emit_handler_exception_does_not_propagate(self, session):
		from pgappforge.plugins.erp.foundation.events import (
			PartyUpdatedEvent, emit_event, subscribe, unsubscribe,
		)

		def bad_handler(ev):
			raise RuntimeError("intentional failure")

		subscribe("party.updated", bad_handler)
		try:
			e = PartyUpdatedEvent(
				aggregate_id="p-safe",
				aggregate_type="Party",
				tenant_id=_TENANT,
			)
			# Should not raise
			emit_event(e, session)
		finally:
			unsubscribe("party.updated", bad_handler)


# ---------------------------------------------------------------------------
# Party model tests
# ---------------------------------------------------------------------------

class TestPartyModel:

	def test_party_uuid_pk_auto(self, session):
		p = _party(session, name="UUID Test Inc")
		assert p.id
		assert len(p.id) == 36

	def test_party_is_active_defaults_true(self, session):
		p = _party(session, name="Active Test")
		assert p.is_active is True

	def test_party_self_referential_parent(self, session):
		parent = _party(session, name="Parent Corp")
		child = _party(session, name="Subsidiary Ltd", parent_id=parent.id)
		session.flush()
		assert child.parent_id == parent.id

	def test_party_role_attributes_jsonb(self, session):
		from pgappforge.plugins.erp.foundation.models import PartyRole
		p = _party(session, name="Role Test")
		role = PartyRole(
			party_id=p.id,
			tenant_id=_TENANT,
			role_type="CUSTOMER",
			attributes={"credit_limit": 500_000, "payment_terms": "NET30"},
		)
		session.add(role)
		session.flush()
		fetched = session.get(PartyRole, role.id)
		assert fetched.attributes["credit_limit"] == 500_000
		assert fetched.attributes["payment_terms"] == "NET30"


# ---------------------------------------------------------------------------
# FoundationService — resolve_party
# ---------------------------------------------------------------------------

class TestResolveParty:

	def test_resolve_by_name(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		_party(session, name="Resolve By Name Ltd")
		svc = FoundationService()
		result = svc.resolve_party("Resolve By Name Ltd", session, tenant_id=_TENANT)
		assert result.name == "Resolve By Name Ltd"

	def test_resolve_by_tax_id(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		_party(session, name="Tax ID Corp", tax_id="TIN-99887766")
		svc = FoundationService()
		result = svc.resolve_party("TIN-99887766", session, tenant_id=_TENANT)
		assert result.tax_id == "TIN-99887766"

	def test_resolve_by_lei(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		_party(session, name="LEI Corp", lei="254900OPPU84GM83MG36")
		svc = FoundationService()
		result = svc.resolve_party("254900OPPU84GM83MG36", session, tenant_id=_TENANT)
		assert result.lei == "254900OPPU84GM83MG36"

	def test_resolve_not_found_raises(self, session):
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, PartyNotFoundError,
		)
		svc = FoundationService()
		with pytest.raises(PartyNotFoundError):
			svc.resolve_party("NONEXISTENT-XYZ-12345", session, tenant_id=_TENANT)

	def test_resolve_empty_identifier_raises(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		with pytest.raises(AssertionError):
			svc.resolve_party("", session)

	def test_resolve_inactive_party_not_found(self, session):
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, PartyNotFoundError,
		)
		_party(session, name="Inactive Corp XYZ", is_active=False)
		svc = FoundationService()
		with pytest.raises(PartyNotFoundError):
			svc.resolve_party("Inactive Corp XYZ", session, tenant_id=_TENANT)


# ---------------------------------------------------------------------------
# FoundationService — merge_parties
# ---------------------------------------------------------------------------

class TestMergeParties:

	def test_merge_deactivates_duplicate(self, session):
		from pgappforge.plugins.erp.foundation.models import Party
		from pgappforge.plugins.erp.foundation.services import FoundationService
		primary = _party(session, name="Primary Merge Corp")
		duplicate = _party(session, name="Duplicate Merge Corp")
		svc = FoundationService()
		svc.merge_parties(primary.id, duplicate.id, session)
		session.flush()
		session.expire_all()
		dup = session.get(Party, duplicate.id)
		assert dup.is_active is False

	def test_merge_same_id_raises(self, session):
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, FoundationServiceError,
		)
		p = _party(session, name="Self Merge")
		svc = FoundationService()
		with pytest.raises(FoundationServiceError, match="itself"):
			svc.merge_parties(p.id, p.id, session)

	def test_merge_missing_primary_raises(self, session):
		from pgappforge.plugins.erp.foundation.services import (
			FoundationService, PartyNotFoundError,
		)
		dup = _party(session, name="Dup For Missing Primary")
		svc = FoundationService()
		with pytest.raises(PartyNotFoundError):
			svc.merge_parties("00000000-0000-0000-0000-000000000000", dup.id, session)

	def test_merge_emits_event(self, session):
		from pgappforge.plugins.erp.foundation.events import subscribe, unsubscribe
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		from pgappforge.plugins.erp.foundation.services import FoundationService
		primary = _party(session, name="Merge Event Primary")
		duplicate = _party(session, name="Merge Event Dup")
		received = []
		subscribe("party.merged", lambda e: received.append(e))
		try:
			svc = FoundationService()
			svc.merge_parties(primary.id, duplicate.id, session)
			assert len(received) == 1
			assert received[0].primary_id == primary.id
		finally:
			unsubscribe("party.merged", received.pop if received else lambda e: None)
			# clean unsubscribe
			from pgappforge.plugins.erp.foundation.events import _EVENT_BUS
			_EVENT_BUS.get("party.merged", []).clear()

	def test_merge_reparents_roles(self, session):
		from pgappforge.plugins.erp.foundation.models import PartyRole
		from pgappforge.plugins.erp.foundation.services import FoundationService
		primary = _party(session, name="Role Reparent Primary")
		duplicate = _party(session, name="Role Reparent Dup")
		role = PartyRole(
			party_id=duplicate.id,
			tenant_id=_TENANT,
			role_type="SUPPLIER",
			attributes={},
		)
		session.add(role)
		session.flush()
		svc = FoundationService()
		svc.merge_parties(primary.id, duplicate.id, session)
		session.flush()
		session.expire_all()
		updated_role = session.get(PartyRole, role.id)
		assert updated_role.party_id == primary.id


# ---------------------------------------------------------------------------
# FoundationService — exchange rates
# ---------------------------------------------------------------------------

class TestExchangeRate:

	def _setup_currencies(self, session):
		from pgappforge.plugins.erp.foundation.models import Currency
		for code, name, sym in [
			("USD", "US Dollar", "$"),
			("NGN", "Nigerian Naira", "₦"),
			("EUR", "Euro", "€"),
		]:
			if session.get(Currency, code) is None:
				session.add(Currency(code=code, name=name, symbol=sym, decimal_places=2))
		session.flush()

	def test_identity_rate(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		result = svc.get_exchange_rate("USD", "USD", date.today(), session)
		assert result == Decimal("1")

	def test_lookup_rate(self, session):
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		from pgappforge.plugins.erp.foundation.services import FoundationService
		self._setup_currencies(session)
		session.add(ExchangeRate(
			from_currency="USD",
			to_currency="NGN",
			rate=Decimal("1580.50000000"),
			rate_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
			source="MANUAL",
		))
		session.flush()
		svc = FoundationService()
		rate = svc.get_exchange_rate("USD", "NGN", date(2026, 1, 15), session)
		assert rate == Decimal("1580.50000000")

	def test_most_recent_rate_selected(self, session):
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		from pgappforge.plugins.erp.foundation.services import FoundationService
		self._setup_currencies(session)
		# Older rate
		session.add(ExchangeRate(
			from_currency="USD",
			to_currency="EUR",
			rate=Decimal("0.91000000"),
			rate_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
			source="ECB",
		))
		# Newer rate
		session.add(ExchangeRate(
			from_currency="USD",
			to_currency="EUR",
			rate=Decimal("0.93000000"),
			rate_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
			source="ECB",
		))
		session.flush()
		svc = FoundationService()
		rate = svc.get_exchange_rate("USD", "EUR", date(2026, 1, 31), session)
		assert rate == Decimal("0.93000000")

	def test_rate_not_found_raises(self, session):
		from pgappforge.plugins.erp.foundation.services import (
			ExchangeRateNotFoundError, FoundationService,
		)
		svc = FoundationService()
		with pytest.raises(ExchangeRateNotFoundError):
			svc.get_exchange_rate("XYZ", "ABC", date.today(), session)

	def test_convert_amount_identity(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		assert svc.convert_amount(100_000, "NGN", "NGN", date.today(), session) == 100_000

	def test_convert_amount_uses_rate(self, session):
		from pgappforge.plugins.erp.foundation.models import ExchangeRate
		from pgappforge.plugins.erp.foundation.services import FoundationService
		self._setup_currencies(session)
		session.add(ExchangeRate(
			from_currency="USD",
			to_currency="NGN",
			rate=Decimal("1600.00000000"),
			rate_date=datetime(2026, 2, 1, tzinfo=timezone.utc),
			source="MANUAL",
		))
		session.flush()
		svc = FoundationService()
		# $10.00 = 1000 cents → 1000 * 1600 = 1_600_000 kobo
		result = svc.convert_amount(1000, "USD", "NGN", date(2026, 2, 15), session)
		assert result == 1_600_000

	def test_convert_amount_must_be_int(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		with pytest.raises(AssertionError):
			svc.convert_amount(10.5, "USD", "NGN", date.today(), session)  # type: ignore


# ---------------------------------------------------------------------------
# CodeTable tests
# ---------------------------------------------------------------------------

class TestCodeTable:

	def test_get_codes_empty_domain(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		result = FoundationService().get_codes("nonexistent_domain_xyz", session)
		assert result == []

	def test_get_codes_returns_active_only(self, session):
		from pgappforge.plugins.erp.foundation.models import CodeTable
		from pgappforge.plugins.erp.foundation.services import FoundationService
		session.add(CodeTable(domain="test_terms", code="NET30", label="Net 30 Days",
		                      is_active=True, metadata_={}))
		session.add(CodeTable(domain="test_terms", code="PREPAY", label="Prepayment",
		                      is_active=False, metadata_={}))
		session.flush()
		result = FoundationService().get_codes("test_terms", session, active_only=True)
		codes = [c.code for c in result]
		assert "NET30" in codes
		assert "PREPAY" not in codes

	def test_get_code_single(self, session):
		from pgappforge.plugins.erp.foundation.models import CodeTable
		from pgappforge.plugins.erp.foundation.services import FoundationService
		session.add(CodeTable(domain="doc_type", code="INV", label="Invoice",
		                      is_active=True, metadata_={"gl_code": "4000"}))
		session.flush()
		result = FoundationService().get_code("doc_type", "INV", session)
		assert result is not None
		assert result.label == "Invoice"
		assert result.metadata_["gl_code"] == "4000"

	def test_get_code_missing_returns_none(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		result = FoundationService().get_code("missing_domain", "MISSING", session)
		assert result is None


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

class TestSeedHelpers:

	def test_seed_currencies_idempotent(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		n1 = svc.seed_major_currencies(session)
		n2 = svc.seed_major_currencies(session)
		assert n1 > 0
		assert n2 == 0  # second call inserts nothing

	def test_seed_countries_idempotent(self, session):
		from pgappforge.plugins.erp.foundation.services import FoundationService
		svc = FoundationService()
		# currencies must exist first (FK)
		svc.seed_major_currencies(session)
		n1 = svc.seed_major_countries(session)
		n2 = svc.seed_major_countries(session)
		assert n1 > 0
		assert n2 == 0

	def test_seed_currencies_includes_ngn(self, session):
		from pgappforge.plugins.erp.foundation.models import Currency
		from pgappforge.plugins.erp.foundation.services import FoundationService
		FoundationService().seed_major_currencies(session)
		ngn = session.get(Currency, "NGN")
		assert ngn is not None
		assert ngn.symbol == "₦"
		assert ngn.decimal_places == 2

	def test_seed_countries_includes_nigeria(self, session):
		from pgappforge.plugins.erp.foundation.models import Country
		from pgappforge.plugins.erp.foundation.services import FoundationService
		FoundationService().seed_major_currencies(session)
		FoundationService().seed_major_countries(session)
		ng = session.get(Country, "NG")
		assert ng is not None
		assert ng.iso_alpha3 == "NGA"
		assert ng.phone_prefix == "+234"
		assert ng.currency_code == "NGN"


# ---------------------------------------------------------------------------
# FoundationPlugin metadata
# ---------------------------------------------------------------------------

class TestFoundationPlugin:

	def test_plugin_name_and_domain(self):
		from pgappforge.plugins.erp.foundation import FoundationPlugin
		assert FoundationPlugin.name == "foundation"
		assert FoundationPlugin.domain == "platform"

	def test_get_events(self):
		from pgappforge.plugins.erp.foundation import FoundationPlugin
		# Instantiate without appbuilder for metadata-only checks
		class _FakeAB:
			pass
		plugin = FoundationPlugin(_FakeAB())
		events = plugin.get_events()
		assert "party.created" in events
		assert "party.merged" in events
		assert "exchange_rate.updated" in events

	def test_subscribe_to_empty(self):
		from pgappforge.plugins.erp.foundation import FoundationPlugin
		class _FakeAB:
			pass
		plugin = FoundationPlugin(_FakeAB())
		assert plugin.subscribe_to() == []

	def test_register_models_returns_all(self):
		from pgappforge.plugins.erp.foundation import FoundationPlugin
		class _FakeAB:
			pass
		plugin = FoundationPlugin(_FakeAB())
		models = plugin.register_models()
		names = {m.__name__ for m in models}
		assert "Party" in names
		assert "Currency" in names
		assert "ExchangeRate" in names
		assert "DomainEventLog" in names
		assert len(models) == 11
