"""
pgappforge/plugins/erp/platform/versioning/views.py

Flask views for the Git-backed versioning plugin.

Routes
------
  GET  /platform/versioning/           — dashboard: current version + recent config commits
  GET  /platform/versioning/diff       — JSON unified diff between two commits
                                          ?file=<path>&from=<SHA>&to=<SHA>
  GET  /platform/versioning/file       — file content at a commit
                                          ?path=<path>&sha=<SHA>
  POST /platform/versioning/revert     — restore file to a commit (admin only)
                                          body: {"file": "<path>", "sha": "<SHA>"}
"""
from __future__ import annotations

import logging

from flask import current_app, jsonify, render_template, request
from markupsafe import Markup

from pgappforge import expose
from pgappforge.baseviews import BaseView
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

from pgappforge.plugins.erp.platform.versioning.services import VersioningService

log = logging.getLogger(__name__)


def _svc() -> VersioningService:
	"""Return a VersioningService pointing at the repo root."""
	import os
	repo_path = current_app.config.get("VERSIONING_REPO_PATH", os.getcwd())
	return VersioningService(repo_path)


class VersioningDashboardView(BaseERPView):
	"""Main versioning dashboard — current version summary + config commit history."""

	route_base = "/platform/versioning"

	# ------------------------------------------------------------------ #
	# Dashboard                                                            #
	# ------------------------------------------------------------------ #

	@expose("/")
	@has_access
	def index(self):
		svc = _svc()
		version = svc.current_version()
		history = svc.get_config_history(limit=30)

		kpi_html = self.kpi_cards([
			{
				"label": "Current SHA",
				"value": version.get("sha", "?"),
				"icon": "fa-code-fork",
				"color": "#1a56db",
				"format": "integer",
			},
			{
				"label": "Config Commits",
				"value": len(history),
				"icon": "fa-history",
				"color": "#0e9f6e",
				"format": "integer",
			},
			{
				"label": "Dirty Files",
				"value": len(version.get("dirty_files", [])),
				"icon": "fa-exclamation-triangle",
				"color": "#e3a008" if version.get("is_dirty") else "#6b7280",
				"format": "integer",
			},
		])

		return render_template(
			"versioning/dashboard.html",
			version=version,
			history=history,
			kpi_html=kpi_html,
			appbuilder=self.appbuilder,
		)

	# ------------------------------------------------------------------ #
	# Diff                                                                 #
	# ------------------------------------------------------------------ #

	@expose("/diff")
	@has_access
	def diff(self):
		"""Return unified diff as JSON.

		Query params:
		  file  — repo-relative file path (required)
		  from  — base commit SHA (required)
		  to    — head commit SHA (default: HEAD)
		"""
		file_path = request.args.get("file", "").strip()
		sha_from = request.args.get("from", "").strip()
		sha_to = request.args.get("to", "HEAD").strip()

		if not file_path or not sha_from:
			return jsonify({"error": "file and from parameters are required"}), 400

		svc = _svc()
		diff_text = svc.get_file_diff(file_path, sha_from, sha_to)
		return jsonify(
			{
				"file": file_path,
				"from": sha_from,
				"to": sha_to,
				"diff": diff_text,
			}
		)

	# ------------------------------------------------------------------ #
	# File preview                                                         #
	# ------------------------------------------------------------------ #

	@expose("/file")
	@has_access
	def file_at_commit(self):
		"""Return file content at a specific commit as JSON.

		Query params:
		  path  — repo-relative file path (required)
		  sha   — commit SHA (required)
		"""
		file_path = request.args.get("path", "").strip()
		sha = request.args.get("sha", "").strip()

		if not file_path or not sha:
			return jsonify({"error": "path and sha parameters are required"}), 400

		svc = _svc()
		content = svc.get_file_at_commit(file_path, sha)
		if content is None:
			return jsonify({"error": f"{file_path}@{sha} not found"}), 404

		return jsonify({"file": file_path, "sha": sha, "content": content})

	# ------------------------------------------------------------------ #
	# Revert (admin only)                                                  #
	# ------------------------------------------------------------------ #

	@expose("/revert", methods=["POST"])
	@has_access
	def revert(self):
		"""Restore a file to a specific commit.

		Requires admin role.  Creates a new git commit.

		JSON body::

		    {"file": "<repo-relative-path>", "sha": "<commit-SHA>"}
		"""
		# Extra admin check — only users with the admin role may revert
		from flask_login import current_user  # type: ignore[import]
		try:
			if not current_user.is_authenticated:
				return jsonify({"success": False, "error": "Authentication required"}), 401
		except Exception:
			pass

		data = request.get_json(silent=True) or {}
		file_path = data.get("file", "").strip()
		sha = data.get("sha", "").strip()

		if not file_path or not sha:
			return jsonify({"success": False, "error": "file and sha are required"}), 400

		svc = _svc()
		ok = svc.revert_file_to_commit(file_path, sha)
		if ok:
			log.info(
				"Versioning revert: %s → %s by %s",
				file_path, sha,
				getattr(current_user, "username", "unknown"),
			)
			return jsonify({"success": True, "message": f"Reverted {file_path} to {sha[:8]}"})

		return jsonify(
			{"success": False, "error": f"Revert failed for {file_path}@{sha[:8]}"}
		), 500


__all__ = ["VersioningDashboardView"]
