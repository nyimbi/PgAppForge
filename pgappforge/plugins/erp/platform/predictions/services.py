"""
pgappforge/plugins/erp/platform/predictions/services.py

PredictionService — ML-powered predictions displayed inline in ERP list views.

Predictions appear as computed colour-coded badge columns — no separate analytics
page required.

Implemented prediction types
-----------------------------
credit_score         — SACCO loan application credit score
duplicate_invoice    — AP invoice duplicate risk
(delegated to MLPredictionService for actual scoring; wraps result for display)

Bulk API
--------
get_bulk_predictions() pre-loads predictions for all visible rows in a list view
with a single call, using the plat_ml_prediction cache table (last 24h) to avoid
redundant computation.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class PredictionService:
	"""ML-powered predictions formatted for inline ERP list-view display.

	Every method returns a display-ready dict::

		{
			"score_pct":        int,      # 0-100 percentage
			"label":            str,      # e.g. "HIGH", "DUPLICATE", "N/A"
			"color":            str,      # CSS hex colour
			"tooltip":          str,      # human-readable explanation
			"last_computed_at": str|None, # ISO timestamp or "now"
			"from_cache":       bool,
		}
	"""

	# ── Display colour map ──────────────────────────────────────────────
	_RISK_COLORS: dict[str, str] = {
		"HIGH":      "#e02424",
		"MEDIUM":    "#ff5a1f",
		"LOW":       "#0e9f6e",
		"DUPLICATE": "#e02424",
		"UNIQUE":    "#0e9f6e",
		"HOT":       "#0e9f6e",
		"WARM":      "#ff5a1f",
		"COLD":      "#6b7280",
		"ANOMALY":   "#e02424",
		"UNKNOWN":   "#6b7280",
		"N/A":       "#6b7280",
		"ERROR":     "#6b7280",
	}

	# ------------------------------------------------------------------
	# 1. SACCO loan credit score
	# ------------------------------------------------------------------

	def predict_loan_credit_score(
		self,
		application_id: str,
		tenant_id: str,
		session,
	) -> dict[str, Any]:
		"""Predict credit score for a SACCO loan application.

		Delegates to MLPredictionService.predict_attrition_risk (reusing the
		rule-based scoring + LLM explanation infrastructure) and maps the
		attrition risk signal onto a credit-friendy display.

		Returns::

			{score_pct, label, color, tooltip, last_computed_at, from_cache}
		"""
		try:
			from pgappforge.plugins.erp.platform.ml_predictions.services import MLPredictionService
			result = MLPredictionService().predict_attrition_risk(
				application_id, tenant_id, session
			)
			score = float(result.get("score", 0))
			label = str(result.get("label", "UNKNOWN"))
			factors = result.get("risk_factors") or []
			explanation = result.get("explanation") or ""

			tooltip = "; ".join(factors) if factors else explanation if explanation else label

			return {
				"score_pct":        int(score * 100),
				"label":            label,
				"color":            self._RISK_COLORS.get(label, "#6b7280"),
				"tooltip":          tooltip,
				"last_computed_at": "now",
				"from_cache":       False,
			}
		except Exception as exc:
			log.debug("predict_loan_credit_score(%r): %s", application_id, exc)
			return self._unavailable()

	# ------------------------------------------------------------------
	# 2. AP invoice duplicate risk
	# ------------------------------------------------------------------

	def predict_invoice_duplicate_risk(
		self,
		invoice_id: str,
		tenant_id: str,
		session,
	) -> dict[str, Any]:
		"""Check if an AP invoice might be a duplicate.

		Returns::

			{score_pct, label, color, tooltip, duplicate_of_id, last_computed_at, from_cache}
		"""
		try:
			from pgappforge.plugins.erp.platform.ml_predictions.services import MLPredictionService
			result = MLPredictionService().detect_duplicate_invoice(
				invoice_id, tenant_id, session
			)
			score  = float(result.get("score", 0))
			is_dup = bool(result.get("is_duplicate", False))
			label  = "DUPLICATE" if is_dup else "UNIQUE"

			return {
				"score_pct":        int(score * 100),
				"label":            label,
				"color":            self._RISK_COLORS[label],
				"tooltip":          result.get("explanation") or label,
				"duplicate_of_id":  result.get("duplicate_of_id"),
				"last_computed_at": "now",
				"from_cache":       False,
			}
		except Exception as exc:
			log.debug("predict_invoice_duplicate_risk(%r): %s", invoice_id, exc)
			return self._unavailable()

	# ------------------------------------------------------------------
	# 3. CRM lead score (convenience wrapper)
	# ------------------------------------------------------------------

	def predict_lead_score(
		self,
		opportunity_id: str,
		tenant_id: str,
		session,
	) -> dict[str, Any]:
		"""Score a CRM opportunity's close probability for inline display."""
		try:
			from pgappforge.plugins.erp.platform.ml_predictions.services import MLPredictionService
			result = MLPredictionService().score_lead(opportunity_id, tenant_id, session)
			score  = float(result.get("score", 0))
			label  = str(result.get("label", "UNKNOWN"))
			return {
				"score_pct":        int(score * 100),
				"label":            label,
				"color":            self._RISK_COLORS.get(label, "#6b7280"),
				"tooltip":          result.get("recommended_action") or label,
				"last_computed_at": "now",
				"from_cache":       False,
			}
		except Exception as exc:
			log.debug("predict_lead_score(%r): %s", opportunity_id, exc)
			return self._unavailable()

	# ------------------------------------------------------------------
	# Bulk pre-load (for list views)
	# ------------------------------------------------------------------

	def get_bulk_predictions(
		self,
		prediction_type: str,
		record_ids: list[str],
		tenant_id: str,
		session,
	) -> dict[str, dict[str, Any]]:
		"""Pre-load predictions for a page of list-view records.

		Args:
			prediction_type: One of ``"credit_score"`` | ``"duplicate_invoice"``
			                 | ``"lead_score"``.
			record_ids:      List of record primary-key strings (e.g. from the current
			                 page of a ModelView list).
			tenant_id:       Tenant identifier.
			session:         SQLAlchemy session.

		Returns:
			Mapping of ``{record_id: display_dict}``.  Records not found in cache or
			computation cap are returned as unavailable stubs.

		Implementation
		--------------
		1. Hit ``plat_ml_prediction`` cache for any rows computed within the last 24h.
		2. Compute fresh predictions for up to 20 remaining IDs (to bound latency).
		3. Return all results in a single dict.
		"""
		_TYPE_MAP: dict[str, str] = {
			"credit_score":       "HR_ATTRITION",   # reused scoring infra
			"duplicate_invoice":  "AP_DUPLICATE",
			"lead_score":         "LEAD_SCORE",
		}
		db_type = _TYPE_MAP.get(prediction_type, prediction_type.upper())

		results: dict[str, dict[str, Any]] = {}

		# ── 1. Cache hit ──────────────────────────────────────────────
		try:
			import sqlalchemy as sa
			rows = session.execute(sa.text("""
				SELECT reference_id, score, label, features_used, created_at
				FROM plat_ml_prediction
				WHERE prediction_type = :ptype
				  AND reference_id    = ANY(:ids)
				  AND tenant_id       = :tid
				  AND created_at      > NOW() - INTERVAL '24 hours'
				ORDER BY created_at DESC
			"""), {
				"ptype": db_type,
				"ids":   record_ids,
				"tid":   tenant_id,
			}).fetchall()

			seen: set[str] = set()
			for row in rows:
				rid = str(row[0])
				if rid in seen:
					continue
				seen.add(rid)
				score_raw = float(row[1]) if row[1] is not None else 0.0
				label     = str(row[2]) if row[2] else "UNKNOWN"
				results[rid] = {
					"score_pct":        int(score_raw * 100),
					"label":            label,
					"color":            self._RISK_COLORS.get(label, "#6b7280"),
					"tooltip":          label,
					"last_computed_at": str(row[4]) if row[4] else None,
					"from_cache":       True,
				}
		except Exception as exc:
			log.debug("get_bulk_predictions cache query failed: %s", exc)

		# ── 2. Fresh computation for cache misses (capped at 20) ───────
		missing = [rid for rid in record_ids if rid not in results]
		for record_id in missing[:20]:
			try:
				if prediction_type == "credit_score":
					results[record_id] = self.predict_loan_credit_score(
						record_id, tenant_id, session
					)
				elif prediction_type == "duplicate_invoice":
					results[record_id] = self.predict_invoice_duplicate_risk(
						record_id, tenant_id, session
					)
				elif prediction_type == "lead_score":
					results[record_id] = self.predict_lead_score(
						record_id, tenant_id, session
					)
				else:
					results[record_id] = self._unavailable()
			except Exception:
				results[record_id] = self._unavailable()

		# ── 3. Fill remaining with unavailable stub ────────────────────
		for rid in record_ids:
			if rid not in results:
				results[rid] = self._unavailable()

		return results

	# ------------------------------------------------------------------
	# Internal
	# ------------------------------------------------------------------

	@staticmethod
	def _unavailable() -> dict[str, Any]:
		return {
			"score_pct":        0,
			"label":            "N/A",
			"color":            "#6b7280",
			"tooltip":          "Prediction unavailable",
			"last_computed_at": None,
			"from_cache":       False,
		}


__all__ = ["PredictionService"]
