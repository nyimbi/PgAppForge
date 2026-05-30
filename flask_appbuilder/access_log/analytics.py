"""Analytical queries over the HTTP access log table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, desc, text
from sqlalchemy.orm import Session

from .models import AccessLogEntry


class AccessLogAnalytics:
	"""High-level analytical queries over the fab_access_log table.

	All methods accept a ``hours`` parameter to restrict the time window.
	All queries use PostgreSQL-specific functions for optimal performance.

	Usage::

	    analytics = AccessLogAnalytics(db.session)
	    top = analytics.top_endpoints(limit=10, hours=1)
	"""

	def __init__(self, session: Session) -> None:
		self.session = session

	def _since(self, hours: int) -> datetime:
		return datetime.now(tz=timezone.utc) - timedelta(hours=hours)

	def top_endpoints(
		self, limit: int = 20, hours: int = 24
	) -> list[dict[str, Any]]:
		"""Most frequently accessed endpoints with latency stats."""
		since = self._since(hours)
		rows = (
			self.session.query(
				AccessLogEntry.path,
				AccessLogEntry.method,
				func.count().label("hits"),
				func.round(func.avg(AccessLogEntry.duration_ms)).label("avg_ms"),
				func.percentile_cont(0.95)
				.within_group(AccessLogEntry.duration_ms)
				.label("p95_ms"),
				func.sum(
					(AccessLogEntry.status_code >= 400).cast(type_=func.count().type)
				).label("errors"),
			)
			.filter(AccessLogEntry.requested_at >= since)
			.group_by(AccessLogEntry.path, AccessLogEntry.method)
			.order_by(desc("hits"))
			.limit(limit)
			.all()
		)
		return [
			{
				"path": r.path,
				"method": r.method,
				"hits": r.hits,
				"avg_ms": int(r.avg_ms or 0),
				"p95_ms": int(r.p95_ms or 0),
				"errors": int(r.errors or 0),
				"error_rate_pct": round(100 * (r.errors or 0) / max(r.hits, 1), 1),
			}
			for r in rows
		]

	def top_users(
		self, limit: int = 20, hours: int = 24
	) -> list[dict[str, Any]]:
		"""Most active users with request counts and last-seen time."""
		since = self._since(hours)
		rows = (
			self.session.query(
				AccessLogEntry.username,
				AccessLogEntry.user_id,
				func.count().label("requests"),
				func.max(AccessLogEntry.requested_at).label("last_seen"),
				func.count(func.distinct(AccessLogEntry.path)).label("unique_paths"),
			)
			.filter(
				AccessLogEntry.requested_at >= since,
				AccessLogEntry.user_id.isnot(None),
			)
			.group_by(AccessLogEntry.username, AccessLogEntry.user_id)
			.order_by(desc("requests"))
			.limit(limit)
			.all()
		)
		return [
			{
				"username": r.username,
				"user_id": r.user_id,
				"requests": r.requests,
				"last_seen": r.last_seen,
				"unique_paths": r.unique_paths,
			}
			for r in rows
		]

	def error_summary(self, hours: int = 1) -> dict[str, Any]:
		"""Overall error rate and breakdown by status code."""
		since = self._since(hours)
		total = (
			self.session.query(func.count())
			.filter(AccessLogEntry.requested_at >= since)
			.scalar()
			or 0
		)
		errors = (
			self.session.query(func.count())
			.filter(
				AccessLogEntry.requested_at >= since,
				AccessLogEntry.status_code >= 400,
			)
			.scalar()
			or 0
		)
		server_errors = (
			self.session.query(func.count())
			.filter(
				AccessLogEntry.requested_at >= since,
				AccessLogEntry.status_code >= 500,
			)
			.scalar()
			or 0
		)
		return {
			"total": total,
			"errors_4xx": errors - server_errors,
			"errors_5xx": server_errors,
			"error_rate_pct": round(100 * errors / max(total, 1), 2),
			"server_error_rate_pct": round(100 * server_errors / max(total, 1), 2),
		}

	def slow_requests(
		self, threshold_ms: int = 1000, hours: int = 1, limit: int = 50
	) -> list[AccessLogEntry]:
		"""Requests that exceeded the duration threshold."""
		since = self._since(hours)
		return (
			self.session.query(AccessLogEntry)
			.filter(
				AccessLogEntry.requested_at >= since,
				AccessLogEntry.duration_ms >= threshold_ms,
			)
			.order_by(desc(AccessLogEntry.duration_ms))
			.limit(limit)
			.all()
		)

	def requests_per_minute(self, hours: int = 1) -> list[dict[str, Any]]:
		"""Request volume bucketed by minute (for time-series charts)."""
		since = self._since(hours)
		rows = self.session.execute(
			text("""
			    SELECT
			        date_trunc('minute', requested_at AT TIME ZONE 'UTC') AS minute,
			        count(*) AS requests,
			        count(*) FILTER (WHERE status_code >= 400) AS errors,
			        round(avg(duration_ms)) AS avg_ms
			    FROM fab_access_log
			    WHERE requested_at >= :since
			    GROUP BY 1
			    ORDER BY 1
			"""),
			{"since": since},
		).fetchall()
		return [
			{
				"minute": r.minute,
				"requests": r.requests,
				"errors": r.errors,
				"avg_ms": int(r.avg_ms or 0),
			}
			for r in rows
		]

	def user_session_timeline(
		self, user_id: int, date: datetime | None = None
	) -> list[AccessLogEntry]:
		"""All requests from a specific user on a given day."""
		if date is None:
			date = datetime.now(tz=timezone.utc)
		day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
		day_end = day_start + timedelta(days=1)
		return (
			self.session.query(AccessLogEntry)
			.filter(
				AccessLogEntry.user_id == user_id,
				AccessLogEntry.requested_at >= day_start,
				AccessLogEntry.requested_at < day_end,
			)
			.order_by(AccessLogEntry.requested_at)
			.all()
		)

	def top_ips(self, limit: int = 20, hours: int = 24) -> list[dict[str, Any]]:
		"""Most active IP addresses — useful for detecting scraping or attacks."""
		since = self._since(hours)
		rows = (
			self.session.query(
				AccessLogEntry.ip_address,
				func.count().label("requests"),
				func.count(func.distinct(AccessLogEntry.user_id)).label("users"),
				func.count().filter(AccessLogEntry.status_code >= 400).label("errors"),
			)
			.filter(AccessLogEntry.requested_at >= since)
			.group_by(AccessLogEntry.ip_address)
			.order_by(desc("requests"))
			.limit(limit)
			.all()
		)
		return [
			{"ip": str(r.ip_address), "requests": r.requests,
			 "users": r.users, "errors": r.errors}
			for r in rows
		]

	def summary_stats(self, hours: int = 24) -> dict[str, Any]:
		"""Overview card stats for the analytics dashboard."""
		since = self._since(hours)
		total = self.session.query(func.count()).filter(
			AccessLogEntry.requested_at >= since).scalar() or 0
		unique_users = self.session.query(
			func.count(func.distinct(AccessLogEntry.user_id))
		).filter(AccessLogEntry.requested_at >= since,
		         AccessLogEntry.user_id.isnot(None)).scalar() or 0
		avg_ms = self.session.query(func.avg(AccessLogEntry.duration_ms)).filter(
			AccessLogEntry.requested_at >= since).scalar() or 0
		errors = self.session.query(func.count()).filter(
			AccessLogEntry.requested_at >= since,
			AccessLogEntry.status_code >= 400).scalar() or 0
		rph = round(total / max(hours, 1))
		return {
			"total_requests": total,
			"requests_per_hour": rph,
			"unique_users": unique_users,
			"avg_response_ms": int(avg_ms),
			"error_count": errors,
			"error_rate_pct": round(100 * errors / max(total, 1), 1),
		}
