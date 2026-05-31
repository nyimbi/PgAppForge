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
	data_binding  = Column(String(255), nullable=True)   # SQL column alias
	format_string = Column(String(128), nullable=True)   # e.g. "{:,.2f}"

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
	error_message = Column(Text,        nullable=True)
	scheduled_at  = Column(DateTime(timezone=True), nullable=True)
	sent_at       = Column(DateTime(timezone=True), nullable=True)
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
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"PaperSize",
	"Orientation",
	"BandType",
	"FieldType",
	"ParameterType",
	"DispatchStatus",
	"Report",
	"ReportBand",
	"ReportField",
	"ReportParameter",
	"ReportDispatch",
	"SavedQuery",
]
