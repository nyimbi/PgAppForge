"""Form Builder models."""
from __future__ import annotations
from datetime import datetime, timezone
from pgappforge import Model
from sqlalchemy import (BigInteger, Boolean, Column, DateTime, ForeignKey,
	Integer, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import INET, JSONB


class Form(Model):
	"""A form definition with fields, steps, conditions, and settings."""
	__tablename__ = "pgaf_form"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	title = Column(String(255), nullable=False)
	slug = Column(String(128), unique=True)
	description = Column(Text)
	definition = Column(JSONB, nullable=False, default=dict)
	# {fields: [...], steps: [...], settings: {...}, conditions: [...]}
	status = Column(String(20), default="draft")  # draft/published/archived
	current_version_id = Column(Integer, ForeignKey("pgaf_form_version.id"), nullable=True)
	target_model = Column(String(255))  # auto-save submissions to this model
	field_mapping = Column(JSONB, default=dict)  # form_field_id → model_field
	submit_actions = Column(JSONB, default=list)
	# [{type: rules|bpm|notify|report, config: {}}]
	scoring_enabled = Column(Boolean, default=False)
	score_bands = Column(JSONB, default=list)
	# [{min: 0, max: 59, label: "Needs Improvement", color: "#ef5350"}]
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
	updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))


class FormVersion(Model):
	"""Immutable snapshot of a form definition at publish time."""
	__tablename__ = "pgaf_form_version"
	__table_args__ = (
		UniqueConstraint("form_id", "version_number"),
		{"extend_existing": True},
	)
	id = Column(Integer, primary_key=True)
	form_id = Column(Integer, ForeignKey("pgaf_form.id", ondelete="CASCADE"), index=True)
	version_number = Column(Integer, nullable=False)
	definition = Column(JSONB, nullable=False)
	published_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
	published_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)


class FormShareToken(Model):
	"""Share token for public (unauthenticated) form access."""
	__tablename__ = "pgaf_form_share_token"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	form_id = Column(Integer, ForeignKey("pgaf_form.id", ondelete="CASCADE"), index=True)
	token = Column(String(64), unique=True, nullable=False)
	max_submissions = Column(Integer)  # null = unlimited
	submissions_used = Column(Integer, default=0)
	expires_at = Column(DateTime(timezone=True))
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FormSubmission(Model):
	"""A single form submission with field data and optional score."""
	__tablename__ = "pgaf_form_submission"
	__table_args__ = {"extend_existing": True}
	id = Column(BigInteger, primary_key=True)
	form_id = Column(Integer, ForeignKey("pgaf_form.id"), index=True)
	version_id = Column(Integer, ForeignKey("pgaf_form_version.id"), nullable=True)
	data = Column(JSONB, nullable=False, default=dict)  # {field_id: value}
	score = Column(Numeric(10, 2))
	outcome = Column(String(255))   # score band label
	submitter_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	submitter_ip = Column(INET)
	submitter_ua = Column(String(512))
	draft_token = Column(String(64), index=True)
	submitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FormAnalyticsEvent(Model):
	"""Analytics events for funnel analysis."""
	__tablename__ = "pgaf_form_analytics"
	__table_args__ = {"extend_existing": True}
	id = Column(BigInteger, primary_key=True)
	form_id = Column(Integer, ForeignKey("pgaf_form.id"), index=True)
	session_id = Column(String(64), index=True)
	event_type = Column(String(20))
	# view / start / step_complete / field_focus / field_error / abandon / submit
	step_number = Column(Integer)
	field_id = Column(String(64))
	duration_ms = Column(Integer)
	created_at = Column(DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc), index=True)
