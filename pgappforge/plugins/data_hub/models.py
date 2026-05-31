"""Data Hub models for import/export job tracking."""
from __future__ import annotations
from datetime import datetime, timezone
from pgappforge import Model
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer,
	String, Text)
from sqlalchemy.dialects.postgresql import JSONB


class ImportJob(Model):
	"""Tracks an async data import operation."""
	__tablename__ = "pgaf_import_job"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	model_name = Column(String(255), nullable=False)
	filename = Column(String(512))
	file_format = Column(String(20))  # csv/xlsx/json/ndjson/parquet
	status = Column(String(20), default="pending")
	# pending → validating → processing → done/failed/partial
	column_mapping = Column(JSONB, default=dict)
	# {upload_col: {"model_field": str, "transform": str|None}}
	options = Column(JSONB, default=dict)
	# {dedup_key: [cols], on_duplicate: skip|update|error, chunk_size: 500, dry_run: bool}
	total_rows = Column(Integer, default=0)
	rows_inserted = Column(Integer, default=0)
	rows_updated = Column(Integer, default=0)
	rows_skipped = Column(Integer, default=0)
	rows_errored = Column(Integer, default=0)
	error_details = Column(JSONB, default=list)
	# [{row_num: int, field: str, error: str, value: Any}]
	validation_summary = Column(JSONB, default=dict)
	# {missing_required: N, type_errors: N, fk_errors: N, duplicates: N}
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc))
	started_at = Column(DateTime(timezone=True))
	completed_at = Column(DateTime(timezone=True))
	file_path = Column(String(1024))  # temp file location


class ExportJob(Model):
	"""Tracks a scheduled or on-demand data export."""
	__tablename__ = "pgaf_export_job"
	__table_args__ = {"extend_existing": True}
	id = Column(Integer, primary_key=True)
	model_name = Column(String(255), nullable=False)
	file_format = Column(String(20), default="csv")
	status = Column(String(20), default="pending")
	filters = Column(JSONB, default=dict)        # active filter state
	columns = Column(JSONB, default=list)        # selected columns (empty = all)
	options = Column(JSONB, default=dict)
	# {redact_pii: bool, include_fk_labels: bool, max_rows: int}
	schedule = Column(String(256))               # RRULE for recurring exports
	last_run_at = Column(DateTime(timezone=True))
	next_run_at = Column(DateTime(timezone=True))
	delivery_method = Column(String(20), default="download")
	# download / email / storage
	delivery_config = Column(JSONB, default=dict)
	# {email: str} or {bucket: str, key_prefix: str}
	output_url = Column(String(1024))            # download link when done
	row_count = Column(Integer)
	created_by_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_at = Column(DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc))
	completed_at = Column(DateTime(timezone=True))
