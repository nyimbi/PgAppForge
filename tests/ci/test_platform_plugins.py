"""
tests/ci/test_platform_plugins.py

CI tests for Platform modules: Documents, Discuss, Surveys.

Strategy
--------
- SQLite in-memory engine; fresh MetaData with SQLite-compatible types.
- JSONB → JSON, UUID(as_uuid=False) → String(36), DateTime(timezone=True) → DateTime,
  Numeric → Float.  search_vector (tsvector) → Text.
- emit_event() tries to INSERT into erp_domain_event_log — we include that table
  so it succeeds silently (errors are swallowed by emit_event anyway).
- No Flask context, no mocks for session — real SQLAlchemy Session throughout.
- AuditMixin adds no physical columns (it uses SA session events), so no extra
  column stubs are needed.
- scope="module" engine; session fixture is function-scoped and rolls back.

Run:
    uv run pytest -vxs tests/ci/test_platform_plugins.py
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


TENANT = _uid()


# ---------------------------------------------------------------------------
# Shared engine fixture — SQLite in-memory with all required tables
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
	eng = create_engine("sqlite:///:memory:", future=True)
	meta = sa.MetaData()

	# ── erp_domain_event_log — required by emit_event() ────────────────────
	# PK is UUID string (matches DomainEventLog model with UUID(as_uuid=False))
	sa.Table(
		"erp_domain_event_log", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("event_id", sa.String(36), nullable=False, unique=True),
		sa.Column("event_type", sa.String(200), nullable=False),
		sa.Column("aggregate_type", sa.String(100)),
		sa.Column("aggregate_id", sa.String(64)),
		sa.Column("tenant_id", sa.String(36)),
		sa.Column("payload", sa.JSON, default=dict),
		sa.Column("correlation_id", sa.String(36)),
		sa.Column("causation_id", sa.String(36)),
		sa.Column("published_at", sa.DateTime),
	)

	# ── DOCUMENTS ────────────────────────────────────────────────────────────

	sa.Table(
		"dms_folder", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("name", sa.String(300), nullable=False),
		sa.Column("parent_id", sa.String(36)),          # no FK — self-ref OK
		sa.Column("owner_id", sa.String(50)),
		sa.Column("access_policy", sa.JSON, default=dict),
		sa.Column("path_string", sa.Text),
		sa.Column("entity_id", sa.String(50)),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
	)

	sa.Table(
		"dms_document", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("title", sa.String(500), nullable=False),
		sa.Column("description", sa.Text),
		sa.Column("folder_id", sa.String(36)),           # no FK to keep SQLite simple
		sa.Column("owner_id", sa.String(50), nullable=False),
		sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),
		sa.Column("doc_type", sa.String(50)),
		sa.Column("tags", sa.JSON, default=list),
		sa.Column("latest_version_id", sa.String(50)),
		sa.Column("source_module", sa.String(100)),
		sa.Column("source_record_id", sa.String(50)),
		sa.Column("search_vector", sa.Text),             # tsvector → Text for SQLite
		sa.Column("metadata_", sa.JSON, default=dict),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
	)

	sa.Table(
		"dms_version", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("document_id", sa.String(36), sa.ForeignKey("dms_document.id", ondelete="CASCADE"), nullable=False),
		sa.Column("version_number", sa.Integer, nullable=False, default=1),
		sa.Column("filename", sa.String(500), nullable=False),
		sa.Column("file_path", sa.Text, nullable=False),
		sa.Column("file_size_bytes", sa.Integer),
		sa.Column("mime_type", sa.String(100)),
		sa.Column("checksum_sha256", sa.String(64)),
		sa.Column("uploaded_by", sa.String(50), nullable=False),
		sa.Column("uploaded_at", sa.DateTime),
		sa.Column("change_summary", sa.Text),
		sa.Column("is_current", sa.Boolean, nullable=False, default=True),
		sa.Column("metadata_", sa.JSON, default=dict),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
		sa.UniqueConstraint("document_id", "version_number", name="uq_dms_version_doc_num"),
	)

	sa.Table(
		"dms_access", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("document_id", sa.String(36), sa.ForeignKey("dms_document.id", ondelete="CASCADE"), nullable=False),
		sa.Column("grantee_id", sa.String(50), nullable=False),
		sa.Column("grantee_type", sa.String(20), nullable=False, default="USER"),
		sa.Column("access_level", sa.String(20), nullable=False, default="VIEW"),
		sa.Column("granted_by", sa.String(50), nullable=False),
		sa.Column("granted_at", sa.DateTime),
		sa.Column("expires_at", sa.DateTime),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
		sa.UniqueConstraint("document_id", "grantee_id", "grantee_type", name="uq_dms_access_doc_grantee"),
	)

	# ── DISCUSS ──────────────────────────────────────────────────────────────

	sa.Table(
		"dsc_channel", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("name", sa.String(200), nullable=False),
		sa.Column("description", sa.Text),
		sa.Column("channel_type", sa.String(20), nullable=False, default="PUBLIC"),
		sa.Column("created_by", sa.String(50), nullable=False),
		sa.Column("is_archived", sa.Boolean, nullable=False, default=False),
		sa.Column("linked_module", sa.String(100)),
		sa.Column("linked_record_id", sa.String(50)),
		sa.Column("avatar_url", sa.Text),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
	)

	sa.Table(
		"dsc_member", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("channel_id", sa.String(36), sa.ForeignKey("dsc_channel.id", ondelete="CASCADE"), nullable=False),
		sa.Column("member_id", sa.String(50), nullable=False),
		sa.Column("role", sa.String(20), nullable=False, default="MEMBER"),
		sa.Column("joined_at", sa.DateTime),
		sa.Column("last_read_message_id", sa.String(50)),
		sa.Column("is_muted", sa.Boolean, nullable=False, default=False),
		sa.UniqueConstraint("channel_id", "member_id", name="uq_dsc_member_channel_user"),
	)

	sa.Table(
		"dsc_message", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("created_at", sa.DateTime, nullable=False,
		          default=lambda: datetime.now(timezone.utc)),
		sa.Column("channel_id", sa.String(36), sa.ForeignKey("dsc_channel.id", ondelete="CASCADE"), nullable=False),
		sa.Column("author_id", sa.String(50), nullable=False),
		sa.Column("body", sa.Text, nullable=False),
		sa.Column("message_type", sa.String(20), nullable=False, default="TEXT"),
		sa.Column("parent_message_id", sa.String(36)),   # self-ref; no FK for SQLite compat
		sa.Column("reply_count", sa.Integer, nullable=False, default=0),
		sa.Column("attachments", sa.JSON, default=list),
		sa.Column("reactions", sa.JSON, default=dict),  # JSONB → JSON
		sa.Column("is_edited", sa.Boolean, nullable=False, default=False),
		sa.Column("edited_at", sa.DateTime),
		sa.Column("is_deleted", sa.Boolean, nullable=False, default=False),
		sa.Column("metadata", sa.JSON, default=dict),
		sa.Column("updated_at", sa.DateTime),
	)

	# ── SURVEYS ──────────────────────────────────────────────────────────────

	sa.Table(
		"srv_survey", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("created_at", sa.DateTime, nullable=False,
		          default=lambda: datetime.now(timezone.utc)),
		sa.Column("title", sa.String(300), nullable=False),
		sa.Column("description", sa.Text),
		sa.Column("survey_type", sa.String(30), nullable=False, default="CUSTOM"),
		sa.Column("status", sa.String(20), nullable=False, default="DRAFT"),
		sa.Column("is_anonymous", sa.Boolean, nullable=False, default=True),
		sa.Column("target_roles", sa.JSON, default=list),
		sa.Column("target_entity_id", sa.String(50)),
		sa.Column("opens_at", sa.DateTime),
		sa.Column("closes_at", sa.DateTime),
		sa.Column("created_by", sa.String(50)),
		sa.Column("allow_multiple_responses", sa.Boolean, nullable=False, default=False),
		sa.Column("show_results_to_respondents", sa.Boolean, nullable=False, default=False),
		sa.Column("updated_at", sa.DateTime),
	)

	sa.Table(
		"srv_question", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("survey_id", sa.String(36), sa.ForeignKey("srv_survey.id", ondelete="CASCADE"), nullable=False),
		sa.Column("question_text", sa.Text, nullable=False),
		sa.Column("question_type", sa.String(30), nullable=False),
		sa.Column("order_num", sa.Integer, nullable=False, default=0),
		sa.Column("is_required", sa.Boolean, nullable=False, default=True),
		sa.Column("options", sa.JSON, default=list),
		sa.Column("scale_min", sa.Integer),
		sa.Column("scale_max", sa.Integer),
		sa.Column("logic", sa.JSON, default=dict),
	)

	sa.Table(
		"srv_response", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("survey_id", sa.String(36), sa.ForeignKey("srv_survey.id", ondelete="CASCADE"), nullable=False),
		sa.Column("respondent_id", sa.String(50)),
		sa.Column("submitted_at", sa.DateTime),
		sa.Column("is_complete", sa.Boolean, nullable=False, default=True),
		sa.Column("response_token", sa.String(100), unique=True),
		sa.Column("metadata", sa.JSON, default=dict),
	)

	sa.Table(
		"srv_answer", meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("response_id", sa.String(36), sa.ForeignKey("srv_response.id", ondelete="CASCADE"), nullable=False),
		sa.Column("question_id", sa.String(36), sa.ForeignKey("srv_question.id", ondelete="CASCADE"), nullable=False),
		sa.Column("answer_text", sa.Text),
		sa.Column("answer_choice", sa.String(200)),
		sa.Column("answer_choices", sa.JSON),
		sa.Column("answer_number", sa.Float),            # Numeric → Float for SQLite
	)

	meta.create_all(eng)
	return eng


@pytest.fixture(autouse=True)
def _patch_pg_functions(monkeypatch):
	"""Stub out PostgreSQL-only functions that blow up on SQLite.

	- DocumentService._update_search_vector → no-op (to_tsvector not in SQLite)
	- DocumentService.search_documents → title LIKE fallback
	"""
	from pgappforge.plugins.erp.platform.documents import services as _dms_svc
	import sqlalchemy as _sa
	from pgappforge.plugins.erp.platform.documents.models import Document as _Doc

	def _noop_update_search_vector(self, doc, session):  # noqa: ANN001
		# SQLite has no to_tsvector; store a plain-text representation instead
		text_val = (doc.title or "") + " " + (doc.description or "")
		session.execute(
			_sa.update(_Doc).where(_Doc.id == doc.id).values(search_vector=text_val.strip())
		)
		session.expire(doc, ["search_vector"])

	def _sqlite_search_documents(self, query, tenant_id, session, *, doc_type=None, tags=None, owner_id=None, limit=50):  # noqa: ANN001
		assert tenant_id, "tenant_id must be non-empty"
		assert query, "query must be non-empty"
		stmt = (
			_sa.select(_Doc)
			.where(_Doc.tenant_id == tenant_id)
			.where(_Doc.status != "DELETED")
			.where(_Doc.title.ilike(f"%{query}%"))
		)
		if doc_type is not None:
			stmt = stmt.where(_Doc.doc_type == doc_type)
		if owner_id is not None:
			stmt = stmt.where(_Doc.owner_id == owner_id)
		stmt = stmt.limit(limit)
		return list(session.execute(stmt).scalars().all())

	monkeypatch.setattr(_dms_svc.DocumentService, "_update_search_vector", _noop_update_search_vector)
	monkeypatch.setattr(_dms_svc.DocumentService, "search_documents", _sqlite_search_documents)


@pytest.fixture
def session(engine):
	"""Function-scoped session; rolls back after each test."""
	with Session(engine) as sess:
		yield sess
		sess.rollback()


# ===========================================================================
# DOCUMENTS
# ===========================================================================

def test_documents_imports():
	from pgappforge.plugins.erp.platform.documents import (
		DocumentsPlugin,
		DocumentService,
		Document,
		DocumentVersion,
		DocumentFolder,
	)
	assert DocumentsPlugin.name == "documents"
	assert callable(DocumentService)
	# Models are importable and carry correct tablenames
	assert Document.__tablename__ == "dms_document"
	assert DocumentVersion.__tablename__ == "dms_version"
	assert DocumentFolder.__tablename__ == "dms_folder"


def test_upload_and_version(session):
	from pgappforge.plugins.erp.platform.documents.services import DocumentService
	from pgappforge.plugins.erp.platform.documents.models import DocumentVersion
	import sqlalchemy as _sa

	svc = DocumentService()
	doc = svc.upload_document(
		"Contract",
		"contract.pdf",
		"/files/contract.pdf",
		"USER01",
		TENANT,
		session,
		doc_type="CONTRACT",
		mime_type="application/pdf",
	)
	assert doc.id is not None
	assert doc.status == "ACTIVE"
	assert doc.latest_version_id is not None

	# Upload a second version
	v2 = svc.upload_new_version(
		doc.id,
		"contract_v2.pdf",
		"/files/v2.pdf",
		"USER01",
		session,
	)
	assert v2.version_number == 2
	assert v2.is_current is True

	# Confirm two versions in DB
	count = session.execute(
		_sa.select(_sa.func.count(DocumentVersion.id))
		.where(DocumentVersion.document_id == doc.id)
	).scalar_one()
	assert count == 2

	# latest_version_id updated
	session.expire(doc)
	refreshed = session.get(type(doc), doc.id)
	assert refreshed.latest_version_id == v2.id


def test_search_documents(session):
	"""search_documents uses the SQLite LIKE fallback patched by _patch_pg_functions."""
	from pgappforge.plugins.erp.platform.documents.services import DocumentService

	tenant = _uid()
	svc = DocumentService()
	svc.upload_document("Annual Contract Review", "acr.pdf", "/f/acr.pdf", "OWNER1", tenant, session)
	svc.upload_document("Invoice Q1", "inv.pdf", "/f/inv.pdf", "OWNER1", tenant, session)

	# "Contract" matches "Annual Contract Review" but not "Invoice Q1"
	results = svc.search_documents("Contract", tenant, session)
	assert isinstance(results, list)
	assert len(results) == 1
	assert results[0].title == "Annual Contract Review"

	# "Invoice" matches only the invoice doc
	invoice_results = svc.search_documents("Invoice", tenant, session)
	assert len(invoice_results) == 1
	assert invoice_results[0].title == "Invoice Q1"


def test_grant_access_and_get(session):
	from pgappforge.plugins.erp.platform.documents.services import (
		DocumentService, DocumentAccessError,
	)

	svc = DocumentService()
	tenant = _uid()
	doc = svc.upload_document(
		"Policy Doc", "policy.pdf", "/f/policy.pdf", "USER01", tenant, session,
	)

	# USER02 has no access yet — should raise
	with pytest.raises(DocumentAccessError):
		svc.get_document(doc.id, "USER02", tenant, session)

	# Grant VIEW to USER02
	grant = svc.grant_access(doc.id, "USER02", "USER", "VIEW", "USER01", session)
	assert grant.access_level == "VIEW"
	assert grant.grantee_id == "USER02"

	# Now USER02 can read
	fetched = svc.get_document(doc.id, "USER02", tenant, session)
	assert fetched.id == doc.id

	# Owner always has access
	fetched_owner = svc.get_document(doc.id, "USER01", tenant, session)
	assert fetched_owner.id == doc.id


def test_archive_document(session):
	from pgappforge.plugins.erp.platform.documents.services import DocumentService

	svc = DocumentService()
	tenant = _uid()
	doc = svc.upload_document(
		"Old Report", "report.pdf", "/f/report.pdf", "USER01", tenant, session,
	)
	assert doc.status == "ACTIVE"

	archived = svc.archive_document(doc.id, "USER01", session)
	assert archived.status == "ARCHIVED"

	# Verify persisted
	session.expire(archived)
	reloaded = session.get(type(doc), doc.id)
	assert reloaded.status == "ARCHIVED"


# ===========================================================================
# DISCUSS
# ===========================================================================

def test_discuss_imports():
	from pgappforge.plugins.erp.platform.discuss import DiscussPlugin
	from pgappforge.plugins.erp.platform.discuss.services import DiscussService
	from pgappforge.plugins.erp.platform.discuss.models import (
		DiscussChannel,
		DiscussMessage,
	)
	assert DiscussPlugin.name == "discuss"
	assert callable(DiscussService)
	assert DiscussChannel.__tablename__ == "dsc_channel"
	assert DiscussMessage.__tablename__ == "dsc_message"


def test_channel_and_message(session):
	from pgappforge.plugins.erp.platform.discuss.services import DiscussService

	tenant = _uid()
	svc = DiscussService()

	channel = svc.create_channel("general", "USER01", tenant, session)
	assert channel.id is not None
	assert channel.channel_type == "PUBLIC"
	assert channel.name == "general"

	msg = svc.post_message(channel.id, "USER01", "Hello!", session)
	assert msg.body == "Hello!"
	assert msg.channel_id == channel.id
	assert msg.author_id == "USER01"
	assert msg.parent_message_id is None


def test_discuss_service_validates_public_inputs(session):
	from pgappforge.plugins.erp.platform.discuss.services import (
		DiscussService,
		DiscussValidationError,
	)

	tenant = _uid()
	svc = DiscussService()

	with pytest.raises(DiscussValidationError, match="name"):
		svc.create_channel("", "USER01", tenant, session)
	with pytest.raises(DiscussValidationError, match="channel_type"):
		svc.create_channel("ops", "USER01", tenant, session, channel_type="bad")

	channel = svc.create_channel("ops", "USER01", tenant, session)

	with pytest.raises(DiscussValidationError, match="body"):
		svc.post_message(channel.id, "USER01", "", session)
	with pytest.raises(DiscussValidationError, match="attachments"):
		svc.post_message(channel.id, "USER01", "hello", session, attachments={"bad": True})
	with pytest.raises(DiscussValidationError, match="limit"):
		svc.get_channel_history(channel.id, session, limit=0)


def test_discuss_service_normalizes_channel_and_message_inputs(session):
	from pgappforge.plugins.erp.platform.discuss.models import DiscussChannelMember
	from pgappforge.plugins.erp.platform.discuss.services import DiscussService

	tenant = _uid()
	svc = DiscussService()

	channel = svc.create_channel(
		" ops ",
		"USER01",
		tenant,
		session,
		description=" daily ops ",
		channel_type="private",
		member_ids=["USER02", "USER02", "USER01"],
	)

	assert channel.name == "ops"
	assert channel.description == "daily ops"
	assert channel.channel_type == "PRIVATE"
	member_ids = {
		member.member_id
		for member in session.execute(
			sa.select(DiscussChannelMember).where(
				DiscussChannelMember.channel_id == channel.id
			)
		).scalars()
	}
	assert member_ids == {"USER01", "USER02"}

	msg = svc.post_message(
		channel.id,
		"USER01",
		" hello ",
		session,
		message_type="text",
		attachments=[{"filename": "note.txt", "size_bytes": 12}],
		metadata={"severity": "low"},
	)

	assert msg.body == "hello"
	assert msg.message_type == "TEXT"
	assert msg.attachments == [{"filename": "note.txt", "size_bytes": 12}]
	assert msg.metadata_ == {"severity": "low"}


def test_thread_reply(session):
	from pgappforge.plugins.erp.platform.discuss.services import DiscussService

	tenant = _uid()
	svc = DiscussService()

	channel = svc.create_channel("dev", "USER01", tenant, session)
	parent = svc.post_message(channel.id, "USER01", "Original post", session)
	assert parent.reply_count == 0

	reply = svc.post_message(
		channel.id, "USER02", "A reply", session,
		parent_message_id=parent.id,
	)
	assert reply.parent_message_id == parent.id

	# parent.reply_count should be 1 after the service increments it
	session.expire(parent)
	refreshed = session.get(type(parent), parent.id)
	assert refreshed.reply_count == 1


def test_unread_count(session):
	from pgappforge.plugins.erp.platform.discuss.services import DiscussService

	tenant = _uid()
	svc = DiscussService()

	channel = svc.create_channel("updates", "USER01", tenant, session)

	# Add USER02 as member (no read pointer yet)
	svc.add_member(channel.id, "USER02", "USER01", session)

	# USER01 posts 3 messages
	m1 = svc.post_message(channel.id, "USER01", "Msg 1", session)
	m2 = svc.post_message(channel.id, "USER01", "Msg 2", session)
	m3 = svc.post_message(channel.id, "USER01", "Msg 3", session)  # noqa: F841
	assert m2.id is not None

	# Mark USER02 as having read up to m1
	svc.mark_read(channel.id, "USER02", m1.id, session)

	# Messages after m1 are m2 and m3 → unread count = 2
	unread = svc.get_unread_count(channel.id, "USER02", session)
	assert unread == 2


# ===========================================================================
# SURVEYS
# ===========================================================================

def test_surveys_imports():
	from pgappforge.plugins.erp.platform.surveys import SurveysPlugin
	from pgappforge.plugins.erp.platform.surveys.services import SurveyService
	from pgappforge.plugins.erp.platform.surveys.models import (
		Survey,
		SurveyQuestion,
		SurveyResponse,
	)
	assert SurveysPlugin.name == "surveys"
	assert callable(SurveyService)
	assert Survey.__tablename__ == "srv_survey"
	assert SurveyQuestion.__tablename__ == "srv_question"
	assert SurveyResponse.__tablename__ == "srv_response"


def test_publish_and_respond(session):
	from pgappforge.plugins.erp.platform.surveys.services import SurveyService
	from pgappforge.plugins.erp.platform.surveys.models import Survey, SurveyQuestion

	tenant = _uid()
	svc = SurveyService()

	survey = Survey(
		id=_uid(),
		tenant_id=tenant,
		title="eNPS Q2",
		survey_type="ENPS",
		status="DRAFT",
		is_anonymous=False,    # non-anonymous so respondent_id is preserved
		allow_multiple_responses=False,
		target_roles=[],
	)
	session.add(survey)

	question = SurveyQuestion(
		id=_uid(),
		survey_id=survey.id,
		question_text="How likely are you to recommend us?",
		question_type="NPS",
		order_num=0,
		is_required=True,
		options=[],
		logic={},
	)
	session.add(question)
	session.flush()

	# Publish
	published = svc.publish_survey(survey.id, session)
	assert published.status == "PUBLISHED"

	# Submit a response
	response = svc.submit_response(
		survey.id,
		{question.id: 9},
		session,
		respondent_id="EMP001",
	)
	assert response.is_complete is True
	# Non-anonymous survey preserves respondent_id
	assert response.respondent_id == "EMP001"


def test_nps_computation(session):
	from pgappforge.plugins.erp.platform.surveys.services import SurveyService
	from pgappforge.plugins.erp.platform.surveys.models import Survey, SurveyQuestion

	tenant = _uid()
	svc = SurveyService()

	survey = Survey(
		id=_uid(),
		tenant_id=tenant,
		title="NPS Test",
		survey_type="ENPS",
		status="DRAFT",
		is_anonymous=False,
		allow_multiple_responses=True,   # allow multiple for this test
		target_roles=[],
	)
	session.add(survey)

	question = SurveyQuestion(
		id=_uid(),
		survey_id=survey.id,
		question_text="NPS score",
		question_type="NPS",
		order_num=0,
		is_required=True,
		options=[],
		logic={},
	)
	session.add(question)
	session.flush()

	svc.publish_survey(survey.id, session)

	# Score 9 → promoter, score 8 → passive, score 3 → detractor
	for score, respondent in [(9, "EMP001"), (8, "EMP002"), (3, "EMP003")]:
		svc.submit_response(
			survey.id,
			{question.id: score},
			session,
			respondent_id=respondent,
		)

	result = svc.compute_nps(survey.id, session)

	# NPS = (promoters - detractors) / total * 100 = (1 - 1) / 3 * 100 = 0.0
	assert "nps_score" in result
	assert -100 <= result["nps_score"] <= 100
	assert result["response_count"] == 3
	# promoter = 1 of 3, detractor = 1 of 3
	assert result["nps_score"] == pytest.approx(0.0, abs=0.01)
	assert result["promoters_pct"] == pytest.approx(33.33, abs=0.1)
	assert result["detractors_pct"] == pytest.approx(33.33, abs=0.1)
