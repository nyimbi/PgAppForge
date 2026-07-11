"""
pgappforge/plugins/erp/platform/whatsapp/services.py

WhatsAppService — stateless business logic for the WhatsApp Business API plugin.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries are owned by the caller.

The service manages the *outbox* and *inbox* records plus conversation state.
The actual HTTP call to the WhatsApp Business API (Cloud API or BSP) is
intentionally out-of-scope here — a separate delivery worker polls
get_pending_outbound() and calls the API, then calls update_delivery_status()
with the result.

Public methods:
  send_template_message(to_phone, template_name, params, tenant_id, session, ...)
  send_text_message(to_phone, body, tenant_id, session, ...)
  process_inbound(from_phone, body, wa_message_id, tenant_id, session, ...)
  update_delivery_status(wa_message_id, status, session, ...)
  process_webhook(event_type, payload, tenant_id, session)
  get_conversation_history(phone_number, tenant_id, session, *, limit=50)
  get_pending_outbound(tenant_id, session)
  get_analytics(tenant_id, session, *, from_date=None)

BPM actions registered (lazily, at module import):
  platform.whatsapp.send_template  — Send WhatsApp template message from workflow
  platform.whatsapp.send_text      — Send WhatsApp text message from workflow
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

_MAX_WEBHOOK_BODY_BYTES = 256 * 1024
_MAX_WEBHOOK_ENTRIES = 25
_MAX_WEBHOOK_CHANGES = 50
_MAX_WEBHOOK_ITEMS = 200
_MAX_WA_MESSAGE_ID_CHARS = 200
_MAX_PHONE_CHARS = 30
_MAX_EVENT_TYPE_CHARS = 100
_MAX_STATUS_CHARS = 20
_MAX_TEXT_BODY_CHARS = 4096
_MAX_SIGNATURE_CHARS = 128
_MAX_WEBHOOK_TIMESTAMP = 4_102_444_800  # 2100-01-01 UTC

_VALID_DELIVERY_STATUSES = {"SENT", "DELIVERED", "READ", "FAILED"}
_MEDIA_MESSAGE_TYPES = {"IMAGE", "DOCUMENT", "VIDEO", "AUDIO", "STICKER"}
_SUPPORTED_INBOUND_MESSAGE_TYPES = {
	"TEXT",
	*_MEDIA_MESSAGE_TYPES,
	"BUTTON",
	"CONTACTS",
	"INTERACTIVE",
	"LOCATION",
	"REACTION",
	"UNKNOWN",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WhatsAppServiceError(Exception):
	"""Base domain error for WhatsApp operations."""


class WhatsAppTemplateNotFoundError(WhatsAppServiceError):
	"""Template not found or not approved for the given tenant."""


class WhatsAppMessageNotFoundError(WhatsAppServiceError):
	"""Message not found by wa_message_id."""


class WhatsAppStateError(WhatsAppServiceError):
	"""Invalid state transition on a message or conversation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _now_iso() -> str:
	return _now().isoformat()


def _bounded_text(
	value: Any,
	field_name: str,
	max_chars: int,
	*,
	required: bool = True,
	strip: bool = True,
) -> str:
	if value is None:
		if required:
			raise ValueError(f"{field_name} is required")
		return ""
	if not isinstance(value, str):
		raise ValueError(f"{field_name} must be a string")
	text = value.strip() if strip else value
	if required and not text:
		raise ValueError(f"{field_name} is required")
	if len(text) > max_chars:
		raise ValueError(
			f"{field_name} is {len(text)} characters; maximum is {max_chars}"
		)
	return text


def _bounded_webhook_sequence(value: Any, field_name: str, max_items: int) -> list[Any]:
	if value is None:
		return []
	if not isinstance(value, list):
		raise ValueError(f"{field_name} must be a list")
	if len(value) > max_items:
		raise ValueError(
			f"{field_name} contains {len(value)} items; maximum is {max_items}"
		)
	return value


def _validate_webhook_payload(payload: Any) -> dict[str, Any]:
	if not isinstance(payload, dict):
		raise ValueError("WhatsApp webhook payload must be a JSON object")
	try:
		encoded = json.dumps(
			payload,
			ensure_ascii=False,
			separators=(",", ":"),
		).encode("utf-8")
	except (TypeError, ValueError) as exc:
		raise ValueError("WhatsApp webhook payload must be JSON serializable") from exc
	if len(encoded) > _MAX_WEBHOOK_BODY_BYTES:
		raise ValueError(
			f"WhatsApp webhook payload is {len(encoded)} bytes; "
			f"maximum is {_MAX_WEBHOOK_BODY_BYTES}"
		)
	return payload


def _verify_webhook_hmac(
	hmac_signature: str | None,
	app_secret: str | None,
	raw_body: bytes | None,
) -> None:
	if not app_secret:
		return
	if not hmac_signature:
		raise ValueError(
			"WhatsApp webhook requires X-Hub-Signature-256 when app_secret is set"
		)
	if raw_body is None:
		raise ValueError("WhatsApp webhook raw_body is required for HMAC verification")
	if not isinstance(raw_body, (bytes, bytearray)):
		raise ValueError("WhatsApp webhook raw_body must be bytes")
	if len(raw_body) > _MAX_WEBHOOK_BODY_BYTES:
		raise ValueError(
			f"WhatsApp webhook raw_body is {len(raw_body)} bytes; "
			f"maximum is {_MAX_WEBHOOK_BODY_BYTES}"
		)

	import hashlib
	import hmac as _hmac_lib

	signature = _bounded_text(
		hmac_signature,
		"hmac_signature",
		_MAX_SIGNATURE_CHARS,
	)
	expected = "sha256=" + _hmac_lib.new(
		app_secret.encode(),
		bytes(raw_body),
		hashlib.sha256,
	).hexdigest()
	if not _hmac_lib.compare_digest(expected, signature):
		raise ValueError("WhatsApp webhook HMAC verification failed; request rejected")


def _parse_webhook_timestamp(value: Any) -> datetime | None:
	if value in (None, ""):
		return None
	if isinstance(value, str):
		raw_value = value.strip()
		if not raw_value:
			return None
		if not raw_value.isdigit():
			raise ValueError("webhook timestamp must be a unix epoch integer")
		timestamp = int(raw_value)
	elif isinstance(value, int) and not isinstance(value, bool):
		timestamp = value
	else:
		raise ValueError("webhook timestamp must be a unix epoch integer")
	if timestamp < 0 or timestamp > _MAX_WEBHOOK_TIMESTAMP:
		raise ValueError("webhook timestamp is outside the supported range")
	return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _normalise_wa_message_type(value: Any) -> str:
	raw_value = _bounded_text(
		value or "text",
		"message_type",
		_MAX_STATUS_CHARS,
		required=False,
	)
	message_type = (raw_value or "text").upper()
	if message_type not in _SUPPORTED_INBOUND_MESSAGE_TYPES:
		return "UNKNOWN"
	return message_type


def _extract_webhook_items(payload: dict[str, Any], item_key: str) -> list[dict[str, Any]]:
	items: list[Any] = []
	entries = _bounded_webhook_sequence(
		payload.get("entry", []),
		"payload.entry",
		_MAX_WEBHOOK_ENTRIES,
	)
	for entry in entries:
		if not isinstance(entry, dict):
			raise ValueError("payload.entry[] must be an object")
		changes = _bounded_webhook_sequence(
			entry.get("changes", []),
			"payload.entry[].changes",
			_MAX_WEBHOOK_CHANGES,
		)
		for change in changes:
			if not isinstance(change, dict):
				raise ValueError("payload.entry[].changes[] must be an object")
			value = change.get("value", {})
			if not isinstance(value, dict):
				raise ValueError("payload.entry[].changes[].value must be an object")
			batch = _bounded_webhook_sequence(
				value.get(item_key, []),
				f"payload.entry[].changes[].value.{item_key}",
				_MAX_WEBHOOK_ITEMS,
			)
			if len(items) + len(batch) > _MAX_WEBHOOK_ITEMS:
				raise ValueError(
					f"payload.{item_key} contains more than "
					f"{_MAX_WEBHOOK_ITEMS} items"
				)
			items.extend(batch)

	if not items and item_key in payload:
		items = _bounded_webhook_sequence(
			payload[item_key],
			f"payload.{item_key}",
			_MAX_WEBHOOK_ITEMS,
		)

	normalised_items: list[dict[str, Any]] = []
	for index, item in enumerate(items):
		if not isinstance(item, dict):
			raise ValueError(f"payload.{item_key}[{index}] must be an object")
		normalised_items.append(item)
	return normalised_items


def _normalise_webhook_status(status: dict[str, Any]) -> dict[str, Any]:
	return {
		"id": _bounded_text(
			status.get("id"),
			"status.id",
			_MAX_WA_MESSAGE_ID_CHARS,
			required=False,
		),
		"status": _bounded_text(
			status.get("status"),
			"status.status",
			_MAX_STATUS_CHARS,
			required=False,
		).lower(),
		"timestamp": _parse_webhook_timestamp(status.get("timestamp")),
	}


def _extract_webhook_message_body(
	message: dict[str, Any],
	message_type: str,
) -> str:
	if message_type == "TEXT":
		text_payload = message.get("text") or {}
		if not isinstance(text_payload, dict):
			raise ValueError("message.text must be an object")
		return _bounded_text(
			text_payload.get("body"),
			"message.text.body",
			_MAX_TEXT_BODY_CHARS,
			required=False,
			strip=False,
		)
	if message_type in _MEDIA_MESSAGE_TYPES:
		media_key = message_type.lower()
		media_payload = message.get(media_key) or {}
		if not isinstance(media_payload, dict):
			raise ValueError(f"message.{media_key} must be an object")
		return _bounded_text(
			media_payload.get("caption"),
			f"message.{media_key}.caption",
			_MAX_TEXT_BODY_CHARS,
			required=False,
			strip=False,
		)
	return ""


def _normalise_webhook_message(message: dict[str, Any]) -> dict[str, str]:
	message_type = _normalise_wa_message_type(message.get("type"))
	return {
		"from": _bounded_text(
			message.get("from"),
			"message.from",
			_MAX_PHONE_CHARS,
			required=False,
		),
		"id": _bounded_text(
			message.get("id"),
			"message.id",
			_MAX_WA_MESSAGE_ID_CHARS,
			required=False,
		),
		"type": message_type,
		"body": _extract_webhook_message_body(message, message_type),
	}


# ---------------------------------------------------------------------------
# WhatsAppService
# ---------------------------------------------------------------------------

class WhatsAppService:
	"""Stateless service for the WhatsApp Business API domain.

	All methods are @staticmethod — pass the SQLAlchemy session explicitly so
	transaction boundaries remain with the caller.
	"""

	# ------------------------------------------------------------------
	# 1. send_template_message
	# ------------------------------------------------------------------

	@staticmethod
	def send_template_message(
		to_phone: str,
		template_name: str,
		params: dict[str, Any],
		tenant_id: str,
		session: Any,
		*,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
	) -> Any:
		"""Create an outbound TEMPLATE message outbox record.

		Loads the named template for the tenant, asserts it is APPROVED, then
		creates a WhatsAppMessage with status=QUEUED and direction=OUTBOUND.
		Emits WhatsAppMessageSentEvent.

		The delivery worker picks this up via get_pending_outbound() and calls
		the WhatsApp Business API; the HTTP layer is outside this service.

		Args:
			to_phone:         E.164 destination number e.g. '+254712345678'.
			template_name:    Name of an APPROVED WhatsAppTemplate for this tenant.
			params:           Variable substitution map for the template components.
			tenant_id:        Tenant scoping UUID string.
			session:          Active SQLAlchemy session.
			linked_module:    Optional source module tag e.g. 'workflow'.
			linked_record_id: Optional UUID of the triggering record.

		Returns:
			Persisted WhatsAppMessage (flushed, id available).

		Raises:
			WhatsAppTemplateNotFoundError: Template not found or not APPROVED.
		"""
		from pgappforge.plugins.erp.platform.whatsapp.models import (
			WhatsAppTemplate, WhatsAppMessage,
		)
		from pgappforge.plugins.erp.platform.whatsapp.events import WhatsAppMessageSentEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		template = session.execute(
			sa.select(WhatsAppTemplate).where(
				WhatsAppTemplate.tenant_id == tenant_id,
				WhatsAppTemplate.template_name == template_name,
			)
		).scalar_one_or_none()

		if template is None:
			raise WhatsAppTemplateNotFoundError(
				f"WhatsApp template {template_name!r} not found for tenant {tenant_id!r}"
			)
		if template.status != "APPROVED":
			raise WhatsAppTemplateNotFoundError(
				f"WhatsApp template {template_name!r} is {template.status!r}; "
				"only APPROVED templates can be sent"
			)

		msg = WhatsAppMessage(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			to_phone=to_phone,
			direction="OUTBOUND",
			message_type="TEMPLATE",
			template_id=template.id,
			template_params=params,
			status="QUEUED",
			linked_module=linked_module,
			linked_record_id=linked_record_id,
		)
		session.add(msg)
		session.flush()

		try:
			emit_event(
				WhatsAppMessageSentEvent(
					aggregate_id=msg.id,
					aggregate_type="WhatsAppMessage",
					tenant_id=tenant_id,
					message_id=msg.id,
					to_phone=to_phone,
					template_name=template_name,
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning(
				"WhatsAppService.send_template_message: event emit failed: %s", exc
			)

		log.info(
			"WhatsAppService.send_template_message: msg=%s template=%r to=%s tenant=%s",
			msg.id, template_name, to_phone, tenant_id,
		)
		return msg

	# ------------------------------------------------------------------
	# 2. send_text_message
	# ------------------------------------------------------------------

	@staticmethod
	def send_text_message(
		to_phone: str,
		body: str,
		tenant_id: str,
		session: Any,
		*,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
	) -> Any:
		"""Create an outbound TEXT message outbox record.

		Unlike template messages, text messages can only be sent within the
		24-hour customer service window (WhatsApp policy).  This service does
		not enforce the window — the delivery worker should check it.

		Args:
			to_phone:         E.164 destination number.
			body:             Plain text message body (max 4096 chars per WA spec).
			tenant_id:        Tenant scoping UUID string.
			session:          Active SQLAlchemy session.
			linked_module:    Optional source module tag.
			linked_record_id: Optional UUID of the triggering record.

		Returns:
			Persisted WhatsAppMessage with status=QUEUED, direction=OUTBOUND.
		"""
		to_phone = _bounded_text(to_phone, "to_phone", _MAX_PHONE_CHARS)
		body = _bounded_text(
			body,
			"body",
			_MAX_TEXT_BODY_CHARS,
			strip=False,
		)

		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppMessage
		from pgappforge.plugins.erp.platform.whatsapp.events import WhatsAppMessageSentEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		msg = WhatsAppMessage(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			to_phone=to_phone,
			direction="OUTBOUND",
			message_type="TEXT",
			body=body,
			status="QUEUED",
			linked_module=linked_module,
			linked_record_id=linked_record_id,
		)
		session.add(msg)
		session.flush()

		try:
			emit_event(
				WhatsAppMessageSentEvent(
					aggregate_id=msg.id,
					aggregate_type="WhatsAppMessage",
					tenant_id=tenant_id,
					message_id=msg.id,
					to_phone=to_phone,
					template_name="",  # no template for TEXT
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning(
				"WhatsAppService.send_text_message: event emit failed: %s", exc
			)

		log.info(
			"WhatsAppService.send_text_message: msg=%s to=%s tenant=%s",
			msg.id, to_phone, tenant_id,
		)
		return msg

	# ------------------------------------------------------------------
	# 3. process_inbound
	# ------------------------------------------------------------------

	@staticmethod
	def process_inbound(
		from_phone: str,
		body: str,
		wa_message_id: str,
		tenant_id: str,
		session: Any,
		*,
		message_type: str = "TEXT",
	) -> Any:
		"""Process an inbound message received from a WhatsApp user.

		Side effects:
		  - Finds or creates a WhatsAppConversation for from_phone.
		  - Increments conversation.message_count, sets last_message_at=now().
		  - Emits WhatsAppConversationStartedEvent if conversation is new.
		  - Creates a WhatsAppMessage with direction=INBOUND, status=DELIVERED.
		  - Emits WhatsAppInboundMessageEvent.

		Args:
			from_phone:    E.164 sender number.
			body:          Text body or media caption.
			wa_message_id: WhatsApp's own message ID (for dedup).
			tenant_id:     Tenant scoping UUID string.
			session:       Active SQLAlchemy session.
			message_type:  WhatsApp message type (TEXT, IMAGE, DOCUMENT, etc.).

		Returns:
			Persisted WhatsAppMessage (direction=INBOUND).
		"""
		from_phone = _bounded_text(from_phone, "from_phone", _MAX_PHONE_CHARS)
		body = _bounded_text(
			body,
			"body",
			_MAX_TEXT_BODY_CHARS,
			required=False,
			strip=False,
		)
		wa_message_id = _bounded_text(
			wa_message_id,
			"wa_message_id",
			_MAX_WA_MESSAGE_ID_CHARS,
		)
		message_type = _normalise_wa_message_type(message_type)

		from pgappforge.plugins.erp.platform.whatsapp.models import (
			WhatsAppConversation, WhatsAppMessage,
		)
		from pgappforge.plugins.erp.platform.whatsapp.events import (
			WhatsAppInboundMessageEvent,
			WhatsAppConversationStartedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		now = _now()
		is_new_conversation = False

		# Find or create conversation
		conv = session.execute(
			sa.select(WhatsAppConversation).where(
				WhatsAppConversation.tenant_id == tenant_id,
				WhatsAppConversation.phone_number == from_phone,
			)
		).scalar_one_or_none()

		if conv is None:
			conv = WhatsAppConversation(
				id=str(uuid.uuid4()),
				tenant_id=tenant_id,
				phone_number=from_phone,
				status="ACTIVE",
				message_count=0,
				last_message_at=now,
			)
			session.add(conv)
			session.flush()
			is_new_conversation = True

		conv.message_count = (conv.message_count or 0) + 1
		conv.last_message_at = now

		# Create inbound message record
		msg = WhatsAppMessage(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			to_phone="",        # inbound — platform number; not stored here
			from_phone=from_phone,
			direction="INBOUND",
			message_type=message_type,
			body=body,
			wa_message_id=wa_message_id,
			status="DELIVERED",  # inbound messages are by definition delivered
			delivered_at=now,
		)
		session.add(msg)
		session.flush()

		# Emit conversation started event if brand new
		if is_new_conversation:
			try:
				emit_event(
					WhatsAppConversationStartedEvent(
						aggregate_id=conv.id,
						aggregate_type="WhatsAppConversation",
						tenant_id=tenant_id,
						conversation_id=conv.id,
						from_phone=from_phone,
					),
					session,
				)
			except Exception as exc:  # pragma: no cover
				log.warning(
					"WhatsAppService.process_inbound: conversation event emit failed: %s", exc
				)

		# Emit inbound message event
		try:
			emit_event(
				WhatsAppInboundMessageEvent(
					aggregate_id=msg.id,
					aggregate_type="WhatsAppMessage",
					tenant_id=tenant_id,
					from_phone=from_phone,
					body=body,
					message_id=msg.id,
				),
				session,
			)
		except Exception as exc:  # pragma: no cover
			log.warning(
				"WhatsAppService.process_inbound: inbound event emit failed: %s", exc
			)

		log.info(
			"WhatsAppService.process_inbound: msg=%s from=%s tenant=%s new_conv=%s",
			msg.id, from_phone, tenant_id, is_new_conversation,
		)
		return msg

	# ------------------------------------------------------------------
	# 4. update_delivery_status
	# ------------------------------------------------------------------

	@staticmethod
	def update_delivery_status(
		wa_message_id: str,
		status: str,
		session: Any,
		*,
		delivered_at: datetime | None = None,
		read_at: datetime | None = None,
	) -> Any:
		"""Update delivery status of an outbound message from a webhook callback.

		Finds the WhatsAppMessage by wa_message_id (WhatsApp's ID), updates
		status and timestamp fields, and emits the appropriate event.

		Args:
			wa_message_id: WhatsApp's own message ID from the webhook.
			status:        New status: SENT | DELIVERED | READ | FAILED.
			session:       Active SQLAlchemy session.
			delivered_at:  Timestamp for DELIVERED transitions.
			read_at:       Timestamp for READ transitions.

		Returns:
			Updated WhatsAppMessage instance.

		Raises:
			WhatsAppMessageNotFoundError: No message found with this wa_message_id.
		"""
		wa_message_id = _bounded_text(
			wa_message_id,
			"wa_message_id",
			_MAX_WA_MESSAGE_ID_CHARS,
		)
		status = _bounded_text(status, "status", _MAX_STATUS_CHARS).upper()
		if status not in _VALID_DELIVERY_STATUSES:
			raise WhatsAppStateError(
				f"Unsupported WhatsApp delivery status {status!r}"
			)

		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppMessage
		from pgappforge.plugins.erp.platform.whatsapp.events import (
			WhatsAppMessageDeliveredEvent,
			WhatsAppMessageReadEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		msg = session.execute(
			sa.select(WhatsAppMessage).where(
				WhatsAppMessage.wa_message_id == wa_message_id,
			)
		).scalar_one_or_none()

		if msg is None:
			raise WhatsAppMessageNotFoundError(
				f"WhatsApp message with wa_message_id={wa_message_id!r} not found"
			)

		now = _now()
		msg.status = status

		if status == "DELIVERED":
			msg.delivered_at = delivered_at or now
			try:
				emit_event(
					WhatsAppMessageDeliveredEvent(
						aggregate_id=msg.id,
						aggregate_type="WhatsAppMessage",
						tenant_id=msg.tenant_id,
						message_id=msg.id,
						to_phone=msg.to_phone,
						delivered_at=(msg.delivered_at).isoformat(),
					),
					session,
				)
			except Exception as exc:  # pragma: no cover
				log.warning(
					"WhatsAppService.update_delivery_status: delivered event emit failed: %s", exc
				)

		elif status == "READ":
			msg.read_at = read_at or now
			if msg.delivered_at is None:
				msg.delivered_at = msg.read_at
			try:
				emit_event(
					WhatsAppMessageReadEvent(
						aggregate_id=msg.id,
						aggregate_type="WhatsAppMessage",
						tenant_id=msg.tenant_id,
						message_id=msg.id,
						to_phone=msg.to_phone,
						read_at=(msg.read_at).isoformat(),
					),
					session,
				)
			except Exception as exc:  # pragma: no cover
				log.warning(
					"WhatsAppService.update_delivery_status: read event emit failed: %s", exc
				)

		elif status == "SENT":
			msg.sent_at = now

		session.flush()

		log.debug(
			"WhatsAppService.update_delivery_status: msg=%s wa_id=%s status=%s",
			msg.id, wa_message_id, status,
		)
		return msg

	# ------------------------------------------------------------------
	# 5. process_webhook
	# ------------------------------------------------------------------

	@staticmethod
	def process_webhook(
		event_type: str,
		payload: dict[str, Any],
		tenant_id: str,
		session: Any,
		*,
		hmac_signature: str | None = None,
		app_secret: str | None = None,
		raw_body: bytes | None = None,
	) -> dict[str, Any]:
		"""Persist and route a raw webhook payload from WhatsApp.

		Flow:
		  0. If app_secret is configured, require raw_body and verify
		     X-Hub-Signature-256 before any processing.
		  1. Validate webhook shape, size, item counts, IDs, timestamps, and
		     text/caption lengths before persistence.
		  2. Append a WhatsAppWebhookLog row (processed=False).
		  3. Route by event_type:
		       messages.statuses  → update_delivery_status for each status entry
		       messages.inbound   → process_inbound for each message entry
		  4. Mark log row processed=True.
		  5. Return {processed: True, action: "..."}.

		On any routing error the log row is left with processed=False and the
		error is stored in log.error — caller can retry.

		Args:
			event_type:     Logical type derived by the webhook endpoint controller.
			payload:        Parsed JSON from the WhatsApp webhook POST body.
			tenant_id:      Tenant scoping UUID string.
			session:        Active SQLAlchemy session.
			hmac_signature: Value of X-Hub-Signature-256 header (optional).
			app_secret:     WhatsApp app secret for HMAC verification (optional).
			raw_body:       Raw request bytes for HMAC computation (optional).

		Returns:
			dict with keys: processed (bool), action (str), detail (str|None).
		"""
		_verify_webhook_hmac(hmac_signature, app_secret, raw_body)
		event_type = _bounded_text(
			event_type,
			"event_type",
			_MAX_EVENT_TYPE_CHARS,
		)
		payload = _validate_webhook_payload(payload)

		status_updates: list[dict[str, Any]] = []
		inbound_messages: list[dict[str, str]] = []
		if event_type == "messages.statuses":
			status_updates = [
				_normalise_webhook_status(status)
				for status in _extract_statuses(payload)
			]
		elif event_type == "messages.inbound":
			inbound_messages = [
				_normalise_webhook_message(message)
				for message in _extract_messages(payload)
			]

		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppWebhookLog

		log_row = WhatsAppWebhookLog(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			event_type=event_type,
			payload=payload,
			processed=False,
		)
		session.add(log_row)
		session.flush()

		action = "ignored"
		detail: str | None = None

		try:
			if event_type == "messages.statuses":
				# WhatsApp Cloud API format:
				# payload.entry[].changes[].value.statuses[]
				for s in status_updates:
					wa_message_id = s["id"]
					new_status = _map_wa_status(s["status"])
					ts = s["timestamp"]
					if not wa_message_id or not new_status:
						continue
					try:
						WhatsAppService.update_delivery_status(
							wa_message_id=wa_message_id,
							status=new_status,
							session=session,
							delivered_at=ts if new_status == "DELIVERED" else None,
							read_at=ts if new_status == "READ" else None,
						)
					except WhatsAppMessageNotFoundError:
						log.debug(
							"process_webhook: wa_message_id=%s not found — may be "
							"from a different channel; skipping",
							wa_message_id,
						)
				action = "statuses_updated"
				detail = f"processed {len(status_updates)} status update(s)"

			elif event_type == "messages.inbound":
				# WhatsApp Cloud API format:
				# payload.entry[].changes[].value.messages[]
				for m in inbound_messages:
					from_phone = m["from"]
					wa_msg_id = m["id"]
					msg_type = m["type"]
					body = m["body"]
					if from_phone and wa_msg_id:
						WhatsAppService.process_inbound(
							from_phone=from_phone,
							body=body,
							wa_message_id=wa_msg_id,
							tenant_id=tenant_id,
							session=session,
							message_type=msg_type,
						)
				action = "inbound_processed"
				detail = f"processed {len(inbound_messages)} inbound message(s)"

			else:
				action = "ignored"
				detail = f"unhandled event_type={event_type!r}"
				log.debug("WhatsAppService.process_webhook: %s", detail)

		except Exception as exc:
			log_row.error = str(exc)
			session.flush()
			log.error(
				"WhatsAppService.process_webhook: error processing %s: %s",
				event_type, exc,
			)
			return {"processed": False, "action": "error", "detail": str(exc)}

		log_row.processed = True
		session.flush()

		log.info(
			"WhatsAppService.process_webhook: event_type=%s action=%s tenant=%s",
			event_type, action, tenant_id,
		)
		return {"processed": True, "action": action, "detail": detail}

	# ------------------------------------------------------------------
	# 6. get_conversation_history
	# ------------------------------------------------------------------

	@staticmethod
	def get_conversation_history(
		phone_number: str,
		tenant_id: str,
		session: Any,
		*,
		limit: int = 50,
	) -> list[Any]:
		"""Return message history for a phone number, newest first.

		Returns both INBOUND and OUTBOUND messages involving this number,
		ordered by sent_at DESC (NULLS LAST for QUEUED outbound messages).

		Args:
			phone_number: E.164 number.
			tenant_id:    Tenant scoping UUID string.
			session:      Active SQLAlchemy session.
			limit:        Maximum number of messages to return (default 50).

		Returns:
			List of WhatsAppMessage ordered by sent_at DESC.
		"""
		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppMessage

		stmt = (
			sa.select(WhatsAppMessage)
			.where(
				WhatsAppMessage.tenant_id == tenant_id,
				sa.or_(
					WhatsAppMessage.to_phone == phone_number,
					WhatsAppMessage.from_phone == phone_number,
				),
			)
			.order_by(WhatsAppMessage.sent_at.desc().nullslast())
			.limit(limit)
		)
		return list(session.execute(stmt).scalars().all())

	# ------------------------------------------------------------------
	# 7. get_pending_outbound
	# ------------------------------------------------------------------

	@staticmethod
	def get_pending_outbound(
		tenant_id: str,
		session: Any,
	) -> list[Any]:
		"""Return QUEUED outbound messages ready for delivery.

		Used by the delivery worker to pick up messages and call the WhatsApp
		Business API.  Ordered by created_at ASC (FIFO).

		Args:
			tenant_id: Tenant scoping UUID string.
			session:   Active SQLAlchemy session.

		Returns:
			List of WhatsAppMessage with status=QUEUED, direction=OUTBOUND.
		"""
		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppMessage

		stmt = (
			sa.select(WhatsAppMessage)
			.where(
				WhatsAppMessage.tenant_id == tenant_id,
				WhatsAppMessage.direction == "OUTBOUND",
				WhatsAppMessage.status == "QUEUED",
			)
			.order_by(WhatsAppMessage.created_at.asc())
		)
		return list(session.execute(stmt).scalars().all())

	# ------------------------------------------------------------------
	# 8. dispatch_pending
	# ------------------------------------------------------------------

	def dispatch_pending(self, tenant_id: str, session: Any) -> dict:
		"""Dispatch QUEUED outbound WhatsApp messages via WhatsApp Cloud API.

		Requires config: WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN.
		Processes up to 50 messages per call. Marks SENT on success, FAILED on error.
		"""
		try:
			from flask import current_app
			phone_number_id = current_app.config.get("WHATSAPP_PHONE_NUMBER_ID", "")
			token = current_app.config.get("WHATSAPP_ACCESS_TOKEN", "")
		except (RuntimeError, AttributeError):
			return {"dispatched": 0, "reason": "no_flask_context"}
		if not phone_number_id or not token:
			return {
				"dispatched": 0,
				"reason": "WHATSAPP_PHONE_NUMBER_ID or WHATSAPP_ACCESS_TOKEN not set",
			}
		import requests as _req
		from pgappforge.plugins.erp.platform.whatsapp.models import WhatsAppTemplate
		pending = self.get_pending_outbound(tenant_id, session)[:50]
		dispatched = 0
		errors: list[dict] = []
		for msg in pending:
			try:
				if msg.message_type == "TEMPLATE" and msg.template_id:
					tmpl = session.execute(
						sa.select(WhatsAppTemplate).where(WhatsAppTemplate.id == msg.template_id)
					).scalar_one_or_none()
					payload: dict = {
						"messaging_product": "whatsapp",
						"recipient_type": "individual",
						"to": msg.to_phone,
						"type": "template",
						"template": {
							"name": tmpl.template_name if tmpl else "unknown",
							"language": {"code": "en"},
							"components": [],
						},
					}
					if msg.template_params:
						params = [
							{"type": "text", "text": str(v)}
							for v in (
								msg.template_params.values()
								if isinstance(msg.template_params, dict)
								else []
							)
						]
						if params:
							payload["template"]["components"] = [{"type": "body", "parameters": params}]
				else:
					payload = {
						"messaging_product": "whatsapp",
						"recipient_type": "individual",
						"to": msg.to_phone,
						"type": "text",
						"text": {"body": msg.body or ""},
					}
				resp = _req.post(
					f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
					headers={
						"Authorization": f"Bearer {token}",
						"Content-Type": "application/json",
					},
					json=payload,
					timeout=10,
				)
				if resp.ok:
					wa_id = resp.json().get("messages", [{}])[0].get("id", "")
					msg.wa_message_id = wa_id
					msg.status = "SENT"
					session.flush()
					dispatched += 1
				else:
					errors.append({"to": msg.to_phone, "error": resp.text[:200]})
					msg.status = "FAILED"
					msg.error_code = str(resp.status_code)
					session.flush()
			except Exception as exc:
				log.warning("dispatch_pending: failed for msg %s: %s", msg.id, exc)
				errors.append({"to": msg.to_phone, "error": str(exc)})
		return {"dispatched": dispatched, "errors": errors, "total_pending": len(pending)}

	# ------------------------------------------------------------------
	# 9. get_analytics
	# ------------------------------------------------------------------

	@staticmethod
	def get_analytics(
		tenant_id: str,
		session: Any,
		*,
		from_date: datetime | None = None,
	) -> dict[str, Any]:
		"""Return messaging analytics for a tenant.

		Args:
			tenant_id:  Tenant scoping UUID string.
			session:    Active SQLAlchemy session.
			from_date:  Optional lower bound for sent_at / created_at filter.

		Returns:
			dict with keys:
			  messages_sent         — OUTBOUND messages (all statuses except QUEUED)
			  messages_delivered    — OUTBOUND messages in DELIVERED or READ status
			  delivery_rate_pct     — messages_delivered / messages_sent * 100 (float, 1dp)
			  messages_read         — OUTBOUND messages in READ status
			  read_rate_pct         — messages_read / messages_sent * 100 (float, 1dp)
			  active_conversations  — WhatsAppConversation with status=ACTIVE
			  inbound_count         — INBOUND messages received
		"""
		from pgappforge.plugins.erp.platform.whatsapp.models import (
			WhatsAppMessage, WhatsAppConversation,
		)

		# Base filter helpers
		def _outbound_filter(*extra):
			clauses = [
				WhatsAppMessage.tenant_id == tenant_id,
				WhatsAppMessage.direction == "OUTBOUND",
				WhatsAppMessage.status.notin_(["QUEUED"]),
			]
			if from_date is not None:
				clauses.append(WhatsAppMessage.created_at >= from_date)
			clauses.extend(extra)
			return clauses

		def _inbound_filter():
			clauses = [
				WhatsAppMessage.tenant_id == tenant_id,
				WhatsAppMessage.direction == "INBOUND",
			]
			if from_date is not None:
				clauses.append(WhatsAppMessage.created_at >= from_date)
			return clauses

		messages_sent: int = session.execute(
			sa.select(sa.func.count()).select_from(WhatsAppMessage).where(
				*_outbound_filter()
			)
		).scalar_one() or 0

		messages_delivered: int = session.execute(
			sa.select(sa.func.count()).select_from(WhatsAppMessage).where(
				*_outbound_filter(
					WhatsAppMessage.status.in_(["DELIVERED", "READ"])
				)
			)
		).scalar_one() or 0

		messages_read: int = session.execute(
			sa.select(sa.func.count()).select_from(WhatsAppMessage).where(
				*_outbound_filter(
					WhatsAppMessage.status == "READ"
				)
			)
		).scalar_one() or 0

		inbound_count: int = session.execute(
			sa.select(sa.func.count()).select_from(WhatsAppMessage).where(
				*_inbound_filter()
			)
		).scalar_one() or 0

		active_conversations: int = session.execute(
			sa.select(sa.func.count()).select_from(WhatsAppConversation).where(
				WhatsAppConversation.tenant_id == tenant_id,
				WhatsAppConversation.status == "ACTIVE",
			)
		).scalar_one() or 0

		def _rate(numerator: int, denominator: int) -> float:
			if denominator == 0:
				return 0.0
			return round(numerator / denominator * 100, 1)

		return {
			"messages_sent": messages_sent,
			"messages_delivered": messages_delivered,
			"delivery_rate_pct": _rate(messages_delivered, messages_sent),
			"messages_read": messages_read,
			"read_rate_pct": _rate(messages_read, messages_sent),
			"active_conversations": active_conversations,
			"inbound_count": inbound_count,
		}


# ---------------------------------------------------------------------------
# Payload extraction helpers (WhatsApp Cloud API format)
# ---------------------------------------------------------------------------

def _extract_statuses(payload: dict[str, Any]) -> list[dict[str, Any]]:
	"""Pull statuses[] from a WhatsApp Cloud API webhook payload."""
	return _extract_webhook_items(payload, "statuses")


def _extract_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
	"""Pull messages[] from a WhatsApp Cloud API webhook payload."""
	return _extract_webhook_items(payload, "messages")


def _map_wa_status(wa_status: str) -> str:
	"""Map WhatsApp API status string to internal status enum value."""
	mapping = {
		"sent": "SENT",
		"delivered": "DELIVERED",
		"read": "READ",
		"failed": "FAILED",
	}
	return mapping.get(wa_status.lower(), "")


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

_bpm_actions_registered = False


def _register_bpm_actions() -> None:
	"""Register WhatsApp service operations with the BPMActionRegistry.

	Called at module import time; guarded by try/except so missing workflow
	plugin never blocks startup.
	"""
	global _bpm_actions_registered
	if _bpm_actions_registered:
		return
	_bpm_actions_registered = True

	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"platform.whatsapp.send_template",
		"Send WhatsApp template message from workflow",
	)
	def _bpm_send_template(
		record_ctx: dict,
		session: Any,
		to_phone: str = "",
		template_name: str = "",
		params: dict | None = None,
		linked_module: str | None = None,
		linked_record_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		if not to_phone:
			return {"status": "error", "message": "to_phone is required"}
		if not template_name:
			return {"status": "error", "message": "template_name is required"}
		try:
			msg = WhatsAppService.send_template_message(
				to_phone=to_phone,
				template_name=template_name,
				params=params or {},
				tenant_id=tenant_id,
				session=session,
				linked_module=linked_module,
				linked_record_id=linked_record_id,
			)
			return {"status": "ok", "message_id": msg.id, "wa_status": msg.status}
		except WhatsAppServiceError as exc:
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"platform.whatsapp.send_text",
		"Send WhatsApp text message from workflow",
	)
	def _bpm_send_text(
		record_ctx: dict,
		session: Any,
		to_phone: str = "",
		body: str = "",
		linked_module: str | None = None,
		linked_record_id: str | None = None,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		if not to_phone:
			return {"status": "error", "message": "to_phone is required"}
		if not body:
			return {"status": "error", "message": "body is required"}
		try:
			msg = WhatsAppService.send_text_message(
				to_phone=to_phone,
				body=body,
				tenant_id=tenant_id,
				session=session,
				linked_module=linked_module,
				linked_record_id=linked_record_id,
			)
			return {"status": "ok", "message_id": msg.id, "wa_status": msg.status}
		except WhatsAppServiceError as exc:
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"WhatsAppService",
	"WhatsAppServiceError",
	"WhatsAppTemplateNotFoundError",
	"WhatsAppMessageNotFoundError",
	"WhatsAppStateError",
]
