"""Shared RRULE next-occurrence computation for ReportForge scheduler/subscriptions."""

from __future__ import annotations
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def next_occurrence(rule_str: str, after_dt: datetime) -> datetime | None:
	"""Return the next datetime after *after_dt* for an RRULE string, or None.

	*rule_str* may be a bare RRULE fragment (e.g. ``FREQ=WEEKLY;BYDAY=MO``)
	or a full ``RRULE:FREQ=...`` value. dateutil.rrule handles both.

	Returns None when the rule is exhausted or dateutil is not available.
	"""
	try:
		from dateutil.rrule import rrulestr
		return rrulestr(rule_str, dtstart=after_dt, ignoretz=False).after(after_dt)
	except Exception as exc:
		log.warning("ReportForge RRULE: next_occurrence failed for %r: %s", rule_str, exc)
		return None
