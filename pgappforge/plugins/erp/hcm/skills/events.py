from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"SkillDefinedEvent",
	"SkillEndorsedEvent",
	"SkillGapIdentifiedEvent",
	"InternalCandidateFoundEvent",
	"LearningRecommendedEvent",
]


@dataclass
class SkillDefinedEvent(DomainEvent):
	event_type: str = field(default="hcm.skills.defined", init=False)
	skill_id: str = ""
	name: str = ""
	category_id: str = ""
	tenant_id: str = ""


@dataclass
class SkillEndorsedEvent(DomainEvent):
	event_type: str = field(default="hcm.skills.endorsed", init=False)
	employee_id: str = ""
	skill_id: str = ""
	proficiency: int = 0
	endorsed_by: str = ""


@dataclass
class SkillGapIdentifiedEvent(DomainEvent):
	event_type: str = field(default="hcm.skills.gap.identified", init=False)
	employee_id: str = ""
	target_position: str = ""
	missing_skill_ids: list = field(default_factory=list)


@dataclass
class InternalCandidateFoundEvent(DomainEvent):
	event_type: str = field(default="hcm.skills.candidate.found", init=False)
	position_code: str = ""
	employee_id: str = ""
	match_score: float = 0.0


@dataclass
class LearningRecommendedEvent(DomainEvent):
	event_type: str = field(default="hcm.skills.learning.recommended", init=False)
	employee_id: str = ""
	skill_id: str = ""
	course_ids: list = field(default_factory=list)
