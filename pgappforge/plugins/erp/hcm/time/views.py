"""
pgappforge/plugins/erp/hcm/time/views.py

Flask views for the HCM Time & Attendance plugin.

Registered views:
  ShiftDefinitionView   — CRUD
  AttendanceView        — clock-in/out + list
  LeaveRequestView      — submit/approve/reject/cancel
  TimesheetView         — CRUD + submit/approve/reject
  TimeReportView        — 3 canned reports:
                          * Overtime Summary
                          * Leave Balance Report
                          * Attendance Summary
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# ShiftDefinitionView
# ---------------------------------------------------------------------------

class ShiftDefinitionView(BaseERPView):
	"""Shift definition CRUD.

	GET  /hcm/time/shifts/       — list
	GET  /hcm/time/shifts/<id>   — detail
	POST /hcm/time/shifts/       — create
	PUT  /hcm/time/shifts/<id>   — update
	"""

	route_base = "/hcm/time/shifts"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.hcm.time.models import ShiftDefinition
		session = _get_session()
		q = sa.select(ShiftDefinition).order_by(ShiftDefinition.shift_code)
		if request.args.get("tenant_id"):
			q = q.where(ShiftDefinition.tenant_id == request.args["tenant_id"])
		shifts = session.execute(q.limit(200)).scalars().all()
		return jsonify({"shifts": [
			{
				"id": s.id, "shift_code": s.shift_code, "name": s.name,
				"start_time": str(s.start_time), "end_time": str(s.end_time),
				"break_minutes": s.break_minutes, "is_overnight": s.is_overnight,
				"days_of_week": s.days_of_week,
			}
			for s in shifts
		]})

	@expose("/<string:shift_id>")
	@has_access
	def detail(self, shift_id: str):
		from pgappforge.plugins.erp.hcm.time.models import ShiftDefinition
		session = _get_session()
		s = session.get(ShiftDefinition, shift_id)
		if s is None:
			abort(404)
		return jsonify({
			"id": s.id, "tenant_id": s.tenant_id,
			"shift_code": s.shift_code, "name": s.name,
			"start_time": str(s.start_time), "end_time": str(s.end_time),
			"break_minutes": s.break_minutes, "is_overnight": s.is_overnight,
			"days_of_week": s.days_of_week,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.time.models import ShiftDefinition
		from datetime import time as time_type
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "shift_code", "name", "start_time", "end_time")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		def _parse_time(s: str) -> time_type:
			h, m = (s.split(":") + ["00"])[:2]
			return time_type(int(h), int(m))

		s = ShiftDefinition(
			tenant_id=data["tenant_id"],
			shift_code=data["shift_code"].upper(),
			name=data["name"],
			start_time=_parse_time(data["start_time"]),
			end_time=_parse_time(data["end_time"]),
			break_minutes=int(data.get("break_minutes", 0)),
			is_overnight=bool(data.get("is_overnight", False)),
			days_of_week=data.get("days_of_week", [0, 1, 2, 3, 4]),
		)
		session.add(s)
		session.commit()
		return jsonify({"ok": True, "id": s.id}), 201

	@expose("/<string:shift_id>", methods=["PUT"])
	@has_access
	def update(self, shift_id: str):
		from pgappforge.plugins.erp.hcm.time.models import ShiftDefinition
		session = _get_session()
		s = session.get(ShiftDefinition, shift_id)
		if s is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for field in ("name", "break_minutes", "is_overnight", "days_of_week"):
			if field in data:
				setattr(s, field, data[field])
		s.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# AttendanceView
# ---------------------------------------------------------------------------

class AttendanceView(BaseERPView):
	"""Clock-in/out and attendance list.

	POST /hcm/time/attendance/clock-in              — clock in
	POST /hcm/time/attendance/clock-out             — clock out
	GET  /hcm/time/attendance/<employee_id>         — list records for employee
	GET  /hcm/time/attendance/<employee_id>/<date>  — detail for date
	"""

	route_base = "/hcm/time/attendance"
	default_view = "list"

	@expose("/clock-in", methods=["POST"])
	@has_access
	def clock_in(self):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimeServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		employee_id = data.get("employee_id")
		if not employee_id:
			return jsonify({"ok": False, "error": "employee_id required"}), 400
		try:
			record = TimeService().clock_in(
				employee_id, session,
				location=data.get("location"),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": record.id,
				"attendance_date": record.attendance_date.isoformat(),
				"clock_in": record.clock_in.isoformat() if record.clock_in else None,
			}), 201
		except TimeServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/clock-out", methods=["POST"])
	@has_access
	def clock_out(self):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimeServiceError
		from decimal import Decimal
		session = _get_session()
		data = request.get_json(silent=True) or {}
		employee_id = data.get("employee_id")
		if not employee_id:
			return jsonify({"ok": False, "error": "employee_id required"}), 400
		try:
			record = TimeService().clock_out(
				employee_id, session,
				standard_hours=Decimal(str(data.get("standard_hours", 8))),
			)
			session.commit()
			return jsonify({
				"ok": True, "id": record.id,
				"clock_out": record.clock_out.isoformat() if record.clock_out else None,
				"regular_hours": str(record.regular_hours),
				"overtime_hours": str(record.overtime_hours),
			})
		except TimeServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:employee_id>")
	@has_access
	def list(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.time.models import AttendanceRecord
		from datetime import date as date_type, timedelta
		session = _get_session()
		days = int(request.args.get("days", 30))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)
		records = session.execute(
			sa.select(AttendanceRecord)
			.where(AttendanceRecord.employee_id == employee_id)
			.where(AttendanceRecord.attendance_date >= since)
			.order_by(sa.desc(AttendanceRecord.attendance_date))
		).scalars().all()
		return jsonify({"attendance": [
			{
				"id": r.id,
				"attendance_date": r.attendance_date.isoformat(),
				"clock_in": r.clock_in.isoformat() if r.clock_in else None,
				"clock_out": r.clock_out.isoformat() if r.clock_out else None,
				"regular_hours": str(r.regular_hours) if r.regular_hours is not None else None,
				"overtime_hours": str(r.overtime_hours),
				"status": r.status,
			}
			for r in records
		]})


# ---------------------------------------------------------------------------
# LeaveRequestView
# ---------------------------------------------------------------------------

class LeaveRequestView(BaseERPView):
	"""Leave request workflow.

	POST /hcm/time/leave/                          — submit request
	GET  /hcm/time/leave/<employee_id>             — list requests for employee
	POST /hcm/time/leave/<request_id>/approve      — approve
	POST /hcm/time/leave/<request_id>/reject       — reject
	POST /hcm/time/leave/<request_id>/cancel       — cancel
	GET  /hcm/time/leave/balance/<employee_id>     — leave balances
	"""

	route_base = "/hcm/time/leave"
	default_view = "list"

	@expose("/", methods=["POST"])
	@has_access
	def submit(self):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, LeaveError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			req = TimeService().submit_leave_request(data, session)
			session.commit()
			return jsonify({
				"ok": True, "id": req.id,
				"days_requested": str(req.days_requested),
				"status": req.status,
			}), 201
		except LeaveError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:employee_id>")
	@has_access
	def list(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.time.models import LeaveRequest
		session = _get_session()
		q = (
			sa.select(LeaveRequest)
			.where(LeaveRequest.employee_id == employee_id)
			.order_by(sa.desc(LeaveRequest.start_date))
		)
		if request.args.get("status"):
			q = q.where(LeaveRequest.status == request.args["status"].upper())
		reqs = session.execute(q.limit(200)).scalars().all()
		return jsonify({"leave_requests": [
			{
				"id": r.id, "leave_type": r.leave_type,
				"start_date": r.start_date.isoformat() if r.start_date else None,
				"end_date": r.end_date.isoformat() if r.end_date else None,
				"days_requested": str(r.days_requested),
				"status": r.status, "approver_id": r.approver_id,
			}
			for r in reqs
		]})

	@expose("/<string:request_id>/approve", methods=["POST"])
	@has_access
	def approve(self, request_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, LeaveError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id", "")
		try:
			req = TimeService().approve_leave_request(request_id, approver_id, session)
			session.commit()
			return jsonify({"ok": True, "status": req.status})
		except LeaveError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:request_id>/reject", methods=["POST"])
	@has_access
	def reject(self, request_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, LeaveError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			req = TimeService().reject_leave_request(
				request_id,
				data.get("approver_id", ""),
				data.get("reason", ""),
				session,
			)
			session.commit()
			return jsonify({"ok": True, "status": req.status})
		except LeaveError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:request_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, request_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, LeaveError
		session = _get_session()
		try:
			req = TimeService().cancel_leave_request(request_id, session)
			session.commit()
			return jsonify({"ok": True, "status": req.status})
		except LeaveError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/balance/<string:employee_id>")
	@has_access
	def balance(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.time.models import LeaveBalance
		session = _get_session()
		year = int(request.args.get("year", datetime.now(timezone.utc).year))
		balances = session.execute(
			sa.select(LeaveBalance)
			.where(LeaveBalance.employee_id == employee_id)
			.where(LeaveBalance.balance_year == year)
		).scalars().all()
		return jsonify({"leave_balances": [
			{
				"id": b.id, "leave_type": b.leave_type,
				"balance_year": b.balance_year,
				"accrued": str(b.accrued), "taken": str(b.taken),
				"pending": str(b.pending), "remaining": str(b.remaining),
			}
			for b in balances
		]})


# ---------------------------------------------------------------------------
# TimesheetView
# ---------------------------------------------------------------------------

class TimesheetView(BaseERPView):
	"""Timesheet management.

	POST /hcm/time/timesheets/                     — create DRAFT
	GET  /hcm/time/timesheets/<id>                 — detail + entries
	POST /hcm/time/timesheets/<id>/entries         — add time entry
	POST /hcm/time/timesheets/<id>/submit          — submit for approval
	POST /hcm/time/timesheets/<id>/approve         — approve
	POST /hcm/time/timesheets/<id>/reject          — reject → DRAFT
	GET  /hcm/time/timesheets/employee/<employee_id> — list for employee
	"""

	route_base = "/hcm/time/timesheets"
	default_view = "list_for_employee"

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimesheetError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			ts = TimeService().create_timesheet(data, session)
			session.commit()
			return jsonify({"ok": True, "id": ts.id, "status": ts.status}), 201
		except TimesheetError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:timesheet_id>")
	@has_access
	def detail(self, timesheet_id: str):
		from pgappforge.plugins.erp.hcm.time.models import Timesheet
		session = _get_session()
		ts = session.get(Timesheet, timesheet_id)
		if ts is None:
			abort(404)
		return jsonify({
			"id": ts.id, "employee_id": ts.employee_id,
			"week_start": ts.week_start.isoformat() if ts.week_start else None,
			"total_regular_hours": str(ts.total_regular_hours),
			"total_overtime_hours": str(ts.total_overtime_hours),
			"status": ts.status, "approved_by": ts.approved_by,
			"entries": [
				{
					"id": e.id,
					"entry_date": e.entry_date.isoformat() if e.entry_date else None,
					"project_code": e.project_code, "cost_center": e.cost_center,
					"regular_hours": str(e.regular_hours),
					"overtime_hours": str(e.overtime_hours),
					"description": e.description,
				}
				for e in ts.entries
			],
		})

	@expose("/<string:timesheet_id>/entries", methods=["POST"])
	@has_access
	def add_entry(self, timesheet_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimesheetError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		data["timesheet_id"] = timesheet_id
		try:
			entry = TimeService().add_time_entry(data, session)
			session.commit()
			return jsonify({
				"ok": True, "id": entry.id,
				"regular_hours": str(entry.regular_hours),
				"overtime_hours": str(entry.overtime_hours),
			}), 201
		except TimesheetError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:timesheet_id>/submit", methods=["POST"])
	@has_access
	def submit(self, timesheet_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimesheetError
		session = _get_session()
		try:
			ts = TimeService().submit_timesheet(timesheet_id, session)
			session.commit()
			return jsonify({"ok": True, "status": ts.status})
		except TimesheetError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:timesheet_id>/approve", methods=["POST"])
	@has_access
	def approve(self, timesheet_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimesheetError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		approver_id = data.get("approver_id", "")
		try:
			ts = TimeService().approve_timesheet(timesheet_id, approver_id, session)
			session.commit()
			return jsonify({"ok": True, "status": ts.status})
		except TimesheetError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:timesheet_id>/reject", methods=["POST"])
	@has_access
	def reject(self, timesheet_id: str):
		from pgappforge.plugins.erp.hcm.time.services import TimeService, TimesheetError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		try:
			ts = TimeService().reject_timesheet(timesheet_id, data.get("approver_id", ""), session)
			session.commit()
			return jsonify({"ok": True, "status": ts.status})
		except TimesheetError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/employee/<string:employee_id>")
	@has_access
	def list_for_employee(self, employee_id: str):
		from pgappforge.plugins.erp.hcm.time.models import Timesheet
		session = _get_session()
		q = (
			sa.select(Timesheet)
			.where(Timesheet.employee_id == employee_id)
			.order_by(sa.desc(Timesheet.week_start))
		)
		if request.args.get("status"):
			q = q.where(Timesheet.status == request.args["status"].upper())
		timesheets = session.execute(q.limit(52)).scalars().all()
		return jsonify({"timesheets": [
			{
				"id": ts.id,
				"week_start": ts.week_start.isoformat() if ts.week_start else None,
				"total_regular_hours": str(ts.total_regular_hours),
				"total_overtime_hours": str(ts.total_overtime_hours),
				"status": ts.status,
			}
			for ts in timesheets
		]})


# ---------------------------------------------------------------------------
# TimeReportView
# ---------------------------------------------------------------------------

class TimeReportView(BaseERPView):
	"""Time & Attendance canned reports.

	GET /hcm/time/reports/overtime         — overtime summary by employee
	GET /hcm/time/reports/leave-balances   — leave balance snapshot
	GET /hcm/time/reports/attendance       — attendance status summary
	"""

	route_base = "/hcm/time/reports"
	default_view = "overtime"

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Time & Attendance dashboard — KPIs + attendance heatmap."""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet, AttendanceRecord
		from datetime import timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		now = datetime.now(timezone.utc)
		week_start = now.date() - timedelta(days=now.weekday())

		# KPIs
		q_submitted = sa.select(sa.func.count(Timesheet.id)).where(
			Timesheet.week_start == week_start,
			Timesheet.status.in_(("SUBMITTED", "APPROVED")),
		)
		q_pending = sa.select(sa.func.count(Timesheet.id)).where(
			Timesheet.week_start == week_start,
			Timesheet.status == "SUBMITTED",
		)
		q_hours = sa.select(
			sa.func.coalesce(sa.func.sum(Timesheet.total_regular_hours), 0),
			sa.func.coalesce(sa.func.sum(Timesheet.total_overtime_hours), 0),
		).where(Timesheet.week_start == week_start)
		if tenant_id:
			q_submitted = q_submitted.where(Timesheet.tenant_id == tenant_id)
			q_pending = q_pending.where(Timesheet.tenant_id == tenant_id)
			q_hours = q_hours.where(Timesheet.tenant_id == tenant_id)

		timesheets_submitted = session.execute(q_submitted).scalar() or 0
		pending_approval = session.execute(q_pending).scalar() or 0
		reg_h, ot_h = session.execute(q_hours).one()
		hours_this_period = float(reg_h or 0)
		overtime_hours = float(ot_h or 0)

		kpi_html = self.kpi_cards([
			{"label": "Timesheets Submitted", "value": timesheets_submitted, "format": "integer", "color": "#1a56db", "icon": "fa-file-alt"},
			{"label": "Hours This Period", "value": hours_this_period, "format": "number", "color": "#057a55", "icon": "fa-clock"},
			{"label": "Pending Approval", "value": pending_approval, "format": "integer", "color": "#d97706", "icon": "fa-hourglass-half"},
			{"label": "Overtime Hours", "value": overtime_hours, "format": "number", "color": "#e02424", "icon": "fa-exclamation-circle"},
		])

		# Attendance heatmap — last 90 days
		since = now.date() - timedelta(days=90)
		q_att = (
			sa.select(
				AttendanceRecord.attendance_date.label("date"),
				sa.func.coalesce(
					sa.func.sum(
						sa.cast(
							sa.func.extract("epoch", AttendanceRecord.clock_out - AttendanceRecord.clock_in) / 3600,
							sa.Numeric,
						)
					),
					0,
				).label("hours"),
			)
			.where(AttendanceRecord.attendance_date >= since)
			.group_by(AttendanceRecord.attendance_date)
			.order_by(AttendanceRecord.attendance_date)
		)
		if tenant_id:
			q_att = q_att.where(AttendanceRecord.tenant_id == tenant_id)
		att_rows = [
			{"date": str(r.date), "hours": float(r.hours or 0)}
			for r in session.execute(q_att).all()
		]
		heatmap_html = self.heatmap_calendar(att_rows, date_col="date", value_col="hours", title="Attendance Hours")

		body = (
			f'<h3>Time &amp; Attendance Dashboard</h3>'
			f'{kpi_html}'
			f'{heatmap_html}'
		)
		return make_response(_page_html("Time Dashboard", body), 200)

	@expose("/overtime")
	@has_access
	def overtime(self):
		"""Overtime summary — total overtime hours per employee over N days."""
		from pgappforge.plugins.erp.hcm.time.models import Timesheet, TimeEntry
		from datetime import timedelta
		session = _get_session()
		days = int(request.args.get("days", 30))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				Timesheet.employee_id,
				sa.func.sum(TimeEntry.overtime_hours).label("total_ot"),
				sa.func.sum(TimeEntry.regular_hours).label("total_reg"),
			)
			.join(TimeEntry, TimeEntry.timesheet_id == Timesheet.id)
			.where(Timesheet.week_start >= since)
			.where(Timesheet.status == "APPROVED")
			.group_by(Timesheet.employee_id)
			.order_by(sa.desc("total_ot"))
		)
		if tenant_id:
			q = q.where(Timesheet.tenant_id == tenant_id)

		rows = session.execute(q).all()

		if request.args.get("format") == "json":
			return jsonify({"overtime": [
				{
					"employee_id": r.employee_id,
					"total_overtime_hours": str(r.total_ot or 0),
					"total_regular_hours": str(r.total_reg or 0),
				}
				for r in rows
			]})

		trs = "".join(
			f"<tr><td>{_he(r.employee_id)}</td>"
			f"<td class='text-right'>{float(r.total_reg or 0):.2f}</td>"
			f"<td class='text-right text-warning'>{float(r.total_ot or 0):.2f}</td></tr>"
			for r in rows
		)
		body = (
			f'<h3>Overtime Summary — last {days} days</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Employee</th><th>Regular Hrs</th><th>Overtime Hrs</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Overtime Summary", body), 200)

	@expose("/leave-balances")
	@has_access
	def leave_balances(self):
		"""Leave balance snapshot — all employees, current year."""
		from pgappforge.plugins.erp.hcm.time.models import LeaveBalance
		session = _get_session()
		year = int(request.args.get("year", datetime.now(timezone.utc).year))
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(LeaveBalance)
			.where(LeaveBalance.balance_year == year)
			.order_by(LeaveBalance.employee_id, LeaveBalance.leave_type)
		)
		if tenant_id:
			q = q.where(LeaveBalance.tenant_id == tenant_id)

		balances = session.execute(q.limit(2000)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"leave_balances": [
				{
					"employee_id": b.employee_id,
					"leave_type": b.leave_type,
					"balance_year": b.balance_year,
					"accrued": str(b.accrued),
					"taken": str(b.taken),
					"pending": str(b.pending),
					"remaining": str(b.remaining),
				}
				for b in balances
			]})

		trs = "".join(
			f"<tr><td>{_he(b.employee_id)}</td><td>{_he(b.leave_type)}</td>"
			f"<td>{b.accrued}</td><td>{b.taken}</td><td>{b.pending}</td>"
			f"<td class='{'text-danger' if float(b.remaining) < 0 else 'text-success'}'>{b.remaining}</td></tr>"
			for b in balances
		)
		body = (
			f'<h3>Leave Balances — {year}</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Employee</th><th>Type</th><th>Accrued</th><th>Taken</th><th>Pending</th><th>Remaining</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Leave Balances", body), 200)

	@expose("/attendance")
	@has_access
	def attendance_summary(self):
		"""Attendance status summary — counts by status for a date range."""
		from pgappforge.plugins.erp.hcm.time.models import AttendanceRecord
		from datetime import timedelta
		session = _get_session()
		days = int(request.args.get("days", 7))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				AttendanceRecord.status,
				sa.func.count().label("count"),
			)
			.where(AttendanceRecord.attendance_date >= since)
			.group_by(AttendanceRecord.status)
			.order_by(AttendanceRecord.status)
		)
		if tenant_id:
			q = q.where(AttendanceRecord.tenant_id == tenant_id)

		rows = session.execute(q).all()
		data = [{"status": r.status, "count": r.count} for r in rows]
		total = sum(r.count for r in rows)

		if request.args.get("format") == "json":
			return jsonify({"attendance_summary": data, "total": total, "days": days})

		trs = "".join(
			f"<tr><td>{_he(r['status'])}</td><td class='text-right'>{r['count']}</td>"
			f"<td class='text-right'>{r['count'] / total * 100:.1f}%</td></tr>"
			for r in data
		) if total > 0 else "<tr><td colspan='3'>No records</td></tr>"
		body = (
			f'<h3>Attendance Summary — last {days} days</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>Status</th><th>Count</th><th>%</th></tr></thead>'
			f'<tbody>{trs}</tbody></table>'
		)
		return make_response(_page_html("Attendance Summary", body), 200)


__all__ = [
	"ShiftDefinitionView",
	"AttendanceView",
	"LeaveRequestView",
	"TimesheetView",
	"TimeReportView",
]
