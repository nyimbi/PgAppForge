"""
tests/ci/test_time_hcm_gaps.py

Unit tests for CRITICAL and HIGH gap implementations in the HCM Time &
Attendance plugin (Kenya Employment Act 2007 compliance).

Strategy
--------
- Pure-logic tests with MagicMock sessions — no real DB, no Flask context.
- Service functions are imported directly via the real package (uv run).
- Model instances are constructed with __new__ + manual attribute assignment
  to avoid needing a mapped session / DB.

Covers:
  - Easter / Good Friday date computation
  - PublicHoliday seed logic (idempotency, count returned)
  - is_public_holiday  / get_working_days
  - Monthly leave accrual (ANNUAL 1.75/mo, SICK 0.83/mo)
  - Accrual idempotency
  - Statutory hire grants (21/10/90/14 days per type, idempotency)
  - Year-end carry-forward (cap 10 days, forfeiture, new-year balance)
  - Overtime: weekday 1.5x, weekend 1.5x, PH 2.0x, zero OT at exactly 8h
  - Overtime pay (integer cents arithmetic)
  - Biometric import (normal, missing clock_out, duration exceeded, batch)
  - ShiftPattern create + EmployeeShift assignment + open-overlap guard
  - get_roster result structure
  - get_leave_balance zero-default for unknown employee
  - Module __all__ completeness
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from pgappforge.plugins.erp.hcm.time.services import (
	_easter_date,
	accrue_monthly,
	assign_shift,
	calculate_overtime,
	calculate_overtime_pay,
	create_shift_pattern,
	get_leave_balance,
	get_roster,
	get_working_days,
	import_attendance,
	initialise_statutory_entitlements,
	is_public_holiday,
	process_year_end_carryforward,
	seed_kenya_public_holidays,
	TimeServiceError,
	_KE_ANNUAL_ACCRUAL_RATE,
	_KE_SICK_ACCRUAL_RATE,
	_KE_ANNUAL_DAYS_PER_YEAR,
	_KE_SICK_DAYS_PER_YEAR,
	_KE_MATERNITY_DAYS,
	_KE_PATERNITY_DAYS,
	_KE_ANNUAL_MAX_CARRY,
	_OT_WEEKDAY_RATE,
	_OT_WEEKEND_RATE,
	_OT_PUBLIC_HOLIDAY_RATE,
)
from pgappforge.plugins.erp.hcm.time.models import (
	PublicHoliday,
	LeaveAccrual,
	LeaveBalance,
	OvertimeRecord,
	BiometricAttendance,
	ShiftPattern,
	EmployeeShift,
	AttendanceRecord,
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


def _tid() -> str:
	return "00000000-0000-0000-0000-000000000000"


def _make_session(
	*,
	scalar_one_or_none=None,
	scalar=None,
	scalars_all=None,
) -> MagicMock:
	"""Return a MagicMock session with sensible defaults."""
	session = MagicMock()
	exec_result = MagicMock()
	exec_result.scalar_one_or_none.return_value = scalar_one_or_none
	exec_result.scalar.return_value = scalar if scalar is not None else 0
	exec_result.scalars.return_value.all.return_value = scalars_all or []
	exec_result.all.return_value = scalars_all or []
	session.execute.return_value = exec_result
	session.get.return_value = None
	session.flush.return_value = None
	session.add.return_value = None
	return session


# ---------------------------------------------------------------------------
# Factories — use MagicMock so attribute assignment works without SA ORM state
# ---------------------------------------------------------------------------

def _att(emp_id: str, att_date: date, clock_in: datetime, clock_out: datetime | None = None) -> MagicMock:
	rec = MagicMock()
	rec.id = _uid()
	rec.tenant_id = _tid()
	rec.employee_id = emp_id
	rec.attendance_date = att_date
	rec.clock_in = clock_in
	rec.clock_out = clock_out
	rec.status = "PRESENT"
	rec.location = {}
	return rec


def _lb(emp_id: str, leave_type: str, year: int, accrued: str, taken: str = "0", pending: str = "0") -> MagicMock:
	lb = MagicMock()
	lb.id = _uid()
	lb.tenant_id = _tid()
	lb.employee_id = emp_id
	lb.leave_type = leave_type
	lb.balance_year = year
	lb.accrued = Decimal(accrued)
	lb.taken = Decimal(taken)
	lb.pending = Decimal(pending)
	lb.remaining = Decimal(accrued) - Decimal(taken) - Decimal(pending)
	return lb


def _sp(name: str = "Day Shift") -> MagicMock:
	from datetime import time as dt_time
	sp = MagicMock()
	sp.id = _uid()
	sp.tenant_id = _tid()
	sp.name = name
	sp.start_time = dt_time(8, 0)
	sp.end_time = dt_time(17, 0)
	sp.days_of_week = [0, 1, 2, 3, 4]
	sp.break_minutes = 60
	sp.is_overnight = False
	sp.is_active = True
	return sp


def _es(emp_id: str, pattern_id: str, eff_from: date, eff_to: date | None = None) -> MagicMock:
	es = MagicMock()
	es.id = _uid()
	es.tenant_id = _tid()
	es.employee_id = emp_id
	es.shift_pattern_id = pattern_id
	es.effective_from = eff_from
	es.effective_to = eff_to
	es.department_id = None
	return es


def _ot_rec(emp_id: str, work_date: date, ot_type: str, ot_hundredths: int, reg_hundredths: int, rate: str) -> MagicMock:
	rec = MagicMock()
	rec.id = _uid()
	rec.tenant_id = _tid()
	rec.employee_id = emp_id
	rec.work_date = work_date
	rec.overtime_type = ot_type
	rec.overtime_hours_hundredths = ot_hundredths
	rec.regular_hours_hundredths = reg_hundredths
	rec.rate_multiplier = Decimal(rate)
	rec.pay_cents = None
	return rec


# ---------------------------------------------------------------------------
# 1. Easter computation
# ---------------------------------------------------------------------------

class TestEasterComputation:

	def test_easter_2026(self):
		# Easter 2026 is April 5
		assert _easter_date(2026) == date(2026, 4, 5)

	def test_easter_2025(self):
		# Easter 2025 is April 20
		assert _easter_date(2025) == date(2025, 4, 20)

	def test_easter_2024(self):
		# Easter 2024 is March 31
		assert _easter_date(2024) == date(2024, 3, 31)

	def test_good_friday_is_2_days_before_easter(self):
		easter = _easter_date(2026)
		good_friday = easter - timedelta(days=2)
		assert good_friday == date(2026, 4, 3)

	def test_easter_monday_is_1_day_after_easter(self):
		easter = _easter_date(2026)
		assert easter + timedelta(days=1) == date(2026, 4, 6)


# ---------------------------------------------------------------------------
# 2. Public holiday calendar
# ---------------------------------------------------------------------------

class TestPublicHolidayCalendar:

	def test_seed_returns_correct_count(self):
		"""seed_kenya_public_holidays inserts 9 rows for a fresh year (7 fixed + 2 floating)."""
		session = _make_session(scalar=0)  # .scalar() → 0 means "not exists"
		count = seed_kenya_public_holidays(session, 2026, tenant_id=_tid())
		assert count == 9
		assert session.add.call_count == 9
		assert session.flush.called

	def test_seed_idempotent_all_exist(self):
		"""If all holidays already exist (scalar returns 1) nothing is inserted."""
		session = _make_session(scalar=1)
		count = seed_kenya_public_holidays(session, 2026, tenant_id=_tid())
		assert count == 0
		session.add.assert_not_called()

	def test_is_public_holiday_true_when_found(self):
		"""is_public_holiday returns True when DB count > 0."""
		session = _make_session(scalar=1)
		result = is_public_holiday(session, date(2026, 12, 25), tenant_id=_tid())
		assert result is True

	def test_is_public_holiday_false_when_not_found(self):
		session = _make_session(scalar=0)
		result = is_public_holiday(session, date(2026, 6, 2), tenant_id=_tid())
		assert result is False

	def test_get_working_days_all_weekdays_no_holidays(self):
		"""Mon-Fri week with no holidays → 5 working days."""
		session = _make_session(scalar=0)  # no public holidays
		# 2026-06-01 is Monday, 2026-06-05 is Friday
		count = get_working_days(session, date(2026, 6, 1), date(2026, 6, 5), tenant_id=_tid())
		assert count == 5

	def test_get_working_days_excludes_weekend(self):
		"""Full calendar week Mon-Sun → 5 working days."""
		session = _make_session(scalar=0)
		count = get_working_days(session, date(2026, 6, 1), date(2026, 6, 7), tenant_id=_tid())
		assert count == 5

	def test_get_working_days_excludes_holiday(self):
		"""5-day week where Friday is a public holiday → 4 working days."""
		call_count = [0]
		def _scalar():
			call_count[0] += 1
			# Only the last call (Friday = Christmas-equivalent) is a holiday
			return 0

		session = MagicMock()
		exec_result = MagicMock()

		# is_public_holiday uses session.execute().scalar()
		# We want Mon-Thu = 0, Fri = 1
		dates_called = []
		def _execute(q):
			r = MagicMock()
			# Capture which date is being queried via call order
			r.scalar.return_value = 1 if len(dates_called) >= 4 else 0
			dates_called.append(1)
			return r
		session.execute.side_effect = _execute
		session.flush.return_value = None

		# Mon 2026-06-01 through Fri 2026-06-05
		count = get_working_days(session, date(2026, 6, 1), date(2026, 6, 5), tenant_id=_tid())
		# 4 non-holiday weekdays + 1 holiday weekday = 4
		assert count == 4

	def test_get_working_days_empty_range(self):
		session = _make_session(scalar=0)
		assert get_working_days(session, date(2026, 6, 5), date(2026, 6, 4)) == 0


# ---------------------------------------------------------------------------
# 3. Leave accrual constants
# ---------------------------------------------------------------------------

class TestAccrualConstants:
	"""Verify the Kenya Employment Act 2007 rates are correct."""

	def test_annual_accrual_rate(self):
		assert _KE_ANNUAL_ACCRUAL_RATE == Decimal("1.75")

	def test_sick_accrual_rate(self):
		assert _KE_SICK_ACCRUAL_RATE == Decimal("0.83")

	def test_annual_days_per_year(self):
		assert _KE_ANNUAL_DAYS_PER_YEAR == Decimal("21")

	def test_sick_days_per_year(self):
		assert _KE_SICK_DAYS_PER_YEAR == Decimal("10")

	def test_maternity_days(self):
		assert _KE_MATERNITY_DAYS == Decimal("90")

	def test_paternity_days(self):
		assert _KE_PATERNITY_DAYS == Decimal("14")

	def test_carry_forward_cap(self):
		assert _KE_ANNUAL_MAX_CARRY == Decimal("10")

	def test_twelve_months_accrual_equals_21_days(self):
		"""1.75 * 12 = 21.00 — meets statutory annual leave minimum."""
		assert (_KE_ANNUAL_ACCRUAL_RATE * 12).quantize(Decimal("0.01")) == Decimal("21.00")

	def test_overtime_rates(self):
		assert _OT_WEEKDAY_RATE == Decimal("1.50")
		assert _OT_WEEKEND_RATE == Decimal("1.50")
		assert _OT_PUBLIC_HOLIDAY_RATE == Decimal("2.00")


# ---------------------------------------------------------------------------
# 4. Monthly accrual service
# ---------------------------------------------------------------------------

class TestMonthlyAccrual:

	def _session_no_existing(self) -> MagicMock:
		"""Session where no LeaveAccrual and no LeaveBalance exists yet."""
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added

		# execute().scalar_one_or_none() → None (nothing exists)
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		return s

	def test_accrue_monthly_returns_two_entries(self):
		s = self._session_no_existing()
		result = accrue_monthly(s, _uid(), date(2026, 6, 1), _tid())
		assert len(result["entries"]) == 2

	def test_accrue_monthly_annual_rate(self):
		s = self._session_no_existing()
		emp = _uid()
		result = accrue_monthly(s, emp, date(2026, 6, 1), _tid())
		annual = next(e for e in result["entries"] if e["leave_type"] == "ANNUAL")
		assert Decimal(annual["days_accrued"]) == Decimal("1.75")
		assert annual["skipped"] is False

	def test_accrue_monthly_sick_rate(self):
		s = self._session_no_existing()
		result = accrue_monthly(s, _uid(), date(2026, 6, 1), _tid())
		sick = next(e for e in result["entries"] if e["leave_type"] == "SICK")
		assert Decimal(sick["days_accrued"]) == Decimal("0.83")
		assert sick["skipped"] is False

	def test_accrue_monthly_idempotent_when_existing(self):
		"""When LeaveAccrual row already exists, entry is marked skipped."""
		s = MagicMock()
		s.flush.return_value = None
		existing_accrual = MagicMock()
		existing_accrual.days_accrued = Decimal("1.75")
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = existing_accrual
		s.execute.return_value = exec_result
		result = accrue_monthly(s, _uid(), date(2026, 6, 1), _tid())
		assert all(e["skipped"] for e in result["entries"])
		s.add.assert_not_called()

	def test_accrue_monthly_creates_balance_if_missing(self):
		"""When no LeaveBalance exists, a new one is created."""
		s = self._session_no_existing()
		accrue_monthly(s, _uid(), date(2026, 6, 1), _tid())
		added_types = [type(obj).__name__ for obj in s._added]
		# Should have LeaveBalance + LeaveAccrual for each of ANNUAL and SICK
		assert added_types.count("LeaveBalance") == 2
		assert added_types.count("LeaveAccrual") == 2

	def test_accrue_monthly_normalises_to_first_of_month(self):
		"""accrual_month is always normalised to first day."""
		s = self._session_no_existing()
		result = accrue_monthly(s, _uid(), date(2026, 6, 15), _tid())
		assert result["accrual_month"] == "2026-06-01"


# ---------------------------------------------------------------------------
# 5. Statutory hire entitlements
# ---------------------------------------------------------------------------

class TestStatutoryEntitlements:

	def _fresh_session(self) -> MagicMock:
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		return s

	def test_grants_four_leave_types(self):
		s = self._fresh_session()
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		assert len(result["granted"]) == 4

	def test_annual_grant_is_21(self):
		s = self._fresh_session()
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		annual = next(g for g in result["granted"] if g["leave_type"] == "ANNUAL")
		assert Decimal(annual["days"]) == Decimal("21")

	def test_sick_grant_is_10(self):
		s = self._fresh_session()
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		sick = next(g for g in result["granted"] if g["leave_type"] == "SICK")
		assert Decimal(sick["days"]) == Decimal("10")

	def test_maternity_grant_is_90(self):
		s = self._fresh_session()
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		mat = next(g for g in result["granted"] if g["leave_type"] == "MATERNITY")
		assert Decimal(mat["days"]) == Decimal("90")

	def test_paternity_grant_is_14(self):
		s = self._fresh_session()
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		pat = next(g for g in result["granted"] if g["leave_type"] == "PATERNITY")
		assert Decimal(pat["days"]) == Decimal("14")

	def test_idempotent_when_hire_grant_exists(self):
		"""Second call with an existing hire_grant row → no grants, no DB writes."""
		s = MagicMock()
		s.flush.return_value = None
		existing = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = existing
		s.execute.return_value = exec_result
		result = initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		assert len(result["granted"]) == 0
		s.add.assert_not_called()

	def test_creates_balance_and_accrual_rows(self):
		s = self._fresh_session()
		initialise_statutory_entitlements(s, _uid(), date(2026, 1, 15), _tid())
		added_types = [type(obj).__name__ for obj in s._added]
		assert "LeaveBalance" in added_types
		assert "LeaveAccrual" in added_types


# ---------------------------------------------------------------------------
# 6. Year-end carry-forward
# ---------------------------------------------------------------------------

class TestYearEndCarryForward:

	def _session_with_balances(self, balances: list[LeaveBalance]) -> MagicMock:
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added

		# First execute() returns the list of old-year balances
		# Subsequent execute() calls (inside the loop: check existing accrual /
		# check existing new-year balance) return None
		call_iter = iter([balances])

		def _execute(q):
			r = MagicMock()
			try:
				val = next(call_iter)
				r.scalars.return_value.all.return_value = val
			except StopIteration:
				r.scalars.return_value.all.return_value = []
			r.scalar_one_or_none.return_value = None
			return r

		s.execute.side_effect = _execute
		return s

	def test_carry_forward_caps_at_10(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2025, accrued="21", taken="6")  # 15 remaining
		s = self._session_with_balances([lb])
		result = process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		detail = next(d for d in result["details"] if d["employee_id"] == emp)
		assert Decimal(detail["carried"]) == Decimal("10")
		assert Decimal(detail["forfeited"]) == Decimal("5")

	def test_carry_forward_under_cap(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2025, accrued="10", taken="2")  # 8 remaining < 10 cap
		s = self._session_with_balances([lb])
		result = process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		detail = next(d for d in result["details"] if d["employee_id"] == emp)
		assert Decimal(detail["carried"]) == Decimal("8")
		assert Decimal(detail["forfeited"]) == Decimal("0")

	def test_carry_forward_zero_remaining_skipped(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2025, accrued="21", taken="21")  # 0 remaining
		s = self._session_with_balances([lb])
		result = process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		assert all(d["employee_id"] != emp for d in result["details"])

	def test_carry_forward_totals(self):
		emp1, emp2 = _uid(), _uid()
		lb1 = _lb(emp1, "ANNUAL", 2025, accrued="21", taken="6")   # 15 remaining → carry 10
		lb2 = _lb(emp2, "ANNUAL", 2025, accrued="8", taken="0")    # 8 remaining → carry 8
		s = self._session_with_balances([lb1, lb2])
		result = process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		assert Decimal(result["carried_total"]) == Decimal("18")    # 10 + 8
		assert Decimal(result["forfeited_total"]) == Decimal("5")   # 5 + 0

	def test_carry_forward_writes_forfeiture_ledger(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2025, accrued="21", taken="6")  # 5 days forfeited
		s = self._session_with_balances([lb])
		process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		forfeiture_rows = [
			obj for obj in s._added
			if isinstance(obj, LeaveAccrual) and obj.reason == "forfeiture"
		]
		assert len(forfeiture_rows) == 1
		assert forfeiture_rows[0].days_accrued == Decimal("-5")

	def test_carry_forward_writes_carry_ledger(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2025, accrued="8", taken="0")
		s = self._session_with_balances([lb])
		process_year_end_carryforward(s, date(2026, 1, 1), tenant_id=_tid())
		carry_rows = [
			obj for obj in s._added
			if isinstance(obj, LeaveAccrual) and obj.reason == "carry_forward"
		]
		assert len(carry_rows) == 1
		assert carry_rows[0].days_accrued == Decimal("8")


# ---------------------------------------------------------------------------
# 7. Overtime calculation
# ---------------------------------------------------------------------------

class TestOvertimeCalculation:

	def _session_for_overtime(self, att: AttendanceRecord, is_ph: bool = False) -> MagicMock:
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added
		s.get.return_value = att

		call_num = [0]

		def _execute(q):
			r = MagicMock()
			call_num[0] += 1
			if call_num[0] == 1:
				# First call: idempotency check for existing OvertimeRecord
				r.scalar_one_or_none.return_value = None
			else:
				# Subsequent calls: is_public_holiday count query
				r.scalar.return_value = 1 if is_ph else 0
				r.scalar_one_or_none.return_value = None
			return r

		s.execute.side_effect = _execute
		return s

	def test_weekday_overtime_10h(self):
		emp = _uid()
		att = _att(
			emp, date(2026, 6, 1),  # Monday
			clock_in=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
			clock_out=datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc),  # 10h
		)
		s = self._session_for_overtime(att)
		rec = calculate_overtime(s, emp, att.id, _tid())
		assert rec.overtime_type == "WEEKDAY"
		assert Decimal(str(rec.rate_multiplier)) == Decimal("1.50")
		assert rec.overtime_hours_hundredths == 200   # 2h * 100
		assert rec.regular_hours_hundredths == 800    # 8h * 100

	def test_weekday_exactly_8h_no_overtime(self):
		emp = _uid()
		att = _att(
			emp, date(2026, 6, 2),  # Tuesday
			clock_in=datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc),
			clock_out=datetime(2026, 6, 2, 16, 0, tzinfo=timezone.utc),  # 8h
		)
		s = self._session_for_overtime(att)
		rec = calculate_overtime(s, emp, att.id, _tid())
		assert rec.overtime_hours_hundredths == 0
		assert rec.regular_hours_hundredths == 800

	def test_weekend_entire_shift_overtime(self):
		emp = _uid()
		att = _att(
			emp, date(2026, 6, 6),  # Saturday
			clock_in=datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc),
			clock_out=datetime(2026, 6, 6, 14, 0, tzinfo=timezone.utc),  # 5h
		)
		s = self._session_for_overtime(att)
		rec = calculate_overtime(s, emp, att.id, _tid())
		assert rec.overtime_type == "WEEKEND"
		assert rec.regular_hours_hundredths == 0
		assert rec.overtime_hours_hundredths == 500

	def test_public_holiday_rate_2x(self):
		emp = _uid()
		att = _att(
			emp, date(2026, 12, 25),
			clock_in=datetime(2026, 12, 25, 8, 0, tzinfo=timezone.utc),
			clock_out=datetime(2026, 12, 25, 16, 0, tzinfo=timezone.utc),  # 8h
		)
		s = self._session_for_overtime(att, is_ph=True)
		rec = calculate_overtime(s, emp, att.id, _tid())
		assert rec.overtime_type == "PUBLIC_HOLIDAY"
		assert Decimal(str(rec.rate_multiplier)) == Decimal("2.00")
		assert rec.regular_hours_hundredths == 0
		assert rec.overtime_hours_hundredths == 800

	def test_missing_clock_out_raises(self):
		emp = _uid()
		att = _att(emp, date(2026, 6, 3), clock_in=datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc))
		s = MagicMock()
		s.get.return_value = att
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		with pytest.raises(TimeServiceError, match="missing clock_in or clock_out"):
			calculate_overtime(s, emp, att.id, _tid())

	def test_attendance_record_not_found_raises(self):
		s = MagicMock()
		s.get.return_value = None
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		with pytest.raises(TimeServiceError, match="not found"):
			calculate_overtime(s, _uid(), _uid(), _tid())

	def test_idempotent_returns_existing(self):
		emp = _uid()
		existing_rec = _ot_rec(emp, date(2026, 6, 1), "WEEKDAY", 200, 800, "1.50")
		s = MagicMock()
		s.get.return_value = _att(  # dummy — shouldn't be used
			emp, date(2026, 6, 1),
			clock_in=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
			clock_out=datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc),
		)
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = existing_rec
		s.execute.return_value = exec_result
		result = calculate_overtime(s, emp, _uid(), _tid())
		assert result is existing_rec
		s.add.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Overtime pay
# ---------------------------------------------------------------------------

class TestOvertimePay:

	def _session_with_ot_rec(self, rec: OvertimeRecord) -> MagicMock:
		s = MagicMock()
		s.get.return_value = rec
		s.flush.return_value = None
		return s

	def test_zero_ot_hours_pay_is_zero(self):
		rec = _ot_rec(_uid(), date(2026, 6, 1), "WEEKDAY", 0, 800, "1.50")
		s = self._session_with_ot_rec(rec)
		pay = calculate_overtime_pay(s, rec.id, hourly_rate_cents=100_00)
		assert pay == 0

	def test_weekday_2h_overtime(self):
		rec = _ot_rec(_uid(), date(2026, 6, 2), "WEEKDAY", 200, 800, "1.50")
		s = self._session_with_ot_rec(rec)
		# 2h * 1000 cents/h * 1.5 = 3000 cents
		pay = calculate_overtime_pay(s, rec.id, hourly_rate_cents=1000)
		assert pay == 3000

	def test_public_holiday_8h_overtime(self):
		rec = _ot_rec(_uid(), date(2026, 12, 25), "PUBLIC_HOLIDAY", 800, 0, "2.00")
		s = self._session_with_ot_rec(rec)
		# 8h * 50000 cents/h * 2.0 = 800000
		pay = calculate_overtime_pay(s, rec.id, hourly_rate_cents=50000)
		assert pay == 800_000

	def test_weekend_5h_overtime(self):
		rec = _ot_rec(_uid(), date(2026, 6, 6), "WEEKEND", 500, 0, "1.50")
		s = self._session_with_ot_rec(rec)
		# 5h * 20000 * 1.5 = 150000
		pay = calculate_overtime_pay(s, rec.id, hourly_rate_cents=20000)
		assert pay == 150_000

	def test_pay_cents_persisted_on_record(self):
		rec = _ot_rec(_uid(), date(2026, 6, 5), "WEEKDAY", 400, 800, "1.50")
		s = self._session_with_ot_rec(rec)
		calculate_overtime_pay(s, rec.id, hourly_rate_cents=10000)
		# 4h * 10000 * 1.5 = 60000
		assert rec.pay_cents == 60_000

	def test_missing_record_raises(self):
		s = MagicMock()
		s.get.return_value = None
		with pytest.raises(TimeServiceError, match="not found"):
			calculate_overtime_pay(s, _uid(), hourly_rate_cents=1000)

	def test_result_is_integer(self):
		rec = _ot_rec(_uid(), date(2026, 6, 3), "WEEKDAY", 150, 800, "1.50")
		s = self._session_with_ot_rec(rec)
		pay = calculate_overtime_pay(s, rec.id, hourly_rate_cents=777)
		# 1.5h * 777 * 1.5 = 1748.25 → rounds to 1748
		assert isinstance(pay, int)


# ---------------------------------------------------------------------------
# 9. Biometric attendance import
# ---------------------------------------------------------------------------

class TestBiometricImport:

	def _session(self) -> MagicMock:
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added
		return s

	def test_import_normal_record(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T08:00:00+00:00",
			"clock_out_iso": "2026-06-01T17:00:00+00:00",
			"device_id": "ZK-001",
			"source": "BIOMETRIC",
		}]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["imported"] == 1
		assert result["anomalies"] == 0
		assert result["errors"] == []
		assert len(s._added) == 1
		assert isinstance(s._added[0], BiometricAttendance)

	def test_import_computes_duration(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T08:00:00+00:00",
			"clock_out_iso": "2026-06-01T17:00:00+00:00",
		}]
		import_attendance(s, records, tenant_id=_tid())
		rec = s._added[0]
		assert rec.duration_minutes == 540  # 9h

	def test_import_flags_missing_clock_out(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T08:00:00+00:00",
			"clock_out_iso": None,
		}]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["anomalies"] == 1
		rec = s._added[0]
		assert rec.is_anomaly is True
		assert rec.anomaly_reason == "MISSING_CLOCK_OUT"

	def test_import_flags_duration_exceeded(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T06:00:00+00:00",
			"clock_out_iso": "2026-06-01T20:00:00+00:00",  # 14h > 12h
		}]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["anomalies"] == 1
		assert s._added[0].anomaly_reason == "DURATION_EXCEEDED"

	def test_import_batch_counts(self):
		s = self._session()
		records = [
			{
				"employee_id": _uid(),
				"clock_in_iso": "2026-06-02T08:00:00+00:00",
				"clock_out_iso": "2026-06-02T17:00:00+00:00",
			},
			{
				"employee_id": _uid(),
				"clock_in_iso": "2026-06-02T07:00:00+00:00",
				"clock_out_iso": None,
			},
			{
				"employee_id": _uid(),
				"clock_in_iso": "2026-06-02T08:00:00+00:00",
				"clock_out_iso": "2026-06-02T22:00:00+00:00",  # 14h
			},
		]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["imported"] == 3
		assert result["anomalies"] == 2

	def test_import_captures_error(self):
		s = self._session()
		records = [{"employee_id": _uid(), "clock_in_iso": "not-a-date"}]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["imported"] == 0
		assert len(result["errors"]) == 1

	def test_import_source_defaults_to_biometric(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T08:00:00+00:00",
			"clock_out_iso": "2026-06-01T17:00:00+00:00",
		}]
		import_attendance(s, records, tenant_id=_tid())
		assert s._added[0].source == "BIOMETRIC"

	def test_import_naive_datetime_treated_as_utc(self):
		s = self._session()
		records = [{
			"employee_id": _uid(),
			"clock_in_iso": "2026-06-01T08:00:00",   # naive
			"clock_out_iso": "2026-06-01T17:00:00",  # naive
		}]
		result = import_attendance(s, records, tenant_id=_tid())
		assert result["imported"] == 1
		rec = s._added[0]
		assert rec.clock_in.tzinfo is not None


# ---------------------------------------------------------------------------
# 10. Shift pattern + roster
# ---------------------------------------------------------------------------

class TestShiftManagement:

	def _session(self, existing_open_assignment=None, existing_pattern=None) -> MagicMock:
		s = MagicMock()
		s.flush.return_value = None
		added = []
		s.add.side_effect = lambda obj: added.append(obj)
		s._added = added
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = existing_open_assignment
		exec_result.all.return_value = []
		s.execute.return_value = exec_result
		s.get.return_value = existing_pattern
		return s

	def test_create_shift_pattern_basic(self):
		s = self._session()
		pattern = create_shift_pattern(s, {
			"tenant_id": _tid(),
			"name": "Morning",
			"start_time": "08:00",
			"end_time": "17:00",
			"days_of_week": [0, 1, 2, 3, 4],
			"break_minutes": 60,
		})
		assert pattern.name == "Morning"
		assert pattern.break_minutes == 60
		assert pattern.is_overnight is False
		assert len(s._added) == 1

	def test_create_shift_pattern_overnight(self):
		s = self._session()
		pattern = create_shift_pattern(s, {
			"tenant_id": _tid(),
			"name": "Night",
			"start_time": "22:00",
			"end_time": "06:00",
			"days_of_week": [0, 1, 2, 3, 4],
		})
		assert pattern.is_overnight is True

	def test_create_shift_pattern_missing_field_raises(self):
		s = self._session()
		with pytest.raises(TimeServiceError, match="missing required field"):
			create_shift_pattern(s, {"tenant_id": _tid(), "name": "X"})

	def test_assign_shift_creates_employee_shift(self):
		pattern = _sp("Day")
		s = self._session(existing_open_assignment=None, existing_pattern=pattern)
		assignment = assign_shift(s, {
			"tenant_id": _tid(),
			"employee_id": _uid(),
			"shift_pattern_id": pattern.id,
			"effective_from": "2026-06-01",
		})
		assert isinstance(assignment, EmployeeShift)
		assert assignment.effective_to is None
		assert len(s._added) == 1

	def test_assign_shift_rejects_open_overlap(self):
		pattern = _sp("Day")
		emp = _uid()
		existing_open = _es(emp, pattern.id, date(2026, 1, 1))
		s = self._session(existing_open_assignment=existing_open, existing_pattern=pattern)
		with pytest.raises(TimeServiceError, match="open-ended shift assignment"):
			assign_shift(s, {
				"tenant_id": _tid(),
				"employee_id": emp,
				"shift_pattern_id": pattern.id,
				"effective_from": "2026-07-01",
			})

	def test_assign_shift_effective_to_before_from_raises(self):
		pattern = _sp("Day")
		s = self._session(existing_open_assignment=None, existing_pattern=pattern)
		with pytest.raises(TimeServiceError, match="effective_to must be"):
			assign_shift(s, {
				"tenant_id": _tid(),
				"employee_id": _uid(),
				"shift_pattern_id": pattern.id,
				"effective_from": "2026-06-01",
				"effective_to": "2026-05-01",
			})

	def test_assign_shift_pattern_not_found_raises(self):
		s = self._session(existing_open_assignment=None, existing_pattern=None)
		with pytest.raises(TimeServiceError, match="not found"):
			assign_shift(s, {
				"tenant_id": _tid(),
				"employee_id": _uid(),
				"shift_pattern_id": _uid(),
				"effective_from": "2026-06-01",
			})

	def test_get_roster_returns_list(self):
		emp = _uid()
		pattern = _sp("Roster Shift")
		assignment = _es(emp, pattern.id, date(2026, 6, 1))

		s = MagicMock()
		exec_result = MagicMock()
		exec_result.all.return_value = [(assignment, pattern)]
		s.execute.return_value = exec_result

		roster = get_roster(s, date(2026, 6, 1), date(2026, 6, 30), tenant_id=_tid())
		assert len(roster) == 1
		assert roster[0]["employee_id"] == emp
		assert roster[0]["shift_name"] == "Roster Shift"
		assert "start_time" in roster[0]
		assert "days_of_week" in roster[0]

	def test_get_roster_empty_returns_empty_list(self):
		s = MagicMock()
		exec_result = MagicMock()
		exec_result.all.return_value = []
		s.execute.return_value = exec_result
		result = get_roster(s, date(2026, 6, 1), date(2026, 6, 30))
		assert result == []


# ---------------------------------------------------------------------------
# 11. get_leave_balance
# ---------------------------------------------------------------------------

class TestGetLeaveBalance:

	def test_unknown_employee_returns_zero_dict(self):
		s = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		result = get_leave_balance(s, _uid(), "ANNUAL")
		assert result["accrued"] == "0.00"
		assert result["remaining"] == "0.00"
		assert result["taken"] == "0.00"
		assert result["pending"] == "0.00"

	def test_returns_balance_values(self):
		emp = _uid()
		lb = _lb(emp, "ANNUAL", 2026, accrued="15", taken="5", pending="2")
		s = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = lb
		s.execute.return_value = exec_result
		result = get_leave_balance(s, emp, "ANNUAL", as_of_date=date(2026, 6, 1))
		assert Decimal(result["accrued"]) == Decimal("15")
		assert Decimal(result["taken"]) == Decimal("5")
		assert Decimal(result["pending"]) == Decimal("2")
		assert Decimal(result["remaining"]) == Decimal("8")

	def test_uses_as_of_date_year(self):
		"""get_leave_balance uses as_of_date.year to scope the query."""
		s = MagicMock()
		exec_result = MagicMock()
		exec_result.scalar_one_or_none.return_value = None
		s.execute.return_value = exec_result
		result = get_leave_balance(s, _uid(), "SICK", as_of_date=date(2025, 12, 31))
		assert result["year"] == 2025


# ---------------------------------------------------------------------------
# 12. __all__ completeness
# ---------------------------------------------------------------------------

class TestModuleExports:

	def test_models_all_contains_new_models(self):
		from pgappforge.plugins.erp.hcm.time import models as m
		for name in ("PublicHoliday", "LeaveAccrual", "OvertimeRecord",
		             "BiometricAttendance", "ShiftPattern", "EmployeeShift"):
			assert name in m.__all__, f"{name} missing from models.__all__"

	def test_services_all_contains_new_functions(self):
		from pgappforge.plugins.erp.hcm.time import services as svc
		for name in (
			"accrue_monthly", "get_leave_balance", "initialise_statutory_entitlements",
			"process_year_end_carryforward", "is_public_holiday", "get_working_days",
			"seed_kenya_public_holidays", "calculate_overtime", "calculate_overtime_pay",
			"import_attendance", "create_shift_pattern", "assign_shift", "get_roster",
		):
			assert name in svc.__all__, f"{name} missing from services.__all__"

	def test_events_all_contains_new_events(self):
		from pgappforge.plugins.erp.hcm.time import events as ev
		for name in (
			"LeaveAccruedEvent", "LeaveCarryForwardEvent", "OvertimeCalculatedEvent",
			"OvertimePayComputedEvent", "BiometricImportCompleteEvent",
			"ShiftPatternCreatedEvent", "EmployeeShiftAssignedEvent",
		):
			assert name in ev.__all__, f"{name} missing from events.__all__"

	def test_init_all_contains_key_symbols(self):
		import pgappforge.plugins.erp.hcm.time as pkg
		for name in (
			"PublicHoliday", "LeaveAccrual", "OvertimeRecord", "BiometricAttendance",
			"ShiftPattern", "EmployeeShift", "accrue_monthly", "get_leave_balance",
			"seed_kenya_public_holidays", "calculate_overtime", "import_attendance",
		):
			assert name in pkg.__all__, f"{name} missing from __init__.__all__"
