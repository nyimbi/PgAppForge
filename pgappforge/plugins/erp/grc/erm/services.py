"""
pgappforge/plugins/erp/grc/erm/services.py

ErmService — Enterprise Risk Management operations.

Key operations:
  create_risk         — register a new risk with computed score + level
  update_risk_scores  — recompute score/level and emit update event
  get_heat_map        — 5×5 likelihood/impact matrix with risk counts
  add_mitigation      — attach an action item to a risk
  add_kri             — attach a KRI threshold monitor to a risk
  update_kri_value    — record a KRI reading; emit breach event if crossed
  monitor_kris        — refresh all KRIs for a tenant
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("ErmService: emit suppressed: %s", exc)


def _compute_risk_level(score: int) -> str:
	if score >= 20:
		return "CRITICAL"
	if score >= 10:
		return "HIGH"
	if score >= 5:
		return "MEDIUM"
	return "LOW"


# ---------------------------------------------------------------------------
# ErmService
# ---------------------------------------------------------------------------

class ErmService:
	"""Stateless Enterprise Risk Management service."""

	# ------------------------------------------------------------------
	# create_risk
	# ------------------------------------------------------------------

	def create_risk(
		self,
		name: str,
		category: str,
		likelihood_score: int,
		impact_score: int,
		tenant_id: str,
		session: Any,
		*,
		description: str | None = None,
		treatment: str = "ACCEPT",
		owner_id: str | None = None,
		entity_id: str | None = None,
		status: str = "ACTIVE",
	) -> Any:
		"""Create a RiskRegister entry with computed risk_score and risk_level."""
		from pgappforge.plugins.erp.grc.erm.models import RiskRegister
		from pgappforge.plugins.erp.grc.erm.events import RiskCreatedEvent

		risk_score = likelihood_score * impact_score
		risk_level = _compute_risk_level(risk_score)

		risk = RiskRegister(
			tenant_id=tenant_id,
			name=name,
			description=description,
			category=category,
			likelihood_score=likelihood_score,
			impact_score=impact_score,
			risk_score=risk_score,
			risk_level=risk_level,
			treatment=treatment,
			owner_id=owner_id,
			entity_id=entity_id,
			status=status,
		)
		session.add(risk)
		session.flush()

		_emit(
			RiskCreatedEvent(
				aggregate_id=risk.id,
				aggregate_type="RiskRegister",
				tenant_id=tenant_id,
				risk_id=risk.id,
				name=name,
				risk_score=risk_score,
			),
			session,
		)
		return risk

	# ------------------------------------------------------------------
	# update_risk_scores
	# ------------------------------------------------------------------

	def update_risk_scores(
		self,
		risk_id: str,
		likelihood_score: int,
		impact_score: int,
		session: Any,
	) -> Any:
		"""Recompute risk_score/risk_level and emit RiskScoreUpdatedEvent."""
		from pgappforge.plugins.erp.grc.erm.models import RiskRegister
		from pgappforge.plugins.erp.grc.erm.events import RiskScoreUpdatedEvent

		risk = session.execute(
			select(RiskRegister).where(RiskRegister.id == risk_id)
		).scalar_one_or_none()
		if risk is None:
			raise ValueError(f"RiskRegister {risk_id!r} not found")

		old_score = risk.risk_score
		new_score = likelihood_score * impact_score
		risk.likelihood_score = likelihood_score
		risk.impact_score = impact_score
		risk.risk_score = new_score
		risk.risk_level = _compute_risk_level(new_score)
		session.flush()

		_emit(
			RiskScoreUpdatedEvent(
				aggregate_id=risk.id,
				aggregate_type="RiskRegister",
				tenant_id=risk.tenant_id,
				risk_id=risk.id,
				old_score=old_score,
				new_score=new_score,
			),
			session,
		)
		return risk

	# ------------------------------------------------------------------
	# get_heat_map
	# ------------------------------------------------------------------

	def get_heat_map(self, tenant_id: str, session: Any) -> dict:
		"""Return a 5×5 risk heat map.

		Result structure:
		  {
		    "matrix": {(likelihood, impact): [risk_ids]},
		    "counts": {"CRITICAL": n, "HIGH": n, "MEDIUM": n, "LOW": n},
		    "total": n,
		  }
		"""
		from pgappforge.plugins.erp.grc.erm.models import RiskRegister

		risks = session.execute(
			select(RiskRegister).where(
				RiskRegister.tenant_id == tenant_id,
				RiskRegister.status != "CLOSED",
			)
		).scalars().all()

		matrix: dict[tuple[int, int], list[str]] = {}
		counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

		for risk in risks:
			key = (risk.likelihood_score, risk.impact_score)
			matrix.setdefault(key, []).append(risk.id)
			counts[risk.risk_level] = counts.get(risk.risk_level, 0) + 1

		return {
			"matrix": {f"{k[0]}x{k[1]}": v for k, v in matrix.items()},
			"counts": counts,
			"total": len(risks),
		}

	# ------------------------------------------------------------------
	# add_mitigation
	# ------------------------------------------------------------------

	def add_mitigation(
		self,
		risk_id: str,
		action: str,
		owner_id: str,
		due_date: date,
		session: Any,
	) -> Any:
		"""Attach a mitigation action to a risk."""
		from pgappforge.plugins.erp.grc.erm.models import RiskMitigationAction, RiskRegister

		risk = session.execute(
			select(RiskRegister).where(RiskRegister.id == risk_id)
		).scalar_one_or_none()
		if risk is None:
			raise ValueError(f"RiskRegister {risk_id!r} not found")

		m = RiskMitigationAction(
			tenant_id=risk.tenant_id,
			risk_id=risk_id,
			action_description=action,
			owner_id=owner_id,
			due_date=due_date,
			status="PLANNED",
		)
		session.add(m)
		session.flush()
		return m

	# ------------------------------------------------------------------
	# add_kri
	# ------------------------------------------------------------------

	def add_kri(
		self,
		risk_id: str,
		metric_name: str,
		threshold_value: Decimal,
		session: Any,
		*,
		breach_direction: str = "ABOVE",
		description: str | None = None,
	) -> Any:
		"""Attach a Key Risk Indicator to a risk."""
		from pgappforge.plugins.erp.grc.erm.models import KeyRiskIndicator, RiskRegister

		risk = session.execute(
			select(RiskRegister).where(RiskRegister.id == risk_id)
		).scalar_one_or_none()
		if risk is None:
			raise ValueError(f"RiskRegister {risk_id!r} not found")

		kri = KeyRiskIndicator(
			tenant_id=risk.tenant_id,
			risk_id=risk_id,
			metric_name=metric_name,
			description=description,
			threshold_value=threshold_value,
			breach_direction=breach_direction,
			breach_status="OK",
		)
		session.add(kri)
		session.flush()
		return kri

	# ------------------------------------------------------------------
	# update_kri_value
	# ------------------------------------------------------------------

	def update_kri_value(
		self,
		kri_id: str,
		current_value: Decimal,
		session: Any,
	) -> Any:
		"""Record a new KRI value; emit KriBreachEvent if threshold crossed."""
		from pgappforge.plugins.erp.grc.erm.models import KeyRiskIndicator
		from pgappforge.plugins.erp.grc.erm.events import KriBreachEvent

		kri = session.execute(
			select(KeyRiskIndicator).where(KeyRiskIndicator.id == kri_id)
		).scalar_one_or_none()
		if kri is None:
			raise ValueError(f"KeyRiskIndicator {kri_id!r} not found")

		kri.current_value = current_value
		kri.last_updated = datetime.now(timezone.utc)

		threshold = Decimal(str(kri.threshold_value)).quantize(
			Decimal("0.0001"), rounding=ROUND_HALF_UP
		)
		cv = current_value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		if kri.breach_direction == "ABOVE":
			breached = cv > threshold
		else:
			breached = cv < threshold

		kri.breach_status = "BREACH" if breached else "OK"
		session.flush()

		if breached:
			_emit(
				KriBreachEvent(
					aggregate_id=kri.id,
					aggregate_type="KeyRiskIndicator",
					tenant_id=kri.tenant_id,
					kri_id=kri.id,
					risk_id=kri.risk_id,
					metric_name=kri.metric_name,
					threshold=str(threshold),
					current_value=str(cv),
				),
				session,
			)
		return kri

	# ------------------------------------------------------------------
	# monitor_kris
	# ------------------------------------------------------------------

	def monitor_kris(self, tenant_id: str, session: Any) -> dict:
		"""Re-evaluate all KRIs for *tenant_id* and return breach summary.

		Current values are assumed to be already populated (external ingestion).
		This method re-checks breach conditions and emits events as needed.

		Returns: {breaches: list[{kri_id, metric_name, risk_id, status}]}
		"""
		from pgappforge.plugins.erp.grc.erm.models import KeyRiskIndicator

		kris = session.execute(
			select(KeyRiskIndicator).where(KeyRiskIndicator.tenant_id == tenant_id)
		).scalars().all()

		breaches: list[dict] = []
		for kri in kris:
			if kri.current_value is None:
				continue
			try:
				updated = self.update_kri_value(kri.id, Decimal(str(kri.current_value)), session)
				if updated.breach_status == "BREACH":
					breaches.append({
						"kri_id": kri.id,
						"metric_name": kri.metric_name,
						"risk_id": kri.risk_id,
						"status": "BREACH",
					})
			except Exception as exc:
				log.warning("monitor_kris: kri %s failed: %s", kri.id, exc)

		return {"breaches": breaches}


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"grc.erm.update_kri",
	"Update Key Risk Indicator value",
)
def _bpm_erm_update_kri(
	record_ctx: dict,
	session: Any,
	kri_id: str = "",
	current_value: str = "0",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.grc.erm.services import ErmService
	except ImportError:
		return {"status": "error", "message": "grc.erm plugin not installed"}
	try:
		kri = ErmService().update_kri_value(
			kri_id=kri_id,
			current_value=Decimal(current_value),
			session=session,
		)
		return {"status": "ok", "kri_id": kri.id, "breach_status": kri.breach_status}
	except Exception as exc:
		log.warning("bpm erm.update_kri failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"grc.erm.monitor_kris",
	"Monitor all KRIs for threshold breaches",
)
def _bpm_erm_monitor_kris(
	record_ctx: dict,
	session: Any,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.grc.erm.services import ErmService
	except ImportError:
		return {"status": "error", "message": "grc.erm plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		result = ErmService().monitor_kris(tenant_id=tenant_id, session=session)
		return {"status": "ok", **result}
	except Exception as exc:
		log.warning("bpm erm.monitor_kris failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["ErmService"]
