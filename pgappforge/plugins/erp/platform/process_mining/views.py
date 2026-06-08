"""
pgappforge/plugins/erp/platform/process_mining/views.py

Flask views for the Platform / Process Mining plugin.

Registered views:
  ProcessMiningView  — event-log explorer with distinct event-type summary
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import current_app

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _tenant_id() -> str:
	return str(current_app.config.get("DEFAULT_TENANT_ID", ""))


# ---------------------------------------------------------------------------
# ProcessMiningView
# ---------------------------------------------------------------------------

class ProcessMiningView(BaseView):
	"""Process mining event-log explorer.

	GET /platform/process-mining/  — renders distinct event types from the
	                                  last 90 days of DomainEventLog entries
	"""

	route_base = "/platform/process-mining"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		from flask import render_template

		event_types: list[str] = []
		cutoff = datetime.now(timezone.utc) - timedelta(days=90)

		try:
			from pgappforge.plugins.erp.platform.process_mining.models import DomainEventLog
			session = _get_session()
			q = (
				sa.select(sa.distinct(DomainEventLog.event_type))
				.where(DomainEventLog.tenant_id == _tenant_id())
				.where(DomainEventLog.occurred_at >= cutoff)
				.order_by(DomainEventLog.event_type)
			)
			rows = session.execute(q).all()
			event_types = [r[0] for r in rows if r[0]]
		except Exception:
			log.exception("ProcessMiningView.index: failed to load event types")
			event_types = []

		return render_template(
			"platform/process_mining_view.html",
			event_types=event_types,
			cutoff=cutoff,
		)


__all__ = ["ProcessMiningView"]
