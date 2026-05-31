"""
ERD Designer persistence models.

ErdDesign        — saved canvas state (Cytoscape JSON + schema snapshot)
ErdMigrationLog  — append-only DDL audit trail
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge import Model

__allow_unmapped__ = True


class ErdDesign(Model):
	"""
	A saved ERD canvas design.

	``canvas_json`` holds the Cytoscape.js element list so the designer can
	restore the exact layout, positions, and module groupings.
	``schema_json`` holds the normalised schema dict (tables/columns/FKs)
	that was current when the design was last saved.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erd_design"
	__table_args__ = (
		Index("ix_erd_design_owner", "owner_id"),
		Index("ix_erd_design_name",  "name"),
	)

	id          = Column(Integer, primary_key=True)
	name        = Column(String(255), nullable=False)
	description = Column(Text,        nullable=True)
	canvas_json = Column(JSONB,       nullable=False, server_default="{}")
	schema_json = Column(JSONB,       nullable=False, server_default="{}")
	is_public   = Column(Boolean,     nullable=False, default=False)
	owner_id    = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	created_on  = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on  = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	owner = relationship("User", foreign_keys=[owner_id])

	def __repr__(self) -> str:
		return f"<ErdDesign id={self.id} name={self.name!r}>"


class ErdMigrationLog(Model):
	"""
	Append-only DDL audit log.

	Written by ``ERDSchemaManager.apply_changes()`` on every successful
	(and failed) invocation. Never mutate existing rows — only INSERT.

	``rollback_sql`` holds auto-generated inverse DDL where deterministic
	(e.g. CREATE TABLE → DROP TABLE; ADD COLUMN → DROP COLUMN).
	Destructive ops (DROP TABLE, ALTER COLUMN TYPE) have no safe auto-rollback.
	"""

	__allow_unmapped__ = True
	__tablename__ = "erd_migration_log"
	__table_args__ = (
		Index("ix_erd_mig_log_user",   "user_id"),
		Index("ix_erd_mig_log_status", "status"),
		Index("ix_erd_mig_log_ts",     "applied_at"),
	)

	id           = Column(Integer, primary_key=True)
	user_id      = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	applied_at   = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	ops_json     = Column(JSONB, nullable=False, server_default="[]")
	sql_json     = Column(JSONB, nullable=False, server_default="[]")
	status       = Column(String(20), nullable=False)  # "success" | "error"
	error        = Column(Text,       nullable=True)
	rollback_sql = Column(JSONB, nullable=False, server_default="[]")

	user = relationship("User", foreign_keys=[user_id])

	def __repr__(self) -> str:
		return (
			f"<ErdMigrationLog id={self.id} status={self.status!r} "
			f"user={self.user_id} at={self.applied_at}>"
		)


__all__ = ["ErdDesign", "ErdMigrationLog"]
