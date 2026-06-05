"""
pgappforge/plugins/erp/industry/education/views.py

Flask views for the Education Cloud plugin.

Views:
  StudentView         — CRUD + generate transcript + flag at-risk actions
  CourseView          — CRUD with prerequisite management
  EnrollmentView      — CRUD + grade posting
  InterventionView    — CRUD with rich-text action plan
  AtRiskDashboardView — at-risk student list with risk distribution chart
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.education.services import EducationService
	return EducationService()


# ---------------------------------------------------------------------------
# StudentView
# ---------------------------------------------------------------------------

class StudentView(BaseView):
	"""Student CRUD.

	List columns : student_number, name (party_id denorm), program, gpa,
	               enrollment_status
	Widgets used  : RangeSliderWidget (GPA filter 0.0–4.0),
	                Select2 (program picker),
	                EmbeddingWidget (detail — student similarity)
	Actions       : Generate Transcript, Flag At-Risk

	GET  /education/students/                         — list
	GET  /education/students/<id>                     — detail
	POST /education/students/                         — create
	GET  /education/students/<id>/transcript          — generate transcript
	POST /education/students/<id>/flag-at-risk        — trigger intervention
	"""

	route_base = "/education/students"
	default_view = "list"

	# Widget hints consumed by the FAB form renderer
	widgets = {
		"gpa": {
			"widget": "RangeSliderWidget",
			"min": 0.0,
			"max": 4.0,
			"step": 0.01,
			"label": "GPA",
		},
		"program_id": {
			"widget": "Select2Widget",
			"label": "Program",
			"placeholder": "Select academic program…",
		},
		"detail_similarity": {
			"widget": "EmbeddingWidget",
			"label": "Similar Students",
			"endpoint": "/education/students/similar",
		},
	}

	list_columns = ["student_number", "program_name", "gpa", "enrollment_status", "year_of_study"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.education.models import Student
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("enrollment_status")
		gpa_min = request.args.get("gpa_min")
		gpa_max = request.args.get("gpa_max")

		q = sa.select(Student).order_by(Student.student_number)
		if tenant_id:
			q = q.where(Student.tenant_id == tenant_id)
		if status:
			q = q.where(Student.enrollment_status == status)
		if gpa_min is not None:
			q = q.where(Student.gpa >= Decimal(gpa_min))
		if gpa_max is not None:
			q = q.where(Student.gpa <= Decimal(gpa_max))

		students = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": s.id,
				"student_number": s.student_number,
				"program_name": s.program_name,
				"program_id": s.program_id,
				"gpa": str(s.gpa) if s.gpa is not None else None,
				"enrollment_status": s.enrollment_status,
				"year_of_study": s.year_of_study,
				"advisor_id": s.advisor_id,
				"total_credits_earned": s.total_credits_earned,
			}
			for s in students
		])

	@expose("/<string:student_id>")
	@has_access
	def detail(self, student_id: str):
		from pgappforge.plugins.erp.industry.education.models import Student
		session = _get_session()
		student = session.get(Student, student_id)
		if student is None:
			abort(404)
		return jsonify({
			"id": student.id,
			"tenant_id": student.tenant_id,
			"party_id": student.party_id,
			"student_number": student.student_number,
			"enrollment_status": student.enrollment_status,
			"program_id": student.program_id,
			"program_name": student.program_name,
			"year_of_study": student.year_of_study,
			"advisor_id": student.advisor_id,
			"gpa": str(student.gpa) if student.gpa is not None else None,
			"total_credits_earned": student.total_credits_earned,
			"credits_required": student.credits_required,
			"enrollment_date": student.enrollment_date.isoformat() if student.enrollment_date else None,
			"expected_graduation_date": (
				student.expected_graduation_date.isoformat()
				if student.expected_graduation_date else None
			),
			"financial_aid_status": student.financial_aid_status,
			"outstanding_fees_cents": student.outstanding_fees_cents,
			"notes": student.notes,
			# EmbeddingWidget metadata — consumed by frontend
			"_widget_hints": StudentView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.education.models import Student
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "student_number")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		student = Student(
			tenant_id=data["tenant_id"],
			student_number=data["student_number"],
			party_id=data.get("party_id"),
			program_id=data.get("program_id"),
			program_name=data.get("program_name"),
			year_of_study=data.get("year_of_study"),
			advisor_id=data.get("advisor_id"),
			enrollment_date=data.get("enrollment_date"),
			expected_graduation_date=data.get("expected_graduation_date"),
			credits_required=data.get("credits_required"),
			financial_aid_status=data.get("financial_aid_status"),
			enrollment_status=data.get("enrollment_status", "ENROLLED"),
		)
		session.add(student)
		session.commit()
		log.info("StudentView.create: %r", student.student_number)
		return jsonify({"student_id": student.id, "student_number": student.student_number}), 201

	@expose("/<string:student_id>/transcript")
	@has_access
	def transcript(self, student_id: str):
		"""Generate a full academic transcript for the student."""
		session = _get_session()
		try:
			result = _svc().generate_transcript(student_id, session)
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404

	@expose("/<string:student_id>/flag-at-risk", methods=["POST"])
	@has_access
	def flag_at_risk(self, student_id: str):
		"""Manually trigger an at-risk intervention for a student."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		trigger_type = data.get("trigger_type", "ACADEMIC")
		risk_score = Decimal(str(data.get("risk_score", "0.7500")))
		try:
			intervention = _svc().trigger_intervention(
				tenant_id=data.get("tenant_id", ""),
				student_id=student_id,
				trigger_type=trigger_type,
				risk_score=risk_score,
				assigned_advisor_id=data.get("assigned_advisor_id"),
				risk_factors=data.get("risk_factors", []),
				session=session,
			)
			session.commit()
			return jsonify({
				"intervention_id": intervention.id,
				"student_id": student_id,
				"trigger_type": trigger_type,
				"risk_score": str(risk_score),
				"status": intervention.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CourseView
# ---------------------------------------------------------------------------

class CourseView(BaseView):
	"""Course catalogue CRUD.

	Widgets used : Select2ManyWidget (prerequisites),
	               StarRatingWidget (average course rating, read-only)

	GET  /education/courses/        — list
	GET  /education/courses/<id>    — detail
	POST /education/courses/        — create
	PUT  /education/courses/<id>    — update
	"""

	route_base = "/education/courses"
	default_view = "list"

	widgets = {
		"prerequisites": {
			"widget": "Select2ManyWidget",
			"label": "Prerequisites",
			"placeholder": "Select prerequisite courses…",
			"allow_clear": True,
		},
		"avg_rating": {
			"widget": "StarRatingWidget",
			"label": "Average Course Rating",
			"max_stars": 5,
			"readonly": True,
		},
	}

	list_columns = ["course_code", "title", "credits", "instructor_name", "capacity", "current_enrollment", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.education.models import Course
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		department = request.args.get("department")
		status = request.args.get("status", "ACTIVE")

		q = sa.select(Course).order_by(Course.course_code)
		if tenant_id:
			q = q.where(Course.tenant_id == tenant_id)
		if department:
			q = q.where(Course.department == department)
		if status:
			q = q.where(Course.status == status)

		courses = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": c.id,
				"course_code": c.course_code,
				"title": c.title,
				"department": c.department,
				"credits": c.credits,
				"instructor_id": c.instructor_id,
				"instructor_name": c.instructor_name,
				"capacity": c.capacity,
				"current_enrollment": c.current_enrollment,
				"prerequisites": c.prerequisites,
				"level": c.level,
				"delivery_mode": c.delivery_mode,
				"status": c.status,
			}
			for c in courses
		])

	@expose("/<string:course_id>")
	@has_access
	def detail(self, course_id: str):
		from pgappforge.plugins.erp.industry.education.models import Course
		session = _get_session()
		course = session.get(Course, course_id)
		if course is None:
			abort(404)
		return jsonify({
			"id": course.id,
			"tenant_id": course.tenant_id,
			"course_code": course.course_code,
			"title": course.title,
			"description": course.description,
			"department": course.department,
			"credits": course.credits,
			"instructor_id": course.instructor_id,
			"instructor_name": course.instructor_name,
			"capacity": course.capacity,
			"current_enrollment": course.current_enrollment,
			"prerequisites": course.prerequisites,
			"level": course.level,
			"delivery_mode": course.delivery_mode,
			"status": course.status,
			"_widget_hints": CourseView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.education.models import Course
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "course_code", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		course = Course(
			tenant_id=data["tenant_id"],
			course_code=data["course_code"],
			title=data["title"],
			description=data.get("description"),
			department=data.get("department"),
			credits=int(data.get("credits", 3)),
			instructor_id=data.get("instructor_id"),
			instructor_name=data.get("instructor_name"),
			capacity=data.get("capacity"),
			prerequisites=data.get("prerequisites", []),
			level=data.get("level"),
			delivery_mode=data.get("delivery_mode"),
			status=data.get("status", "ACTIVE"),
		)
		session.add(course)
		session.commit()
		return jsonify({"course_id": course.id, "course_code": course.course_code}), 201


# ---------------------------------------------------------------------------
# EnrollmentView
# ---------------------------------------------------------------------------

class EnrollmentView(BaseView):
	"""Student enrollment CRUD + grade posting.

	Widgets used : RangeSliderWidget (attendance_pct 0–100)

	GET  /education/enrollments/                  — list
	GET  /education/enrollments/<id>             — detail
	POST /education/enrollments/                  — enroll student
	POST /education/enrollments/<id>/grade        — post grade
	"""

	route_base = "/education/enrollments"
	default_view = "list"

	widgets = {
		"attendance_pct": {
			"widget": "RangeSliderWidget",
			"label": "Attendance %",
			"min": 0,
			"max": 100,
			"step": 0.5,
			"unit": "%",
		},
	}

	list_columns = ["student_id", "course_id", "term", "grade", "attendance_pct", "status"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.education.models import Enrollment
		session = _get_session()
		student_id = request.args.get("student_id")
		course_id = request.args.get("course_id")
		term = request.args.get("term")
		status = request.args.get("status")

		q = (
			sa.select(Enrollment)
			.order_by(Enrollment.term.desc(), Enrollment.enrolled_at.desc())
			.limit(500)
		)
		if student_id:
			q = q.where(Enrollment.student_id == student_id)
		if course_id:
			q = q.where(Enrollment.course_id == course_id)
		if term:
			q = q.where(Enrollment.term == term)
		if status:
			q = q.where(Enrollment.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": e.id,
				"student_id": e.student_id,
				"course_id": e.course_id,
				"term": e.term,
				"enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
				"grade": e.grade,
				"grade_points": str(e.grade_points) if e.grade_points is not None else None,
				"grade_submitted_at": (
					e.grade_submitted_at.isoformat() if e.grade_submitted_at else None
				),
				"attendance_pct": str(e.attendance_pct) if e.attendance_pct is not None else None,
				"midterm_grade": e.midterm_grade,
				"status": e.status,
			}
			for e in rows
		])

	@expose("/<string:enrollment_id>")
	@has_access
	def detail(self, enrollment_id: str):
		from pgappforge.plugins.erp.industry.education.models import Enrollment
		session = _get_session()
		e = session.get(Enrollment, enrollment_id)
		if e is None:
			abort(404)
		return jsonify({
			"id": e.id,
			"tenant_id": e.tenant_id,
			"student_id": e.student_id,
			"course_id": e.course_id,
			"term": e.term,
			"enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
			"dropped_at": e.dropped_at.isoformat() if e.dropped_at else None,
			"grade": e.grade,
			"grade_points": str(e.grade_points) if e.grade_points is not None else None,
			"grade_submitted_at": (
				e.grade_submitted_at.isoformat() if e.grade_submitted_at else None
			),
			"attendance_pct": str(e.attendance_pct) if e.attendance_pct is not None else None,
			"midterm_grade": e.midterm_grade,
			"status": e.status,
			"notes": e.notes,
			"_widget_hints": EnrollmentView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Enroll a student in a course."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "student_id", "course_id", "term")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			enrollment = _svc().enroll_student(
				tenant_id=data["tenant_id"],
				student_id=data["student_id"],
				course_id=data["course_id"],
				term=data["term"],
				session=session,
			)
			session.commit()
			return jsonify({
				"enrollment_id": enrollment.id,
				"student_id": data["student_id"],
				"course_id": data["course_id"],
				"term": data["term"],
				"status": enrollment.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:enrollment_id>/grade", methods=["POST"])
	@has_access
	def post_grade(self, enrollment_id: str):
		"""Post a grade for an enrollment."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("grade") or data.get("grade_points") is None:
			return jsonify({"error": "grade and grade_points are required"}), 400
		try:
			enrollment = _svc().post_grade(
				enrollment_id=enrollment_id,
				grade=data["grade"],
				grade_points=Decimal(str(data["grade_points"])),
				session=session,
			)
			session.commit()
			return jsonify({
				"enrollment_id": enrollment_id,
				"grade": enrollment.grade,
				"grade_points": str(enrollment.grade_points),
				"status": enrollment.status,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# InterventionView
# ---------------------------------------------------------------------------

class InterventionView(BaseView):
	"""Student intervention CRUD.

	Widgets used : StarRatingWidget (risk_score — 1 star per 0.2, 5 = critical),
	               RichTextEditorWidget (action_plan)

	GET  /education/interventions/              — list
	GET  /education/interventions/<id>         — detail
	POST /education/interventions/              — create
	POST /education/interventions/<id>/resolve  — mark resolved
	"""

	route_base = "/education/interventions"
	default_view = "list"

	widgets = {
		"risk_score": {
			"widget": "StarRatingWidget",
			"label": "Risk Level",
			"max_stars": 5,
			"description": "1=low risk, 5=critical (risk_score 0.0–1.0 mapped to stars)",
		},
		"action_plan": {
			"widget": "RichTextEditorWidget",
			"label": "Action Plan",
			"toolbar": ["bold", "italic", "ul", "ol", "link"],
		},
	}

	list_columns = ["student_id", "trigger_type", "risk_score", "assigned_advisor_id", "status", "triggered_at"]

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.education.models import Intervention
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		student_id = request.args.get("student_id")
		status = request.args.get("status")

		q = (
			sa.select(Intervention)
			.order_by(Intervention.triggered_at.desc())
			.limit(500)
		)
		if tenant_id:
			q = q.where(Intervention.tenant_id == tenant_id)
		if student_id:
			q = q.where(Intervention.student_id == student_id)
		if status:
			q = q.where(Intervention.status == status)

		rows = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": i.id,
				"student_id": i.student_id,
				"trigger_type": i.trigger_type,
				"risk_score": str(i.risk_score),
				"assigned_advisor_id": i.assigned_advisor_id,
				"status": i.status,
				"triggered_at": i.triggered_at.isoformat() if i.triggered_at else None,
				"follow_up_date": i.follow_up_date.isoformat() if i.follow_up_date else None,
			}
			for i in rows
		])

	@expose("/<string:intervention_id>")
	@has_access
	def detail(self, intervention_id: str):
		from pgappforge.plugins.erp.industry.education.models import Intervention
		session = _get_session()
		i = session.get(Intervention, intervention_id)
		if i is None:
			abort(404)
		return jsonify({
			"id": i.id,
			"tenant_id": i.tenant_id,
			"student_id": i.student_id,
			"assigned_advisor_id": i.assigned_advisor_id,
			"trigger_type": i.trigger_type,
			"risk_score": str(i.risk_score),
			"risk_factors": i.risk_factors,
			"triggered_at": i.triggered_at.isoformat() if i.triggered_at else None,
			"action_plan": i.action_plan,
			"follow_up_date": i.follow_up_date.isoformat() if i.follow_up_date else None,
			"resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
			"status": i.status,
			"outcome": i.outcome,
			"notes": i.notes,
			"_widget_hints": InterventionView.widgets,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "student_id", "trigger_type", "risk_score")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400
		try:
			intervention = _svc().trigger_intervention(
				tenant_id=data["tenant_id"],
				student_id=data["student_id"],
				trigger_type=data["trigger_type"],
				risk_score=Decimal(str(data["risk_score"])),
				assigned_advisor_id=data.get("assigned_advisor_id"),
				risk_factors=data.get("risk_factors", []),
				session=session,
			)
			session.commit()
			return jsonify({
				"intervention_id": intervention.id,
				"student_id": data["student_id"],
				"trigger_type": data["trigger_type"],
				"risk_score": str(Decimal(str(data["risk_score"]))),
				"status": intervention.status,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:intervention_id>/resolve", methods=["POST"])
	@has_access
	def resolve(self, intervention_id: str):
		"""Mark an intervention as resolved with outcome notes."""
		from pgappforge.plugins.erp.industry.education.models import Intervention
		session = _get_session()
		data = request.get_json(force=True) or {}
		i = session.get(Intervention, intervention_id)
		if i is None:
			abort(404)
		if i.status in ("RESOLVED", "CLOSED"):
			return jsonify({"error": f"Intervention is already {i.status!r}"}), 422
		i.status = "RESOLVED"
		i.resolved_at = datetime.now(timezone.utc)
		i.outcome = data.get("outcome", "")
		session.commit()
		return jsonify({
			"intervention_id": intervention_id,
			"status": "RESOLVED",
			"resolved_at": i.resolved_at.isoformat(),
		})


# ---------------------------------------------------------------------------
# AtRiskDashboardView
# ---------------------------------------------------------------------------

class AtRiskDashboardView(BaseView):
	"""At-risk student dashboard.

	Shows at-risk students with their risk factors and intervention status.
	Uses AdvancedChartsWidget for risk score distribution.

	GET /education/at-risk/           — at-risk student list
	GET /education/at-risk/chart-data — risk distribution data for charts
	"""

	route_base = "/education/at-risk"
	default_view = "index"

	widgets = {
		"risk_distribution": {
			"widget": "AdvancedChartsWidget",
			"chart_type": "histogram",
			"label": "Risk Score Distribution",
			"x_label": "Risk Score Bucket",
			"y_label": "Number of Students",
			"data_endpoint": "/education/at-risk/chart-data",
		},
	}

	@expose("/")
	@has_access
	def index(self):
		"""Return at-risk students with risk factors and open intervention status."""
		from pgappforge.plugins.erp.industry.education.models import Intervention, Student
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		gpa_threshold = float(request.args.get("gpa_min", "2.0"))
		attendance_threshold = float(request.args.get("attendance_min", "75"))

		try:
			at_risk = _svc().identify_at_risk_students(
				tenant_id=tenant_id,
				threshold_gpa=gpa_threshold,
				attendance_threshold=attendance_threshold,
				session=session,
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

		# Fetch open interventions for these students
		if at_risk:
			student_ids = [s.id for s in at_risk]
			open_interventions = session.execute(
				sa.select(Intervention).where(
					Intervention.student_id.in_(student_ids),
					Intervention.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]),
				)
			).scalars().all()
			interventions_by_student: dict[str, list[dict]] = {}
			for iv in open_interventions:
				interventions_by_student.setdefault(iv.student_id, []).append({
					"intervention_id": iv.id,
					"trigger_type": iv.trigger_type,
					"risk_score": str(iv.risk_score),
					"status": iv.status,
					"assigned_advisor_id": iv.assigned_advisor_id,
				})
		else:
			interventions_by_student = {}

		return jsonify({
			"tenant_id": tenant_id,
			"thresholds": {
				"gpa": gpa_threshold,
				"attendance_pct": attendance_threshold,
			},
			"at_risk_count": len(at_risk),
			"students": [
				{
					"student_id": s.id,
					"student_number": s.student_number,
					"program_name": s.program_name,
					"gpa": str(s.gpa) if s.gpa is not None else None,
					"enrollment_status": s.enrollment_status,
					"advisor_id": s.advisor_id,
					"open_interventions": interventions_by_student.get(s.id, []),
				}
				for s in at_risk
			],
			"_widget_hints": AtRiskDashboardView.widgets,
		})

	@expose("/chart-data")
	@has_access
	def chart_data(self):
		"""Risk score histogram data for AdvancedChartsWidget.

		Buckets: 0.0–0.2, 0.2–0.4, 0.4–0.6, 0.6–0.8, 0.8–1.0
		"""
		from pgappforge.plugins.erp.industry.education.models import Intervention
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = sa.select(Intervention.risk_score).where(
			Intervention.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"])
		)
		if tenant_id:
			q = q.where(Intervention.tenant_id == tenant_id)

		scores = [float(r) for r in session.execute(q).scalars().all()]

		buckets = [
			{"label": "0.0–0.2 (Low)", "min": 0.0, "max": 0.2, "count": 0},
			{"label": "0.2–0.4", "min": 0.2, "max": 0.4, "count": 0},
			{"label": "0.4–0.6 (Medium)", "min": 0.4, "max": 0.6, "count": 0},
			{"label": "0.6–0.8 (High)", "min": 0.6, "max": 0.8, "count": 0},
			{"label": "0.8–1.0 (Critical)", "min": 0.8, "max": 1.0, "count": 0},
		]
		for score in scores:
			for bucket in buckets:
				if bucket["min"] <= score < bucket["max"] or (
					bucket["max"] == 1.0 and score == 1.0
				):
					bucket["count"] += 1
					break

		return jsonify({
			"chart_type": "histogram",
			"title": "Active Intervention Risk Distribution",
			"data": [{"x": b["label"], "y": b["count"]} for b in buckets],
		})


__all__ = [
	"StudentView",
	"CourseView",
	"EnrollmentView",
	"InterventionView",
	"AtRiskDashboardView",
]
