"""
pgappforge/plugins/erp/industry/education/events.py

Domain events for the Education plugin.

Events emitted:
  education.student.enrolled         — student enrolled in a course
  education.student.grade_submitted  — grade recorded for enrollment
  education.student.at_risk          — intervention triggered by risk score
  education.student.graduated        — student status changed to GRADUATED
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class StudentEnrolledEvent(DomainEvent):
	event_type: str = "education.student.enrolled"
	enrollment_id: str = ""
	student_id: str = ""
	student_number: str = ""
	course_id: str = ""
	course_code: str = ""
	term: str = ""


@dataclass
class GradeSubmittedEvent(DomainEvent):
	event_type: str = "education.student.grade_submitted"
	enrollment_id: str = ""
	student_id: str = ""
	course_id: str = ""
	term: str = ""
	grade: str = ""
	grade_points: str = ""  # Decimal string


@dataclass
class StudentAtRiskEvent(DomainEvent):
	event_type: str = "education.student.at_risk"
	intervention_id: str = ""
	student_id: str = ""
	student_number: str = ""
	trigger_type: str = ""
	risk_score: str = ""  # Decimal string
	assigned_advisor_id: str = ""


@dataclass
class StudentGraduatedEvent(DomainEvent):
	event_type: str = "education.student.graduated"
	student_id: str = ""
	student_number: str = ""
	program_id: str = ""
	graduation_date: str = ""  # ISO date
	final_gpa: str = ""        # Decimal string


__all__ = [
	"StudentEnrolledEvent",
	"GradeSubmittedEvent",
	"StudentAtRiskEvent",
	"StudentGraduatedEvent",
]
