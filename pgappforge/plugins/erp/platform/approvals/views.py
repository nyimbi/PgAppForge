"""
pgappforge/plugins/erp/platform/approvals/views.py

AppBuilder views and endpoint helpers for ERP approvals.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

import sqlalchemy as sa
from flask import abort, jsonify, make_response, render_template_string, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.platform.approvals.models import ApprovalRequest
from pgappforge.plugins.erp.platform.approvals.services import ApprovalService, ApprovalServiceError
from pgappforge.security.decorators import has_access


def get_request_data() -> dict[str, Any]:
	if request.is_json:
		return request.get_json(silent=True) or {}
	return dict(request.form.items())


def current_user_id(default: str = "") -> str:
	try:
		from flask_login import current_user
		if current_user and getattr(current_user, "is_authenticated", False):
			for attr in ("id", "username", "email"):
				value = getattr(current_user, attr, None)
				if value:
					return str(value)
	except Exception:
		pass
	return default


def object_amount_cents(obj: Any, *fields: str) -> int:
	for field in fields:
		if hasattr(obj, field):
			value = getattr(obj, field)
			if value is not None:
				return int(value)
	return 0


def submit_document_approval(
	document_type: str,
	document_id: str,
	document_model: type,
	session: Any,
	amount_getter: Callable[[Any], int],
	requester_getter: Callable[[Any], str],
) -> Any:
	data = get_request_data()
	doc = session.execute(
		sa.select(document_model).where(document_model.id == document_id)
	).scalar_one_or_none()
	if doc is None:
		abort(404)
	tenant_id = str(data.get("tenant_id") or getattr(doc, "tenant_id", ""))
	requester_id = str(data.get("requester_id") or requester_getter(doc) or current_user_id())
	amount_cents = int(data.get("amount_cents") or amount_getter(doc) or 0)
	if not tenant_id or not requester_id:
		return jsonify({"ok": False, "error": "tenant_id and requester_id are required"}), 400
	try:
		approval = ApprovalService().submit_for_approval(
			document_type=document_type,
			document_id=document_id,
			requester_id=requester_id,
			amount_cents=amount_cents,
			tenant_id=tenant_id,
			session=session,
		)
		session.commit()
		return jsonify({
			"ok": True,
			"approval_request_id": approval.id,
			"status": approval.status,
			"current_step": approval.current_step,
			"total_steps": approval.total_steps,
		}), 201
	except ApprovalServiceError as exc:
		session.rollback()
		return jsonify({"ok": False, "error": str(exc)}), 400


def approve_document_approval(approval_request_id: str, session: Any) -> Any:
	data = get_request_data()
	approver_id = str(data.get("approver_id") or current_user_id())
	if not approver_id:
		return jsonify({"ok": False, "error": "approver_id is required"}), 400
	try:
		approval = ApprovalService().approve(
			approval_request_id,
			approver_id,
			data.get("comments"),
			session,
		)
		session.commit()
		return jsonify({
			"ok": True,
			"approval_request_id": approval.id,
			"status": approval.status,
			"current_step": approval.current_step,
		})
	except ApprovalServiceError as exc:
		session.rollback()
		return jsonify({"ok": False, "error": str(exc)}), 400


def reject_document_approval(approval_request_id: str, session: Any) -> Any:
	data = get_request_data()
	approver_id = str(data.get("approver_id") or current_user_id())
	reason = str(data.get("reason") or data.get("comments") or "")
	if not approver_id:
		return jsonify({"ok": False, "error": "approver_id is required"}), 400
	try:
		approval = ApprovalService().reject(approval_request_id, approver_id, reason, session)
		session.commit()
		return jsonify({
			"ok": True,
			"approval_request_id": approval.id,
			"status": approval.status,
		})
	except ApprovalServiceError as exc:
		session.rollback()
		return jsonify({"ok": False, "error": str(exc)}), 400


def _html_escape(value: object) -> str:
	return (
		str(value)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


class PendingApprovalsView(BaseERPView):
	"""Inbox for approvals assigned to the current user's roles."""

	route_base = "/erp/approvals"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		approver_id = request.args.get("approver_id") or current_user_id()
		tenant_id = request.args.get("tenant_id") or self._tenant_id()
		if not approver_id or not tenant_id:
			return jsonify({"ok": False, "error": "approver_id and tenant_id are required"}), 400
		pending = ApprovalService().get_pending_approvals(approver_id, tenant_id, session)
		grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
		for row in pending:
			grouped[row["document_type"]].append(row)

		if request.args.get("format") == "json":
			return jsonify({"ok": True, "approvals": dict(grouped)})

		sections = []
		for document_type, rows in sorted(grouped.items()):
			body_rows = "".join(
				"<tr>"
				f"<td>{_html_escape(row['document_id'])}</td>"
				f"<td>{row['amount_cents'] / 100:,.2f}</td>"
				f"<td>{_html_escape(row['requester_id'])}</td>"
				f"<td>{_html_escape(row['current_step'])}/{_html_escape(row['total_steps'])}</td>"
				f"<td>{_html_escape(row['created_at'] or '')}</td>"
				"</tr>"
				for row in rows
			)
			sections.append(
				f"<h4>{_html_escape(document_type.replace('_', ' ').title())}</h4>"
				'<table class="table table-bordered table-condensed">'
				"<thead><tr><th>Document</th><th>Amount</th><th>Requester</th><th>Step</th><th>Submitted</th></tr></thead>"
				f"<tbody>{body_rows}</tbody></table>"
			)

		html = render_template_string(
			"""
			<h3>Pending Approvals</h3>
			{% if sections %}
				{{ sections|safe }}
			{% else %}
				<p>No pending approvals.</p>
			{% endif %}
			""",
			sections="".join(sections),
			appbuilder=self.appbuilder,
		)
		return make_response(html, 200)

	@expose("/submit/<string:document_type>/<string:document_id>", methods=["POST"])
	@has_access
	def submit(self, document_type: str, document_id: str):
		data = get_request_data()
		session = self._session()
		try:
			approval = ApprovalService().submit_for_approval(
				document_type=document_type,
				document_id=document_id,
				requester_id=str(data.get("requester_id") or current_user_id()),
				amount_cents=int(data.get("amount_cents", 0) or 0),
				tenant_id=str(data.get("tenant_id") or self._tenant_id()),
				session=session,
			)
			session.commit()
			return jsonify({"ok": True, "approval_request_id": approval.id, "status": approval.status}), 201
		except ApprovalServiceError as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/approve/<string:request_id>", methods=["POST"])
	@has_access
	def approve(self, request_id: str):
		return approve_document_approval(request_id, self._session())

	@expose("/reject/<string:request_id>", methods=["POST"])
	@has_access
	def reject(self, request_id: str):
		return reject_document_approval(request_id, self._session())


__all__ = [
	"ApprovalRequest",
	"PendingApprovalsView",
	"approve_document_approval",
	"current_user_id",
	"get_request_data",
	"object_amount_cents",
	"reject_document_approval",
	"submit_document_approval",
]
