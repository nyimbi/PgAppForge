"""
tests/ci/test_crm_plugins.py

CI tests for four CRM plugins:
  - Marketing Automation (mkt_*)
  - Events Management    (evt_*)
  - E-Sign Portal        (sgn_*)
  - Appointments/Booking (apt_*)

Strategy
--------
- SQLite in-memory engine (no PostgreSQL required).
- PG-specific column types replaced: JSONB→JSON, UUID→String(36),
  DateTime(timezone=True)→DateTime, Numeric→Float, BigInteger→Integer.
- Tables built from minimal schema matching each model (no cross-plugin FKs).
- erp_domain_event_log included so emit_event() can persist event rows.
- Real SQLAlchemy Session — no MagicMock.
- scope="module" engine/session fixtures.
- No @pytest.mark.asyncio — plain sync functions.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.types import JSON
from sqlalchemy.orm import declarative_base, Session

# ---------------------------------------------------------------------------
# Helpers / module-level constants
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


TENANT = _uid()

Base = declarative_base()


# ---------------------------------------------------------------------------
# Minimal table definitions (SQLite-compatible)
# ---------------------------------------------------------------------------

# --- erp_domain_event_log (required by emit_event) -------------------------

class _DomainEventLog(Base):
    __tablename__ = "erp_domain_event_log"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    # unique=True omitted: no need to enforce in-test; avoids cross-test collision
    # on shared in-memory engine when connection-level rollback doesn't cover all rows.
    event_id = Column(String(36), nullable=False)
    event_type = Column(String(200), nullable=False)
    aggregate_type = Column(String(100), nullable=True)
    aggregate_id = Column(String(64), nullable=True)
    tenant_id = Column(String(36), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    published_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    correlation_id = Column(String(36), nullable=True)
    causation_id = Column(String(36), nullable=True)


# --- Marketing Automation ---------------------------------------------------

class _MktCampaign(Base):
    __tablename__ = "mkt_campaign"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    name = Column(String(300), nullable=False, default="Test Campaign")
    description = Column(Text, nullable=True)
    campaign_type = Column(String(30), nullable=False, default="EMAIL")
    status = Column(String(20), nullable=False, default="DRAFT")
    entity_id = Column(String(50), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    budget_cents = Column(Integer, nullable=False, default=0)
    spent_cents = Column(Integer, nullable=False, default=0)
    target_segment = Column(JSON, nullable=False, default=dict)
    ab_test_enabled = Column(Boolean, nullable=False, default=False)
    ab_variants = Column(JSON, nullable=False, default=list)
    utm_params = Column(JSON, nullable=False, default=dict)
    goals = Column(JSON, nullable=False, default=dict)


class _MktSequence(Base):
    __tablename__ = "mkt_sequence"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    campaign_id = Column(String(36), ForeignKey("mkt_campaign.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    step_type = Column(String(30), nullable=False, default="EMAIL")
    delay_hours = Column(Integer, nullable=False, default=0)
    conditions_json = Column(JSON, nullable=False, default=list)
    template_id = Column(String(50), nullable=True)
    subject_line = Column(String(500), nullable=True)
    body_text = Column(Text, nullable=True)
    webhook_url = Column(Text, nullable=True)


class _MktContact(Base):
    __tablename__ = "mkt_contact"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_mkt_contact_campaign_contact"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    campaign_id = Column(String(36), ForeignKey("mkt_campaign.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(String(50), nullable=False)
    email = Column(String(320), nullable=True)
    phone = Column(String(30), nullable=True)
    status = Column(String(20), nullable=False, default="ENROLLED")
    ab_variant = Column(String(50), nullable=True)
    enrolled_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    current_step = Column(Integer, nullable=False, default=0)
    next_action_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata_", JSON, nullable=False, default=dict)


class _MktLeadScore(Base):
    __tablename__ = "mkt_lead_score"
    __table_args__ = (
        UniqueConstraint("tenant_id", "contact_id", name="uq_mkt_lead_score_tenant_contact"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    contact_id = Column(String(50), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    grade = Column(String(5), nullable=False, default="D")
    scoring_factors = Column(JSON, nullable=False, default=list)
    last_activity_at = Column(DateTime, nullable=True)
    converted = Column(Boolean, nullable=False, default=False)


class _MktAttribution(Base):
    __tablename__ = "mkt_attribution"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    campaign_id = Column(String(36), ForeignKey("mkt_campaign.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(String(50), nullable=False)
    opportunity_id = Column(String(50), nullable=True)
    revenue_cents = Column(Integer, nullable=False, default=0)
    attribution_model = Column(String(30), nullable=False, default="LAST_TOUCH")
    attributed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Events -----------------------------------------------------------------

class _EvtEvent(Base):
    __tablename__ = "evt_event"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    title = Column(String(300), nullable=False, default="Test Event")
    description = Column(Text, nullable=True)
    event_type = Column(String(30), nullable=False, default="OTHER")
    status = Column(String(20), nullable=False, default="DRAFT")
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=False)
    venue = Column(String(500), nullable=True)
    venue_address = Column(Text, nullable=True)
    is_virtual = Column(Boolean, nullable=False, default=False)
    virtual_link = Column(Text, nullable=True)
    max_capacity = Column(Integer, nullable=True)
    registration_deadline = Column(DateTime, nullable=True)
    entity_id = Column(String(50), nullable=True)
    created_by = Column(String(50), nullable=True)
    cover_image_url = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list)


class _EvtTicketType(Base):
    __tablename__ = "evt_ticket_type"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    event_id = Column(String(36), ForeignKey("evt_event.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False, default="General")
    price_cents = Column(Integer, nullable=False, default=0)
    quantity = Column(Integer, nullable=True)
    sold_count = Column(Integer, nullable=False, default=0)
    sale_starts_at = Column(DateTime, nullable=True)
    sale_ends_at = Column(DateTime, nullable=True)
    perks = Column(JSON, nullable=False, default=list)


class _EvtTicket(Base):
    __tablename__ = "evt_ticket"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_ref", name="uq_evt_ticket_tenant_ref"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    event_id = Column(String(36), ForeignKey("evt_event.id", ondelete="CASCADE"), nullable=False)
    ticket_type_id = Column(String(36), ForeignKey("evt_ticket_type.id", ondelete="CASCADE"), nullable=False)
    attendee_id = Column(String(50), nullable=False)
    attendee_email = Column(String(320), nullable=False)
    attendee_name = Column(String(200), nullable=False)
    ticket_ref = Column(String(50), nullable=False)
    amount_paid_cents = Column(Integer, nullable=False)
    currency_code = Column(String(3), nullable=False, default="KES")
    status = Column(String(20), nullable=False, default="CONFIRMED")
    purchased_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    qr_code_data = Column(Text, nullable=True)
    metadata_ = Column("metadata_", JSON, nullable=False, default=dict)


class _EvtAttendance(Base):
    __tablename__ = "evt_attendance"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_evt_attendance_ticket"),
        {"extend_existing": True},
    )

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    event_id = Column(String(36), ForeignKey("evt_event.id", ondelete="CASCADE"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("evt_ticket.id", ondelete="CASCADE"), nullable=False)
    attendee_id = Column(String(50), nullable=False)
    checked_in_at = Column(DateTime, nullable=True)
    checked_in_by = Column(String(50), nullable=True)
    checked_out_at = Column(DateTime, nullable=True)


class _EvtSponsor(Base):
    __tablename__ = "evt_sponsor"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    event_id = Column(String(36), ForeignKey("evt_event.id", ondelete="CASCADE"), nullable=False)
    sponsor_name = Column(String(300), nullable=False)
    sponsor_tier = Column(String(30), nullable=False, default="COMMUNITY")
    amount_cents = Column(Integer, nullable=False)
    logo_url = Column(Text, nullable=True)
    website_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)


# --- Sign -------------------------------------------------------------------

class _SgnRequest(Base):
    __tablename__ = "sgn_request"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    document_id = Column(String(50), nullable=False)
    document_title = Column(String(500), nullable=False)
    initiator_id = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    signing_order = Column(String(20), nullable=False, default="PARALLEL")
    subject = Column(String(500), nullable=True)
    message = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    bpm_instance_id = Column(String(50), nullable=True)
    metadata_ = Column("metadata_", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _SgnSignatory(Base):
    __tablename__ = "sgn_signatory"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    request_id = Column(String(36), ForeignKey("sgn_request.id", ondelete="CASCADE"), nullable=False)
    signer_id = Column(String(50), nullable=True)
    signer_email = Column(String(320), nullable=False)
    signer_name = Column(String(200), nullable=False)
    signer_role = Column(String(100), nullable=True)
    order_number = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="PENDING")
    access_token = Column(String(100), nullable=True, unique=True)
    signed_at = Column(DateTime, nullable=True)
    declined_at = Column(DateTime, nullable=True)
    decline_reason = Column(Text, nullable=True)
    signature_image_base64 = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _SgnAuditLog(Base):
    __tablename__ = "sgn_audit_log"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    request_id = Column(String(36), ForeignKey("sgn_request.id", ondelete="CASCADE"), nullable=False)
    signatory_id = Column(String(36), ForeignKey("sgn_signatory.id", ondelete="CASCADE"), nullable=True)
    action = Column(String(50), nullable=False)
    actor_id = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    metadata_ = Column("metadata_", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


# --- Appointments -----------------------------------------------------------

class _AptService(Base):
    __tablename__ = "apt_service"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=60)
    buffer_minutes = Column(Integer, nullable=False, default=0)
    price_cents = Column(Integer, nullable=False, default=0)
    currency_code = Column(String(3), nullable=False, default="KES")
    is_active = Column(Boolean, nullable=False, default=True)
    category = Column(String(100), nullable=True)
    max_advance_days = Column(Integer, nullable=False, default=90)
    min_advance_hours = Column(Integer, nullable=False, default=0)
    eligible_staff_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _AptAvailability(Base):
    __tablename__ = "apt_availability"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    staff_id = Column(String(50), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    entity_id = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _AptBlockedSlot(Base):
    __tablename__ = "apt_blocked_slot"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    staff_id = Column(String(50), nullable=False)
    blocked_from = Column(DateTime, nullable=False)
    blocked_to = Column(DateTime, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class _AptAppointment(Base):
    __tablename__ = "apt_appointment"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uid)
    tenant_id = Column(String(36), nullable=False)
    service_id = Column(String(36), ForeignKey("apt_service.id", ondelete="SET NULL"), nullable=True)
    staff_id = Column(String(50), nullable=False)
    customer_id = Column(String(50), nullable=True)
    customer_email = Column(String(320), nullable=True)
    customer_name = Column(String(200), nullable=True)
    customer_phone = Column(String(30), nullable=True)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    amount_cents = Column(Integer, nullable=False, default=0)
    currency_code = Column(String(3), nullable=False, default="KES")
    notes = Column(Text, nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    cancelled_by = Column(String(50), nullable=True)
    reminder_sent = Column(Boolean, nullable=False, default=False)
    booking_ref = Column(String(50), nullable=True)
    metadata_ = Column("metadata_", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = sa.create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Per-test session that rolls back after each test for isolation."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Monkey-patch: redirect model imports to our local SQLite-backed tables
# ---------------------------------------------------------------------------

def _patch_models(monkeypatch):
    """Redirect plugin model imports to the SQLite-compatible local classes.

    Services use ``from .models import X`` at module import time, so their
    module-level names must be patched in addition to the models module itself.
    Foundation models module must also be patched so emit_event() uses the
    SQLite-backed DomainEventLog table.
    """
    import pgappforge.plugins.erp.crm.marketing_automation.models as mkt_m
    import pgappforge.plugins.erp.crm.marketing_automation.services as mkt_s
    import pgappforge.plugins.erp.crm.events.models as evt_m
    import pgappforge.plugins.erp.crm.events.services as evt_s
    import pgappforge.plugins.erp.crm.sign.models as sgn_m
    import pgappforge.plugins.erp.crm.appointments.models as apt_m
    import pgappforge.plugins.erp.foundation.models as fnd_m

    # --- marketing_automation models module ---
    monkeypatch.setattr(mkt_m, "MarketingCampaign", _MktCampaign)
    monkeypatch.setattr(mkt_m, "MarketingSequence", _MktSequence)
    monkeypatch.setattr(mkt_m, "CampaignContact", _MktContact)
    monkeypatch.setattr(mkt_m, "LeadScore", _MktLeadScore)
    monkeypatch.setattr(mkt_m, "CampaignAttribution", _MktAttribution)

    # --- marketing_automation service (has ``from .models import X``) ---
    monkeypatch.setattr(mkt_s, "MarketingCampaign", _MktCampaign)
    monkeypatch.setattr(mkt_s, "MarketingSequence", _MktSequence)
    monkeypatch.setattr(mkt_s, "CampaignContact", _MktContact)
    monkeypatch.setattr(mkt_s, "LeadScore", _MktLeadScore)
    monkeypatch.setattr(mkt_s, "CampaignAttribution", _MktAttribution)

    # --- events models module ---
    monkeypatch.setattr(evt_m, "Event", _EvtEvent)
    monkeypatch.setattr(evt_m, "EventTicketType", _EvtTicketType)
    monkeypatch.setattr(evt_m, "EventTicket", _EvtTicket)
    monkeypatch.setattr(evt_m, "EventAttendance", _EvtAttendance)
    monkeypatch.setattr(evt_m, "EventSponsor", _EvtSponsor)

    # --- events service (has ``from .models import X``) ---
    monkeypatch.setattr(evt_s, "Event", _EvtEvent)
    monkeypatch.setattr(evt_s, "EventTicketType", _EvtTicketType)
    monkeypatch.setattr(evt_s, "EventTicket", _EvtTicket)
    monkeypatch.setattr(evt_s, "EventAttendance", _EvtAttendance)
    monkeypatch.setattr(evt_s, "EventSponsor", _EvtSponsor)

    # --- sign models module ---
    monkeypatch.setattr(sgn_m, "SignatureRequest", _SgnRequest)
    monkeypatch.setattr(sgn_m, "SignatureSignatory", _SgnSignatory)
    monkeypatch.setattr(sgn_m, "SignatureAuditLog", _SgnAuditLog)
    # sign service uses lazy ``from .models import X`` inside methods — no
    # top-level names to patch; the models module patch above is sufficient.

    # --- appointments models module ---
    monkeypatch.setattr(apt_m, "AppointmentService", _AptService)
    monkeypatch.setattr(apt_m, "StaffAvailability", _AptAvailability)
    monkeypatch.setattr(apt_m, "StaffBlockedSlot", _AptBlockedSlot)
    monkeypatch.setattr(apt_m, "Appointment", _AptAppointment)
    # appointments service uses lazy ``from .models import X`` inside methods.

    # --- foundation models (DomainEventLog used by emit_event) ---
    monkeypatch.setattr(fnd_m, "DomainEventLog", _DomainEventLog)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_monday() -> date:
    """Return the date of next Monday (always >= 7 days out for advance-gate safety)."""
    today = date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


# ===========================================================================
# MARKETING AUTOMATION
# ===========================================================================

class TestMarketingImports:

    def test_marketing_imports(self):
        from pgappforge.plugins.erp.crm.marketing_automation import (
            MarketingAutomationPlugin,
            MarketingAutomationService,
            MarketingCampaign,
            CampaignContact,
            LeadScore,
        )
        assert MarketingAutomationPlugin.name == "marketing_automation"
        assert callable(MarketingAutomationService)
        assert MarketingCampaign.__tablename__ == "mkt_campaign"
        assert CampaignContact.__tablename__ == "mkt_contact"
        assert LeadScore.__tablename__ == "mkt_lead_score"


class TestMarketingService:

    def test_activate_and_enroll(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.marketing_automation.services import (
            MarketingAutomationService,
        )

        # Create campaign
        campaign = _MktCampaign(
            id=_uid(),
            tenant_id=TENANT,
            name="Email Drip Q3",
            campaign_type="EMAIL",
            status="DRAFT",
        )
        session.add(campaign)
        session.flush()

        svc = MarketingAutomationService()
        svc.activate_campaign(campaign.id, session)

        status = session.execute(
            sa.select(_MktCampaign.status).where(_MktCampaign.id == campaign.id)
        ).scalar_one()
        assert status == "ACTIVE"

        contact = svc.enroll_contact(
            campaign.id,
            "CONTACT01",
            "test@example.com",
            session,
        )
        assert contact.status == "ENROLLED"
        assert contact.contact_id == "CONTACT01"
        assert contact.email == "test@example.com"

    def test_lead_scoring(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.marketing_automation.services import (
            MarketingAutomationService,
        )

        svc = MarketingAutomationService()
        score = svc.score_lead("CONTACT01", "page_view", 10, TENANT, session)

        assert score.score == 10
        assert score.grade in ("A+", "A", "B", "C", "D")
        assert score.contact_id == "CONTACT01"
        assert len(score.scoring_factors) >= 1

    def test_revenue_attribution(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.marketing_automation.services import (
            MarketingAutomationService,
        )

        svc = MarketingAutomationService()

        campaign = _MktCampaign(
            id=_uid(),
            tenant_id=TENANT,
            name="Attribution Campaign",
            campaign_type="EMAIL",
            status="DRAFT",
        )
        session.add(campaign)
        session.flush()

        svc.activate_campaign(campaign.id, session)
        svc.enroll_contact(campaign.id, "CONTACT02", "c2@example.com", session)

        svc.attribute_revenue(campaign.id, "CONTACT02", "OPP001", 50000, session)
        analytics = svc.get_campaign_analytics(campaign.id, session)

        assert analytics["revenue_attributed_cents"] >= 50000
        assert "enrolled" in analytics
        assert analytics["enrolled"] >= 1


# ===========================================================================
# EVENTS MANAGEMENT
# ===========================================================================

class TestEventsImports:

    def test_events_imports(self):
        from pgappforge.plugins.erp.crm.events import (
            EventsPlugin,
            EventsService,
            Event,
            EventTicketType,
            EventTicket,
        )
        assert EventsPlugin.name == "events"
        assert callable(EventsService)
        assert Event.__tablename__ == "evt_event"
        assert EventTicketType.__tablename__ == "evt_ticket_type"
        assert EventTicket.__tablename__ == "evt_ticket"


class TestEventsService:

    def test_publish_and_purchase_ticket(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.events.services import EventsService

        now = datetime.now(timezone.utc)

        event = _EvtEvent(
            id=_uid(),
            tenant_id=TENANT,
            title="TechConf 2026",
            status="DRAFT",
            start_datetime=now + timedelta(days=7),
            end_datetime=now + timedelta(days=8),
        )
        session.add(event)
        session.flush()

        ticket_type = _EvtTicketType(
            id=_uid(),
            tenant_id=TENANT,
            event_id=event.id,
            name="General Admission",
            price_cents=1000,
            quantity=100,
            sold_count=0,
        )
        session.add(ticket_type)
        session.flush()

        svc = EventsService()
        svc.publish_event(event.id, session)
        # Read back via query (avoids autoflush on session.get after expire)
        assert session.execute(
            sa.select(_EvtEvent.status).where(_EvtEvent.id == event.id)
        ).scalar_one() == "PUBLISHED"

        ticket = svc.purchase_ticket(
            event.id,
            ticket_type.id,
            "ATT01",
            "att@example.com",
            "Attendee One",
            session,
            tenant_id=TENANT,
        )
        assert ticket.status == "CONFIRMED"
        assert ticket.attendee_id == "ATT01"

        sold = session.execute(
            sa.select(_EvtTicketType.sold_count).where(_EvtTicketType.id == ticket_type.id)
        ).scalar_one()
        assert sold == 1

    def test_checkin(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.events.services import EventsService

        now = datetime.now(timezone.utc)

        event = _EvtEvent(
            id=_uid(),
            tenant_id=TENANT,
            title="Check-In Event",
            status="DRAFT",
            start_datetime=now + timedelta(days=3),
            end_datetime=now + timedelta(days=4),
        )
        session.add(event)
        ticket_type = _EvtTicketType(
            id=_uid(),
            tenant_id=TENANT,
            event_id=event.id,
            name="Standard",
            price_cents=500,
            quantity=50,
            sold_count=0,
        )
        session.add(ticket_type)
        session.flush()

        svc = EventsService()
        svc.publish_event(event.id, session)
        ticket = svc.purchase_ticket(
            event.id,
            ticket_type.id,
            "ATT02",
            "att2@example.com",
            "Attendee Two",
            session,
            tenant_id=TENANT,
        )

        attendance = svc.check_in_attendee(ticket.id, "STAFF01", session)
        assert attendance.checked_in_at is not None
        assert attendance.checked_in_by == "STAFF01"
        assert attendance.attendee_id == "ATT02"


# ===========================================================================
# E-SIGN PORTAL
# ===========================================================================

class TestSignImports:

    def test_sign_imports(self):
        from pgappforge.plugins.erp.crm.sign import (
            SignPlugin,
            SignatureService,
            SignatureRequest,
            SignatureSignatory,
        )
        assert SignPlugin.name == "sign"
        assert callable(SignatureService)
        assert SignatureRequest.__tablename__ == "sgn_request"
        assert SignatureSignatory.__tablename__ == "sgn_signatory"


class TestSignService:

    def test_signature_request_lifecycle(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.sign.services import SignatureService

        signatories_data = [
            {
                "signer_email": "alice@example.com",
                "signer_name": "Alice",
                "order_number": 0,
            }
        ]

        req = SignatureService.create_request(
            document_id="DOC001",
            document_title="Contract.pdf",
            initiator_id="USER01",
            signatories_data=signatories_data,
            tenant_id=TENANT,
            session=session,
        )
        assert req.status == "PENDING"
        assert req.document_id == "DOC001"

        # Retrieve the signatory access_token before sending (send_request
        # transitions to IN_PROGRESS but does not clear the token)
        signatory = session.execute(
            sa.select(_SgnSignatory).where(_SgnSignatory.request_id == req.id)
        ).scalar_one()
        token = signatory.access_token
        assert token is not None

        SignatureService.send_request(req.id, session)

        status_after_send = session.execute(
            sa.select(_SgnRequest.status).where(_SgnRequest.id == req.id)
        ).scalar_one()
        assert status_after_send == "IN_PROGRESS"

        # sign_document consumes and nulls the token, then completes the request
        SignatureService.sign_document(token, "base64sigdata==", session)

        status_after_sign = session.execute(
            sa.select(_SgnRequest.status).where(_SgnRequest.id == req.id)
        ).scalar_one()
        assert status_after_sign == "COMPLETED"

    def test_sign_decline_lifecycle(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.sign.services import SignatureService

        req = SignatureService.create_request(
            document_id="DOC002",
            document_title="NDA.pdf",
            initiator_id="USER01",
            signatories_data=[
                {"signer_email": "bob@example.com", "signer_name": "Bob", "order_number": 0}
            ],
            tenant_id=TENANT,
            session=session,
        )

        signatory = session.execute(
            sa.select(_SgnSignatory).where(_SgnSignatory.request_id == req.id)
        ).scalar_one()
        token = signatory.access_token

        SignatureService.send_request(req.id, session)
        SignatureService.decline_document(token, "Not agreed", session)

        declined_status = session.execute(
            sa.select(_SgnRequest.status).where(_SgnRequest.id == req.id)
        ).scalar_one()
        assert declined_status == "DECLINED"


# ===========================================================================
# APPOINTMENTS
# ===========================================================================

class TestAppointmentsImports:

    def test_appointments_imports(self):
        from pgappforge.plugins.erp.crm.appointments import (
            AppointmentsPlugin,
            AppointmentsService,
            AppointmentService as AptSvc,
            Appointment,
        )
        assert AppointmentsPlugin.name == "appointments"
        assert callable(AppointmentsService)
        assert AptSvc.__tablename__ == "apt_service"
        assert Appointment.__tablename__ == "apt_appointment"


class TestAppointmentsService:

    def test_get_available_slots(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.appointments.services import AppointmentsService

        svc_record = _AptService(
            id=_uid(),
            tenant_id=TENANT,
            name="Consultation",
            duration_minutes=60,
            buffer_minutes=0,
            price_cents=0,
            is_active=True,
            max_advance_days=90,
            min_advance_hours=0,
            eligible_staff_ids=[],
        )
        session.add(svc_record)

        next_monday = _next_monday()
        avail = _AptAvailability(
            id=_uid(),
            tenant_id=TENANT,
            staff_id="STAFF01",
            day_of_week=next_monday.weekday(),  # 0=Monday
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_active=True,
        )
        session.add(avail)
        session.flush()

        slots = AppointmentsService.get_available_slots(
            svc_record.id,
            "STAFF01",
            next_monday,
            TENANT,
            session,
        )
        assert len(slots) > 0
        assert "start" in slots[0]
        assert "end" in slots[0]

    def test_book_appointment(self, session, monkeypatch):
        _patch_models(monkeypatch)

        from pgappforge.plugins.erp.crm.appointments.services import AppointmentsService

        svc_record = _AptService(
            id=_uid(),
            tenant_id=TENANT,
            name="Follow-Up",
            duration_minutes=30,
            buffer_minutes=0,
            price_cents=0,
            is_active=True,
            max_advance_days=90,
            min_advance_hours=0,
            eligible_staff_ids=[],
        )
        session.add(svc_record)

        next_monday = _next_monday()
        avail = _AptAvailability(
            id=_uid(),
            tenant_id=TENANT,
            staff_id="STAFF02",
            day_of_week=next_monday.weekday(),
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_active=True,
        )
        session.add(avail)
        session.flush()

        slots = AppointmentsService.get_available_slots(
            svc_record.id,
            "STAFF02",
            next_monday,
            TENANT,
            session,
        )
        assert slots, "No slots returned — check availability setup"

        start_dt = datetime.fromisoformat(slots[0]["start"])
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        apt = AppointmentsService.book_appointment(
            svc_record.id,
            "STAFF02",
            start_dt,
            "client@test.com",
            "Client Name",
            TENANT,
            session,
            customer_id="CUST01",
        )
        assert apt.status == "PENDING"
        assert apt.booking_ref is not None

        AppointmentsService.confirm_appointment(apt.id, session)

        confirmed_status = session.execute(
            sa.select(_AptAppointment.status).where(_AptAppointment.id == apt.id)
        ).scalar_one()
        assert confirmed_status == "CONFIRMED"
