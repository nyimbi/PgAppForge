from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.workflow.engine import BPMActionRegistry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	"""Fire-and-forget event emission."""
	try:
		_emit_event(event, session)
	except Exception:  # noqa: BLE001
		log.debug("Event bus unavailable; event %s not published", type(event).__name__)


from .events import (
	InternalCandidateFoundEvent,
	LearningRecommendedEvent,
	SkillDefinedEvent,
	SkillEndorsedEvent,
	SkillGapIdentifiedEvent,
)
from .models import (
	EmployeeSkill,
	JobRequiredSkill,
	Skill,
	SkillCategory,
	SkillDomain,
)

__all__ = [
	"SkillsServiceError",
	"SkillNotFoundError",
	"SkillsService",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SkillsServiceError(Exception):
	"""Base error for Skills service layer."""


class SkillNotFoundError(SkillsServiceError):
	"""Raised when a skill cannot be located."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SkillsService:
	"""Domain service for the Skills Taxonomy module."""

	# ------------------------------------------------------------------
	# Skill definition
	# ------------------------------------------------------------------

	def define_skill(
		self,
		code: str,
		name: str,
		category_id: str,
		tenant_id: str,
		session: Session,
		*,
		is_technical: bool = True,
		description: str | None = None,
	) -> Skill:
		"""Create or upsert a skill definition."""
		existing = session.execute(
			select(Skill).where(
				Skill.tenant_id == tenant_id,
				Skill.code == code,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.name = name
			existing.category_id = category_id
			existing.is_technical = is_technical
			if description is not None:
				existing.description = description
			session.flush()
			skill = existing
		else:
			skill = Skill(
				tenant_id=tenant_id,
				category_id=category_id,
				code=code,
				name=name,
				description=description,
				is_technical=is_technical,
			)
			session.add(skill)
			session.flush()

		_emit(
			SkillDefinedEvent(
				skill_id=skill.id,
				name=skill.name,
				category_id=skill.category_id,
				tenant_id=tenant_id,
			)
		)
		log.info("Skill defined: %s (%s) tenant=%s", code, skill.id, tenant_id)
		return skill

	# ------------------------------------------------------------------
	# Skill endorsement
	# ------------------------------------------------------------------

	def endorse_skill(
		self,
		employee_id: str,
		skill_id: str,
		proficiency: int,
		tenant_id: str,
		session: Session,
		*,
		endorsed_by: str | None = None,
		evidence_url: str | None = None,
	) -> EmployeeSkill:
		"""Upsert an employee skill record with new proficiency. Emits SkillEndorsedEvent."""
		assert 1 <= proficiency <= 5, f"proficiency must be 1-5, got {proficiency}"

		existing = session.execute(
			select(EmployeeSkill).where(
				EmployeeSkill.employee_id == employee_id,
				EmployeeSkill.skill_id == skill_id,
			)
		).scalar_one_or_none()

		from datetime import datetime, timezone
		now = datetime.now(tz=timezone.utc)

		if existing is not None:
			existing.proficiency_level = proficiency
			existing.endorsed_by = endorsed_by
			existing.verified_at = now
			if evidence_url is not None:
				existing.evidence_url = evidence_url
			session.flush()
			emp_skill = existing
		else:
			emp_skill = EmployeeSkill(
				tenant_id=tenant_id,
				employee_id=employee_id,
				skill_id=skill_id,
				proficiency_level=proficiency,
				endorsed_by=endorsed_by,
				verified_at=now,
				evidence_url=evidence_url,
			)
			session.add(emp_skill)
			session.flush()

		_emit(
			SkillEndorsedEvent(
				employee_id=employee_id,
				skill_id=skill_id,
				proficiency=proficiency,
				endorsed_by=endorsed_by or "",
			)
		)
		log.info(
			"Skill %s endorsed for employee %s at proficiency %d",
			skill_id, employee_id, proficiency,
		)
		return emp_skill

	# ------------------------------------------------------------------
	# Employee skill summary
	# ------------------------------------------------------------------

	def get_employee_skills(
		self,
		employee_id: str,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""Return all skills held by an employee with proficiency details."""
		rows = session.execute(
			select(EmployeeSkill, Skill).join(
				Skill, EmployeeSkill.skill_id == Skill.id
			).where(
				EmployeeSkill.employee_id == employee_id,
				Skill.tenant_id == tenant_id,
			)
		).all()

		return [
			{
				"skill_id": skill.id,
				"code": skill.code,
				"name": skill.name,
				"is_technical": skill.is_technical,
				"proficiency_level": emp_skill.proficiency_level,
				"endorsed_by": emp_skill.endorsed_by,
				"verified_at": emp_skill.verified_at.isoformat() if emp_skill.verified_at else None,
				"evidence_url": emp_skill.evidence_url,
			}
			for emp_skill, skill in rows
		]

	# ------------------------------------------------------------------
	# Skill gap analysis
	# ------------------------------------------------------------------

	def get_skill_gaps(
		self,
		employee_id: str,
		target_position_code: str,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""
		Compare employee skills against job requirements for a target position.

		Returns list of gaps: [{skill_id, name, required_level, current_level, gap}].
		Emits SkillGapIdentifiedEvent listing missing skill IDs.
		"""
		# Load job requirements for position
		requirements = session.execute(
			select(JobRequiredSkill, Skill).join(
				Skill, JobRequiredSkill.skill_id == Skill.id
			).where(
				JobRequiredSkill.tenant_id == tenant_id,
				JobRequiredSkill.position_code == target_position_code,
			)
		).all()

		if not requirements:
			return []

		# Load employee skills indexed by skill_id
		emp_skills_rows = session.execute(
			select(EmployeeSkill).where(
				EmployeeSkill.employee_id == employee_id,
			)
		).scalars().all()
		emp_by_skill: dict[str, int] = {es.skill_id: es.proficiency_level for es in emp_skills_rows}

		gaps: list[dict[str, Any]] = []
		missing_skill_ids: list[str] = []

		for req, skill in requirements:
			current_level = emp_by_skill.get(skill.id, 0)
			if current_level < req.required_level:
				gap_entry = {
					"skill_id": skill.id,
					"name": skill.name,
					"code": skill.code,
					"required_level": req.required_level,
					"current_level": current_level,
					"gap": req.required_level - current_level,
					"is_mandatory": req.is_mandatory,
				}
				gaps.append(gap_entry)
				missing_skill_ids.append(skill.id)

		if gaps:
			_emit(
				SkillGapIdentifiedEvent(
					employee_id=employee_id,
					target_position=target_position_code,
					missing_skill_ids=missing_skill_ids,
				)
			)
			log.info(
				"Skill gap analysis: employee=%s position=%s gaps=%d",
				employee_id, target_position_code, len(gaps),
			)

		return gaps

	# ------------------------------------------------------------------
	# Internal candidate matching
	# ------------------------------------------------------------------

	def find_internal_candidates(
		self,
		position_code: str,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""
		Score all employees against mandatory skill requirements for a position.

		match_score = matched_mandatory / total_mandatory * 100
		Returns list sorted by match_score desc: [{employee_id, match_score, matched, missing}]
		"""
		# Load mandatory job requirements
		requirements = session.execute(
			select(JobRequiredSkill, Skill).join(
				Skill, JobRequiredSkill.skill_id == Skill.id
			).where(
				JobRequiredSkill.tenant_id == tenant_id,
				JobRequiredSkill.position_code == position_code,
				JobRequiredSkill.is_mandatory.is_(True),
			)
		).all()

		if not requirements:
			return []

		total_mandatory = len(requirements)
		mandatory_reqs: list[tuple[str, int, str]] = [
			(skill.id, req.required_level, skill.name)
			for req, skill in requirements
		]

		# Load all employee skills for tenant (grouped by employee)
		all_emp_skills = session.execute(
			select(EmployeeSkill, Skill).join(
				Skill, EmployeeSkill.skill_id == Skill.id
			).where(
				Skill.tenant_id == tenant_id,
			)
		).all()

		# Group by employee_id
		by_employee: dict[str, dict[str, int]] = {}
		for emp_skill, skill in all_emp_skills:
			by_employee.setdefault(emp_skill.employee_id, {})[skill.id] = emp_skill.proficiency_level

		results: list[dict[str, Any]] = []
		for employee_id, skill_map in by_employee.items():
			matched: list[str] = []
			missing: list[str] = []
			for skill_id, required_level, skill_name in mandatory_reqs:
				current = skill_map.get(skill_id, 0)
				if current >= required_level:
					matched.append(skill_name)
				else:
					missing.append(skill_name)

			match_score = len(matched) / total_mandatory * 100

			_emit(
				InternalCandidateFoundEvent(
					position_code=position_code,
					employee_id=employee_id,
					match_score=match_score,
				)
			)

			results.append({
				"employee_id": employee_id,
				"match_score": round(match_score, 2),
				"matched": matched,
				"missing": missing,
			})

		results.sort(key=lambda r: r["match_score"], reverse=True)
		return results

	# ------------------------------------------------------------------
	# Learning recommendations
	# ------------------------------------------------------------------

	def recommend_learning(
		self,
		employee_id: str,
		target_position_code: str,
		tenant_id: str,
		session: Session,
	) -> list[dict[str, Any]]:
		"""
		For each skill gap, find LMS courses tagged with the skill code.

		Returns [{skill_id, skill_name, recommended_courses: [{course_id, title}]}].
		Emits LearningRecommendedEvent per skill with course IDs.
		"""
		gaps = self.get_skill_gaps(
			employee_id=employee_id,
			target_position_code=target_position_code,
			tenant_id=tenant_id,
			session=session,
		)

		recommendations: list[dict[str, Any]] = []

		for gap in gaps:
			skill_id = gap["skill_id"]
			skill_code = gap["code"]
			courses: list[dict[str, Any]] = []

			try:
				from pgappforge.plugins.erp.hcm.lms.models import LmsCourse
				# courses where tags JSONB array contains the skill_code
				lms_rows = session.execute(
					select(LmsCourse).where(
						LmsCourse.tenant_id == tenant_id,
						LmsCourse.status == "PUBLISHED",
						LmsCourse.tags.contains([skill_code]),
					)
				).scalars().all()
				courses = [{"course_id": c.id, "title": c.title} for c in lms_rows]
			except ImportError:
				log.debug("LMS plugin not available; skipping course lookup for skill %s", skill_code)

			course_ids = [c["course_id"] for c in courses]

			_emit(
				LearningRecommendedEvent(
					employee_id=employee_id,
					skill_id=skill_id,
					course_ids=course_ids,
				)
			)

			recommendations.append({
				"skill_id": skill_id,
				"skill_name": gap["name"],
				"gap": gap["gap"],
				"recommended_courses": courses,
			})

		return recommendations


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"hcm.skills.find_candidates",
	"Find internal candidates for position by skills",
)
def _bpm_find_candidates(
	record_ctx: dict,
	session: Any,
	position_code: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.skills.services import SkillsService
	except ImportError:
		return {"status": "error", "message": "hcm.skills plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = SkillsService()
		candidates = svc.find_internal_candidates(
			position_code=position_code,
			tenant_id=_tenant_id,
			session=session,
		)
		return {"status": "ok", "candidates": candidates, "count": len(candidates)}
	except Exception as exc:
		log.warning("bpm hcm.skills.find_candidates failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"hcm.skills.recommend_learning",
	"Recommend learning for skill gaps",
)
def _bpm_recommend_learning(
	record_ctx: dict,
	session: Any,
	employee_id: str = "",
	target_position_code: str = "",
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.hcm.skills.services import SkillsService
	except ImportError:
		return {"status": "error", "message": "hcm.skills plugin not installed"}
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = SkillsService()
		recs = svc.recommend_learning(
			employee_id=employee_id,
			target_position_code=target_position_code,
			tenant_id=_tenant_id,
			session=session,
		)
		return {"status": "ok", "recommendations": recs, "count": len(recs)}
	except Exception as exc:
		log.warning("bpm hcm.skills.recommend_learning failed: %s", exc)
		return {"status": "error", "message": str(exc)}
