from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	Text,
	VARCHAR,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

__all__ = [
	"Survey",
	"SurveyQuestion",
	"SurveyResponse",
	"SurveyAnswer",
]

_uuid4 = sa.text("gen_random_uuid()")


class Survey(AuditMixin, Model):
	"""Survey definition.  Supports CUSTOM, ENPS, EXIT, ONBOARDING, ENGAGEMENT and PULSE types.

	target_roles: empty list means all roles are targeted.
	opens_at / closes_at: optional scheduling window; None means open-ended.
	"""

	__tablename__ = "srv_survey"
	__table_args__ = (
		Index("ix_srv_survey_tenant_status", "tenant_id", "status"),
		Index("ix_srv_survey_tenant_type", "tenant_id", "survey_type"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	title = Column(VARCHAR(300), nullable=False)
	description = Column(Text, nullable=True)
	survey_type = Column(VARCHAR(30), nullable=False, default="CUSTOM")
	status = Column(VARCHAR(20), nullable=False, default="DRAFT")
	is_anonymous = Column(Boolean, nullable=False, default=True, server_default="true")
	target_roles = Column(JSONB, nullable=False, default=list, server_default="[]")
	target_entity_id = Column(VARCHAR(50), nullable=True)
	opens_at = Column(DateTime(timezone=True), nullable=True)
	closes_at = Column(DateTime(timezone=True), nullable=True)
	created_by = Column(VARCHAR(50), nullable=True)
	allow_multiple_responses = Column(Boolean, nullable=False, default=False, server_default="false")
	show_results_to_respondents = Column(Boolean, nullable=False, default=False, server_default="false")

	questions: list[SurveyQuestion] = relationship(
		"SurveyQuestion",
		back_populates="survey",
		cascade="all, delete-orphan",
		order_by="SurveyQuestion.order_num",
		lazy="select",
	)
	responses: list[SurveyResponse] = relationship(
		"SurveyResponse",
		back_populates="survey",
		cascade="all, delete-orphan",
		lazy="select",
	)


class SurveyQuestion(Model):
	"""A single question in a survey.

	options JSONB: list of strings for SINGLE_CHOICE / MULTI_CHOICE types.
	logic JSONB: branching rules, e.g. {"if_answer": "No", "skip_to": "<question_id>"}.
	scale_min / scale_max: bounds for RATING_SCALE type.
	"""

	__tablename__ = "srv_question"
	__table_args__ = (
		Index("ix_srv_question_survey_order", "survey_id", "order_num"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	survey_id = Column(
		UUID(as_uuid=False),
		ForeignKey("srv_survey.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	question_text = Column(Text, nullable=False)
	question_type = Column(VARCHAR(30), nullable=False)
	order_num = Column(Integer, nullable=False, default=0, server_default="0")
	is_required = Column(Boolean, nullable=False, default=True, server_default="true")
	options = Column(JSONB, nullable=False, default=list, server_default="[]")
	scale_min = Column(Integer, nullable=True)
	scale_max = Column(Integer, nullable=True)
	logic = Column(JSONB, nullable=False, default=dict, server_default="{}")

	survey: Survey = relationship("Survey", back_populates="questions", lazy="select")
	answers: list[SurveyAnswer] = relationship(
		"SurveyAnswer",
		back_populates="question",
		cascade="all, delete-orphan",
		lazy="select",
	)


class SurveyResponse(Model):
	"""One completed (or partial) submission of a survey.

	respondent_id is null for anonymous surveys; response_token allows
	re-linking for deduplication without exposing identity.
	metadata_ can carry sourcing info: {"source": "email_campaign", "employee_id": "..."}.
	"""

	__tablename__ = "srv_response"
	__table_args__ = (
		Index("ix_srv_response_survey_ts", "survey_id", "submitted_at"),
		Index("ix_srv_response_respondent", "respondent_id", "survey_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	survey_id = Column(
		UUID(as_uuid=False),
		ForeignKey("srv_survey.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	respondent_id = Column(VARCHAR(50), nullable=True)
	submitted_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
		server_default=sa.text("now()"),
	)
	is_complete = Column(Boolean, nullable=False, default=True, server_default="true")
	response_token = Column(VARCHAR(100), nullable=True, unique=True)
	metadata_ = Column("metadata", JSONB, nullable=False, default=dict, server_default="{}")

	survey: Survey = relationship("Survey", back_populates="responses", lazy="select")
	answers: list[SurveyAnswer] = relationship(
		"SurveyAnswer",
		back_populates="response",
		cascade="all, delete-orphan",
		lazy="select",
	)


class SurveyAnswer(Model):
	"""Single answer to a question within a response.

	Only one of answer_text / answer_choice / answer_choices / answer_number
	will be populated depending on question_type.
	"""

	__tablename__ = "srv_answer"
	__table_args__ = (
		Index("ix_srv_answer_response_question", "response_id", "question_id"),
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=lambda: __import__("uuid").uuid4().hex,
		server_default=_uuid4,
	)
	response_id = Column(
		UUID(as_uuid=False),
		ForeignKey("srv_response.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	question_id = Column(
		UUID(as_uuid=False),
		ForeignKey("srv_question.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	answer_text = Column(Text, nullable=True)
	answer_choice = Column(VARCHAR(200), nullable=True)
	answer_choices = Column(JSONB, nullable=True)
	answer_number = Column(Numeric(10, 2), nullable=True)

	response: SurveyResponse = relationship("SurveyResponse", back_populates="answers", lazy="select")
	question: SurveyQuestion = relationship("SurveyQuestion", back_populates="answers", lazy="select")
