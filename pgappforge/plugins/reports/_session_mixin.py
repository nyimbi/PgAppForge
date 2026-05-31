"""Shared session accessor mixin for all ReportForge views."""

from __future__ import annotations


class ReportSessionMixin:
	"""Mixin that provides a uniform ``_get_session()`` for all ReportForge views.

	Preferred resolution order:
	1. FAB AppBuilder's session (main app session)
	2. Flask-SQLAlchemy's db.session
	3. RuntimeError

	All 6 ReportForge view classes previously had 3 divergent copies of this logic.
	"""

	def _get_session(self):
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab is not None:
			return ab.session
		db = current_app.extensions.get("sqlalchemy")
		if db is not None:
			return db.session
		raise RuntimeError("ReportForge: cannot obtain a SQLAlchemy session")
