"""
statemachine_mixin.py - Advanced State Machine System for PgAppForge

Provides a comprehensive state machine implementation with workflow management
for PgAppForge models. Event-driven architecture with full audit trail,
role-based access control, async notifications, and workflow visualization.

Core Components:
- StateMachineMixin: Adds state machine functionality to SQLAlchemy models
- StateChangeHistory: Audit table for all state transitions
- State: State descriptor with metadata and validators
- Transition: Transition descriptor with conditions and callbacks
- Workflow: Orchestrates states and transitions with validation
- NotificationManager: Email, SMS (Twilio-optional), webhook, blinker signals
- HistoryManager: Audit trail CRUD with cleanup utilities

Requirements:
- Python 3.10+
- PgAppForge
- SQLAlchemy 2.x
- blinker (bundled with Flask)

Optional:
- aiohttp (webhook notifications)
- flask-mail (email notifications)
- twilio (SMS notifications)
- graphviz (diagram export)
- pyyaml (YAML export)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import textwrap
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, TYPE_CHECKING

from blinker import signal
from flask import current_app, flash, g, request, session
from pgappforge import Model
from pgappforge.models.decorators import renders
from sqlalchemy import (
	Boolean,
	DateTime,
	ForeignKey,
	Integer,
	String,
	Text,
	event,
	func,
	inspect,
	select,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, Session

# SQLAlchemy 2.x Mapped types with 1.x fallback
try:
	from sqlalchemy.orm import Mapped, mapped_column
	_SA2 = True
except ImportError:
	_SA2 = False

# JSONB for PostgreSQL, fallback to JSON-as-Text via TypeDecorator for others
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
	_HAS_JSONB = True
except ImportError:
	_HAS_JSONB = False

from sqlalchemy import JSON as _JSON
from sqlalchemy import Column

if TYPE_CHECKING:
	from pgappforge.security.sqla.models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
JsonDict = dict[str, Any]
StateCallback = Callable[[Any, "User"], None]
StateValidator = Callable[[Any, "User"], bool]


# ---------------------------------------------------------------------------
# Portable JSON column helper
# ---------------------------------------------------------------------------
def _json_column(nullable: bool = True, default: Any = None):
	"""Return JSONB on PostgreSQL, JSON elsewhere."""
	col_type = _JSONB if _HAS_JSONB else _JSON
	return Column(col_type, nullable=nullable, default=default)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class State:
	"""Represents a state in the state machine with metadata and validation."""

	def __init__(
		self,
		name: str,
		description: str = "",
		metadata: JsonDict | None = None,
		is_initial: bool = False,
		is_final: bool = False,
		is_restricted: bool = False,
		required_roles: list[str] | None = None,
		validators: list[StateValidator] | None = None,
		timeout: int | None = None,
		retry_count: int | None = None,
		custom_handlers: dict[str, StateCallback] | None = None,
		auto_transitions: list[str] | None = None,
		error_state: str | None = None,
		ui_color: str | None = None,
		max_retries: int = 3,
		ttl: int | None = None,
	) -> None:
		if timeout and not error_state:
			raise ValueError("error_state is required when timeout is specified")

		self.name = name
		self.description = description
		self.metadata: JsonDict = metadata or {}
		self.is_initial = is_initial
		self.is_final = is_final
		self.is_restricted = is_restricted
		self.required_roles: list[str] = required_roles or []
		self.validators: list[StateValidator] = validators or []
		self.timeout = timeout
		self.retry_count = retry_count
		self.custom_handlers: dict[str, StateCallback] = custom_handlers or {}
		self.auto_transitions: list[str] = auto_transitions or []
		self.error_state = error_state
		self.ui_color = ui_color or "#CCCCCC"
		self.max_retries = max_retries
		self.ttl = ttl

	def __repr__(self) -> str:
		return f"<State {self.name}>"

	def validate(self, instance: Any, user: User) -> bool:
		"""Run all validators; returns False on any failure or exception."""
		try:
			return all(v(instance, user) for v in self.validators)
		except Exception as exc:
			logger.error("State validation error in %s: %s", self.name, exc)
			return False


# ---------------------------------------------------------------------------
# Transition
# ---------------------------------------------------------------------------
class Transition:
	"""Represents a permitted state transition with guards and callbacks."""

	def __init__(
		self,
		trigger: str,
		source: str | list[str],
		dest: str,
		conditions: list[StateValidator] | None = None,
		before: list[StateCallback] | None = None,
		after: list[StateCallback] | None = None,
		priority: int = 0,
		required_roles: list[str] | None = None,
		auto_trigger: bool = False,
		validation_message: str | None = None,
		side_effects: list[StateCallback] | None = None,
		retry_policy: JsonDict | None = None,
		timeout: int | None = None,
		error_state: str | None = None,
		rollback: bool = True,
		async_dispatch: bool = False,
		batch_size: int | None = None,
	) -> None:
		if timeout and not error_state:
			raise ValueError("error_state is required when timeout is specified")

		self.trigger = trigger
		self.source: list[str] = source if isinstance(source, list) else [source]
		self.dest = dest
		self.conditions: list[StateValidator] = conditions or []
		self.before: list[StateCallback] = before or []
		self.after: list[StateCallback] = after or []
		self.priority = priority
		self.required_roles: list[str] = required_roles or []
		self.auto_trigger = auto_trigger
		self.validation_message = validation_message
		self.side_effects: list[StateCallback] = side_effects or []
		self.retry_policy: JsonDict = retry_policy or {}
		self.timeout = timeout
		self.error_state = error_state
		self.rollback = rollback
		self.async_dispatch = async_dispatch
		self.batch_size = batch_size

	def __repr__(self) -> str:
		return f"<Transition {self.trigger}: {self.source} -> {self.dest}>"

	def can_trigger(self, instance: Any, user: User) -> bool:
		"""Check role requirements and all conditions."""
		try:
			if self.required_roles and not any(
				user.has_role(role) for role in self.required_roles
			):
				return False
			return all(c(instance, user) for c in self.conditions)
		except Exception as exc:
			logger.error("Transition check error for %s: %s", self.trigger, exc)
			return False


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
class Workflow:
	"""Orchestrates states and transitions; validates configuration at construction."""

	def __init__(
		self,
		name: str,
		states: list[State],
		transitions: list[Transition],
		sub_workflows: list[Workflow] | None = None,
		metadata: JsonDict | None = None,
		version: str = "1.0",
		description: str = "",
		tags: list[str] | None = None,
		owner: str | None = None,
		timeout: int | None = None,
		notification_config: JsonDict | None = None,
		validation_rules: list[StateValidator] | None = None,
		error_state: str | None = None,
		max_retries: int = 3,
		auto_transitions: bool = False,
		parallel_execution: bool = False,
		history_limit: int | None = None,
	) -> None:
		self.name = name
		self.states = states
		self.transitions = transitions
		self.sub_workflows: list[Workflow] = sub_workflows or []
		self.metadata: JsonDict = metadata or {}
		self.version = version
		self.description = description
		self.tags: list[str] = tags or []
		self.owner = owner
		self.timeout = timeout
		self.notification_config: JsonDict = notification_config or {}
		self.validation_rules: list[StateValidator] = validation_rules or []
		self.error_state = error_state
		self.max_retries = max_retries
		self.auto_transitions = auto_transitions
		self.parallel_execution = parallel_execution
		self.history_limit = history_limit

		self._validate()
		self._setup_validation()
		self._setup_notifications()
		self._setup_error_handling()

	# ------------------------------------------------------------------
	# Internal setup
	# ------------------------------------------------------------------

	def _validate(self) -> None:
		state_names = {s.name for s in self.states}
		initial_states = [s for s in self.states if s.is_initial]

		if not initial_states:
			raise ValueError("Workflow must have at least one initial state")
		if len(initial_states) > 1:
			raise ValueError("Workflow cannot have multiple initial states")

		for t in self.transitions:
			if not set(t.source).issubset(state_names):
				raise ValueError(f"Invalid source state(s) in transition '{t.trigger}'")
			if t.dest not in state_names:
				raise ValueError(f"Invalid destination state in transition '{t.trigger}'")

		if self.error_state and self.error_state not in state_names:
			raise ValueError(f"Invalid workflow error_state: {self.error_state!r}")

	def _setup_validation(self) -> None:
		self._validators: dict[str, list[StateValidator]] = {
			s.name: s.validators for s in self.states
		}

	def _setup_notifications(self) -> None:
		self._notification_handlers: list[Any] = list(
			self.notification_config.get("handlers", [])
		)

	def _setup_error_handling(self) -> None:
		self._error_handlers: dict[str, str] = {
			s.name: s.error_state
			for s in self.states
			if s.error_state
		}

	# ------------------------------------------------------------------
	# Queries
	# ------------------------------------------------------------------

	def get_available_transitions(self, current_state: str) -> list[Transition]:
		return [t for t in self.transitions if current_state in t.source]

	def get_state(self, state_name: str) -> State | None:
		return next((s for s in self.states if s.name == state_name), None)

	@property
	def initial_state(self) -> State:
		return next(s for s in self.states if s.is_initial)

	def handle_timeout(self, state: State) -> str | None:
		if state.timeout:
			return state.error_state or self.error_state
		return None

	def handle_error(self, state: State, error: Exception) -> str | None:
		error_state = state.error_state or self.error_state
		if error_state:
			logger.error(
				"Transitioning to error state %r due to: %s", error_state, error
			)
			return error_state
		return None


# ---------------------------------------------------------------------------
# NotificationManager
# ---------------------------------------------------------------------------
class NotificationManager:
	"""Sends notifications via email, SMS, webhooks, and blinker signals."""

	@staticmethod
	async def send_notifications(notifications: list[dict[str, Any]]) -> None:
		"""Dispatch all notifications concurrently."""
		tasks: list[Any] = []
		for notification in notifications:
			handler = getattr(
				NotificationManager, f"send_{notification['type']}", None
			)
			if handler:
				tasks.append(handler(**notification["data"]))
		if tasks:
			await asyncio.gather(*tasks, return_exceptions=True)

	@staticmethod
	async def send_email(
		subject: str,
		recipients: list[str],
		body: str,
		template: str | None = None,
		attachments: list[str] | None = None,
		html: bool = False,
		cc: list[str] | None = None,
		bcc: list[str] | None = None,
		reply_to: str | None = None,
		sender: str | None = None,
		retry: int = 3,
	) -> bool:
		"""Send email via flask-mail (optional dependency)."""
		try:
			from flask_mail import Message as MailMessage
			from flask import render_template as _render
		except ImportError:
			logger.warning("flask-mail not installed; email notification skipped")
			return False

		for attempt in range(retry):
			try:
				msg = MailMessage(
					subject,
					recipients=recipients,
					cc=cc,
					bcc=bcc,
					reply_to=reply_to,
					sender=sender,
				)
				if html:
					msg.html = _render(template, body=body) if template else body
				else:
					msg.body = body

				if attachments:
					for attachment in attachments:
						with current_app.open_resource(attachment) as f:
							msg.attach(
								os.path.basename(attachment),
								"application/octet-stream",
								f.read(),
							)

				mail = current_app.extensions.get("mail")
				if mail is None:
					logger.warning("Flask-Mail extension not registered")
					return False

				# flask-mail >= 0.10 exposes send(); run in executor to avoid blocking
				loop = asyncio.get_event_loop()
				await loop.run_in_executor(None, mail.send, msg)
				return True

			except Exception as exc:
				logger.error("Email error (attempt %d): %s", attempt + 1, exc)
				if attempt == retry - 1:
					return False
				await asyncio.sleep(1)

		return False

	@staticmethod
	async def send_sms(
		to: str,
		body: str,
		callback_url: str | None = None,
		media_url: str | None = None,
		retry: int = 3,
		status_callback: str | None = None,
		validity_period: int | None = None,
		application_sid: str | None = None,
		max_price: float | None = None,
		provide_feedback: bool = False,
		force_delivery: bool = False,
	) -> bool:
		"""Send SMS via Twilio (optional dependency)."""
		try:
			from twilio.rest import Client
		except ImportError:
			logger.warning("twilio not installed; SMS notification skipped")
			return False

		for attempt in range(retry):
			try:
				client = Client(
					current_app.config["TWILIO_ACCOUNT_SID"],
					current_app.config["TWILIO_AUTH_TOKEN"],
				)
				message_data: dict[str, Any] = {
					"to": to,
					"from_": current_app.config["TWILIO_PHONE_NUMBER"],
					"body": body,
					"status_callback": callback_url or status_callback,
					"application_sid": application_sid,
					"max_price": max_price,
					"provide_feedback": provide_feedback,
					"validity_period": validity_period,
				}
				if media_url:
					message_data["media_url"] = [media_url]

				loop = asyncio.get_event_loop()
				await loop.run_in_executor(
					None, lambda: client.messages.create(**message_data)
				)
				return True

			except Exception as exc:
				logger.error("SMS error (attempt %d): %s", attempt + 1, exc)
				if attempt == retry - 1:
					return False
				await asyncio.sleep(1)

		return False

	@staticmethod
	async def send_webhook(
		url: str,
		payload: dict[str, Any],
		method: str = "POST",
		headers: dict[str, str] | None = None,
		timeout: int = 30,
		retry: int = 3,
		verify_ssl: bool = True,
		basic_auth: tuple | None = None,
		json_encode: bool = True,
		expected_status: list[int] | None = None,
		retry_codes: list[int] | None = None,
	) -> bool:
		"""Send HTTP webhook (requires aiohttp)."""
		try:
			import aiohttp
		except ImportError:
			logger.warning("aiohttp not installed; webhook notification skipped")
			return False

		if expected_status is None:
			expected_status = [200, 201, 202, 204]
		if retry_codes is None:
			retry_codes = [408, 429, 500, 502, 503, 504]

		connector = aiohttp.TCPConnector(ssl=verify_ssl)
		client_timeout = aiohttp.ClientTimeout(total=timeout)

		for attempt in range(retry):
			try:
				async with aiohttp.ClientSession(
					connector=connector, timeout=client_timeout
				) as sess:
					auth = (
						aiohttp.BasicAuth(*basic_auth) if basic_auth else None
					)
					async with sess.request(
						method=method,
						url=url,
						json=payload if json_encode else None,
						data=None if json_encode else payload,
						headers=headers or {},
						auth=auth,
					) as response:
						if response.status in expected_status:
							return True
						if response.status not in retry_codes:
							logger.error(
								"Webhook %s failed with status %d", url, response.status
							)
							return False

			except Exception as exc:
				logger.error("Webhook error (attempt %d): %s", attempt + 1, exc)
				if attempt == retry - 1:
					return False

			await asyncio.sleep(min(2 ** attempt, 30))

		return False

	@staticmethod
	def send_signal(
		signal_name: str,
		sender: Any,
		synchronous: bool = True,
		**kwargs: Any,
	) -> None:
		"""Emit a blinker signal."""
		try:
			sig = signal(signal_name)
			sig.send(sender, **kwargs)
		except Exception as exc:
			logger.error("Signal error for %r: %s", signal_name, exc)

	@staticmethod
	def flash_message(
		message: str,
		category: str = "info",
		variables: dict[str, Any] | None = None,
		sanitize: bool = True,
		translate: bool = True,
	) -> None:
		"""Display a Flask flash message."""
		try:
			if variables:
				message = message.format(**variables)
			if translate:
				try:
					from flask_babel import gettext as _
					message = _(message)
				except ImportError:
					pass
			if sanitize:
				from markupsafe import escape
				message = str(escape(message))
			flash(message, category)
		except Exception as exc:
			logger.error("Flash message error: %s", exc)


# ---------------------------------------------------------------------------
# StateChangeHistory — audit table
# ---------------------------------------------------------------------------
class StateChangeHistory(Model):
	"""Audit record for every state transition executed via StateMachineMixin."""

	__tablename__ = "state_change_history"

	id = Column(Integer, primary_key=True)
	model_id = Column(Integer, nullable=False, index=True)
	model_type = Column(String(255), nullable=False, index=True)
	from_state = Column(String(100), nullable=True)
	to_state = Column(String(100), nullable=False)
	changed_by = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	changed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
	reason = Column(Text, nullable=True)
	trace_id = Column(String(64), nullable=True, index=True)
	priority = Column(Integer, default=0)
	expires = Column(DateTime, nullable=True)
	extra_tags = Column(Text, nullable=True)  # JSON-encoded list[str]

	# Portable JSON field: JSONB on PostgreSQL, JSON elsewhere
	if _HAS_JSONB:
		from sqlalchemy.dialects.postgresql import JSONB
		extra_metadata = Column(JSONB, nullable=True, default=dict)
	else:
		extra_metadata = Column(_JSON, nullable=True, default=dict)

	def __repr__(self) -> str:
		return (
			f"<StateChangeHistory {self.model_type}#{self.model_id} "
			f"{self.from_state!r} -> {self.to_state!r}>"
		)

	@property
	def tags(self) -> list[str]:
		if not self.extra_tags:
			return []
		try:
			return json.loads(self.extra_tags)
		except (json.JSONDecodeError, TypeError):
			return []

	@tags.setter
	def tags(self, value: list[str]) -> None:
		self.extra_tags = json.dumps(value or [])

	def to_dict(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"model_id": self.model_id,
			"model_type": self.model_type,
			"from_state": self.from_state,
			"to_state": self.to_state,
			"changed_by": self.changed_by,
			"changed_at": self.changed_at.isoformat() if self.changed_at else None,
			"reason": self.reason,
			"metadata": self.extra_metadata or {},
			"trace_id": self.trace_id,
			"tags": self.tags,
			"priority": self.priority,
		}


# ---------------------------------------------------------------------------
# HistoryManager
# ---------------------------------------------------------------------------
class HistoryManager:
	"""CRUD and cleanup utilities for StateChangeHistory."""

	@staticmethod
	def _db():
		from pgappforge import db as _fab_db
		return _fab_db

	@staticmethod
	def add_entry(
		instance: Any,
		from_state: str | None,
		to_state: str,
		user: User | None,
		reason: str | None = None,
		metadata: JsonDict | None = None,
		trace_id: str | None = None,
		tags: list[str] | None = None,
		priority: int = 0,
		expires: datetime | None = None,
		notify: bool = True,
	) -> StateChangeHistory | None:
		"""Create and persist a StateChangeHistory record."""
		db = HistoryManager._db()
		try:
			entry = StateChangeHistory(
				model_id=instance.id,
				model_type=instance.__class__.__name__,
				from_state=from_state,
				to_state=to_state,
				changed_by=user.id if user else None,
				changed_at=datetime.now(tz=timezone.utc),
				reason=reason,
				extra_metadata=metadata or {},
				trace_id=trace_id,
				priority=priority,
				expires=expires,
			)
			entry.tags = tags or []

			# Enrich with request context if available
			audit_meta: dict[str, Any] = {}
			try:
				audit_meta["ip_address"] = getattr(request, "remote_addr", None)
				audit_meta["user_agent"] = (
					request.user_agent.string
					if hasattr(request, "user_agent")
					else None
				)
				audit_meta["session_id"] = session.get("_id") if session else None
				audit_meta["correlation_id"] = g.get("correlation_id")
				audit_meta["source"] = g.get("source", "web")
			except RuntimeError:
				# Outside request context
				audit_meta["source"] = "internal"

			entry.extra_metadata = {**(metadata or {}), **audit_meta}

			db.session.add(entry)
			db.session.commit()

			if notify:
				HistoryManager._notify_change(entry)

			return entry

		except Exception as exc:
			logger.error("Error adding history entry: %s", exc)
			db.session.rollback()
			return None

	@staticmethod
	def _notify_change(entry: StateChangeHistory) -> None:
		try:
			signal("state_history_change").send(entry)

			if current_app.config.get("HISTORY_WEBHOOKS"):
				webhook_url = current_app.config.get("HISTORY_WEBHOOK_URL")
				if webhook_url:
					asyncio.ensure_future(
						NotificationManager.send_webhook(
							webhook_url,
							{"type": "history_change", "entry": entry.to_dict()},
						)
					)
		except Exception as exc:
			logger.error("History notification error: %s", exc)

	@staticmethod
	def get_history(
		instance: Any,
		filters: JsonDict | None = None,
		limit: int | None = None,
		offset: int | None = None,
		order_by: list[str] | None = None,
		since: datetime | None = None,
		until: datetime | None = None,
		states: list[str] | None = None,
		users: list[int] | None = None,
		tags: list[str] | None = None,
		search: str | None = None,
	) -> list[StateChangeHistory]:
		"""Query history entries for an instance with rich filtering."""
		db = HistoryManager._db()
		try:
			stmt = select(StateChangeHistory).where(
				StateChangeHistory.model_id == instance.id,
				StateChangeHistory.model_type == instance.__class__.__name__,
			)

			if filters:
				for key, value in filters.items():
					col = getattr(StateChangeHistory, key, None)
					if col is not None:
						stmt = stmt.where(col == value)

			if since:
				stmt = stmt.where(StateChangeHistory.changed_at >= since)
			if until:
				stmt = stmt.where(StateChangeHistory.changed_at <= until)
			if states:
				stmt = stmt.where(StateChangeHistory.to_state.in_(states))
			if users:
				stmt = stmt.where(StateChangeHistory.changed_by.in_(users))
			if tags:
				# Portable substring match across tag JSON
				for tag in tags:
					stmt = stmt.where(
						StateChangeHistory.extra_tags.contains(tag)
					)
			if search:
				pattern = f"%{search}%"
				stmt = stmt.where(
					StateChangeHistory.reason.ilike(pattern)
				)

			# Sorting
			if order_by:
				for col_spec in order_by:
					descending = col_spec.startswith("-")
					col_name = col_spec.lstrip("-")
					col = getattr(StateChangeHistory, col_name, None)
					if col is not None:
						stmt = stmt.order_by(col.desc() if descending else col.asc())
			else:
				stmt = stmt.order_by(StateChangeHistory.changed_at.desc())

			if offset:
				stmt = stmt.offset(offset)
			if limit:
				stmt = stmt.limit(limit)

			return list(db.session.execute(stmt).scalars().all())

		except Exception as exc:
			logger.error("Error getting history: %s", exc)
			return []

	@staticmethod
	def revert_to_state(
		instance: Any,
		target_state: str,
		user: User,
		reason: str | None = None,
		validate: bool = True,
		force: bool = False,
		dry_run: bool = False,
		notify: bool = True,
		skip_handlers: bool = False,
	) -> bool:
		"""Revert instance to a previously occupied state."""
		db = HistoryManager._db()
		try:
			history = HistoryManager.get_history(instance)
			if not any(e.to_state == target_state for e in history):
				raise ValueError(f"State {target_state!r} not found in history")

			if validate and hasattr(instance, "can_revert_to"):
				if not instance.can_revert_to(target_state, user):
					if not force:
						raise ValueError("Revert not permitted")
					logger.warning("Forcing revert to state %r", target_state)

			if dry_run:
				return True

			current_state = instance.state
			instance.state = target_state

			HistoryManager.add_entry(
				instance,
				current_state,
				target_state,
				user,
				reason or "State reverted",
				{
					"revert": True,
					"forced": force,
					"original_state": current_state,
					"skip_handlers": skip_handlers,
				},
				notify=notify,
			)

			if not skip_handlers and hasattr(instance, "handle_revert"):
				instance.handle_revert(current_state, target_state, user)

			db.session.commit()
			return True

		except Exception as exc:
			logger.error("Error reverting state: %s", exc)
			db.session.rollback()
			return False

	@staticmethod
	def cleanup_history(
		max_age: int | None = None,
		max_entries: int | None = None,
		states: list[str] | None = None,
		models: list[str] | None = None,
		before: datetime | None = None,
		dry_run: bool = False,
		batch_size: int = 1000,
	) -> int:
		"""Delete old history entries in batches; returns count removed."""
		db = HistoryManager._db()
		try:
			stmt = select(StateChangeHistory)

			if max_age:
				cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age)
				stmt = stmt.where(StateChangeHistory.changed_at < cutoff)
			if before:
				stmt = stmt.where(StateChangeHistory.changed_at < before)
			if states:
				stmt = stmt.where(StateChangeHistory.to_state.in_(states))
			if models:
				stmt = stmt.where(StateChangeHistory.model_type.in_(models))

			if dry_run:
				return db.session.execute(
					select(func.count()).select_from(stmt.subquery())
				).scalar() or 0

			deleted = 0
			while True:
				if max_entries and deleted >= max_entries:
					break
				rows = db.session.execute(
					stmt.with_only_columns(StateChangeHistory.id).limit(batch_size)
				).scalars().all()
				if not rows:
					break
				db.session.execute(
					StateChangeHistory.__table__.delete().where(
						StateChangeHistory.id.in_(rows)
					)
				)
				deleted += len(rows)
				db.session.commit()

			return deleted

		except Exception as exc:
			logger.error("Error cleaning history: %s", exc)
			db.session.rollback()
			return 0


# ---------------------------------------------------------------------------
# StateMachineMixin
# ---------------------------------------------------------------------------
class StateMachineMixin:
	"""
	Add declarative state machine behaviour to a PgAppForge / SQLAlchemy model.

	Usage::

		class Invoice(StateMachineMixin, Model):
			__tablename__ = "invoices"
			id = Column(Integer, primary_key=True)
			...
			workflow = Workflow(
				name="invoice_workflow",
				states=[DRAFT, SENT, PAID, CANCELLED],
				transitions=[SEND, PAY, CANCEL, REOPEN],
			)

	The mixin contributes:
	- ``state`` column (String 100)
	- ``state_changed_at`` column (DateTime)
	- ``trigger_event(trigger, user, **kwargs)`` — execute a named transition
	- ``get_available_transitions(user)`` — list permitted transitions for current user
	- ``get_state_metadata()`` — current State descriptor
	- ``visualize(...)`` — emit GraphViz diagram (graphviz optional)
	- ``generate_mermaid_diagram()`` — Mermaid.js state diagram string
	- ``export_definition(format)`` — JSON or YAML workflow export
	"""

	# ------------------------------------------------------------------
	# SQLAlchemy columns (declared_attr so they survive mixin inheritance)
	# ------------------------------------------------------------------

	@declared_attr
	def state(cls):
		return Column(String(100), nullable=True, index=True)

	@declared_attr
	def state_changed_at(cls):
		return Column(DateTime, nullable=True)

	# ------------------------------------------------------------------
	# Initialisation
	# ------------------------------------------------------------------

	def __init_subclass__(cls, **kwargs: Any) -> None:
		super().__init_subclass__(**kwargs)
		workflow: Workflow | None = getattr(cls, "workflow", None)
		if workflow is not None:
			# Register SQLAlchemy after_insert to seed the initial state
			event.listen(cls, "after_insert", cls._sm_seed_initial_state)

	@staticmethod
	def _sm_seed_initial_state(mapper: Any, connection: Any, target: Any) -> None:
		"""Set initial state immediately after first INSERT."""
		workflow: Workflow | None = getattr(target, "workflow", None)
		if workflow and not target.state:
			connection.execute(
				target.__table__.update()
				.where(target.__table__.c.id == target.id)
				.values(
					state=workflow.initial_state.name,
					state_changed_at=datetime.now(tz=timezone.utc),
				)
			)
			target.state = workflow.initial_state.name
			target.state_changed_at = datetime.now(tz=timezone.utc)

	def _ensure_state(self) -> None:
		"""Seed state if not yet set (covers factory-pattern creation)."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if workflow and not self.state:
			self.state = workflow.initial_state.name
			self.state_changed_at = datetime.now(tz=timezone.utc)

	# ------------------------------------------------------------------
	# Core transition engine
	# ------------------------------------------------------------------

	async def trigger_event(
		self,
		trigger: str,
		user: User,
		reason: str | None = None,
		metadata: JsonDict | None = None,
		trace_id: str | None = None,
		dry_run: bool = False,
		notify: bool = True,
	) -> bool:
		"""
		Execute a named transition.

		Returns True on success, False on any guard or execution failure.
		Performs DB commit and writes a HistoryManager entry on success.
		"""
		self._ensure_state()
		workflow: Workflow | None = getattr(self, "workflow", None)
		if workflow is None:
			logger.error("%s has no workflow defined", self.__class__.__name__)
			return False

		# Locate matching transition
		transition = self._find_transition(trigger, workflow)
		if transition is None:
			logger.warning(
				"No transition %r from state %r on %s#%s",
				trigger, self.state, self.__class__.__name__, getattr(self, "id", "?"),
			)
			return False

		# Guard checks
		if not transition.can_trigger(self, user):
			msg = transition.validation_message or f"Transition {trigger!r} not permitted"
			NotificationManager.flash_message(msg, "warning")
			return False

		# State-level validation
		current_state_def = workflow.get_state(self.state)
		if current_state_def and not current_state_def.validate(self, user):
			NotificationManager.flash_message(
				f"Current state {self.state!r} validation failed", "danger"
			)
			return False

		if dry_run:
			return True

		from pgappforge import db
		previous_state = self.state

		try:
			# Before callbacks
			for cb in transition.before:
				cb(self, user)

			# Execute transition
			self.state = transition.dest
			self.state_changed_at = datetime.now(tz=timezone.utc)

			# Custom state-entry handler
			dest_state_def = workflow.get_state(transition.dest)
			if dest_state_def:
				on_enter = dest_state_def.custom_handlers.get("on_enter")
				if on_enter:
					on_enter(self)

			# Side effects
			for cb in transition.side_effects:
				cb(self, user)

			db.session.add(self)
			db.session.commit()

			# After callbacks (post-commit)
			for cb in transition.after:
				cb(self, user)

			# Audit trail
			HistoryManager.add_entry(
				self,
				previous_state,
				transition.dest,
				user,
				reason=reason,
				metadata=metadata,
				trace_id=trace_id,
				notify=notify,
			)

			# Async dispatch if configured
			if transition.async_dispatch:
				asyncio.ensure_future(
					NotificationManager.send_notifications(
						workflow.notification_config.get("handlers", [])
					)
				)

			# Emit signal
			NotificationManager.send_signal(
				f"state_change_{self.__class__.__name__.lower()}",
				self,
				from_state=previous_state,
				to_state=transition.dest,
				user=user,
			)

			return True

		except Exception as exc:
			logger.error(
				"Error executing transition %r on %s#%s: %s",
				trigger, self.__class__.__name__, getattr(self, "id", "?"), exc,
			)
			if transition.rollback:
				db.session.rollback()
				self.state = previous_state
			# Attempt error-state transition
			error_target = workflow.handle_error(
				current_state_def or State(previous_state), exc
			)
			if error_target and error_target != previous_state:
				self.state = error_target
				self.state_changed_at = datetime.now(tz=timezone.utc)
				try:
					db.session.add(self)
					db.session.commit()
				except Exception:
					db.session.rollback()
			return False

	def _find_transition(
		self, trigger: str, workflow: Workflow
	) -> Transition | None:
		"""Find the highest-priority matching transition for current state."""
		candidates = [
			t for t in workflow.transitions
			if t.trigger == trigger and self.state in t.source
		]
		if not candidates:
			return None
		return max(candidates, key=lambda t: t.priority)

	# ------------------------------------------------------------------
	# Introspection helpers
	# ------------------------------------------------------------------

	def get_available_transitions(self, user: User) -> list[Transition]:
		"""Return all transitions the given user may trigger from current state."""
		self._ensure_state()
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return []
		return [
			t for t in workflow.get_available_transitions(self.state)
			if t.can_trigger(self, user)
		]

	def get_state_metadata(self) -> State | None:
		"""Return the State descriptor for the current state, or None."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow or not self.state:
			return None
		return workflow.get_state(self.state)

	def is_in_state(self, *state_names: str) -> bool:
		return self.state in state_names

	def can_trigger(self, trigger: str, user: User) -> bool:
		"""Quick check whether a named transition is currently available."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return False
		t = self._find_transition(trigger, workflow)
		return t is not None and t.can_trigger(self, user)

	def can_revert_to(self, target_state: str, user: User) -> bool:
		"""Default revert policy: allowed unless state is restricted."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return False
		state_def = workflow.get_state(target_state)
		if state_def is None:
			return False
		if state_def.is_restricted and state_def.required_roles:
			return any(user.has_role(r) for r in state_def.required_roles)
		return True

	def handle_revert(
		self, from_state: str, to_state: str, user: User
	) -> None:
		"""Override to add custom revert logic."""

	# ------------------------------------------------------------------
	# FAB renderer
	# ------------------------------------------------------------------

	@renders("state")
	def state_badge(self) -> str:
		"""Render the current state as an HTML badge for FAB list views."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		color = "#CCCCCC"
		if workflow and self.state:
			state_def = workflow.get_state(self.state)
			if state_def:
				color = state_def.ui_color
		return (
			f'<span class="badge" style="background-color:{color}">'
			f'{self.state or "—"}</span>'
		)

	# ------------------------------------------------------------------
	# Visualization
	# ------------------------------------------------------------------

	def visualize(
		self,
		filename: str = "workflow",
		fmt: str = "png",
		view: bool = False,
	) -> str | None:
		"""
		Render the workflow as a GraphViz diagram.

		Returns the output file path, or None if graphviz is unavailable.
		"""
		try:
			import graphviz as gv
		except ImportError:
			logger.warning("graphviz not installed; visualization skipped")
			return None

		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return None

		dot = gv.Digraph(name=workflow.name, format=fmt)
		dot.attr(rankdir="LR")

		for state in workflow.states:
			shape = "doublecircle" if state.is_final else "circle"
			dot.node(
				state.name,
				label=state.name,
				shape=shape,
				style="filled",
				fillcolor=state.ui_color,
			)

		for t in workflow.transitions:
			for src in t.source:
				dot.edge(src, t.dest, label=t.trigger)

		return dot.render(filename=filename, view=view)

	def generate_mermaid_diagram(self) -> str:
		"""Return a Mermaid.js stateDiagram-v2 string for the workflow."""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return "stateDiagram-v2\n  [*] --> (no workflow)"

		lines = ["stateDiagram-v2"]
		initial = workflow.initial_state.name
		lines.append(f"  [*] --> {initial}")

		for t in workflow.transitions:
			for src in t.source:
				lines.append(f"  {src} --> {t.dest} : {t.trigger}")

		for state in workflow.states:
			if state.is_final:
				lines.append(f"  {state.name} --> [*]")

		return "\n".join(lines)

	# ------------------------------------------------------------------
	# Export / Import
	# ------------------------------------------------------------------

	def export_definition(self, fmt: str = "json") -> str:
		"""
		Serialize the workflow definition to JSON or YAML.

		Args:
			fmt: "json" (default) or "yaml"
		"""
		workflow: Workflow | None = getattr(self, "workflow", None)
		if not workflow:
			return "{}" if fmt == "json" else "{}"

		data: dict[str, Any] = {
			"name": workflow.name,
			"version": workflow.version,
			"description": workflow.description,
			"tags": workflow.tags,
			"owner": workflow.owner,
			"error_state": workflow.error_state,
			"max_retries": workflow.max_retries,
			"states": [
				{
					"name": s.name,
					"description": s.description,
					"is_initial": s.is_initial,
					"is_final": s.is_final,
					"is_restricted": s.is_restricted,
					"required_roles": s.required_roles,
					"timeout": s.timeout,
					"error_state": s.error_state,
					"ui_color": s.ui_color,
					"max_retries": s.max_retries,
					"ttl": s.ttl,
					"metadata": s.metadata,
				}
				for s in workflow.states
			],
			"transitions": [
				{
					"trigger": t.trigger,
					"source": t.source,
					"dest": t.dest,
					"priority": t.priority,
					"required_roles": t.required_roles,
					"auto_trigger": t.auto_trigger,
					"validation_message": t.validation_message,
					"timeout": t.timeout,
					"error_state": t.error_state,
					"rollback": t.rollback,
					"async_dispatch": t.async_dispatch,
					"batch_size": t.batch_size,
					"retry_policy": t.retry_policy,
				}
				for t in workflow.transitions
			],
			"notification_config": workflow.notification_config,
			"metadata": workflow.metadata,
		}

		if fmt == "yaml":
			try:
				import yaml
				return yaml.dump(data, default_flow_style=False, allow_unicode=True)
			except ImportError:
				logger.warning("pyyaml not installed; falling back to JSON")

		return json.dumps(data, indent=2, default=str)

	@classmethod
	def import_definition(cls, definition: str, fmt: str = "json") -> dict[str, Any]:
		"""
		Parse an exported workflow definition.

		Returns the raw dict; does not reconstruct live State/Transition objects
		(that requires the caller to re-instantiate with their validator closures).
		"""
		if fmt == "yaml":
			try:
				import yaml
				return yaml.safe_load(definition)
			except ImportError:
				pass
		return json.loads(definition)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------
__all__ = [
	"State",
	"Transition",
	"Workflow",
	"NotificationManager",
	"HistoryManager",
	"StateChangeHistory",
	"StateMachineMixin",
]
