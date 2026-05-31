"""
Security Designer models — snapshot storage for the Visual Security Designer.
"""
from __future__ import annotations

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Sequence, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model


class SecuritySnapshot(Model):
	"""Captures a point-in-time YAML snapshot of the full role/permission graph."""

	__tablename__ = "security_snapshot"

	id = Column(Integer, Sequence("security_snapshot_id_seq"), primary_key=True)
	name = Column(String(255), nullable=False)
	description = Column(String(500), nullable=True)
	snapshot_json = Column(JSONB, nullable=False, default=dict)
	taken_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.datetime.now(datetime.timezone.utc),
	)
	taken_by_id = Column(
		Integer,
		ForeignKey("ab_user.id", ondelete="SET NULL"),
		nullable=True,
	)
	taken_by = relationship("User", foreign_keys=[taken_by_id])

	def __repr__(self) -> str:
		return f"<SecuritySnapshot {self.name!r} at {self.taken_at}>"
