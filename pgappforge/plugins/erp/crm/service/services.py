"""
pgappforge/plugins/erp/crm/service/services.py

ServiceCloudService — stateless business logic for the Service Cloud plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Key methods
-----------
  create_case(data, session) -> Case
      Creates a case, computes sla_breach_at from SLAPolicy, emits CaseCreatedEvent.

  escalate_case(case_id, escalated_to, session) -> Case
      Moves case to ESCALATED, re-computes SLA breach, emits CaseEscalatedEvent.

  resolve_case(case_id, resolution_notes, session) -> Case
      Moves case to RESOLVED, sets resolved_at, emits CaseResolvedEvent.

  close_case(case_id, csat_score, session) -> Case
      Moves RESOLVED → CLOSED, records CSAT, emits CaseClosedEvent.

  add_comment(case_id, data, session) -> CaseComment
      Appends a CaseComment; public comments emit notification hook.

  publish_article(article_id, session) -> KnowledgeArticle
      Moves article DRAFT/REVIEW → PUBLISHED, emits KnowledgeArticlePublishedEvent.

  submit_survey(data, session) -> SurveyResponse
      Records a survey response; emits SurveySubmittedEvent.

  check_sla_breaches(tenant_id, session) -> list[Case]
      Returns cases past sla_breach_at; emits SLABreachedEvent per case.

  case_report(tenant_id, filters, session) -> dict
      Returns structured report data (open cases, SLA compliance, CSAT avg).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ServiceCloudError(Exception):
	"""Base exception for Service Cloud service layer."""


class CaseNotFoundError(ServiceCloudError):
	pass


class SLAPolicyNotFoundError(ServiceCloudError):
	pass


class ArticleNotFoundError(ServiceCloudError):
	pass


class ServiceValidationError(ServiceCloudError):
	"""Business rule violation — surfaces as HTTP 422 in views."""


# ---------------------------------------------------------------------------
# ServiceCloudService
# ---------------------------------------------------------------------------

class ServiceCloudService:
	"""Stateless business logic for Service Cloud.

	Instantiate once; pass session per call.
	"""

	# ------------------------------------------------------------------
	# Case lifecycle
	# ------------------------------------------------------------------

	@staticmethod
	def create_case(data: dict[str, Any], session: Any) -> Any:
		"""Create a new support case and compute SLA breach timestamp.

		data keys: subject, description, priority, channel, account_id,
		           contact_id, owner_id, sla_policy_id, category, subcategory,
		           tenant_id, case_number
		"""
		from pgappforge.plugins.erp.crm.service.models import Case, SLAPolicy
		from pgappforge.plugins.erp.crm.service.events import CaseCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		tenant_id = data["tenant_id"]
		priority = data.get("priority", "P3")

		# Compute SLA breach time
		sla_breach_at = None
		sla_policy_id = data.get("sla_policy_id")
		if sla_policy_id:
			policy = session.execute(
				sa.select(SLAPolicy).where(
					SLAPolicy.id == sla_policy_id,
					SLAPolicy.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if policy:
				sla_breach_at = datetime.now(timezone.utc) + timedelta(minutes=policy.resolution_minutes)

		case = Case(
			tenant_id=tenant_id,
			case_number=data["case_number"],
			subject=data["subject"],
			description=data.get("description"),
			priority=priority,
			status="NEW",
			channel=data.get("channel", "WEB"),
			account_id=data.get("account_id"),
			contact_id=data.get("contact_id"),
			owner_id=data.get("owner_id"),
			escalated_to=None,
			sla_policy_id=sla_policy_id,
			sla_breach_at=sla_breach_at,
			category=data.get("category"),
			subcategory=data.get("subcategory"),
		)
		session.add(case)
		session.flush()

		emit_event(CaseCreatedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			account_id=data.get("account_id", ""),
			contact_id=data.get("contact_id", ""),
			priority=priority,
			channel=case.channel,
			owner_id=data.get("owner_id", ""),
		), session)

		log.info("ServiceCloudService.create_case: case %s created", case.case_number)
		return case

	@staticmethod
	def escalate_case(case_id: str, escalated_to: str, session: Any) -> Any:
		"""Escalate a case; re-compute SLA breach based on P1 policy if applicable."""
		from pgappforge.plugins.erp.crm.service.models import Case, SLAPolicy
		from pgappforge.plugins.erp.crm.service.events import CaseEscalatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.execute(
			sa.select(Case).where(Case.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status in ("RESOLVED", "CLOSED"):
			raise ServiceValidationError(f"Cannot escalate a {case.status} case")

		case.status = "ESCALATED"
		case.escalated_to = escalated_to
		case.priority = "P1"

		# Re-compute SLA with P1 policy
		if case.sla_policy_id:
			policy = session.execute(
				sa.select(SLAPolicy).where(SLAPolicy.id == case.sla_policy_id)
			).scalar_one_or_none()
			if policy:
				case.sla_breach_at = datetime.now(timezone.utc) + timedelta(
					minutes=policy.first_response_minutes
				)

		session.flush()

		emit_event(CaseEscalatedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=case.tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			escalated_to=escalated_to,
			priority=case.priority,
			sla_breach_at=case.sla_breach_at.isoformat() if case.sla_breach_at else "",
		), session)

		log.info("ServiceCloudService.escalate_case: %s escalated to %s", case.case_number, escalated_to)
		return case

	@staticmethod
	def resolve_case(case_id: str, resolution_notes: str, session: Any) -> Any:
		"""Mark a case RESOLVED and compute resolution time in minutes."""
		from pgappforge.plugins.erp.crm.service.models import Case
		from pgappforge.plugins.erp.crm.service.events import CaseResolvedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.execute(
			sa.select(Case).where(Case.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status in ("RESOLVED", "CLOSED"):
			raise ServiceValidationError(f"Case already {case.status}")

		now = datetime.now(timezone.utc)
		case.status = "RESOLVED"
		case.resolved_at = now
		case.resolution_notes = resolution_notes

		resolution_minutes = 0
		if case.created_at:
			delta = now - case.created_at
			resolution_minutes = int(delta.total_seconds() / 60)

		session.flush()

		emit_event(CaseResolvedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=case.tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			owner_id=case.owner_id or "",
			resolved_at=now.isoformat(),
			resolution_minutes=resolution_minutes,
		), session)

		log.info("ServiceCloudService.resolve_case: %s resolved in %dm", case.case_number, resolution_minutes)
		return case

	@staticmethod
	def close_case(case_id: str, csat_score: int | None, session: Any) -> Any:
		"""Close a resolved case and record optional CSAT score (1-5)."""
		from pgappforge.plugins.erp.crm.service.models import Case
		from pgappforge.plugins.erp.crm.service.events import CaseClosedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.execute(
			sa.select(Case).where(Case.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status != "RESOLVED":
			raise ServiceValidationError("Only RESOLVED cases can be closed")
		if csat_score is not None and not (1 <= csat_score <= 5):
			raise ServiceValidationError("CSAT score must be between 1 and 5")

		case.status = "CLOSED"
		if csat_score is not None:
			case.csat_score = csat_score
		session.flush()

		emit_event(CaseClosedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=case.tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			csat_score=csat_score or 0,
		), session)

		log.info("ServiceCloudService.close_case: %s closed csat=%s", case.case_number, csat_score)
		return case

	# ------------------------------------------------------------------
	# Comments
	# ------------------------------------------------------------------

	@staticmethod
	def add_comment(case_id: str, data: dict[str, Any], session: Any) -> Any:
		"""Append a comment/note to a case."""
		from pgappforge.plugins.erp.crm.service.models import Case, CaseComment

		case = session.execute(
			sa.select(Case).where(Case.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status == "CLOSED":
			raise ServiceValidationError("Cannot comment on a closed case")

		comment = CaseComment(
			tenant_id=case.tenant_id,
			case_id=case_id,
			author_id=data.get("author_id"),
			is_public=data.get("is_public", False),
			body=data["body"],
			channel=data.get("channel", "INTERNAL"),
		)
		session.add(comment)
		session.flush()
		log.debug("ServiceCloudService.add_comment: case %s comment added", case_id)
		return comment

	# ------------------------------------------------------------------
	# Knowledge
	# ------------------------------------------------------------------

	@staticmethod
	def publish_article(article_id: str, session: Any) -> Any:
		"""Move a knowledge article to PUBLISHED status."""
		from pgappforge.plugins.erp.crm.service.models import KnowledgeArticle
		from pgappforge.plugins.erp.crm.service.events import KnowledgeArticlePublishedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		article = session.execute(
			sa.select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
		).scalar_one_or_none()
		if article is None:
			raise ArticleNotFoundError(f"Article {article_id} not found")
		if article.status not in ("DRAFT", "REVIEW"):
			raise ServiceValidationError(f"Cannot publish article in status {article.status!r}")

		now = datetime.now(timezone.utc)
		article.status = "PUBLISHED"
		article.last_published_at = now
		session.flush()

		emit_event(KnowledgeArticlePublishedEvent(
			aggregate_id=article.id,
			aggregate_type="KnowledgeArticle",
			tenant_id=article.tenant_id,
			article_id=article.id,
			title=article.title,
			category=article.category or "",
			author_id=article.author_id or "",
		), session)

		log.info("ServiceCloudService.publish_article: %r published", article.title)
		return article

	# ------------------------------------------------------------------
	# Surveys
	# ------------------------------------------------------------------

	@staticmethod
	def submit_survey(data: dict[str, Any], session: Any) -> Any:
		"""Record a survey response for a closed case."""
		from pgappforge.plugins.erp.crm.service.models import Case, SurveyResponse
		from pgappforge.plugins.erp.crm.service.events import SurveySubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case_id = data["case_id"]
		case = session.execute(
			sa.select(Case).where(Case.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")

		survey_type = data["survey_type"]
		score = data["score"]
		limits = {"CSAT": (1, 5), "NPS": (0, 10), "CES": (1, 7)}
		lo, hi = limits.get(survey_type, (0, 10))
		if not (lo <= score <= hi):
			raise ServiceValidationError(f"{survey_type} score must be {lo}–{hi}, got {score}")

		response = SurveyResponse(
			tenant_id=case.tenant_id,
			case_id=case_id,
			contact_id=data.get("contact_id"),
			survey_type=survey_type,
			score=score,
			comment=data.get("comment"),
		)
		session.add(response)
		session.flush()

		emit_event(SurveySubmittedEvent(
			aggregate_id=response.id,
			aggregate_type="SurveyResponse",
			tenant_id=case.tenant_id,
			survey_response_id=response.id,
			case_id=case_id,
			contact_id=data.get("contact_id", ""),
			survey_type=survey_type,
			score=score,
		), session)

		log.info("ServiceCloudService.submit_survey: %s score=%s for case %s", survey_type, score, case_id)
		return response

	# ------------------------------------------------------------------
	# SLA monitoring
	# ------------------------------------------------------------------

	@staticmethod
	def check_sla_breaches(tenant_id: str, session: Any) -> list[Any]:
		"""Return open cases past their sla_breach_at; emit SLABreachedEvent per case."""
		from pgappforge.plugins.erp.crm.service.models import Case
		from pgappforge.plugins.erp.crm.service.events import SLABreachedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		now = datetime.now(timezone.utc)
		breached = session.execute(
			sa.select(Case).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("NEW", "OPEN", "PENDING_CUSTOMER", "ESCALATED")),
				Case.sla_breach_at <= now,
			)
		).scalars().all()

		for case in breached:
			emit_event(SLABreachedEvent(
				aggregate_id=case.id,
				aggregate_type="Case",
				tenant_id=case.tenant_id,
				case_id=case.id,
				case_number=case.case_number,
				priority=case.priority,
				breached_at=case.sla_breach_at.isoformat() if case.sla_breach_at else "",
				owner_id=case.owner_id or "",
			), session)

		log.info("ServiceCloudService.check_sla_breaches: %d breached cases for tenant %s", len(breached), tenant_id)
		return list(breached)

	# ------------------------------------------------------------------
	# Assignment
	# ------------------------------------------------------------------

	@staticmethod
	def assign_case(session: Any, case_id: str, agent_id: str, tenant_id: str) -> Any:
		"""Assign a case to an agent; moves status NEW→OPEN."""
		from pgappforge.plugins.erp.crm.service.models import Case

		case = session.execute(
			sa.select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status in ("RESOLVED", "CLOSED"):
			raise ServiceValidationError(f"Cannot assign a {case.status} case")

		case.owner_id = agent_id
		if case.status == "NEW":
			case.status = "OPEN"
		session.flush()
		log.info("ServiceCloudService.assign_case: %s → agent %s", case.case_number, agent_id)
		return case

	# ------------------------------------------------------------------
	# Case notes (public signature variant)
	# ------------------------------------------------------------------

	@staticmethod
	def add_case_note(
		session: Any,
		case_id: str,
		note_text: str,
		author_id: str,
		is_public: bool,
		tenant_id: str,
	) -> Any:
		"""Append a note/comment to a case.  Delegates to add_comment."""
		return ServiceCloudService.add_comment(
			case_id,
			{
				"body": note_text,
				"author_id": author_id,
				"is_public": is_public,
				"channel": "EMAIL" if is_public else "INTERNAL",
			},
			session,
		)

	# ------------------------------------------------------------------
	# Escalation (full signature)
	# ------------------------------------------------------------------

	@staticmethod
	def escalate_case(  # type: ignore[override]
		session: Any,
		case_id: str,
		escalated_to: str,
		reason: str,
		escalated_by: str,
		tenant_id: str,
	) -> Any:
		"""Escalate a case; writes CaseEscalation audit row."""
		from pgappforge.plugins.erp.crm.service.models import Case, SLAPolicy, CaseEscalation
		from pgappforge.plugins.erp.crm.service.events import CaseEscalatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.execute(
			sa.select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status in ("RESOLVED", "CLOSED"):
			raise ServiceValidationError(f"Cannot escalate a {case.status} case")

		case.status = "ESCALATED"
		case.escalated_to = escalated_to
		case.priority = "P1"

		if case.sla_policy_id:
			policy = session.execute(
				sa.select(SLAPolicy).where(SLAPolicy.id == case.sla_policy_id)
			).scalar_one_or_none()
			if policy:
				case.sla_breach_at = datetime.now(timezone.utc) + timedelta(
					minutes=policy.first_response_minutes
				)

		esc = CaseEscalation(
			tenant_id=tenant_id,
			case_id=case_id,
			escalated_to=escalated_to,
			escalated_by=escalated_by,
			reason=reason,
		)
		session.add(esc)
		session.flush()

		emit_event(CaseEscalatedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			escalated_to=escalated_to,
			priority=case.priority,
			sla_breach_at=case.sla_breach_at.isoformat() if case.sla_breach_at else "",
		), session)

		log.info(
			"ServiceCloudService.escalate_case: %s escalated to %s by %s",
			case.case_number, escalated_to, escalated_by,
		)
		return esc

	# ------------------------------------------------------------------
	# Resolution (full signature)
	# ------------------------------------------------------------------

	@staticmethod
	def resolve_case(  # type: ignore[override]
		session: Any,
		case_id: str,
		resolution_notes: str,
		resolved_by: str,
		tenant_id: str,
	) -> Any:
		"""Resolve a case; checks SLA breach; returns Case."""
		from pgappforge.plugins.erp.crm.service.models import Case
		from pgappforge.plugins.erp.crm.service.events import CaseResolvedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		case = session.execute(
			sa.select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if case.status in ("RESOLVED", "CLOSED"):
			raise ServiceValidationError(f"Case already {case.status}")

		now = datetime.now(timezone.utc)
		case.status = "RESOLVED"
		case.resolved_at = now
		case.resolution_notes = resolution_notes

		resolution_minutes = 0
		sla_breached = False
		if case.created_at:
			delta = now - case.created_at
			resolution_minutes = int(delta.total_seconds() / 60)
		if case.sla_breach_at and now > case.sla_breach_at:
			sla_breached = True

		session.flush()

		emit_event(CaseResolvedEvent(
			aggregate_id=case.id,
			aggregate_type="Case",
			tenant_id=case.tenant_id,
			case_id=case.id,
			case_number=case.case_number,
			owner_id=resolved_by,
			resolved_at=now.isoformat(),
			resolution_minutes=resolution_minutes,
		), session)

		log.info(
			"ServiceCloudService.resolve_case: %s resolved in %dm sla_breached=%s",
			case.case_number, resolution_minutes, sla_breached,
		)
		return case

	# ------------------------------------------------------------------
	# Knowledge base search
	# ------------------------------------------------------------------

	@staticmethod
	def search_knowledge_base(
		session: Any,
		query: str,
		category: str | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Full-text search of knowledge articles using PostgreSQL tsvector.

		Uses plainto_tsquery so callers don't need to manage tsquery syntax.
		Falls back gracefully to ILIKE if the query is empty.
		"""
		from pgappforge.plugins.erp.crm.service.models import KnowledgeArticle

		base = sa.select(KnowledgeArticle).where(
			KnowledgeArticle.status == "PUBLISHED",
		)
		if tenant_id:
			base = base.where(KnowledgeArticle.tenant_id == tenant_id)
		if category:
			base = base.where(KnowledgeArticle.category == category)

		if query.strip():
			tsquery = sa.func.plainto_tsquery("english", query)
			try:
				# Use the indexed tsvector column — hits ix_sc_ka_content_gin GIN index
				base = base.where(
					KnowledgeArticle.content_tsv.op("@@")(tsquery)
				).order_by(
					sa.func.ts_rank(KnowledgeArticle.content_tsv, tsquery).desc(),
					KnowledgeArticle.views.desc(),
				)
			except Exception:
				# Graceful fallback when content_tsv column not yet migrated
				base = base.where(
					sa.or_(
						KnowledgeArticle.title.ilike(f"%{query}%"),
						KnowledgeArticle.content.ilike(f"%{query}%"),
					)
				).order_by(KnowledgeArticle.views.desc())
		else:
			base = base.order_by(KnowledgeArticle.views.desc())
		articles = session.execute(base).scalars().all()

		return [
			{
				"id": a.id,
				"title": a.title,
				"category": a.category,
				"tags": a.tags,
				"views": a.views,
				"helpful_votes": a.helpful_votes,
				"author_id": a.author_id,
				"last_published_at": a.last_published_at.isoformat() if a.last_published_at else None,
			}
			for a in articles
		]

	# ------------------------------------------------------------------
	# Feedback
	# ------------------------------------------------------------------

	@staticmethod
	def submit_feedback(
		session: Any,
		case_id: str,
		rating: int,
		comments: str | None,
		is_resolved: bool,
		tenant_id: str,
	) -> Any:
		"""Record customer feedback on a resolved/closed case."""
		from pgappforge.plugins.erp.crm.service.models import Case, CaseFeedback

		case = session.execute(
			sa.select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id)
		).scalar_one_or_none()
		if case is None:
			raise CaseNotFoundError(f"Case {case_id} not found")
		if not (1 <= rating <= 5):
			raise ServiceValidationError(f"Rating must be 1–5, got {rating}")

		fb = CaseFeedback(
			tenant_id=tenant_id,
			case_id=case_id,
			rating=rating,
			comments=comments,
			is_resolved_as_expected=is_resolved,
		)
		session.add(fb)
		session.flush()
		log.info("ServiceCloudService.submit_feedback: case %s rating=%d", case_id, rating)
		return fb

	# ------------------------------------------------------------------
	# Service dashboard
	# ------------------------------------------------------------------

	@staticmethod
	def get_service_dashboard(session: Any, tenant_id: str) -> dict[str, Any]:
		"""Operational dashboard metrics for service managers.

		Returns:
		    open_cases: int
		    sla_breach_count: int
		    avg_resolution_hours: float | None
		    csat_score: float | None   (avg CaseFeedback rating)
		    first_contact_resolution_pct: float | None
		    cases_by_priority: dict[str, int]
		    cases_by_agent: dict[str, int]  (owner_id → open count)
		"""
		from pgappforge.plugins.erp.crm.service.models import Case, CaseFeedback
		import sqlalchemy.func as func

		now = datetime.now(timezone.utc)
		open_statuses = ("NEW", "OPEN", "PENDING_CUSTOMER", "ESCALATED")

		# Open case count
		open_cases: int = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(open_statuses),
			)
		).scalar() or 0

		# SLA breach count (open cases past breach deadline)
		sla_breach_count: int = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(open_statuses),
				Case.sla_breach_at <= now,
				Case.sla_breach_at.isnot(None),
			)
		).scalar() or 0

		# Avg resolution hours (resolved/closed)
		avg_resolution_seconds = session.execute(
			sa.select(
				func.avg(
					sa.func.extract(
						"epoch",
						Case.resolved_at - Case.created_at,
					)
				)
			).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("RESOLVED", "CLOSED")),
				Case.resolved_at.isnot(None),
			)
		).scalar()
		avg_resolution_hours = (
			round(float(avg_resolution_seconds) / 3600, 2) if avg_resolution_seconds else None
		)

		# CSAT from CaseFeedback
		csat_score = session.execute(
			sa.select(func.avg(CaseFeedback.rating)).where(
				CaseFeedback.tenant_id == tenant_id,
			)
		).scalar()
		csat_score = round(float(csat_score), 2) if csat_score else None

		# First contact resolution: single-comment cases that are resolved
		# Proxy: resolved cases with zero escalation events (case.escalated_to is None)
		total_resolved: int = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("RESOLVED", "CLOSED")),
			)
		).scalar() or 0
		fcr_count: int = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("RESOLVED", "CLOSED")),
				Case.escalated_to.is_(None),
			)
		).scalar() or 0
		first_contact_resolution_pct = (
			round(fcr_count / total_resolved * 100, 1) if total_resolved else None
		)

		# Cases by priority (open only)
		priority_rows = session.execute(
			sa.select(Case.priority, func.count(Case.id).label("cnt"))
			.where(Case.tenant_id == tenant_id, Case.status.in_(open_statuses))
			.group_by(Case.priority)
		).all()
		cases_by_priority = {r.priority: r.cnt for r in priority_rows}

		# Cases by agent (owner_id, open only)
		agent_rows = session.execute(
			sa.select(Case.owner_id, func.count(Case.id).label("cnt"))
			.where(
				Case.tenant_id == tenant_id,
				Case.status.in_(open_statuses),
				Case.owner_id.isnot(None),
			)
			.group_by(Case.owner_id)
		).all()
		cases_by_agent = {str(r.owner_id): r.cnt for r in agent_rows}

		return {
			"open_cases": open_cases,
			"sla_breach_count": sla_breach_count,
			"avg_resolution_hours": avg_resolution_hours,
			"csat_score": csat_score,
			"first_contact_resolution_pct": first_contact_resolution_pct,
			"cases_by_priority": cases_by_priority,
			"cases_by_agent": cases_by_agent,
		}

	# ------------------------------------------------------------------
	# Reporting
	# ------------------------------------------------------------------

	@staticmethod
	def case_report(tenant_id: str, filters: dict[str, Any], session: Any) -> dict[str, Any]:
		"""Structured report: open cases by priority, SLA compliance rate, avg CSAT.

		Returns a dict suitable for rendering by ReportForge templates.
		"""
		from pgappforge.plugins.erp.crm.service.models import Case, SurveyResponse
		import sqlalchemy.func as func

		# Open cases by priority
		priority_rows = session.execute(
			sa.select(Case.priority, func.count(Case.id).label("cnt"))
			.where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("NEW", "OPEN", "PENDING_CUSTOMER", "ESCALATED")),
			)
			.group_by(Case.priority)
		).all()
		open_by_priority = {row.priority: row.cnt for row in priority_rows}

		# SLA compliance: resolved cases where resolved_at <= sla_breach_at
		total_resolved = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("RESOLVED", "CLOSED")),
				Case.sla_breach_at.isnot(None),
			)
		).scalar() or 0

		on_time = session.execute(
			sa.select(func.count(Case.id)).where(
				Case.tenant_id == tenant_id,
				Case.status.in_(("RESOLVED", "CLOSED")),
				Case.sla_breach_at.isnot(None),
				Case.resolved_at <= Case.sla_breach_at,
			)
		).scalar() or 0

		sla_compliance_pct = round(on_time / total_resolved * 100, 1) if total_resolved else None

		# Average CSAT
		avg_csat = session.execute(
			sa.select(func.avg(SurveyResponse.score)).where(
				SurveyResponse.tenant_id == tenant_id,
				SurveyResponse.survey_type == "CSAT",
			)
		).scalar()

		return {
			"open_by_priority": open_by_priority,
			"sla_compliance_pct": sla_compliance_pct,
			"avg_csat": round(float(avg_csat), 2) if avg_csat else None,
			"total_resolved": total_resolved,
			"on_time_resolutions": on_time,
		}


__all__ = [
	"ServiceCloudService",
	"ServiceCloudError",
	"CaseNotFoundError",
	"SLAPolicyNotFoundError",
	"ArticleNotFoundError",
	"ServiceValidationError",
]
