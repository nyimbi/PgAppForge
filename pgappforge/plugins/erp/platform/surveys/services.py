from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.erp.platform.surveys.events import (
	SurveyAnalysisGeneratedEvent,
	SurveyClosedEvent,
	SurveyPublishedEvent,
	SurveyResponseSubmittedEvent,
)
from pgappforge.plugins.erp.platform.surveys.models import (
	Survey,
	SurveyAnswer,
	SurveyQuestion,
	SurveyResponse,
)

log = logging.getLogger(__name__)

__all__ = [
	"SurveyServiceError",
	"SurveyNotFoundError",
	"SurveyStateError",
	"SurveyService",
]


class SurveyServiceError(Exception):
	"""Base error for survey service."""


class SurveyNotFoundError(SurveyServiceError):
	"""Raised when the requested survey/response/question does not exist."""


class SurveyStateError(SurveyServiceError):
	"""Raised when an operation is invalid for the current survey state."""


class SurveyService:
	"""Business logic for the Survey Builder module.

	All methods are synchronous and accept an explicit SQLAlchemy Session.
	Callers own transaction boundaries (commit/rollback).
	"""

	# ── Lifecycle ────────────────────────────────────────────────────────────

	def publish_survey(self, survey_id: str, session: Session) -> Survey:
		"""Advance survey from DRAFT → PUBLISHED.  Emits SurveyPublishedEvent."""
		survey = self._get_survey(survey_id, session)
		if survey.status != "DRAFT":
			raise SurveyStateError(
				f"Cannot publish survey in status {survey.status!r}; must be DRAFT"
			)
		survey.status = "PUBLISHED"
		session.flush()

		emit_event(
			SurveyPublishedEvent(
				aggregate_id=survey.id,
				aggregate_type="Survey",
				survey_id=survey.id,
				title=survey.title,
				tenant_id=survey.tenant_id,
			),
			session,
		)
		return survey

	def close_survey(self, survey_id: str, session: Session) -> Survey:
		"""Advance survey from PUBLISHED → CLOSED.  Emits SurveyClosedEvent."""
		survey = self._get_survey(survey_id, session)
		if survey.status != "PUBLISHED":
			raise SurveyStateError(
				f"Cannot close survey in status {survey.status!r}; must be PUBLISHED"
			)
		response_count = session.execute(
			sa.select(sa.func.count(SurveyResponse.id)).where(
				SurveyResponse.survey_id == survey_id
			)
		).scalar_one()

		survey.status = "CLOSED"
		session.flush()

		emit_event(
			SurveyClosedEvent(
				aggregate_id=survey.id,
				aggregate_type="Survey",
				survey_id=survey.id,
				response_count=response_count,
			),
			session,
		)
		return survey

	# ── Responses ────────────────────────────────────────────────────────────

	def submit_response(
		self,
		survey_id: str,
		answers_dict: dict[str, Any],
		session: Session,
		*,
		respondent_id: str | None = None,
		metadata: dict[str, Any] | None = None,
	) -> SurveyResponse:
		"""Submit a completed survey response.

		answers_dict maps question_id → answer_value.
		answer_value semantics per question_type:
		  TEXT          → str
		  SINGLE_CHOICE → str (one option)
		  MULTI_CHOICE  → list[str]
		  RATING_SCALE  → int or float (stored as Numeric)
		  NPS           → int 0-10
		  BOOLEAN       → bool (stored as str "true"/"false" in answer_text)
		  DATE          → ISO date string (stored in answer_text)

		Validates all required questions are answered.
		Emits SurveyResponseSubmittedEvent.
		"""
		survey = self._get_survey(survey_id, session)
		if survey.status != "PUBLISHED":
			raise SurveyStateError(
				f"Survey {survey_id} is not PUBLISHED (status={survey.status!r})"
			)

		# check allow_multiple_responses if respondent is known
		if respondent_id and not survey.allow_multiple_responses:
			existing = session.execute(
				sa.select(SurveyResponse).where(
					SurveyResponse.survey_id == survey_id,
					SurveyResponse.respondent_id == respondent_id,
					SurveyResponse.is_complete.is_(True),
				)
			).scalar_one_or_none()
			if existing is not None:
				raise SurveyStateError(
					f"Respondent {respondent_id} has already submitted a response for survey {survey_id}"
				)

		# load questions
		questions: list[SurveyQuestion] = list(
			session.execute(
				sa.select(SurveyQuestion)
				.where(SurveyQuestion.survey_id == survey_id)
				.order_by(SurveyQuestion.order_num)
			).scalars()
		)

		# validate required
		missing = [
			q.id for q in questions
			if q.is_required and q.id not in answers_dict
		]
		if missing:
			raise SurveyServiceError(
				f"Required questions not answered: {missing}"
			)

		# create response
		token = secrets.token_urlsafe(24) if survey.is_anonymous else None
		response = SurveyResponse(
			survey_id=survey_id,
			respondent_id=None if survey.is_anonymous else respondent_id,
			is_complete=True,
			response_token=token,
			metadata_=metadata or {},
		)
		session.add(response)
		session.flush()

		# create answers
		q_map = {q.id: q for q in questions}
		for question_id, raw_value in answers_dict.items():
			question = q_map.get(question_id)
			if question is None:
				continue  # skip unknown question ids gracefully
			answer = self._build_answer(response.id, question, raw_value)
			session.add(answer)

		session.flush()

		emit_event(
			SurveyResponseSubmittedEvent(
				aggregate_id=response.id,
				aggregate_type="SurveyResponse",
				response_id=response.id,
				survey_id=survey_id,
				respondent_id=respondent_id or "",
			),
			session,
		)
		return response

	# ── Analytics ────────────────────────────────────────────────────────────

	def compute_nps(
		self, survey_id: str, session: Session
	) -> dict[str, Any]:
		"""Compute NPS from all NPS-type questions in the survey.

		Returns:
		  nps_score           — float (-100 to 100)
		  promoters_pct       — float
		  passives_pct        — float
		  detractors_pct      — float
		  response_count      — int
		"""
		nps_questions = list(
			session.execute(
				sa.select(SurveyQuestion).where(
					SurveyQuestion.survey_id == survey_id,
					SurveyQuestion.question_type == "NPS",
				)
			).scalars()
		)
		if not nps_questions:
			raise SurveyServiceError(f"Survey {survey_id} has no NPS questions")

		nps_q_ids = [q.id for q in nps_questions]
		answers = list(
			session.execute(
				sa.select(SurveyAnswer).where(
					SurveyAnswer.question_id.in_(nps_q_ids),
					SurveyAnswer.answer_number.is_not(None),
				)
			).scalars()
		)

		if not answers:
			return {
				"nps_score": None,
				"promoters_pct": 0.0,
				"passives_pct": 0.0,
				"detractors_pct": 0.0,
				"response_count": 0,
			}

		scores = [float(a.answer_number) for a in answers]
		total = len(scores)
		promoters = sum(1 for s in scores if s >= 9)
		detractors = sum(1 for s in scores if s <= 6)
		passives = total - promoters - detractors

		nps_score = (promoters - detractors) / total * 100

		return {
			"nps_score": round(nps_score, 2),
			"promoters_pct": round(promoters / total * 100, 2),
			"passives_pct": round(passives / total * 100, 2),
			"detractors_pct": round(detractors / total * 100, 2),
			"response_count": total,
		}

	def get_response_analytics(
		self, survey_id: str, session: Session
	) -> dict[str, Any]:
		"""Per-question analytics summary.

		Returns a dict keyed by question_id with:
		  response_count    — int
		  text_responses    — list[str] (TEXT questions)
		  choice_distribution — {option: count} (SINGLE/MULTI_CHOICE)
		  avg_rating        — float | None (RATING_SCALE / NPS)
		"""
		questions: list[SurveyQuestion] = list(
			session.execute(
				sa.select(SurveyQuestion)
				.where(SurveyQuestion.survey_id == survey_id)
				.order_by(SurveyQuestion.order_num)
			).scalars()
		)
		if not questions:
			return {}

		q_ids = [q.id for q in questions]
		all_answers: list[SurveyAnswer] = list(
			session.execute(
				sa.select(SurveyAnswer).where(SurveyAnswer.question_id.in_(q_ids))
			).scalars()
		)

		# group answers by question
		from collections import defaultdict
		by_question: dict[str, list[SurveyAnswer]] = defaultdict(list)
		for ans in all_answers:
			by_question[ans.question_id].append(ans)

		result: dict[str, Any] = {}
		for q in questions:
			qa = by_question[q.id]
			entry: dict[str, Any] = {"response_count": len(qa)}

			if q.question_type == "TEXT":
				entry["text_responses"] = [a.answer_text for a in qa if a.answer_text]

			elif q.question_type == "SINGLE_CHOICE":
				dist: dict[str, int] = {}
				for a in qa:
					if a.answer_choice:
						dist[a.answer_choice] = dist.get(a.answer_choice, 0) + 1
				entry["choice_distribution"] = dist

			elif q.question_type == "MULTI_CHOICE":
				dist = {}
				for a in qa:
					for choice in (a.answer_choices or []):
						dist[choice] = dist.get(choice, 0) + 1
				entry["choice_distribution"] = dist

			elif q.question_type in ("RATING_SCALE", "NPS"):
				nums = [float(a.answer_number) for a in qa if a.answer_number is not None]
				entry["avg_rating"] = round(sum(nums) / len(nums), 2) if nums else None

			elif q.question_type == "BOOLEAN":
				true_count = sum(1 for a in qa if a.answer_text and a.answer_text.lower() == "true")
				false_count = len(qa) - true_count
				entry["choice_distribution"] = {"true": true_count, "false": false_count}

			result[q.id] = entry

		return result

	def generate_enps(
		self,
		tenant_id: str,
		session: Session,
		*,
		entity_id: str | None = None,
	) -> dict[str, Any]:
		"""Find the most recent ENPS survey for the tenant/entity, compute NPS,
		and return with a naive trend (current vs previous quarter).

		Returns:
		  nps_score    — float | None
		  trend        — float | None (delta vs previous quarter)
		  breakdown    — full compute_nps output
		  survey_id    — str
		"""
		# find latest closed or published ENPS survey for this entity
		filters = [
			Survey.tenant_id == tenant_id,
			Survey.survey_type == "ENPS",
			Survey.status.in_(["PUBLISHED", "CLOSED"]),
		]
		if entity_id:
			filters.append(Survey.target_entity_id == entity_id)

		latest = session.execute(
			sa.select(Survey)
			.where(*filters)
			.order_by(Survey.created_at.desc())
			.limit(1)
		).scalar_one_or_none()

		if latest is None:
			return {"nps_score": None, "trend": None, "breakdown": {}, "survey_id": None}

		breakdown = self.compute_nps(latest.id, session)
		nps_score = breakdown.get("nps_score")

		# find previous survey for trend
		trend: float | None = None
		prev = session.execute(
			sa.select(Survey)
			.where(
				Survey.tenant_id == tenant_id,
				Survey.survey_type == "ENPS",
				Survey.status.in_(["PUBLISHED", "CLOSED"]),
				Survey.id != latest.id,
				*(([Survey.target_entity_id == entity_id]) if entity_id else []),
			)
			.order_by(Survey.created_at.desc())
			.limit(1)
		).scalar_one_or_none()

		if prev is not None and nps_score is not None:
			try:
				prev_breakdown = self.compute_nps(prev.id, session)
				prev_score = prev_breakdown.get("nps_score")
				if prev_score is not None:
					trend = round(nps_score - prev_score, 2)
			except SurveyServiceError:
				pass

		return {
			"nps_score": nps_score,
			"trend": trend,
			"breakdown": breakdown,
			"survey_id": latest.id,
		}

	# ── Internal helpers ─────────────────────────────────────────────────────

	def _get_survey(self, survey_id: str, session: Session) -> Survey:
		survey = session.execute(
			sa.select(Survey).where(Survey.id == survey_id)
		).scalar_one_or_none()
		if survey is None:
			raise SurveyNotFoundError(f"Survey {survey_id} not found")
		return survey

	def _build_answer(
		self,
		response_id: str,
		question: SurveyQuestion,
		raw_value: Any,
	) -> SurveyAnswer:
		answer = SurveyAnswer(response_id=response_id, question_id=question.id)
		qtype = question.question_type

		if qtype == "TEXT":
			answer.answer_text = str(raw_value) if raw_value is not None else None
		elif qtype == "SINGLE_CHOICE":
			answer.answer_choice = str(raw_value)
		elif qtype == "MULTI_CHOICE":
			answer.answer_choices = list(raw_value) if isinstance(raw_value, (list, tuple)) else [raw_value]
		elif qtype in ("RATING_SCALE", "NPS"):
			answer.answer_number = raw_value
		elif qtype == "BOOLEAN":
			answer.answer_text = "true" if raw_value else "false"
		elif qtype == "DATE":
			answer.answer_text = str(raw_value)
		else:
			answer.answer_text = str(raw_value)

		return answer


# ── BPM Action registrations ─────────────────────────────────────────────────

def _register_bpm_actions() -> None:
	try:
		from pgappforge.plugins.workflow.engine import BPMActionRegistry
	except ImportError:
		return

	@BPMActionRegistry.register(
		"platform.surveys.create_survey",
		"Create and send survey from workflow",
	)
	def _bpm_create_survey(
		record_ctx: dict,
		session: Any,
		title: str = "",
		survey_type: str = "CUSTOM",
		description: str | None = None,
		is_anonymous: bool = True,
		target_roles: list | None = None,
		target_entity_id: str | None = None,
		created_by: str | None = None,
		auto_publish: bool = False,
		**kw: Any,
	) -> dict:
		tenant_id = record_ctx.get("tenant_id", "")
		try:
			survey = Survey(
				tenant_id=tenant_id,
				title=title,
				survey_type=survey_type,
				description=description,
				is_anonymous=is_anonymous,
				target_roles=target_roles or [],
				target_entity_id=target_entity_id,
				created_by=created_by or record_ctx.get("actor_id", "system"),
			)
			session.add(survey)
			session.flush()

			result: dict = {"status": "ok", "survey_id": survey.id, "survey_status": survey.status}

			if auto_publish:
				svc = SurveyService()
				svc.publish_survey(survey.id, session)
				result["survey_status"] = "PUBLISHED"

			return result
		except Exception as exc:
			log.warning("bpm surveys.create_survey failed: %s", exc)
			return {"status": "error", "message": str(exc)}

	@BPMActionRegistry.register(
		"platform.surveys.get_results",
		"Get survey results from workflow",
	)
	def _bpm_get_results(
		record_ctx: dict,
		session: Any,
		survey_id: str = "",
		include_nps: bool = False,
		**kw: Any,
	) -> dict:
		try:
			svc = SurveyService()
			analytics = svc.get_response_analytics(survey_id, session)
			result: dict = {"status": "ok", "survey_id": survey_id, "analytics": analytics}
			if include_nps:
				try:
					nps = svc.compute_nps(survey_id, session)
					result["nps"] = nps
				except SurveyServiceError:
					result["nps"] = None
			return result
		except Exception as exc:
			log.warning("bpm surveys.get_results failed: %s", exc)
			return {"status": "error", "message": str(exc)}


_register_bpm_actions()
