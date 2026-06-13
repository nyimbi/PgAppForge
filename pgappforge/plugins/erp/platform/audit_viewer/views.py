"""
pgappforge/plugins/erp/platform/audit_viewer/views.py

AuditLogView — read-only web browser for pgaf_audit_log.

Routes
------
GET  /platform/audit/              → audit_log.html  (browser UI)
GET  /platform/audit/api/query     → JSON {rows, count}

Both routes are guarded by ``@has_access`` so only authenticated users with
the appropriate permissions can reach them.
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


class AuditLogView(BaseERPView):
	"""Read-only browser for the platform audit log.

	Renders a search UI backed by the ``/platform/audit/api/query`` JSON
	endpoint.  All data is fetched client-side via ``fetch()`` so the initial
	page load is instant even when the audit table has millions of rows.

	Permissions
	-----------
	``can_audit_log_index``     — required to load the UI page
	``can_audit_log_query_api`` — required to call the JSON query endpoint

	Both permissions should be granted to the ``Admin`` role and any dedicated
	``ComplianceOfficer`` / ``InternalAuditor`` roles.
	"""

	route_base     = "/platform/audit"
	default_view   = "index"

	# ── UI route ──────────────────────────────────────────────────────────────

	@expose("/")
	@has_access
	def index(self):
		"""Render the audit log browser page."""
		return render_template(
			"appbuilder/audit/audit_log.html",
			appbuilder=self.appbuilder,
		)

	# ── JSON API route ────────────────────────────────────────────────────────

	@expose("/api/query")
	@has_access
	def query_api(self):
		"""Return audit rows as JSON, filtered by optional query-string params.

		Query parameters
		----------------
		table      str   Filter by exact table name.
		record_id  str   Filter by exact record primary key.
		user_id    str   Filter by exact user UUID.
		limit      int   Max rows (server cap: 500).  Default 100.

		Response
		--------
		.. code-block:: json

		    {
		        "rows":  [ { ...audit_row... }, ... ],
		        "count": 42
		    }
		"""
		from pgappforge.audit import query_audit

		table     = request.args.get("table")     or None
		record_id = request.args.get("record_id") or None
		user_id   = request.args.get("user_id")   or None
		limit     = min(int(request.args.get("limit", 100)), 500)

		try:
			rows = query_audit(
				table_name=table,
				record_id=record_id,
				user_id=user_id,
				limit=limit,
			)
		except Exception as exc:
			log.warning("AuditLogView.query_api error: %s", exc)
			rows = []

		return jsonify({"rows": rows, "count": len(rows)})


__all__ = ["AuditLogView"]
