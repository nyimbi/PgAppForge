"""Analytics engine models."""
from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgappforge.models.sqla import Model


class AnalyticsCube(Model):
	__tablename__ = "platform_analytics_cube"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(100), nullable=False)
	base_query = sa.Column(sa.Text, nullable=False, comment="SELECT query that backs the materialized view")
	refresh_schedule = sa.Column(sa.String(50), nullable=True, comment="cron expression")
	last_refreshed = sa.Column(sa.DateTime(timezone=True), nullable=True)
	dimensions = sa.Column(JSONB, nullable=False, comment="[{name, field, type}]")
	measures = sa.Column(JSONB, nullable=False, comment="[{name, field, agg: SUM|AVG|COUNT}]")
	is_active = sa.Column(sa.Boolean, nullable=False, default=True)


class AnalyticsReport(Model):
	__tablename__ = "platform_analytics_report"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	cube_id = sa.Column(sa.String(36), sa.ForeignKey("platform_analytics_cube.id"), nullable=False, index=True)
	tenant_id = sa.Column(sa.String(36), nullable=False, index=True)
	name = sa.Column(sa.String(200), nullable=False)
	filters = sa.Column(JSONB, nullable=True)
	group_by = sa.Column(JSONB, nullable=True)
	order_by = sa.Column(JSONB, nullable=True)
	limit_rows = sa.Column(sa.Integer, nullable=False, default=1000)
	visualization_type = sa.Column(sa.String(20), nullable=False, default="TABLE")


class ReportCache(Model):
	__tablename__ = "platform_report_cache"
	__table_args__ = ({"extend_existing": True},)

	id = sa.Column(sa.String(36), primary_key=True)
	report_id = sa.Column(sa.String(36), sa.ForeignKey("platform_analytics_report.id"), nullable=False, index=True)
	result_json = sa.Column(JSONB, nullable=True)
	cached_at = sa.Column(sa.DateTime(timezone=True), server_default=sa.text("NOW()"))
	expires_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
