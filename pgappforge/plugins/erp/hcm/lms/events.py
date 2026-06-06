from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from pgappforge.plugins.erp.foundation.events import DomainEvent

__all__ = [
	"CoursePublishedEvent",
	"EnrollmentCreatedEvent",
	"LessonCompletedEvent",
	"CourseCompletedEvent",
	"CertificateIssuedEvent",
	"MandatoryTrainingOverdueEvent",
]


@dataclass
class CoursePublishedEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.course.published", init=False)
	course_id: str = ""
	title: str = ""
	tenant_id: str = ""


@dataclass
class EnrollmentCreatedEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.enrollment.created", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	course_id: str = ""
	tenant_id: str = ""


@dataclass
class LessonCompletedEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.lesson.completed", init=False)
	enrollment_id: str = ""
	lesson_id: str = ""
	employee_id: str = ""
	score: int = 0


@dataclass
class CourseCompletedEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.course.completed", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	course_id: str = ""
	final_score: int = 0
	passed: bool = False


@dataclass
class CertificateIssuedEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.certificate.issued", init=False)
	certificate_id: str = ""
	employee_id: str = ""
	course_id: str = ""
	issued_at: datetime | None = None


@dataclass
class MandatoryTrainingOverdueEvent(DomainEvent):
	event_type: str = field(default="hcm.lms.mandatory.overdue", init=False)
	enrollment_id: str = ""
	employee_id: str = ""
	course_id: str = ""
	due_date: date | None = None
