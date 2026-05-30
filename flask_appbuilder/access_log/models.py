"""SQLAlchemy model for HTTP access log entries."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
	BigInteger, Column, DateTime, Index, Integer, SmallInteger, String, Text,
	ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import INET
from flask_appbuilder import Model


class AccessLogEntry(Model):
	"""Every HTTP request to the application, logged for analysis.

	Indexes optimised for the most common analytical queries:
	- time-series analysis (requested_at)
	- per-user activity (user_id)
	- endpoint popularity (path)
	- error monitoring (status_code)

	Keep this table partitioned by month in high-traffic deployments::

	    CREATE TABLE fab_access_log_2026_01 PARTITION OF fab_access_log
	    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
	"""
	__tablename__ = "fab_access_log"

	id = Column(BigInteger, primary_key=True)

	# Request
	method = Column(String(8), nullable=False)
	path = Column(String(2048), nullable=False)
	query_string = Column(Text)
	blueprint = Column(String(128))          # FAB blueprint name if available
	view_func = Column(String(256))          # endpoint function name

	# Identity
	user_id = Column(Integer, ForeignKey("ab_user.id", ondelete="SET NULL"), nullable=True)
	username = Column(String(64))
	ip_address = Column(INET)
	user_agent = Column(Text)
	referer = Column(Text)
	session_id = Column(String(64))          # hashed session key

	# Response
	status_code = Column(SmallInteger, nullable=False, default=200)
	response_bytes = Column(Integer)
	duration_ms = Column(Integer)            # wall-clock milliseconds

	# Timestamps
	requested_at = Column(
		DateTime(timezone=True),
		nullable=False,
		server_default=func.now(),
		index=True,
	)

	__table_args__ = (
		Index("ix_fab_access_log_user_id", "user_id"),
		Index("ix_fab_access_log_status", "status_code"),
		Index(
			"ix_fab_access_log_path_pattern",
			"path",
			postgresql_ops={"path": "text_pattern_ops"},
		),
		Index("ix_fab_access_log_ip", "ip_address"),
	)

	def __repr__(self) -> str:
		return f"<AccessLog {self.method} {self.path} {self.status_code}>"
