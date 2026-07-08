from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _uid() -> str:
	return str(uuid.uuid4())


@pytest.fixture
def engine():
	eng = create_engine("sqlite:///:memory:", future=True)
	meta = sa.MetaData()

	sa.Table(
		"dms_folder",
		meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("name", sa.String(300), nullable=False),
		sa.Column("parent_id", sa.String(36)),
		sa.Column("owner_id", sa.String(50)),
		sa.Column("access_policy", sa.JSON, default=dict),
		sa.Column("path_string", sa.Text),
		sa.Column("entity_id", sa.String(50)),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
	)
	sa.Table(
		"dms_document",
		meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("title", sa.String(500), nullable=False),
		sa.Column("description", sa.Text),
		sa.Column("folder_id", sa.String(36)),
		sa.Column("owner_id", sa.String(50), nullable=False),
		sa.Column("status", sa.String(20), nullable=False, default="ACTIVE"),
		sa.Column("doc_type", sa.String(50)),
		sa.Column("tags", sa.JSON, default=list),
		sa.Column("latest_version_id", sa.String(50)),
		sa.Column("source_module", sa.String(100)),
		sa.Column("source_record_id", sa.String(50)),
		sa.Column("search_vector", sa.Text),
		sa.Column("metadata_", sa.JSON, default=dict),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
	)
	sa.Table(
		"dms_version",
		meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("document_id", sa.String(36), nullable=False),
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
		"dms_access",
		meta,
		sa.Column("id", sa.String(36), primary_key=True),
		sa.Column("tenant_id", sa.String(36), nullable=False),
		sa.Column("document_id", sa.String(36), nullable=False),
		sa.Column("grantee_id", sa.String(50), nullable=False),
		sa.Column("grantee_type", sa.String(20), nullable=False, default="USER"),
		sa.Column("access_level", sa.String(20), nullable=False, default="VIEW"),
		sa.Column("granted_by", sa.String(50), nullable=False),
		sa.Column("granted_at", sa.DateTime),
		sa.Column("expires_at", sa.DateTime),
		sa.Column("created_at", sa.DateTime),
		sa.Column("updated_at", sa.DateTime),
		sa.UniqueConstraint(
			"document_id",
			"grantee_id",
			"grantee_type",
			name="uq_dms_access_doc_grantee",
		),
	)

	meta.create_all(eng)
	return eng


@pytest.fixture
def session(engine):
	with Session(engine) as sess:
		yield sess
		sess.rollback()


@pytest.fixture(autouse=True)
def _patch_document_side_effects(monkeypatch):
	from pgappforge.plugins.erp.platform.documents import services as document_services
	from pgappforge.plugins.erp.platform.documents.models import Document

	def _noop_emit(event, session):  # noqa: ANN001
		return None

	def _sqlite_search_vector(self, doc, session):  # noqa: ANN001
		session.execute(
			sa.update(Document)
			.where(Document.id == doc.id)
			.values(search_vector=f"{doc.title or ''} {doc.description or ''}".strip())
		)

	monkeypatch.setattr(document_services, "emit_event", _noop_emit)
	monkeypatch.setattr(
		document_services.DocumentService,
		"_update_search_vector",
		_sqlite_search_vector,
	)


def _service():
	from pgappforge.plugins.erp.platform.documents.services import DocumentService

	return DocumentService()


def test_upload_validates_inputs_folder_scope_and_metadata(session):
	from pgappforge.plugins.erp.platform.documents.models import DocumentFolder
	from pgappforge.plugins.erp.platform.documents.services import (
		DocumentNotFoundError,
		DocumentValidationError,
	)

	tenant = _uid()
	other_tenant = _uid()
	folder = DocumentFolder(
		id=_uid(),
		tenant_id=tenant,
		name="Contracts",
		path_string="/contracts",
	)
	other_folder = DocumentFolder(
		id=_uid(),
		tenant_id=other_tenant,
		name="Other",
		path_string="/other",
	)
	session.add_all([folder, other_folder])
	session.flush()

	svc = _service()
	with pytest.raises(DocumentValidationError, match="title"):
		svc.upload_document("", "contract.pdf", "/f/contract.pdf", "OWNER", tenant, session)
	with pytest.raises(DocumentValidationError, match="file_size_bytes"):
		svc.upload_document("Contract", "c.pdf", "/f/c.pdf", "OWNER", tenant, session, file_size_bytes=-1)
	with pytest.raises(DocumentValidationError, match="tags"):
		svc.upload_document("Contract", "c.pdf", "/f/c.pdf", "OWNER", tenant, session, tags="finance")
	with pytest.raises(DocumentNotFoundError, match="Folder"):
		svc.upload_document(
			"Contract",
			"c.pdf",
			"/f/c.pdf",
			"OWNER",
			tenant,
			session,
			folder_id=other_folder.id,
		)

	doc = svc.upload_document(
		"  Contract  ",
		"contract.pdf",
		"/f/contract.pdf",
		"OWNER",
		tenant,
		session,
		folder_id=folder.id,
		doc_type="contract",
		tags=["Legal", "legal", " Finance "],
		mime_type="APPLICATION/PDF",
		file_size_bytes=1024,
	)
	assert doc.title == "Contract"
	assert doc.folder_id == folder.id
	assert doc.doc_type == "CONTRACT"
	assert doc.tags == ["Legal", "Finance"]


def test_version_upload_requires_write_access_and_active_document(session):
	from pgappforge.plugins.erp.platform.documents.services import (
		DocumentAccessError,
		DocumentStateError,
		DocumentValidationError,
	)

	tenant = _uid()
	svc = _service()
	doc = svc.upload_document("Policy", "policy.pdf", "/f/policy.pdf", "OWNER", tenant, session)

	with pytest.raises(DocumentValidationError, match="checksum"):
		svc.upload_new_version(
			doc.id,
			"policy-v2.pdf",
			"/f/policy-v2.pdf",
			"OWNER",
			session,
			checksum_sha256="not-a-checksum",
		)
	with pytest.raises(DocumentAccessError, match="cannot upload"):
		svc.upload_new_version(
			doc.id,
			"policy-v2.pdf",
			"/f/policy-v2.pdf",
			"VIEWER",
			session,
			tenant_id=tenant,
		)

	svc.grant_access(doc.id, "EDITOR", "USER", "EDIT", "OWNER", session, tenant_id=tenant)
	version = svc.upload_new_version(
		doc.id,
		"policy-v2.pdf",
		"/f/policy-v2.pdf",
		"EDITOR",
		session,
		tenant_id=tenant,
		checksum_sha256="A" * 64,
		file_size_bytes=2048,
	)
	assert version.version_number == 2
	assert version.checksum_sha256 == "a" * 64

	svc.archive_document(doc.id, "OWNER", session, tenant_id=tenant)
	with pytest.raises(DocumentStateError, match="ARCHIVED"):
		svc.upload_new_version(doc.id, "policy-v3.pdf", "/f/policy-v3.pdf", "OWNER", session)


def test_access_grants_require_admin_and_support_roles_and_expiry(session):
	from pgappforge.plugins.erp.platform.documents.models import DocumentAccess
	from pgappforge.plugins.erp.platform.documents.services import (
		DocumentAccessError,
		DocumentValidationError,
	)

	tenant = _uid()
	svc = _service()
	doc = svc.upload_document("Playbook", "playbook.pdf", "/f/playbook.pdf", "OWNER", tenant, session)

	with pytest.raises(DocumentAccessError, match="cannot manage access"):
		svc.grant_access(doc.id, "USER2", "USER", "VIEW", "USER2", session)
	with pytest.raises(DocumentValidationError, match="expires_at"):
		svc.grant_access(
			doc.id,
			"USER2",
			"USER",
			"VIEW",
			"OWNER",
			session,
			expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
		)

	svc.grant_access(doc.id, "DOC_ADMINS", "ROLE", "ADMIN", "OWNER", session)
	role_grant = svc.grant_access(
		doc.id,
		"REVIEWERS",
		"ROLE",
		"view",
		"ADMIN_USER",
		session,
		grantor_role_ids=["DOC_ADMINS"],
		expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
	)
	assert role_grant.access_level == "VIEW"

	fetched = svc.get_document(doc.id, "REVIEWER1", tenant, session, role_ids=["REVIEWERS"])
	assert fetched.id == doc.id

	role_grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
	session.flush()
	with pytest.raises(DocumentAccessError, match="does not have access"):
		svc.get_document(doc.id, "REVIEWER1", tenant, session, role_ids=["REVIEWERS"])

	assert session.execute(sa.select(sa.func.count(DocumentAccess.id))).scalar_one() == 2


def test_attach_validates_module_authority_and_document_state(session):
	from pgappforge.plugins.erp.platform.documents.services import (
		DocumentAccessError,
		DocumentStateError,
		DocumentValidationError,
	)

	tenant = _uid()
	svc = _service()
	doc = svc.upload_document("Invoice", "invoice.pdf", "/f/invoice.pdf", "OWNER", tenant, session)

	with pytest.raises(DocumentValidationError, match="source_module"):
		svc.attach_to_record(doc.id, "../finance", "INV-1", session)
	with pytest.raises(DocumentAccessError, match="cannot attach"):
		svc.attach_to_record(
			doc.id,
			"finance.ap",
			"INV-1",
			session,
			tenant_id=tenant,
			attached_by="VIEWER",
		)

	svc.grant_access(doc.id, "EDITOR", "USER", "EDIT", "OWNER", session)
	attached = svc.attach_to_record(
		doc.id,
		"finance.ap",
		"INV-1",
		session,
		tenant_id=tenant,
		attached_by="EDITOR",
	)
	assert attached.source_module == "finance.ap"
	assert attached.source_record_id == "INV-1"

	svc.archive_document(doc.id, "OWNER", session)
	with pytest.raises(DocumentStateError, match="ARCHIVED"):
		svc.attach_to_record(doc.id, "finance.ap", "INV-2", session, attached_by="OWNER")


def test_folder_tree_is_tenant_bound_entity_filtered_and_depth_capped(session):
	from pgappforge.plugins.erp.platform.documents.models import DocumentFolder
	from pgappforge.plugins.erp.platform.documents.services import DocumentValidationError

	tenant = _uid()
	other_tenant = _uid()
	root = DocumentFolder(
		id=_uid(),
		tenant_id=tenant,
		name="Root",
		parent_id=None,
		path_string="/root",
		entity_id="DEPT1",
	)
	child = DocumentFolder(
		id=_uid(),
		tenant_id=tenant,
		name="Child",
		parent_id=root.id,
		path_string="/root/child",
		entity_id="DEPT1",
	)
	leak = DocumentFolder(
		id=_uid(),
		tenant_id=other_tenant,
		name="Leak",
		parent_id=root.id,
		path_string="/leak",
		entity_id="DEPT1",
	)
	other_entity = DocumentFolder(
		id=_uid(),
		tenant_id=tenant,
		name="Other",
		parent_id=None,
		path_string="/other",
		entity_id="DEPT2",
	)
	session.add_all([root, child, leak, other_entity])
	session.flush()

	svc = _service()
	rows = svc.get_folder_tree(tenant, session, entity_id="DEPT1", max_depth=1)
	assert [row["name"] for row in rows] == ["Root", "Child"]
	assert all(row["entity_id"] == "DEPT1" for row in rows)
	assert "Leak" not in [row["name"] for row in rows]

	with pytest.raises(DocumentValidationError, match="max_depth"):
		svc.get_folder_tree(tenant, session, max_depth=0)
