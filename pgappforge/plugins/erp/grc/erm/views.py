"""
pgappforge/plugins/erp/grc/erm/views.py

Flask views for the GRC Enterprise Risk Management (ERM) plugin.

Registered views:
  ErmDashboardView  — risk register dashboard with KRI summary
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import current_app, make_response

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
# ErmDashboardView
# ---------------------------------------------------------------------------

class ErmDashboardView(BaseView):
	"""ERM risk register dashboard.

	GET /grc/erm/  — renders risk register with associated KRIs
	"""

	route_base = "/grc/erm"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		from flask import render_template

		risks = []
		kris = []

		try:
			from pgappforge.plugins.erp.grc.erm.models import RiskRegisterEntry
			session = _get_session()
			q = (
				sa.select(RiskRegisterEntry)
				.where(RiskRegisterEntry.tenant_id == _tenant_id())
				.order_by(sa.desc(RiskRegisterEntry.residual_score))
				.limit(200)
			)
			risks = session.execute(q).scalars().all()
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load risks")
			risks = []

		try:
			from pgappforge.plugins.erp.grc.erm.models import KeyRiskIndicator
			session = _get_session()
			q = (
				sa.select(KeyRiskIndicator)
				.where(KeyRiskIndicator.tenant_id == _tenant_id())
				.order_by(KeyRiskIndicator.name)
				.limit(200)
			)
			kris = session.execute(q).scalars().all()
		except Exception:
			log.exception("ErmDashboardView.dashboard: failed to load KRIs")
			kris = []

		return render_template("grc/erm_dashboard.html", risks=risks, kris=kris)


__all__ = ["ErmDashboardView"]
