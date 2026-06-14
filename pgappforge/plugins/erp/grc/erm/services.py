"""ERM service."""
from __future__ import annotations
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.grc.erm.models import RiskRegister, RiskMitigationAction, KRI


def _uuid() -> str:
	return str(uuid.uuid4())


class ERMService:
	def create_risk(
		self,
		tenant_id: str,
		name: str,
		category: str,
		likelihood: int,
		impact: int,
		treatment: str = "MITIGATE",
		session: Any = None,
	) -> RiskRegister:
		risk = RiskRegister(
			id=_uuid(),
			tenant_id=tenant_id,
			name=name,
			category=category,
			likelihood_score=likelihood,
			impact_score=impact,
			risk_score=likelihood * impact,
			treatment=treatment,
		)
		if session:
			session.add(risk)
		return risk

	def update_risk_scores(
		self,
		risk_id: str,
		likelihood: int,
		impact: int,
		session: Any,
	) -> None:
		session.execute(
			sa.update(RiskRegister).where(RiskRegister.id == risk_id)
			.values(likelihood_score=likelihood, impact_score=impact, risk_score=likelihood * impact)
		)

	def get_heat_map(self, tenant_id: str, session: Any) -> dict[str, list[str]]:
		risks = session.execute(
			sa.select(RiskRegister).where(
				RiskRegister.tenant_id == tenant_id,
				RiskRegister.status == "OPEN",
			)
		).scalars().all()
		heat_map: dict[str, list[str]] = {}
		for r in risks:
			key = f"L{r.likelihood_score}_I{r.impact_score}"
			heat_map.setdefault(key, []).append(r.id)
		return heat_map

	def add_kri(
		self,
		risk_id: str,
		metric_name: str,
		threshold_value: float,
		session: Any,
	) -> KRI:
		kri = KRI(
			id=_uuid(),
			risk_id=risk_id,
			metric_name=metric_name,
			threshold_value=threshold_value,
		)
		session.add(kri)
		return kri

	def monitor_kris(self, tenant_id: str, session: Any) -> list[KRI]:
		breached = []
		kris = session.execute(
			sa.select(KRI)
			.join(RiskRegister, KRI.risk_id == RiskRegister.id)
			.where(RiskRegister.tenant_id == tenant_id)
		).scalars().all()
		for kri in kris:
			if kri.current_value is not None and kri.current_value > kri.threshold_value:
				if not kri.breach_status:
					session.execute(
						sa.update(KRI).where(KRI.id == kri.id).values(breach_status=True)
					)
					breached.append(kri)
		return breached


__all__ = ["ERMService"]
