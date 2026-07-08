from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


SERVICES_PATH = (
	Path(__file__).resolve().parents[2]
	/ "pgappforge/plugins/erp/platform/whatsapp/services.py"
)


class Base(DeclarativeBase):
	pass


def _uid() -> str:
	return str(uuid.uuid4())


class WaMessage(Base):
	__tablename__ = "wa_message_hardening"

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	to_phone = Column(String(30), nullable=False)
	from_phone = Column(String(30), nullable=True)
	direction = Column(String(10), nullable=False)
	message_type = Column(String(20), nullable=False, default="TEMPLATE")
	body = Column(Text, nullable=True)
	wa_message_id = Column(String(200), nullable=True, index=True)
	status = Column(String(20), nullable=False, default="QUEUED")
	sent_at = Column(DateTime, nullable=True)
	delivered_at = Column(DateTime, nullable=True)
	read_at = Column(DateTime, nullable=True)


class WaConversation(Base):
	__tablename__ = "wa_conversation_hardening"

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	phone_number = Column(String(30), nullable=False)
	status = Column(String(20), nullable=False, default="ACTIVE")
	last_message_at = Column(DateTime, nullable=True)
	message_count = Column(Integer, nullable=False, default=0)


class WaWebhookLog(Base):
	__tablename__ = "wa_webhook_log_hardening"

	id = Column(String(36), primary_key=True, default=_uid)
	tenant_id = Column(String(36), nullable=False)
	event_type = Column(String(100), nullable=False)
	payload = Column(JSON, nullable=False)
	processed = Column(Boolean, nullable=False, default=False)
	error = Column(Text, nullable=True)


class _Event:
	def __init__(self, **kwargs: Any) -> None:
		self.__dict__.update(kwargs)


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
	module = types.ModuleType(name)
	module.__path__ = []  # type: ignore[attr-defined]
	monkeypatch.setitem(sys.modules, name, module)
	parent_name, _, attr = name.rpartition(".")
	if parent_name:
		setattr(sys.modules[parent_name], attr, module)
	return module


@pytest.fixture
def session() -> Session:
	engine = create_engine("sqlite:///:memory:")
	Base.metadata.create_all(engine)
	with Session(engine) as active_session:
		yield active_session


@pytest.fixture
def service_module(monkeypatch: pytest.MonkeyPatch):
	for module_name in (
		"pgappforge",
		"pgappforge.plugins",
		"pgappforge.plugins.erp",
		"pgappforge.plugins.erp.platform",
		"pgappforge.plugins.erp.platform.whatsapp",
		"pgappforge.plugins.erp.foundation",
	):
		_install_module(monkeypatch, module_name)

	models = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.platform.whatsapp.models",
	)
	models.WhatsAppMessage = WaMessage
	models.WhatsAppConversation = WaConversation
	models.WhatsAppWebhookLog = WaWebhookLog

	events = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.platform.whatsapp.events",
	)
	for event_name in (
		"WhatsAppConversationStartedEvent",
		"WhatsAppInboundMessageEvent",
		"WhatsAppMessageDeliveredEvent",
		"WhatsAppMessageReadEvent",
		"WhatsAppMessageSentEvent",
	):
		setattr(events, event_name, _Event)

	foundation_events = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.foundation.events",
	)
	foundation_events.emit_event = lambda event, session: None

	spec = importlib.util.spec_from_file_location(
		"whatsapp_services_hardening_under_test",
		SERVICES_PATH,
	)
	assert spec is not None
	assert spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _sign(payload: dict[str, Any], secret: str) -> tuple[str, bytes]:
	raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
	signature = "sha256=" + hmac.new(
		secret.encode("utf-8"),
		raw_body,
		hashlib.sha256,
	).hexdigest()
	return signature, raw_body


def _webhook_log_count(session: Session, tenant_id: str) -> int:
	return session.execute(
		sa.select(sa.func.count()).select_from(WaWebhookLog).where(
			WaWebhookLog.tenant_id == tenant_id
		)
	).scalar_one()


def test_process_webhook_requires_signature_when_secret_configured(
	service_module,
	session: Session,
) -> None:
	tenant_id = _uid()

	with pytest.raises(ValueError, match="requires X-Hub-Signature-256"):
		service_module.WhatsAppService.process_webhook(
			"messages.inbound",
			{"messages": []},
			tenant_id,
			session,
			app_secret="secret",
			raw_body=b'{"messages":[]}',
		)

	assert _webhook_log_count(session, tenant_id) == 0


def test_process_webhook_signed_inbound_creates_message(
	service_module,
	session: Session,
) -> None:
	tenant_id = _uid()
	wa_msg_id = f"wamid.{_uid()}"
	payload = {
		"entry": [
			{
				"changes": [
					{
						"value": {
							"messages": [
								{
									"from": "+254700000001",
									"id": wa_msg_id,
									"type": "text",
									"text": {"body": "Hello from webhook"},
								}
							]
						}
					}
				]
			}
		]
	}
	secret = "top-secret"
	signature, raw_body = _sign(payload, secret)

	result = service_module.WhatsAppService.process_webhook(
		"messages.inbound",
		payload,
		tenant_id,
		session,
		hmac_signature=signature,
		app_secret=secret,
		raw_body=raw_body,
	)

	assert result == {
		"processed": True,
		"action": "inbound_processed",
		"detail": "processed 1 inbound message(s)",
	}

	msg = session.execute(
		sa.select(WaMessage).where(WaMessage.wa_message_id == wa_msg_id)
	).scalar_one()
	assert msg.direction == "INBOUND"
	assert msg.from_phone == "+254700000001"
	assert msg.body == "Hello from webhook"

	log_row = session.execute(
		sa.select(WaWebhookLog).where(WaWebhookLog.tenant_id == tenant_id)
	).scalar_one()
	assert log_row.processed is True
	assert log_row.error is None


def test_process_webhook_rejects_oversized_message_before_logging(
	service_module,
	session: Session,
) -> None:
	tenant_id = _uid()
	payload = {
		"messages": [
			{
				"from": "+254700000002",
				"id": f"wamid.{_uid()}",
				"type": "text",
				"text": {"body": "x" * 4097},
			}
		]
	}

	with pytest.raises(ValueError, match="message.text.body"):
		service_module.WhatsAppService.process_webhook(
			"messages.inbound",
			payload,
			tenant_id,
			session,
		)

	assert _webhook_log_count(session, tenant_id) == 0


def test_process_webhook_rejects_excessive_message_count_before_logging(
	service_module,
	session: Session,
) -> None:
	tenant_id = _uid()
	payload = {
		"messages": [
			{
				"from": "+254700000003",
				"id": f"wamid.{index}",
				"type": "text",
				"text": {"body": "ok"},
			}
			for index in range(201)
		]
	}

	with pytest.raises(ValueError, match="payload.messages contains 201 items"):
		service_module.WhatsAppService.process_webhook(
			"messages.inbound",
			payload,
			tenant_id,
			session,
		)

	assert _webhook_log_count(session, tenant_id) == 0


def test_update_delivery_status_rejects_unknown_status(
	service_module,
	session: Session,
) -> None:
	with pytest.raises(
		service_module.WhatsAppStateError,
		match="Unsupported WhatsApp delivery status",
	):
		service_module.WhatsAppService.update_delivery_status(
			"wamid.unknown",
			"BOGUS",
			session,
		)
