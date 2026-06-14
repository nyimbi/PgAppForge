"""Ethics hotline service — anonymous reporting."""
from __future__ import annotations
import hashlib
import secrets
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase


def _uuid() -> str:
	return str(uuid.uuid4())


def _hash_token(raw_token: str) -> str:
	return hashlib.sha256(raw_token.encode()).hexdigest()


class EthicsHotlineService:
	def submit_report(
		self,
		tenant_id: str,
		description: str,
		category: str,
		severity: str = "MEDIUM",
		session: Any = None,
	) -> tuple[str, EthicsReport]:
		raw_token = secrets.token_urlsafe(32)
		report = EthicsReport(
			id=_uuid(),
			tenant_id=tenant_id,
			anonymous_token_hash=_hash_token(raw_token),
			category=category,
			description=description,
			severity=severity,
		)
		if session:
			session.add(report)
		return raw_token, report

	def get_status(self, raw_token: str, tenant_id: str, session: Any) -> str | None:
		token_hash = _hash_token(raw_token)
		report = session.execute(
			sa.select(EthicsReport).where(
				EthicsReport.anonymous_token_hash == token_hash,
				EthicsReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		return report.status if report else None

	def open_case(self, report_id: str, assigned_to: str, session: Any) -> EthicsCase:
		case = EthicsCase(
			id=_uuid(),
			report_id=report_id,
			assigned_to=assigned_to,
			timeline=[{"action": "CASE_OPENED", "actor": assigned_to}],
		)
		session.add(case)
		session.execute(
			sa.update(EthicsReport).where(EthicsReport.id == report_id)
			.values(status="UNDER_INVESTIGATION")
		)
		return case

	def resolve_case(self, case_id: str, resolution: str, session: Any) -> None:
		case = session.get(EthicsCase, case_id)
		session.execute(
			sa.update(EthicsCase).where(EthicsCase.id == case_id)
			.values(resolution=resolution, status="RESOLVED")
		)
		session.execute(
			sa.update(EthicsReport).where(EthicsReport.id == case.report_id)
			.values(status="RESOLVED")
		)


__all__ = ["EthicsHotlineService"]
