"""
pgappforge/plugins/erp/platform/ml_predictions/services.py

ML prediction service — five prediction types:
  1. AP duplicate invoice detection (embedding cosine-similarity)
  2. HR attrition risk (rule-based + LLM explanation)
  3. CRM lead scoring (stage/signal heuristics + LLM action)
  4. GL anomaly detection (z-score)
  5. Sales / inventory demand forecasting (moving average)
"""
from __future__ import annotations

import logging
import math

from pgappforge.plugins.erp.platform.nlp.client import cosine_similarity as _cosine_similarity  # shared utility

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MLPredictionService:
	"""Five ML-powered predictions for AP, HR, CRM, GL, and inventory domains."""

	# ------------------------------------------------------------------
	# 1. AP Duplicate Invoice Detection
	# ------------------------------------------------------------------

	def detect_duplicate_invoice(
		self,
		invoice_id: str,
		tenant_id: str,
		session,
		*,
		similarity_threshold: float = 0.85,
	) -> dict:
		"""Detect if an AP invoice is a duplicate of an existing one.

		Embeds invoice description + amount + vendor using LiteLLM and
		compares cosine similarity against recent invoices from the same vendor.

		Returns:
			{is_duplicate, score, duplicate_of_id, explanation}
		"""
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.erp.finance.ap.models import APInvoice

			invoice = session.execute(
				sa.select(APInvoice).where(
					APInvoice.id == invoice_id,
					APInvoice.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if invoice is None:
				return {
					"is_duplicate": False,
					"score": 0.0,
					"duplicate_of_id": None,
					"explanation": "Invoice not found",
				}

			fingerprint = (
				f"Vendor: {getattr(invoice, 'vendor_id', '')} "
				f"Amount: {getattr(invoice, 'total_amount_cents', 0)} "
				f"Description: {getattr(invoice, 'description', '') or ''} "
				f"Date: {str(getattr(invoice, 'invoice_date', ''))}"
			)

			candidates = session.execute(
				sa.select(APInvoice).where(
					APInvoice.tenant_id == tenant_id,
					APInvoice.id != invoice_id,
					APInvoice.vendor_id == getattr(invoice, "vendor_id", None),
				).limit(50)
			).scalars().all()

			if not candidates:
				return {
					"is_duplicate": False,
					"score": 0.0,
					"duplicate_of_id": None,
					"explanation": "No comparison invoices found",
				}

			from pgappforge.plugins.erp.platform.nlp.client import LLMClient
			client = LLMClient()

			all_texts = [fingerprint] + [
				f"Vendor: {getattr(c, 'vendor_id', '')} "
				f"Amount: {getattr(c, 'total_amount_cents', 0)} "
				f"Description: {getattr(c, 'description', '') or ''} "
				f"Date: {str(getattr(c, 'invoice_date', ''))}"
				for c in candidates
			]
			embeddings = client.embed(all_texts)

			if not embeddings or not embeddings[0]:
				return {
					"is_duplicate": False,
					"score": 0.0,
					"duplicate_of_id": None,
					"explanation": "Embedding unavailable",
				}

			q_vec = embeddings[0]
			best_score = 0.0
			best_candidate_id: str | None = None

			for i, cand in enumerate(candidates):
				if i + 1 >= len(embeddings) or not embeddings[i + 1]:
					continue
				score = _cosine_similarity(q_vec, embeddings[i + 1])
				if score > best_score:
					best_score = score
					best_candidate_id = str(cand.id)

			is_dup = best_score >= similarity_threshold
			result = {
				"is_duplicate": is_dup,
				"score": round(best_score, 4),
				"duplicate_of_id": best_candidate_id if is_dup else None,
				"explanation": (
					f"Similarity {best_score:.1%} "
					f"{'≥' if is_dup else '<'} threshold {similarity_threshold:.0%}"
				),
			}
			self._persist_prediction(
				"AP_DUPLICATE", "APInvoice", invoice_id,
				best_score, "DUPLICATE" if is_dup else "UNIQUE",
				tenant_id, session,
				features={"similarity_score": best_score},
			)
			return result

		except Exception as exc:
			log.debug("detect_duplicate_invoice: %s", exc)
			return {
				"is_duplicate": False,
				"score": 0.0,
				"duplicate_of_id": None,
				"explanation": str(exc),
			}

	# ------------------------------------------------------------------
	# 2. HR Attrition Risk
	# ------------------------------------------------------------------

	def predict_attrition_risk(
		self,
		employee_id: str,
		tenant_id: str,
		session,
	) -> dict:
		"""Score attrition risk for an employee (0 = low, 1 = high).

		Uses rule-based scoring on tenure, recent performance, and other
		signals.  An LLM explanation is generated when available.

		Returns:
			{score, label, risk_factors, explanation}
		"""
		try:
			import sqlalchemy as sa
			from datetime import date
			from pgappforge.plugins.erp.hcm.personnel.models import Employee

			emp = session.execute(
				sa.select(Employee).where(
					Employee.id == employee_id,
					Employee.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if not emp:
				return {"score": 0.0, "label": "UNKNOWN", "risk_factors": [], "explanation": ""}

			score: float = 0.0
			risk_factors: list[str] = []

			# Tenure scoring
			hire_date = getattr(emp, "hire_date", None)
			if hire_date:
				tenure_months = (date.today() - hire_date).days / 30
				if tenure_months < 6:
					score += 0.3
					risk_factors.append("Very short tenure (<6 months)")
				elif tenure_months < 12:
					score += 0.2
					risk_factors.append("Short tenure (<1 year)")
				elif tenure_months > 120:
					score += 0.1
					risk_factors.append("Long tenure (>10 years) — retention risk")

			# Recent performance
			try:
				from pgappforge.plugins.erp.hcm.performance.models import PerformanceReview
				recent = session.execute(
					sa.select(PerformanceReview).where(
						PerformanceReview.employee_id == employee_id,
						PerformanceReview.tenant_id == tenant_id,
					).order_by(PerformanceReview.created_at.desc()).limit(1)
				).scalar_one_or_none()
				if recent and getattr(recent, "overall_rating", None) is not None:
					rating = float(recent.overall_rating)
					if rating <= 2:
						score += 0.25
						risk_factors.append(f"Low performance rating ({rating}/5)")
					elif rating >= 5:
						score -= 0.1  # high performer — less likely to leave
			except Exception:
				pass

			score = max(0.0, min(1.0, score))
			label = "HIGH" if score >= 0.6 else "MEDIUM" if score >= 0.35 else "LOW"

			explanation = ""
			try:
				from pgappforge.plugins.erp.platform.nlp.client import LLMClient
				client = LLMClient()
				prompt = (
					f"An employee has an attrition risk score of {score:.0%} ({label} risk). "
					f"Risk factors identified: {', '.join(risk_factors) or 'none'}. "
					"In 2 sentences, what actions should HR consider?"
				)
				explanation = client.chat([{"role": "user", "content": prompt}], max_tokens=100)
			except Exception:
				pass

			result = {
				"score": round(score, 4),
				"label": label,
				"risk_factors": risk_factors,
				"explanation": explanation,
			}
			self._persist_prediction(
				"HR_ATTRITION", "Employee", employee_id,
				score, label, tenant_id, session,
				features={"risk_factors": risk_factors},
			)
			return result

		except Exception as exc:
			log.debug("predict_attrition_risk: %s", exc)
			return {"score": 0.0, "label": "LOW", "risk_factors": [], "explanation": str(exc)}

	# ------------------------------------------------------------------
	# 3. CRM Lead Scoring
	# ------------------------------------------------------------------

	def score_lead(
		self,
		opportunity_id: str,
		tenant_id: str,
		session,
	) -> dict:
		"""Score a CRM opportunity's probability of closing (0 – 1).

		Uses deal stage, deal size, and staleness signals.  LLM recommends
		the single best next action when available.

		Returns:
			{score, label, key_signals, recommended_action}
		"""
		try:
			import sqlalchemy as sa
			from datetime import date
			from pgappforge.plugins.erp.crm.sales.models import Opportunity

			opp = session.execute(
				sa.select(Opportunity).where(
					Opportunity.id == opportunity_id,
					Opportunity.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if not opp:
				return {"score": 0.0, "label": "UNKNOWN", "key_signals": [], "recommended_action": ""}

			signals: list[str] = []

			# Stage progression baseline
			stage = str(getattr(opp, "stage", "") or "").upper()
			stage_scores: dict[str, float] = {
				"QUALIFICATION":  0.1,
				"NEEDS_ANALYSIS": 0.2,
				"PROPOSAL":       0.35,
				"NEGOTIATION":    0.55,
				"CLOSING":        0.75,
			}
			score: float = stage_scores.get(stage, 0.3)

			# Deal size
			amount = int(getattr(opp, "amount_cents", 0) or 0)
			if amount > 10_000_000_00:  # > 10 M in cents
				score -= 0.1
				signals.append("Large deal (>10M) — extended cycle")
			elif amount < 100_000_00:   # < 1 M in cents
				score += 0.05
				signals.append("Small deal — faster close likely")

			# Days in current stage
			updated_at = getattr(opp, "updated_at", None)
			if updated_at:
				days_stale = (date.today() - updated_at.date()).days
				if days_stale > 30:
					score -= 0.15
					signals.append(f"Stale ({days_stale}d in stage)")

			score = max(0.0, min(1.0, score))
			label = "HOT" if score >= 0.7 else "WARM" if score >= 0.4 else "COLD"

			action = ""
			try:
				from pgappforge.plugins.erp.platform.nlp.client import LLMClient
				client = LLMClient()
				prompt = (
					f"CRM deal at {stage} stage, score {score:.0%} ({label}). "
					f"Signals: {', '.join(signals) or 'none'}. "
					"Recommend the single best next action in 15 words or less."
				)
				action = client.chat([{"role": "user", "content": prompt}], max_tokens=50)
			except Exception:
				pass

			result = {
				"score": round(score, 4),
				"label": label,
				"key_signals": signals,
				"recommended_action": action,
			}
			self._persist_prediction(
				"LEAD_SCORE", "Opportunity", opportunity_id,
				score, label, tenant_id, session,
				features={"stage": stage, "signals": signals},
			)
			return result

		except Exception as exc:
			log.debug("score_lead: %s", exc)
			return {"score": 0.0, "label": "COLD", "key_signals": [], "recommended_action": ""}

	# ------------------------------------------------------------------
	# 4. GL Anomaly Detection
	# ------------------------------------------------------------------

	def detect_gl_anomaly(
		self,
		journal_entry_id: str,
		tenant_id: str,
		session,
		z_score_threshold: float = 2.5,
	) -> dict:
		"""Flag GL journal entries that are statistical outliers.

		Computes z-score of entry amount within the same account's year-to-date
		history.  Requires at least 5 historical rows to produce a result.

		Returns:
			{is_anomaly, z_score, mean_cents, std_cents, explanation}
		"""
		try:
			import sqlalchemy as sa
			from datetime import date
			from pgappforge.plugins.erp.finance.gl.models import JournalEntry

			entry = session.execute(
				sa.select(JournalEntry).where(
					JournalEntry.id == journal_entry_id,
					JournalEntry.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if not entry:
				return {"is_anomaly": False, "z_score": 0.0, "explanation": "Entry not found"}

			account_code = getattr(entry, "account_code", "") or ""
			amount       = int(getattr(entry, "amount_cents", 0) or 0)
			year_start   = date.today().replace(month=1, day=1)

			rows = session.execute(
				sa.select(JournalEntry.amount_cents).where(
					JournalEntry.tenant_id == tenant_id,
					JournalEntry.account_code == account_code,
					JournalEntry.id != journal_entry_id,
					JournalEntry.posting_date >= year_start,
				).limit(200)
			).scalars().all()

			if len(rows) < 5:
				return {
					"is_anomaly": False,
					"z_score": 0.0,
					"explanation": "Insufficient history",
				}

			amounts = [float(r) for r in rows if r is not None]
			mean     = sum(amounts) / len(amounts)
			variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
			std      = math.sqrt(variance) if variance > 0 else 1.0
			z_score  = abs((float(amount) - mean) / std)
			is_anomaly = z_score >= z_score_threshold

			explanation = (
				f"Amount {amount:,} is {z_score:.1f}σ from mean "
				f"{mean:,.0f} (account {account_code})"
			)

			if is_anomaly:
				self._persist_prediction(
					"GL_ANOMALY", "JournalEntry", journal_entry_id,
					min(z_score / 10, 1.0), "ANOMALY", tenant_id, session,
					features={"z_score": z_score, "mean": mean, "std": std},
				)

			return {
				"is_anomaly": is_anomaly,
				"z_score": round(z_score, 2),
				"mean_cents": int(mean),
				"std_cents": int(std),
				"explanation": explanation,
			}

		except Exception as exc:
			log.debug("detect_gl_anomaly: %s", exc)
			return {"is_anomaly": False, "z_score": 0.0, "explanation": str(exc)}

	# ------------------------------------------------------------------
	# 5. Demand Forecasting
	# ------------------------------------------------------------------

	def forecast_demand(
		self,
		product_id: str,
		tenant_id: str,
		session,
		periods_ahead: int = 3,
	) -> dict:
		"""Simple moving-average demand forecast for inventory planning.

		Aggregates outbound transactions by month over the past 12 months,
		computes a 3-month moving average, and projects forward.

		Returns:
			{product_id, forecast: [{period, predicted_qty}], trend, confidence, ma_qty}
		"""
		try:
			import sqlalchemy as sa
			from datetime import date
			from collections import defaultdict
			from pgappforge.plugins.erp.operations.inventory.models import InventoryTransaction

			cutoff = date.today().replace(month=max(1, date.today().month - 12), day=1)
			rows = session.execute(
				sa.select(InventoryTransaction).where(
					InventoryTransaction.tenant_id == tenant_id,
					InventoryTransaction.product_id == product_id,
					InventoryTransaction.transaction_type.in_(["ISSUE", "SALE", "TRANSFER_OUT"]),
					InventoryTransaction.transaction_date >= cutoff,
				)
			).scalars().all()

			monthly: dict[str, int] = defaultdict(int)
			for r in rows:
				key = r.transaction_date.strftime("%Y-%m")
				monthly[key] += int(getattr(r, "quantity", 0) or 0)

			if len(monthly) < 3:
				return {
					"product_id": product_id,
					"forecast": [],
					"trend": "INSUFFICIENT_DATA",
					"confidence": 0.0,
					"ma_qty": 0.0,
				}

			values = [monthly[k] for k in sorted(monthly.keys())]
			window  = min(3, len(values))
			ma      = sum(values[-window:]) / window

			# Trend: first half vs second half
			mid              = len(values) // 2
			first_half_avg   = sum(values[:mid]) / mid if mid > 0 else 0.0
			second_half_avg  = sum(values[mid:]) / (len(values) - mid) if len(values) > mid else 0.0
			trend_pct        = (
				(second_half_avg - first_half_avg) / first_half_avg
				if first_half_avg > 0
				else 0.0
			)
			trend = (
				"INCREASING" if trend_pct > 0.05
				else "DECREASING" if trend_pct < -0.05
				else "STABLE"
			)

			today    = date.today()
			forecast = []
			for i in range(1, periods_ahead + 1):
				month = (today.month + i - 1) % 12 + 1
				year  = today.year + (today.month + i - 1) // 12
				predicted = max(0, int(ma * (1 + trend_pct * i / 3)))
				forecast.append({"period": f"{year}-{month:02d}", "predicted_qty": predicted})

			confidence = min(0.9, 0.5 + 0.1 * len(values))
			return {
				"product_id": product_id,
				"forecast": forecast,
				"trend": trend,
				"confidence": round(confidence, 2),
				"ma_qty": round(ma, 1),
			}

		except Exception as exc:
			log.debug("forecast_demand: %s", exc)
			return {
				"product_id": product_id,
				"forecast": [],
				"trend": "ERROR",
				"confidence": 0.0,
				"ma_qty": 0.0,
			}

	# ------------------------------------------------------------------
	# Internal helper
	# ------------------------------------------------------------------

	def _persist_prediction(
		self,
		prediction_type: str,
		ref_type: str,
		ref_id: str,
		score: float,
		label: str,
		tenant_id: str,
		session,
		*,
		features: dict | None = None,
	) -> None:
		"""Persist a prediction row.  Silently swallowed on any error."""
		try:
			from pgappforge.plugins.erp.platform.ml_predictions.models import MLPrediction
			import uuid as _uuid
			session.add(MLPrediction(
				id=str(_uuid.uuid4()),
				tenant_id=tenant_id,
				prediction_type=prediction_type,
				reference_type=ref_type,
				reference_id=str(ref_id),
				score=score,
				label=label,
				features_used=features or {},
			))
			session.flush()
		except Exception as exc:
			log.debug("_persist_prediction: %s", exc)


__all__ = ["MLPredictionService"]
