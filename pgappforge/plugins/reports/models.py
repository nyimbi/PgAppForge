"""
pgappforge/plugins/reports/models.py

SQLAlchemy models for the banded report builder plugin.

Four core tables:
    Report         — top-level report definition (datasource, paper size, orientation)
    ReportBand     — horizontal band on the report canvas (title, detail, footer, …)
    ReportField    — positioned element inside a band (text, number, image, chart, …)
    ReportParameter — runtime parameter that gets substituted into the SQL datasource
"""

from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	Enum as SAEnum,
	Float,
	ForeignKey,
	Index,
	Integer,
	LargeBinary,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge import Model

__allow_unmapped__ = True

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PaperSize(str, enum.Enum):
	A4     = "A4"
	LETTER = "letter"
	LEGAL  = "legal"
	A3     = "A3"
	A5     = "A5"


class Orientation(str, enum.Enum):
	PORTRAIT  = "portrait"
	LANDSCAPE = "landscape"


class BandType(str, enum.Enum):
	TITLE         = "title"
	PAGE_HEADER   = "page_header"
	COLUMN_HEADER = "column_header"
	GROUP_HEADER  = "group_header"
	DETAIL        = "detail"
	GROUP_FOOTER  = "group_footer"
	SUMMARY       = "summary"
	PAGE_FOOTER   = "page_footer"


class FieldType(str, enum.Enum):
	TEXT      = "text"
	NUMBER    = "number"
	DATE      = "date"
	IMAGE     = "image"
	LINE      = "line"
	BOX       = "box"
	CHART     = "chart"
	SUBREPORT = "subreport"


class ParameterType(str, enum.Enum):
	STRING  = "string"
	INTEGER = "integer"
	FLOAT   = "float"
	DATE    = "date"
	BOOLEAN = "boolean"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class Report(Model):
	"""
	Top-level report definition.

	``data_source`` holds either a raw SQL query (when ``is_sql_source`` is
	True) or a dotted model path such as ``"myapp.models.Order"`` that the
	engine will introspect at render time.

	Example layout for ``page_config``::

	    {
	        "margin_top_mm": 10,
	        "margin_bottom_mm": 10,
	        "margin_left_mm": 15,
	        "margin_right_mm": 15,
	        "columns": 1,
	        "column_gap_mm": 5
	    }
	"""

	__allow_unmapped__ = True
	__tablename__ = "report"
	__table_args__ = (
		Index("ix_report_name", "name"),
		Index("ix_report_created_by", "created_by"),
	)

	id          = Column(Integer, primary_key=True)
	name        = Column(String(255), nullable=False)
	description = Column(Text,        nullable=True)

	# datasource — raw SQL or model reference
	data_source    = Column(Text,    nullable=False, default="SELECT 1")
	is_sql_source  = Column(Boolean, nullable=False, default=True)
	# column used to drive GROUP BY bands; NULL means no grouping
	group_field    = Column(String(128), nullable=True)

	# paper settings
	paper_size  = Column(
		SAEnum(PaperSize, name="report_paper_size"),
		nullable=False,
		default=PaperSize.A4,
	)
	orientation = Column(
		SAEnum(Orientation, name="report_orientation"),
		nullable=False,
		default=Orientation.PORTRAIT,
	)

	# JSONB bag for margin, column count, etc.
	page_config = Column(JSONB, nullable=False, server_default="{}")

	# audit
	created_by = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)
	changed_on = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	# ── Visibility ─────────────────────────────────────────────────────────
	is_public = Column(Boolean, nullable=False, default=False)

	# relationships — lazy="select" so changes to bands are tracked by
	# SQLAlchemy attribute events (flag_modified works); "dynamic" broke that.
	bands      = relationship(
		"ReportBand",
		back_populates="report",
		cascade="all, delete-orphan",
		order_by="ReportBand.position",
		lazy="select",
	)
	parameters = relationship(
		"ReportParameter",
		back_populates="report",
		cascade="all, delete-orphan",
		lazy="select",
	)
	creator = relationship("User", foreign_keys=[created_by])

	def __repr__(self) -> str:
		return f"<Report id={self.id} name={self.name!r}>"

	# ── Branding ──────────────────────────────────────────────────────────────
	company_name       = Column(String(255),  nullable=True)
	logo_url           = Column(String(500),  nullable=True)
	primary_color      = Column(String(16),   nullable=False, default="#003366")
	secondary_color    = Column(String(16),   nullable=False, default="#666666")
	watermark_text     = Column(String(255),  nullable=True)
	watermark_opacity  = Column(Float,        nullable=False, default=0.08)
	custom_header_html = Column(Text,         nullable=True)
	custom_footer_html = Column(Text,         nullable=True)

	# ── Template ───────────────────────────────────────────────────────────
	template_key = Column(String(64), nullable=True)  # "invoice" | "quote" | ...

	# ── Organisation ───────────────────────────────────────────────────────
	category_id    = Column(Integer, ForeignKey("reportforge_category.id",  ondelete="SET NULL"), nullable=True)
	datasource_id  = Column(Integer, ForeignKey("reportforge_datasource.id", ondelete="SET NULL"), nullable=True)
	is_draft       = Column(Boolean, nullable=False, default=True)
	current_version = Column(Integer, nullable=False, default=0)

	# ── Relationships (additional) ─────────────────────────────────────────
	dispatches = relationship(
		"ReportDispatch",
		back_populates="report",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def band_list(self) -> list[ReportBand]:
		"""Return bands in render order (position ASC)."""
		return list(self.bands.order_by(ReportBand.position))

	def parameter_dict(self) -> dict[str, Any]:
		"""Return {name: default_value} for all parameters."""
		return {p.name: p.default_value for p in self.parameters}


# ---------------------------------------------------------------------------
# ReportBand
# ---------------------------------------------------------------------------

class ReportBand(Model):
	"""
	A horizontal strip on the report canvas.

	Bands are stacked vertically in ``position`` order.  The engine renders
	each band type at the appropriate point in the print cycle (once per page,
	once per group, once per data row, etc.).

	``background_color`` accepts any CSS colour string (``"#ffffff"``,
	``"transparent"``, ``"rgb(240,240,240)"``).
	"""

	__allow_unmapped__ = True
	__tablename__ = "report_band"
	__table_args__ = (
		Index("ix_report_band_report_id", "report_id"),
		Index("ix_report_band_position",  "report_id", "position"),
	)

	id        = Column(Integer, primary_key=True)
	report_id = Column(
		Integer,
		ForeignKey("report.id", ondelete="CASCADE"),
		nullable=False,
	)
	band_type = Column(
		SAEnum(BandType, name="report_band_type"),
		nullable=False,
		default=BandType.DETAIL,
	)
	position         = Column(Integer,      nullable=False, default=0)
	height_mm        = Column(Float,        nullable=False, default=20.0)
	background_color = Column(String(64),   nullable=False, default="#ffffff")

	# optional: group field value this band is keyed to (group bands only)
	group_field = Column(String(128), nullable=True)

	# JSONB for band-level style overrides (border, padding, visibility rules)
	style = Column(JSONB, nullable=False, server_default="{}")

	# relationships
	report = relationship("Report", back_populates="bands")
	fields = relationship(
		"ReportField",
		back_populates="band",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return (
			f"<ReportBand id={self.id} type={self.band_type.value!r} "
			f"report_id={self.report_id} pos={self.position}>"
		)

	def field_list(self) -> list[ReportField]:
		"""All fields in this band, sorted by y then x."""
		return list(self.fields.order_by(ReportField.y_mm, ReportField.x_mm))


# ---------------------------------------------------------------------------
# ReportField
# ---------------------------------------------------------------------------

class ReportField(Model):
	"""
	A positioned element inside a ReportBand.

	Position and size are in millimetres relative to the band's top-left corner.

	``data_binding`` is the column alias from the report's SQL datasource that
	this field renders, e.g. ``"invoice_total"``.  For static text fields set
	``data_binding`` to NULL and put the literal in ``style["text"]``.

	``format_string`` follows Python's ``str.format`` / ``format()`` mini-language:
	    - numbers : ``"{:,.2f}"``
	    - dates   : ``"{:%Y-%m-%d}"``
	    - text    : ``"{}"``  (default, no-op)

	``style`` JSONB schema (all keys optional)::

	    {
	        "text"        : "Static label",
	        "font_name"   : "Helvetica",
	        "font_size"   : 10,
	        "bold"        : false,
	        "italic"      : false,
	        "color"       : "#000000",
	        "bg_color"    : "transparent",
	        "align"       : "left",       // left | center | right
	        "valign"      : "top",        // top | middle | bottom
	        "border"      : 0,            // pt thickness, 0 = none
	        "border_color": "#000000",
	        "line_width"  : 0.5,          // for line/box fields
	        "image_src"   : "/static/…",  // for image fields
	        "chart_config": {}            // Chart.js or reportlab spec
	    }
	"""

	__allow_unmapped__ = True
	__tablename__ = "report_field"
	__table_args__ = (
		Index("ix_report_field_band_id",    "band_id"),
		Index("ix_report_field_field_type",  "field_type"),
	)

	id      = Column(Integer, primary_key=True)
	band_id = Column(
		Integer,
		ForeignKey("report_band.id", ondelete="CASCADE"),
		nullable=False,
	)
	field_type = Column(
		SAEnum(FieldType, name="report_field_type"),
		nullable=False,
		default=FieldType.TEXT,
	)

	# geometry (mm)
	x_mm      = Column(Float, nullable=False, default=0.0)
	y_mm      = Column(Float, nullable=False, default=0.0)
	width_mm  = Column(Float, nullable=False, default=40.0)
	height_mm = Column(Float, nullable=False, default=8.0)

	# data
	data_binding      = Column(String(255), nullable=True)   # SQL column alias
	format_string     = Column(String(128), nullable=True)   # e.g. "{:,.2f}"
	link_url_template = Column(String(500), nullable=True)   # drill-down: "/reports/run/42?id={customer_id}"
	compute           = Column(String(255), nullable=True)   # aggregate: "sum(amount)", "count(*)"

	# rich style / config blob
	style = Column(JSONB, nullable=False, server_default="{}")

	# relationships
	band = relationship("ReportBand", back_populates="fields")

	def __repr__(self) -> str:
		return (
			f"<ReportField id={self.id} type={self.field_type.value!r} "
			f"binding={self.data_binding!r} x={self.x_mm} y={self.y_mm}>"
		)

	@property
	def rect_mm(self) -> tuple[float, float, float, float]:
		"""(x, y, width, height) in mm — convenience for the engine."""
		return (self.x_mm, self.y_mm, self.width_mm, self.height_mm)


# ---------------------------------------------------------------------------
# ReportParameter
# ---------------------------------------------------------------------------

class ReportParameter(Model):
	"""
	A named, typed runtime parameter injected into the report datasource query.

	The engine replaces ``:name`` placeholders in the SQL with bound values.
	If the caller omits a value the engine falls back to ``default_value``.

	Example usage in a datasource query::

	    SELECT * FROM orders
	    WHERE status = :status
	      AND created_at >= :from_date

	With parameters::

	    ReportParameter(name="status",    type=ParameterType.STRING,  default_value="open")
	    ReportParameter(name="from_date", type=ParameterType.DATE,    default_value="2024-01-01")
	"""

	__allow_unmapped__ = True
	__tablename__ = "report_parameter"
	__table_args__ = (
		Index("ix_report_parameter_report_id", "report_id"),
	)

	id        = Column(Integer, primary_key=True)
	report_id = Column(
		Integer,
		ForeignKey("report.id", ondelete="CASCADE"),
		nullable=False,
	)

	name          = Column(String(128), nullable=False)
	param_type    = Column(
		SAEnum(ParameterType, name="report_parameter_type"),
		nullable=False,
		default=ParameterType.STRING,
	)
	label         = Column(String(255), nullable=True)   # human-readable label for the UI
	default_value = Column(Text,        nullable=True)
	required      = Column(Boolean,     nullable=False, default=False)
	options_sql   = Column(Text,        nullable=True)   # SELECT id, label FROM … for dropdown pickers
	depends_on    = Column(String(128), nullable=True)   # name of parent param (cascading selects)

	# relationships
	report = relationship("Report", back_populates="parameters")

	def __repr__(self) -> str:
		return (
			f"<ReportParameter id={self.id} name={self.name!r} "
			f"type={self.param_type.value!r} default={self.default_value!r}>"
		)

	def coerce(self, raw: str | None) -> Any:
		"""
		Coerce a string value from a web form into the correct Python type.

		Returns ``default_value`` (as a string) when *raw* is None/empty.
		"""
		value = raw if raw not in (None, "") else self.default_value
		if value is None:
			return None

		if self.param_type == ParameterType.INTEGER:
			return int(value)
		if self.param_type == ParameterType.FLOAT:
			return float(value)
		if self.param_type == ParameterType.BOOLEAN:
			return str(value).lower() in ("1", "true", "yes", "on")
		if self.param_type == ParameterType.DATE:
			from datetime import date
			return date.fromisoformat(str(value))
		return str(value)


# ---------------------------------------------------------------------------
# ReportDispatch — email / scheduled delivery records
# ---------------------------------------------------------------------------

class DispatchStatus(str, enum.Enum):
	PENDING  = "pending"
	SENT     = "sent"
	FAILED   = "failed"
	SCHEDULED = "scheduled"


class ReportDispatch(Model):
	"""
	An email dispatch job for a report.

	Supports immediate send (status=sent immediately) and scheduled
	delivery (status=scheduled, scheduled_at set).

	``to_email`` is a comma-separated list of recipient addresses.
	``params_json`` holds report parameter values for this dispatch.
	``export_format`` is "pdf" | "docx" | "xlsx" | "csv".
	"""

	__allow_unmapped__ = True
	__tablename__ = "report_dispatch"
	__table_args__ = (
		Index("ix_report_dispatch_report_id", "report_id"),
		Index("ix_report_dispatch_status",    "status"),
	)

	id        = Column(Integer, primary_key=True)
	report_id = Column(
		Integer,
		ForeignKey("report.id", ondelete="CASCADE"),
		nullable=False,
	)

	to_email      = Column(Text,        nullable=False)         # comma-separated
	cc_email      = Column(Text,        nullable=True)
	subject       = Column(String(500), nullable=False)
	body_text     = Column(Text,        nullable=True)
	export_format = Column(String(10),  nullable=False, default="pdf")
	params_json   = Column(JSONB,       nullable=False, server_default="{}")
	status        = Column(
		SAEnum(DispatchStatus, name="report_dispatch_status"),
		nullable=False,
		default=DispatchStatus.PENDING,
	)
	error_message    = Column(Text,         nullable=True)
	scheduled_at     = Column(DateTime(timezone=True), nullable=True)
	sent_at          = Column(DateTime(timezone=True), nullable=True)
	recurrence_rule  = Column(String(255),  nullable=True)  # RRULE: "FREQ=WEEKLY;BYDAY=MO"
	next_run_at      = Column(DateTime(timezone=True), nullable=True)  # computed after each send
	created_by    = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	created_on    = Column(
		DateTime(timezone=True),
		default=lambda: datetime.now(timezone.utc),
		nullable=False,
	)

	report  = relationship("Report", back_populates="dispatches")
	creator = relationship("User", foreign_keys=[created_by])

	def __repr__(self) -> str:
		return (
			f"<ReportDispatch id={self.id} report_id={self.report_id} "
			f"status={self.status.value!r} to={self.to_email!r}>"
		)


# ---------------------------------------------------------------------------
# SavedQuery — user-saved SQL queries for the visual SQL editor
# ---------------------------------------------------------------------------

class SavedQuery(Model):
	"""
	A user-saved SQL query built with the ReportForge visual SQL editor.

	``sql_text`` holds the final SQL string.
	``query_def`` holds the visual builder definition (tables, columns,
	joins, filters) so the query can be re-loaded into the builder UI.
	``is_public`` makes the query visible to all users (read-only).
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_saved_query"
	__table_args__ = (
		Index("ix_reportforge_query_created_by", "created_by"),
		Index("ix_reportforge_query_is_public",  "is_public"),
	)

	id          = Column(Integer, primary_key=True)
	name        = Column(String(255), nullable=False)
	description = Column(Text,        nullable=True)
	sql_text    = Column(Text,        nullable=False)
	query_def   = Column(JSONB,       nullable=False, server_default="{}")
	is_public   = Column(Boolean,     nullable=False, default=False)
	created_by  = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
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

	creator = relationship("User", foreign_keys=[created_by])

	def __repr__(self) -> str:
		return f"<SavedQuery id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ReportDatasource — shared SQL registry (referenced by multiple reports)
# ---------------------------------------------------------------------------

class ReportDatasource(Model):
	"""A named, reusable SQL query shared across multiple reports."""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_datasource"
	__table_args__ = (Index("ix_reportforge_ds_name", "name"),)

	id          = Column(Integer, primary_key=True)
	name        = Column(String(255), nullable=False)
	description = Column(Text,        nullable=True)
	sql_text    = Column(Text,        nullable=False)
	params_schema = Column(JSONB,     nullable=False, server_default="{}")
	owner_id    = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	created_on  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
	changed_on  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
	                     onupdate=lambda: datetime.now(timezone.utc), nullable=False)

	owner = relationship("User", foreign_keys=[owner_id])

	def __repr__(self) -> str:
		return f"<ReportDatasource id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ReportCategory — folder navigation for reports
# ---------------------------------------------------------------------------

class ReportCategory(Model):
	"""Hierarchical folder for organising reports. Self-referential for nesting."""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_category"
	__table_args__ = (Index("ix_reportforge_cat_parent", "parent_id"),)

	id        = Column(Integer, primary_key=True)
	name      = Column(String(128), nullable=False)
	parent_id = Column(Integer, ForeignKey("reportforge_category.id", ondelete="SET NULL"), nullable=True)
	owner_id  = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	color     = Column(String(16),  nullable=False, default="#0066cc")
	icon      = Column(String(64),  nullable=False, default="fa-folder")
	created_on = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	parent   = relationship("ReportCategory", remote_side="ReportCategory.id", foreign_keys=[parent_id])
	owner    = relationship("User", foreign_keys=[owner_id])

	def __repr__(self) -> str:
		return f"<ReportCategory id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ReportGrant — per-report ACL
# ---------------------------------------------------------------------------

class ReportGrant(Model):
	"""
	Grants a principal (user or role) a permission on a specific report.

	``principal_type`` : "user" | "role"
	``permission``     : "view" | "run" | "download" | "edit"
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_grant"
	__table_args__ = (
		Index("ix_reportforge_grant_report",    "report_id"),
		Index("ix_reportforge_grant_principal", "principal_type", "principal_id"),
	)

	id             = Column(Integer,     primary_key=True)
	report_id      = Column(Integer,     ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	principal_type = Column(String(16),  nullable=False)   # "user" | "role"
	principal_id   = Column(Integer,     nullable=False)
	permission     = Column(String(16),  nullable=False)   # "view" | "run" | "download" | "edit"
	granted_by     = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	granted_on     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report  = relationship("Report")
	granter = relationship("User", foreign_keys=[granted_by])

	def __repr__(self) -> str:
		return (f"<ReportGrant id={self.id} report={self.report_id} "
		        f"{self.principal_type}/{self.principal_id} {self.permission!r}>")


# ---------------------------------------------------------------------------
# ReportAccessLog — audit trail for all report accesses
# ---------------------------------------------------------------------------

class ReportAccessLog(Model):
	"""
	Append-only log of every report run, download, dispatch, and share-token access.
	Write a row via ``acl.log_access()`` — never mutate existing rows.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_access_log"
	__table_args__ = (
		Index("ix_reportforge_log_report",  "report_id"),
		Index("ix_reportforge_log_user",    "user_id"),
		Index("ix_reportforge_log_at",      "accessed_at"),
	)

	id          = Column(Integer, primary_key=True)
	report_id   = Column(Integer, ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	user_id     = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	action      = Column(String(32), nullable=False)  # "run"|"download"|"dispatch"|"embed"|"token"
	format      = Column(String(10), nullable=True)   # "pdf"|"docx"|"xlsx"|"csv"
	params_json = Column(JSONB,   nullable=False, server_default="{}")
	ip_address  = Column(String(64), nullable=True)
	accessed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report = relationship("Report")
	user   = relationship("User", foreign_keys=[user_id])

	def __repr__(self) -> str:
		return f"<ReportAccessLog id={self.id} report={self.report_id} action={self.action!r}>"


# ---------------------------------------------------------------------------
# ReportShareToken — view-once / quota-limited / expiring share links
# ---------------------------------------------------------------------------

class ReportShareToken(Model):
	"""
	A share token that grants access to a report without requiring login.

	Set ``max_uses=1`` for view-once links.
	Set ``expires_at`` to expire after a deadline.
	``params_json`` pre-fills report parameters for the recipient.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_share_token"
	__table_args__ = (
		Index("ix_reportforge_token_report", "report_id"),
		Index("ix_reportforge_token_token",  "token", unique=True),
	)

	id            = Column(Integer, primary_key=True)
	token         = Column(String(64),  nullable=False, unique=True)
	report_id     = Column(Integer,     ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	max_uses      = Column(Integer,     nullable=True)   # None = unlimited
	uses_remaining = Column(Integer,    nullable=True)
	expires_at    = Column(DateTime(timezone=True), nullable=True)
	params_json   = Column(JSONB,       nullable=False, server_default="{}")
	created_by    = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	created_on    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report  = relationship("Report")
	creator = relationship("User", foreign_keys=[created_by])

	@property
	def is_valid(self) -> bool:
		from datetime import timezone
		now = datetime.now(timezone.utc)
		if self.expires_at and self.expires_at < now:
			return False
		if self.uses_remaining is not None and self.uses_remaining <= 0:
			return False
		return True

	def __repr__(self) -> str:
		return f"<ReportShareToken id={self.id} report={self.report_id} remaining={self.uses_remaining}>"


# ---------------------------------------------------------------------------
# ReportVersion — snapshot on "publish"
# ---------------------------------------------------------------------------

class ReportVersion(Model):
	"""
	Immutable snapshot of a Report's definition at the time of publishing.
	Stored as JSONB so it can be restored without complex joins.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_version"
	__table_args__ = (Index("ix_reportforge_ver_report", "report_id"),)

	id            = Column(Integer, primary_key=True)
	report_id     = Column(Integer, ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	version       = Column(Integer, nullable=False)       # monotonically increasing per report
	snapshot_json = Column(JSONB,   nullable=False)       # {bands, fields, params, branding}
	note          = Column(Text,    nullable=True)        # optional changelog note
	created_by    = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
	created_on    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report  = relationship("Report")
	creator = relationship("User", foreign_keys=[created_by])

	def __repr__(self) -> str:
		return f"<ReportVersion id={self.id} report={self.report_id} v={self.version}>"


# ---------------------------------------------------------------------------
# ReportSubscription — user opt-in recurring report delivery
# ---------------------------------------------------------------------------

class ReportSubscription(Model):
	"""
	A user's personal subscription to receive a report on a schedule.

	``frequency`` is an RRULE fragment, e.g. ``FREQ=WEEKLY;BYDAY=MO``.
	``next_run_at`` is computed by the scheduler after each successful send.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_subscription"
	__table_args__ = (
		Index("ix_reportforge_sub_user",    "user_id"),
		Index("ix_reportforge_sub_report",  "report_id"),
		Index("ix_reportforge_sub_next",    "next_run_at"),
	)

	id          = Column(Integer, primary_key=True)
	report_id   = Column(Integer, ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	user_id     = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
	format      = Column(String(10), nullable=False, default="pdf")
	frequency   = Column(String(255), nullable=False)      # RRULE fragment
	params_json = Column(JSONB,   nullable=False, server_default="{}")
	is_active   = Column(Boolean, nullable=False, default=True)
	next_run_at = Column(DateTime(timezone=True), nullable=True)
	created_on  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report = relationship("Report")
	user   = relationship("User", foreign_keys=[user_id])

	def __repr__(self) -> str:
		return f"<ReportSubscription id={self.id} report={self.report_id} user={self.user_id}>"


# ---------------------------------------------------------------------------
# Dashboard — bundles of reports rendered together
# ---------------------------------------------------------------------------

class Dashboard(Model):
	"""
	A named collection of reports arranged in a CSS-Grid layout.

	``layout_json`` schema::

	    [
	      {"report_id": 1, "x": 0, "y": 0, "w": 6, "h": 4, "params": {}},
	      {"report_id": 2, "x": 6, "y": 0, "w": 6, "h": 4, "params": {}}
	    ]
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_dashboard"
	__table_args__ = (Index("ix_reportforge_dash_owner", "owner_id"),)

	id          = Column(Integer, primary_key=True)
	name        = Column(String(255), nullable=False)
	description = Column(Text,        nullable=True)
	layout_json = Column(JSONB,       nullable=False, server_default="[]")
	is_public   = Column(Boolean,     nullable=False, default=False)
	owner_id    = Column(Integer,     ForeignKey("ab_user.id"), nullable=True)
	created_on  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
	changed_on  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
	                     onupdate=lambda: datetime.now(timezone.utc), nullable=False)

	owner = relationship("User", foreign_keys=[owner_id])

	def __repr__(self) -> str:
		return f"<Dashboard id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ReportRenderCache — render cache keyed by (report_id, params, changed_on, fmt)
# ---------------------------------------------------------------------------

class ReportRenderCache(Model):
	"""
	Caches rendered report bytes to avoid re-executing SQL on repeated downloads.

	Cache key is a SHA-256 hex digest of (report_id, sorted_params, changed_on, format).
	Invalidated automatically when a report's ``changed_on`` advances.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_render_cache"
	__table_args__ = (
		Index("ix_reportforge_cache_key",     "cache_key", unique=True),
		Index("ix_reportforge_cache_expires", "expires_at"),
	)

	id         = Column(Integer,     primary_key=True)
	cache_key  = Column(String(64),  nullable=False, unique=True)
	report_id  = Column(Integer,     ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	format     = Column(String(10),  nullable=False)   # "pdf"|"xlsx"|"csv"
	data       = Column(LargeBinary, nullable=False)   # rendered bytes
	size_bytes = Column(Integer,     nullable=False, default=0)
	expires_at = Column(DateTime(timezone=True), nullable=False)
	created_on = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

	report = relationship("Report")

	def __repr__(self) -> str:
		return f"<ReportRenderCache id={self.id} report={self.report_id} fmt={self.format!r}>"


# ---------------------------------------------------------------------------
# ReportJob — background rendering job for large reports
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
	PENDING    = "pending"
	RUNNING    = "running"
	DONE       = "done"
	FAILED     = "failed"


class ReportJob(Model):
	"""
	Background render job. Created by POST /reports/render-async/<id>.
	Worker thread updates status and stores result as a share token URL.
	"""

	__allow_unmapped__ = True
	__tablename__ = "reportforge_job"
	__table_args__ = (
		Index("ix_reportforge_job_report", "report_id"),
		Index("ix_reportforge_job_status", "status"),
	)

	id          = Column(Integer,    primary_key=True)
	report_id   = Column(Integer,    ForeignKey("report.id", ondelete="CASCADE"), nullable=False)
	format      = Column(String(10), nullable=False, default="pdf")
	params_json = Column(JSONB,      nullable=False, server_default="{}")
	status      = Column(
		SAEnum(JobStatus, name="reportforge_job_status"),
		nullable=False,
		default=JobStatus.PENDING,
	)
	result_token = Column(String(64), nullable=True)   # share token for download
	error        = Column(Text,       nullable=True)
	created_by   = Column(Integer,    ForeignKey("ab_user.id"), nullable=True)
	created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
	finished_at  = Column(DateTime(timezone=True), nullable=True)

	report  = relationship("Report")
	creator = relationship("User", foreign_keys=[created_by])

	def __repr__(self) -> str:
		return f"<ReportJob id={self.id} report={self.report_id} status={self.status.value!r}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PaperSize",
	"Orientation",
	"BandType",
	"FieldType",
	"ParameterType",
	"DispatchStatus",
	"JobStatus",
	"Report",
	"ReportBand",
	"ReportField",
	"ReportParameter",
	"ReportDispatch",
	"SavedQuery",
	"ReportDatasource",
	"ReportCategory",
	"ReportGrant",
	"ReportAccessLog",
	"ReportShareToken",
	"ReportVersion",
	"ReportSubscription",
	"Dashboard",
	"ReportRenderCache",
	"ReportJob",
]
