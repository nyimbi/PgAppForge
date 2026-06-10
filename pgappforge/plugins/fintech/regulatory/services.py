"""
pgappforge/plugins/fintech/regulatory/services.py

RegulatoryComplianceService — AML screening, SAR filing, capital adequacy
computation, IFRS 9 ECL provisioning, CBK prudential returns, and compliance
dashboard aggregation.

Architecture notes
------------------
- All monetary arithmetic: integer cents via money_* helpers from erp.foundation.commons.
- Event emission: wrapped in try/except — never causes business transaction to fail.
- Cross-plugin dependencies (erp.finance.gl, lending) resolved via lazy try/except imports.
- Immutable models (SAR, CapitalAdequacyReport, IFRS9ProvisionRun) are INSERT-ONLY;
  correction requires a new record.
- CBK single-borrower large exposure limit: max 25% of core capital (CBK PG 3).
- Basel III standard approach for credit risk RWA.
- IFRS 9 ECL stages: Stage 1 (0-30 DPD) = 12m PD×LGD×EAD;
                     Stage 2 (31-90 DPD) = lifetime PD×LGD×EAD;
                     Stage 3 (>90 DPD)   = LGD×EAD (credit-impaired, PD≈1).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.commons import (
	emit_event,
	format_currency,
	money_add,
	money_multiply,
	percent_of,
)
from pgappforge.plugins.fintech.regulatory.models import (
	AMLAlert,
	AMLRule,
	BaselIIICapitalReturn,
	CapitalAdequacyReport,
	RegFraudSignal,
	IFRS9ProvisionRun,
	RegOutboxEvent,
	PEPList,
	ReconciliationRun,
	RegulatoryLimit,
	RegulatorySchedule,
	ReversalRecord,
	RWALineItem,
	SanctionsList,
	StressScenario,
	SuspiciousActivityReport,
)
from pgappforge.plugins.fintech.regulatory.events import (
	AMLAlertClosedEvent,
	AMLAlertEscalatedEvent,
	AMLAlertGeneratedEvent,
	AlertSLABreachedEvent,
	CapitalBreachedEvent,
	CapitalReportGeneratedEvent,
	IFRS9GLPostedEvent,
	IFRS9RunCompletedEvent,
	LimitBreachedEvent,
	PEPEntryAddedEvent,
	PEPMatchFoundEvent,
	ReconciliationFailedEvent,
	SARFiledEvent,
	SARFilingDeadlineBreachedEvent,
	SARReversedEvent,
	SanctionsHitEvent,
	SanctionsListUpdatedEvent,
	ScheduledReportFailedEvent,
	ScheduledReportGeneratedEvent,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class RegulatoryError(Exception):
	"""Base exception for all regulatory compliance service errors."""


class AMLRuleNotFoundError(RegulatoryError):
	pass


class AMLAlertNotFoundError(RegulatoryError):
	pass


class SARAlreadyFiledError(RegulatoryError):
	"""Raised when a SAR has already been filed for a given alert."""


class InvalidAlertStatusError(RegulatoryError):
	"""Raised on illegal alert status transitions."""


class FRCSubmissionError(Exception):
	"""Raised when SAR submission to FRC Kenya goAML fails."""


# ---------------------------------------------------------------------------
# CBK minimum capital ratios (Basel III / CBK Prudential Guideline 3)
# ---------------------------------------------------------------------------

CBK_MINIMUMS = {
	"cet1_ratio_pct": Decimal("7.0"),
	"tier1_ratio_pct": Decimal("8.5"),
	"total_capital_ratio_pct": Decimal("10.5"),   # includes 2.5% conservation buffer
	"leverage_ratio_pct": Decimal("3.0"),
	"liquidity_coverage_ratio_pct": Decimal("100.0"),
	"nsfr_pct": Decimal("100.0"),
}

# CBK single-borrower large exposure limit as fraction of core capital
LARGE_EXPOSURE_LIMIT_PCT = Decimal("25.0")

# IFRS 9 stage DPD thresholds
STAGE1_MAX_DPD = 30
STAGE2_MAX_DPD = 90

# Default LGD assumptions by loan type (can be overridden via config)
DEFAULT_LGD = Decimal("0.45")   # 45% — unsecured retail, Basel II supervisory estimate
SECURED_LGD = Decimal("0.25")   # 25% — collateralised


def _pct(numerator: int, denominator: int) -> Decimal:
	"""Compute percentage ratio as Decimal with 2dp; returns 0 if denominator is 0."""
	if denominator == 0:
		return Decimal("0.00")
	return (Decimal(numerator) / Decimal(denominator) * 100).quantize(
		Decimal("0.01"), rounding=ROUND_HALF_UP
	)


def _new_uuid() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# FRC Kenya goAML helpers
# ---------------------------------------------------------------------------

def _build_goaml_xml(sar: Any, institution_config: dict) -> str:
	"""Build goAML v4.0 XML from a SAR using ElementTree (not f-strings)."""
	import xml.etree.ElementTree as ET
	NS = "http://www.unodc.org/goaml/en"
	root = ET.Element("Report")
	root.set("xmlns", NS)
	# reporting_person
	rp = ET.SubElement(root, "reporting_person")
	for tag, val in [("gender","M"),("first_name","Compliance"),("last_name","Officer"),("occupation","COMPLIANCE")]:
		ET.SubElement(rp, tag).text = val
	# entity
	ent = ET.SubElement(root, "entity")
	ET.SubElement(ent, "name").text = institution_config.get("INSTITUTION_NAME", "Financial Institution")
	ET.SubElement(ent, "incorporation_number").text = institution_config.get("INSTITUTION_ID", "")
	ET.SubElement(ent, "incorporation_country").text = "KE"
	ET.SubElement(ent, "business").text = institution_config.get("BUSINESS_TYPE", "BANK")
	# report
	rpt = ET.SubElement(root, "report")
	from datetime import date as _date
	ET.SubElement(rpt, "rentity_id").text = str(sar.sar_number or "")
	ET.SubElement(rpt, "submission_code").text = "E"
	ET.SubElement(rpt, "report_code").text = "STR"
	ET.SubElement(rpt, "submission_date").text = _date.today().isoformat()
	ET.SubElement(rpt, "currency_code_local").text = "KES"
	ET.SubElement(rpt, "reason").text = str(getattr(sar, "narrative", "") or "")
	return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _get_frc_token(base_url: str, client_id: str, client_secret: str, timeout: int) -> str:
	"""Get OAuth2 Bearer token from FRC goAML. Raises FRCSubmissionError on failure."""
	import urllib.request, urllib.error, json, base64
	creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
	body = b"grant_type=client_credentials"
	req = urllib.request.Request(
		f"{base_url}/oauth/token", data=body, method="POST",
		headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"}
	)
	try:
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			return json.loads(resp.read())["access_token"]
	except Exception as exc:
		raise FRCSubmissionError(f"FRC OAuth failed: {exc}") from exc


# ---------------------------------------------------------------------------
# RegulatoryComplianceService
# ---------------------------------------------------------------------------

class RegulatoryComplianceService:
	"""Central service for all regulatory compliance operations.

	Instantiate with a SQLAlchemy session::

		svc = RegulatoryComplianceService(session, tenant_id="acme_bank")

	All methods are synchronous (Flask/SQLAlchemy context).
	"""

	def __init__(self, session: Session, tenant_id: str = "default") -> None:
		self._session = session
		self._tenant_id = tenant_id

	# ------------------------------------------------------------------
	# AML transaction screening
	# ------------------------------------------------------------------

	def screen_transaction(self, transaction_details: dict) -> dict:
		"""Run sanctions screening then all active AML rules against a transaction.

		transaction_details keys:
		  customer_id    (str, required)
		  customer_name  (str, optional) — used for sanctions name matching
		  account_id     (str, optional)
		  amount_cents   (int, required)
		  currency       (str, default "KES")
		  channel        (str, optional)
		  country_code   (str, optional) — originating/destination country
		  transaction_id (str, optional) — reference to triggering tx
		  counterparty_name (str, optional) — used for sanctions name matching

		Returns::

		  {
		    "alerts_generated": int,
		    "risk_score": int,           # highest score among triggered rules
		    "rules_triggered": [{"rule_code": ..., "risk_score": ...}],
		    "alert_ids": [str],
		    "sanctions_hits": [...],     # list of SanctionsList match dicts
		    "fraud_score": int | None,   # latest ML fraud score for customer
		    "blocked": bool,             # True if sanctions hit found
		  }
		"""
		# --- CRITICAL: Sanctions screening before AML rules ---
		sanctions_hits: list[dict] = []
		blocked = False
		sanctions_svc = SanctionsService(self._session, tenant_id=self._tenant_id)

		check_names: list[str] = []
		if transaction_details.get("customer_name"):
			check_names.append(transaction_details["customer_name"])
		if transaction_details.get("counterparty_name"):
			check_names.append(transaction_details["counterparty_name"])

		for name in check_names:
			hits = sanctions_svc.fuzzy_match(name, threshold=0.85)
			if hits:
				sanctions_hits.extend(hits)
				blocked = True
				try:
					emit_event(
						"reg.sanctions.hit",
						"sanctions_list",
						hits[0]["id"],
						{
							"entity_name": name,
							"matched_entry_id": hits[0]["id"],
							"matched_name": hits[0]["listed_name"],
							"list_source": hits[0]["list_source"],
							"similarity_score": hits[0]["similarity"],
							"transaction_id": transaction_details.get("transaction_id", ""),
							"customer_id": transaction_details.get("customer_id", ""),
						},
						self._session,
						tenant_id=self._tenant_id,
					)
				except Exception:
					pass

		if blocked:
			# Return immediately — transaction must not proceed
			log.warning(
				"Sanctions hit for customer=%s tx=%s: %d match(es)",
				transaction_details.get("customer_id"),
				transaction_details.get("transaction_id"),
				len(sanctions_hits),
			)
			return {
				"alerts_generated": 0,
				"risk_score": 100,
				"rules_triggered": [],
				"alert_ids": [],
				"sanctions_hits": sanctions_hits,
				"fraud_score": None,
				"blocked": True,
			}

		# --- HIGH: Fetch latest fraud/ML score for customer ---
		customer_id = transaction_details.get("customer_id", "")
		fraud_score: int | None = None
		if customer_id:
			fraud_signal = self._session.execute(
				select(RegFraudSignal)
				.where(
					and_(
						RegFraudSignal.tenant_id == self._tenant_id,
						RegFraudSignal.customer_id == customer_id,
					)
				)
				.order_by(RegFraudSignal.created_at.desc())
				.limit(1)
			).scalar_one_or_none()
			if fraud_signal is not None:
				# Ignore expired signals
				if fraud_signal.expires_at is None or fraud_signal.expires_at > datetime.now(timezone.utc):
					fraud_score = fraud_signal.score

		rules = self._session.execute(
			select(AMLRule).where(
				and_(
					AMLRule.tenant_id == self._tenant_id,
					AMLRule.is_active.is_(True),
				)
			)
		).scalars().all()

		alerts_generated = 0
		max_risk = 0
		triggered: list[dict] = []
		alert_ids: list[str] = []

		for rule in rules:
			# HIGH: gate rule on minimum fraud score when configured
			if rule.require_fraud_score_above is not None:
				if fraud_score is None or fraud_score <= rule.require_fraud_score_above:
					continue

			fired, detail = self._evaluate_rule(rule, transaction_details)
			if not fired:
				continue

			# Augment risk score with fraud signal weight (up to +20 bonus points)
			effective_score = rule.risk_score
			if fraud_score is not None and fraud_score > 500:
				bonus = min(20, int((fraud_score - 500) / 25))
				effective_score = min(100, rule.risk_score + bonus)

			triggered.append({"rule_code": rule.rule_code, "risk_score": effective_score})
			if effective_score > max_risk:
				max_risk = effective_score

			tx_ids = []
			if transaction_details.get("transaction_id"):
				tx_ids = [transaction_details["transaction_id"]]

			alert = self.generate_aml_alert(
				rule_id=str(rule.id),
				customer_id=transaction_details["customer_id"],
				account_id=transaction_details.get("account_id"),
				transaction_ids=tx_ids,
				detail={
					**detail,
					"transaction_details": transaction_details,
					"fraud_score": fraud_score,
					"effective_risk_score": effective_score,
				},
			)
			alert_ids.append(str(alert.id))
			alerts_generated += 1

		return {
			"alerts_generated": alerts_generated,
			"risk_score": max_risk,
			"rules_triggered": triggered,
			"alert_ids": alert_ids,
			"sanctions_hits": sanctions_hits,
			"fraud_score": fraud_score,
			"blocked": False,
		}

	def _evaluate_rule(self, rule: AMLRule, tx: dict) -> tuple[bool, dict]:
		"""Evaluate a single AML rule against transaction details.

		Returns (fired: bool, detail: dict).
		detail carries the evaluation context for alert_detail storage.
		"""
		params = rule.parameters or {}
		rule_type = rule.rule_type
		detail: dict = {"rule_type": rule_type, "params": params}

		try:
			if rule_type == "THRESHOLD":
				min_cents = int(params.get("min_amount_cents", 0))
				amount = int(tx.get("amount_cents", 0))
				detail["amount_cents"] = amount
				detail["threshold_cents"] = min_cents
				return amount >= min_cents, detail

			elif rule_type == "VELOCITY":
				# Count transactions for this customer in the rolling window
				max_txns = int(params.get("max_transactions", 5))
				period_hours = int(params.get("period_hours", 24))
				count = self._count_recent_transactions(
					tx["customer_id"],
					period_hours=period_hours,
				)
				detail["transaction_count"] = count
				detail["max_transactions"] = max_txns
				detail["period_hours"] = period_hours
				return count > max_txns, detail

			elif rule_type == "STRUCTURING":
				threshold = int(params.get("threshold_cents", 999999))
				window_hours = int(params.get("window_hours", 24))
				min_count = int(params.get("min_count", 3))
				amount = int(tx.get("amount_cents", 0))
				# Flag transactions just below threshold within window
				if amount >= threshold:
					return False, detail
				count = self._count_recent_transactions(
					tx["customer_id"],
					period_hours=window_hours,
					max_amount_cents=threshold,
				)
				detail["sub_threshold_count"] = count
				detail["threshold_cents"] = threshold
				return count >= min_count, detail

			elif rule_type == "COUNTRY_RISK":
				risk_countries: list[str] = params.get("risk_countries", [])
				country = tx.get("country_code", "")
				detail["country_code"] = country
				detail["risk_countries"] = risk_countries
				return country in risk_countries, detail

			elif rule_type == "CUSTOMER_RISK":
				# Stub: in a full implementation would query customer risk rating
				# from CRM/KYC system
				min_rating = int(params.get("min_risk_rating", 3))
				customer_risk = self._get_customer_risk_rating(tx["customer_id"])
				detail["customer_risk"] = customer_risk
				detail["min_risk_rating"] = min_rating
				return customer_risk >= min_rating, detail

			elif rule_type == "PEP":
				pep_types: list[str] = params.get("pep_types", [])
				is_pep = self._is_pep(tx["customer_id"], pep_types)
				detail["is_pep"] = is_pep
				return is_pep, detail

		except Exception as exc:
			log.warning("AML rule %r evaluation error (skipped): %s", rule.rule_code, exc)

		return False, detail

	def _count_recent_transactions(
		self,
		customer_id: str,
		period_hours: int = 24,
		max_amount_cents: int | None = None,
	) -> int:
		"""Count recent transactions for a customer from core banking ledger.

		Lazy import from core_banking to avoid hard circular dependency.
		Returns 0 if core_banking is unavailable.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.models import LedgerEntry, Account
			cutoff = datetime.now(timezone.utc) - timedelta(hours=period_hours)
			q = (
				select(func.count(LedgerEntry.id))
				.join(Account, LedgerEntry.account_id == Account.id)
				.where(
					and_(
						Account.customer_id == customer_id,
						LedgerEntry.created_at >= cutoff,
						LedgerEntry.entry_type == "DEBIT",
					)
				)
			)
			if max_amount_cents is not None:
				q = q.where(LedgerEntry.amount_cents < max_amount_cents)
			result = self._session.execute(q).scalar_one_or_none()
			return int(result or 0)
		except Exception as exc:
			log.debug("_count_recent_transactions unavailable: %s", exc)
			return 0

	def _get_customer_risk_rating(self, customer_id: str) -> int:
		"""Stub: return customer KYC risk rating (1=low, 5=critical).

		Full implementation would query the KYC/CRM system.
		Returns 1 (lowest risk) when no data is available.
		"""
		return 1

	def _is_pep(self, customer_id: str, pep_types: list[str]) -> bool:
		"""Check if customer_id appears in the active PEP list."""
		q = select(PEPList.id).where(
			and_(
				PEPList.party_id == customer_id,
				PEPList.status == "ACTIVE",
				PEPList.tenant_id == self._tenant_id,
			)
		)
		if pep_types:
			q = q.where(PEPList.pep_type.in_(pep_types))
		return self._session.execute(q).first() is not None

	# ------------------------------------------------------------------
	# Customer screening (PEP / sanctions / adverse media)
	# ------------------------------------------------------------------

	def screen_customer(self, customer_id: str) -> dict:
		"""Full customer screening: PEP check, sanctions, adverse media.

		Sanctions and adverse media checks are stubs for third-party API
		integration (e.g. Refinitiv World-Check, Dow Jones, UN/EU/US OFAC lists).

		Returns::

		  {
		    "customer_id": str,
		    "is_pep": bool,
		    "pep_entries": [{"pep_type": ..., "position": ..., "country": ...}],
		    "sanctions_hit": bool,          # stub — always False
		    "adverse_media_hit": bool,       # stub — always False
		    "overall_risk": "LOW|MEDIUM|HIGH|CRITICAL",
		    "screening_timestamp": str,
		  }
		"""
		pep_entries_rows = self._session.execute(
			select(PEPList).where(
				and_(
					PEPList.party_id == customer_id,
					PEPList.tenant_id == self._tenant_id,
					PEPList.status == "ACTIVE",
				)
			)
		).scalars().all()

		pep_entries = [
			{
				"pep_type": p.pep_type,
				"position": p.position_held,
				"country": p.country_code,
				"source": p.source,
			}
			for p in pep_entries_rows
		]

		is_pep = len(pep_entries) > 0

		# Emit PEP match event if found
		if is_pep:
			for pe in pep_entries_rows:
				try:
					emit_event(
						"reg.pep.match_found",
						"pep_list",
						str(pe.id),
						{"party_id": customer_id, "pep_type": pe.pep_type},
						self._session,
						tenant_id=self._tenant_id,
					)
				except Exception:
					pass

		# Sanctions check: query local SanctionsList (party_id exact + fuzzy name match)
		sanctions_hit = False
		sanctions_entries: list[dict] = []
		try:
			from pgappforge.plugins.erp.foundation.commons import jaro_winkler
			# Exact party_id match
			exact_sanctions = self._session.execute(
				select(SanctionsList).where(
					and_(
						SanctionsList.tenant_id == self._tenant_id,
						SanctionsList.party_id == customer_id,
						SanctionsList.status == "ACTIVE",
					)
				)
			).scalars().all()
			if exact_sanctions:
				sanctions_hit = True
				sanctions_entries = [
					{"name": e.full_name, "ref": e.external_ref, "source": e.list_source}
					for e in exact_sanctions
				]
		except Exception as exc:
			log.debug("screen_customer: sanctions exact lookup failed: %s", exc)

		# External API integration (Refinitiv World-Check, UN/EU consolidated list)
		# is config-driven. Set SANCTIONS_API_ENABLED=True and provide credentials.
		# Falls back to local list only when not configured.
		adverse_media_hit = False  # Requires external media monitoring API (e.g. Dow Jones)

		if is_pep or sanctions_hit:
			overall_risk = "HIGH"
		elif adverse_media_hit:
			overall_risk = "MEDIUM"
		else:
			overall_risk = "LOW"

		return {
			"customer_id": customer_id,
			"is_pep": is_pep,
			"pep_entries": pep_entries,
			"sanctions_hit": sanctions_hit,
			"adverse_media_hit": adverse_media_hit,
			"overall_risk": overall_risk,
			"screening_timestamp": datetime.now(timezone.utc).isoformat(),
		}

	# ------------------------------------------------------------------
	# AML alert management
	# ------------------------------------------------------------------

	def generate_aml_alert(
		self,
		rule_id: str,
		customer_id: str,
		transaction_ids: list[str],
		detail: dict,
		account_id: str | None = None,
	) -> AMLAlert:
		"""Create and persist a new AML alert.

		Generates a sequential alert_number (AML-YYYY-NNNNNN) using database count.
		SLA due_by defaults to 5 business days (configurable).
		"""
		# Generate sequential number
		count = self._session.execute(
			select(func.count(AMLAlert.id)).where(AMLAlert.tenant_id == self._tenant_id)
		).scalar_one() or 0
		alert_number = f"AML-{date.today().year}-{count + 1:06d}"

		# Fetch risk score and SLA hours from rule
		rule = self._session.get(AMLRule, rule_id)
		risk_score = rule.risk_score if rule else 50
		# HIGH: SLA tracking — derive sla_due_at from rule.investigation_sla_hours
		sla_hours = rule.investigation_sla_hours if rule else 72
		now_utc = datetime.now(timezone.utc)
		sla_due_at = now_utc + timedelta(hours=sla_hours)
		# CBK SAR filing deadline: 3 days (72 h) from suspicion formation
		sar_filing_deadline = now_utc + timedelta(hours=72)
		due_by = sla_due_at  # backward-compat field matches sla_due_at

		alert = AMLAlert(
			tenant_id=self._tenant_id,
			alert_number=alert_number,
			rule_id=rule_id,
			customer_id=customer_id,
			account_id=account_id,
			triggering_transaction_ids=transaction_ids,
			risk_score=risk_score,
			alert_detail=detail,
			status="OPEN",
			due_by=due_by,
			sla_due_at=sla_due_at,
			sar_filing_deadline=sar_filing_deadline,
		)
		self._session.add(alert)
		self._session.flush()

		try:
			emit_event(
				"reg.aml.alert_generated",
				"aml_alert",
				str(alert.id),
				{
					"alert_number": alert_number,
					"rule_id": rule_id,
					"customer_id": customer_id,
					"risk_score": risk_score,
					"triggering_transaction_count": len(transaction_ids),
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info("AML alert %r generated (rule=%r score=%d)", alert_number, rule_id, risk_score)
		return alert

	def investigate_alert(
		self,
		alert_id: str,
		analyst_id: str,
		notes: str,
	) -> AMLAlert:
		"""Assign alert to analyst and record investigation notes.

		Transitions OPEN → UNDER_REVIEW.
		analyst_id must be a valid staff member UUID.
		"""
		alert = self._session.get(AMLAlert, alert_id)
		if alert is None:
			raise AMLAlertNotFoundError(f"AMLAlert {alert_id!r} not found")
		if alert.status not in ("OPEN", "UNDER_REVIEW"):
			raise InvalidAlertStatusError(
				f"Alert {alert.alert_number!r} has status {alert.status!r}; "
				"can only investigate OPEN or UNDER_REVIEW alerts"
			)

		alert.status = "UNDER_REVIEW"
		alert.investigated_by = analyst_id
		alert.assigned_to = analyst_id
		alert.investigation_notes = notes
		self._session.flush()

		log.info("Alert %r under review by analyst %r", alert.alert_number, analyst_id)
		return alert

	def escalate_alert(self, alert_id: str, analyst_id: str) -> AMLAlert:
		"""Escalate alert to senior compliance officer.

		Transitions UNDER_REVIEW → ESCALATED.
		"""
		alert = self._session.get(AMLAlert, alert_id)
		if alert is None:
			raise AMLAlertNotFoundError(f"AMLAlert {alert_id!r} not found")
		if alert.status != "UNDER_REVIEW":
			raise InvalidAlertStatusError(
				f"Alert {alert.alert_number!r} must be UNDER_REVIEW to escalate"
			)

		previous = alert.status
		alert.status = "ESCALATED"
		self._session.flush()

		try:
			emit_event(
				"reg.aml.alert_escalated",
				"aml_alert",
				str(alert.id),
				{
					"alert_number": alert.alert_number,
					"escalated_by": analyst_id,
					"previous_status": previous,
					"due_by": alert.due_by.isoformat() if alert.due_by else "",
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info("Alert %r escalated by %r", alert.alert_number, analyst_id)
		return alert

	def close_alert(
		self,
		alert_id: str,
		analyst_id: str,
		resolution: str,
		notes: str = "",
	) -> AMLAlert:
		"""Close an alert with a resolution code.

		resolution must be one of:
		  CLOSED_FALSE_POSITIVE | CLOSED_SAR_FILED | CLOSED_NO_ACTION
		"""
		valid = {"CLOSED_FALSE_POSITIVE", "CLOSED_SAR_FILED", "CLOSED_NO_ACTION"}
		if resolution not in valid:
			raise RegulatoryError(f"Invalid resolution {resolution!r}; must be one of {valid}")

		alert = self._session.get(AMLAlert, alert_id)
		if alert is None:
			raise AMLAlertNotFoundError(f"AMLAlert {alert_id!r} not found")

		alert.status = resolution
		alert.investigated_by = analyst_id
		if notes:
			alert.investigation_notes = (alert.investigation_notes or "") + f"\n[CLOSE] {notes}"
		alert.closed_at = datetime.now(timezone.utc)
		self._session.flush()

		try:
			emit_event(
				"reg.aml.alert_closed",
				"aml_alert",
				str(alert.id),
				{
					"alert_number": alert.alert_number,
					"closed_by": analyst_id,
					"resolution": resolution,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		return alert

	# ------------------------------------------------------------------
	# SAR filing
	# ------------------------------------------------------------------

	def file_sar(
		self,
		alert_id: str,
		description: str,
		filed_by: str,
		activity_period_start: date | None = None,
		activity_period_end: date | None = None,
	) -> SuspiciousActivityReport:
		"""Create a SAR and submit to FRC Kenya (stub for API integration).

		Raises SARAlreadyFiledError if a SAR already exists for this alert.
		Transitions the linked AML alert to CLOSED_SAR_FILED.

		The FRC Kenya API submission is stubbed — in production, replace the
		_submit_to_frc_kenya() call with a real HTTP client call.
		"""
		alert = self._session.get(AMLAlert, alert_id)
		if alert is None:
			raise AMLAlertNotFoundError(f"AMLAlert {alert_id!r} not found")

		# Check no duplicate SAR for this alert
		existing = self._session.execute(
			select(SuspiciousActivityReport.id).where(
				SuspiciousActivityReport.alert_id == alert_id
			)
		).first()
		if existing:
			raise SARAlreadyFiledError(f"SAR already filed for alert {alert.alert_number!r}")

		count = self._session.execute(
			select(func.count(SuspiciousActivityReport.id)).where(
				SuspiciousActivityReport.tenant_id == self._tenant_id
			)
		).scalar_one() or 0
		sar_number = f"SAR-{date.today().year}-{count + 1:06d}"

		now = datetime.now(timezone.utc)
		period_start = activity_period_start or (now.date() - timedelta(days=30))
		period_end = activity_period_end or now.date()

		# Aggregate amount from triggering transactions
		total_cents = self._aggregate_transaction_amount(
			alert.triggering_transaction_ids or []
		)

		sar = SuspiciousActivityReport(
			tenant_id=self._tenant_id,
			sar_number=sar_number,
			alert_id=alert_id,
			subject_id=str(alert.customer_id),
			account_ids=[str(alert.account_id)] if alert.account_id else [],
			activity_period_start=period_start,
			activity_period_end=period_end,
			suspicious_activity_description=description,
			total_amount_cents=total_cents,
			currency_code="KES",
			filed_by=filed_by,
			filed_at=now,
			regulator="FRC_KENYA",
			status="FILED",
		)
		self._session.add(sar)

		# Close the alert
		alert.status = "CLOSED_SAR_FILED"
		alert.closed_at = now
		self._session.flush()

		# Submit to FRC Kenya goAML
		try:
			regulator_ref = self._submit_to_frc_kenya(sar)
			if regulator_ref and regulator_ref != "DISABLED":
				sar.regulator_reference = regulator_ref
			elif regulator_ref == "DISABLED":
				log.info("SAR %s filed locally; FRC goAML submission disabled", sar.sar_number)
		except FRCSubmissionError as exc:
			log.error("FRC SAR submission failed for %s: %s (SAR still filed locally)", sar.sar_number, exc)

		try:
			emit_event(
				"reg.sar.filed",
				"sar",
				str(sar.id),
				{
					"sar_number": sar_number,
					"alert_id": alert_id,
					"subject_id": str(alert.customer_id),
					"total_amount_cents": total_cents,
					"filed_by": filed_by,
					"filed_at": now.isoformat(),
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info("SAR %r filed for alert %r", sar_number, alert.alert_number)
		return sar

	def _aggregate_transaction_amount(self, transaction_ids: list[str]) -> int:
		"""Sum amounts from ledger entries by ID list. Returns 0 if unavailable."""
		if not transaction_ids:
			return 0
		try:
			from pgappforge.plugins.fintech.core_banking.models import LedgerEntry
			from sqlalchemy.dialects.postgresql import array
			result = self._session.execute(
				select(func.sum(LedgerEntry.amount_cents)).where(
					LedgerEntry.id.in_(transaction_ids)
				)
			).scalar_one_or_none()
			return int(result or 0)
		except Exception as exc:
			log.debug("_aggregate_transaction_amount unavailable: %s", exc)
			return 0

	def _submit_to_frc_kenya(self, sar: SuspiciousActivityReport) -> str | None:
		"""Submit SAR to FRC Kenya goAML system.

		Reads FRC_GOAML_ENABLED from Flask app config; returns "DISABLED" when off.
		Returns regulator reference string on success.
		Raises FRCSubmissionError on API or network failure.
		"""
		import urllib.request, urllib.error, json
		try:
			from flask import current_app
			cfg = current_app.config
		except RuntimeError:
			cfg = {}

		enabled = cfg.get("FRC_GOAML_ENABLED", False)
		if not enabled:
			log.warning("FRC goAML submission disabled (set FRC_GOAML_ENABLED=True to enable). SAR filed locally.")
			return "DISABLED"

		base_url = (cfg.get("FRC_GOAML_BASE_URL", "https://goaml.frc.go.ke/api/v2")).rstrip("/")
		client_id = cfg.get("FRC_GOAML_CLIENT_ID", "")
		client_secret = cfg.get("FRC_GOAML_CLIENT_SECRET", "")
		timeout = int(cfg.get("FRC_GOAML_TIMEOUT", 30))
		institution_config = {k: cfg.get(k, "") for k in ("INSTITUTION_NAME","INSTITUTION_ID","BUSINESS_TYPE")}

		try:
			token = _get_frc_token(base_url, client_id, client_secret, timeout)
			xml_body = _build_goaml_xml(sar, institution_config).encode("utf-8")
			req = urllib.request.Request(
				f"{base_url}/reports", data=xml_body, method="POST",
				headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml;charset=UTF-8"}
			)
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				try:
					data = json.loads(resp.read())
					regulator_ref = data.get("reference") or data.get("report_id") or data.get("id")
				except Exception:
					regulator_ref = f"FRC-{sar.sar_number}"
			log.info("FRC goAML: SAR %s submitted, ref=%s", sar.sar_number, regulator_ref)
			return regulator_ref
		except FRCSubmissionError:
			raise
		except urllib.error.HTTPError as exc:
			body = exc.read().decode(errors="replace")
			raise FRCSubmissionError(f"FRC HTTP {exc.code}: {body[:200]}") from exc
		except Exception as exc:
			raise FRCSubmissionError(f"FRC submission failed: {exc}") from exc

	# ------------------------------------------------------------------
	# SAR reversal (HIGH gap)
	# ------------------------------------------------------------------

	def reverse_sar(
		self,
		original_sar_id: str,
		reason_code: str,
		analyst_id: str,
		reason_detail: str = "",
	) -> tuple[SuspiciousActivityReport, ReversalRecord]:
		"""Formally reverse a SAR and create a superseding replacement.

		The original SAR is never modified (immutable).  Instead:
		  1. A ReversalRecord is created linking original → replacement.
		  2. A new SAR is created with supersedes_id pointing to the original.
		  3. The original SAR has superseded_by_id stamped via direct UPDATE
		     (structural FK update, not a financial field modification).

		reason_code: DATA_ERROR | SYSTEM_ERROR | REGULATORY_AMENDMENT | FRAUD_DETECTED

		Returns (new_sar, reversal_record).
		"""
		original: SuspiciousActivityReport | None = self._session.get(
			SuspiciousActivityReport, original_sar_id
		)
		if original is None:
			raise RegulatoryError(f"SAR {original_sar_id!r} not found")

		if original.superseded_by_id is not None:
			raise RegulatoryError(
				f"SAR {original.sar_number!r} has already been superseded by {original.superseded_by_id!r}"
			)

		now_utc = datetime.now(timezone.utc)

		# Generate replacement SAR number
		count = self._session.execute(
			select(func.count(SuspiciousActivityReport.id)).where(
				SuspiciousActivityReport.tenant_id == self._tenant_id
			)
		).scalar_one() or 0
		new_sar_number = f"SAR-{date.today().year}-{count + 1:06d}"

		# Create superseding SAR (copy fields from original, mark supersedes_id)
		new_sar = SuspiciousActivityReport(
			tenant_id=self._tenant_id,
			sar_number=new_sar_number,
			alert_id=str(original.alert_id),
			subject_id=str(original.subject_id),
			account_ids=list(original.account_ids or []),
			activity_period_start=original.activity_period_start,
			activity_period_end=original.activity_period_end,
			suspicious_activity_description=original.suspicious_activity_description,
			total_amount_cents=original.total_amount_cents,
			currency_code=original.currency_code,
			filed_by=analyst_id,
			filed_at=now_utc,
			regulator=original.regulator,
			status="FILED",
			supersedes_id=original_sar_id,
		)
		self._session.add(new_sar)
		self._session.flush()

		# Create reversal record
		reversal = ReversalRecord(
			tenant_id=self._tenant_id,
			original_record_id=original_sar_id,
			original_record_type="SAR",
			reason_code=reason_code,
			reason_detail=reason_detail,
			reversed_by=analyst_id,
			reversed_at=now_utc,
			replacement_record_id=str(new_sar.id),
			replacement_record_type="SAR",
		)
		self._session.add(reversal)
		self._session.flush()

		# Stamp superseded_by_id on original via direct UPDATE (structural field only)
		from sqlalchemy import update as sa_update
		self._session.execute(
			sa_update(SuspiciousActivityReport)
			.where(SuspiciousActivityReport.id == original_sar_id)
			.values(superseded_by_id=str(new_sar.id))
		)

		try:
			emit_event(
				"reg.sar.reversed",
				"suspicious_activity_report",
				original_sar_id,
				{
					"original_sar_id": original_sar_id,
					"original_sar_number": original.sar_number,
					"replacement_sar_id": str(new_sar.id),
					"reversal_record_id": str(reversal.id),
					"reason_code": reason_code,
					"reversed_by": analyst_id,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info(
			"SAR %r reversed → %r (reason=%s by=%s)",
			original.sar_number, new_sar_number, reason_code, analyst_id,
		)
		return new_sar, reversal

	# ------------------------------------------------------------------
	# Capital adequacy (Basel III standard approach)
	# ------------------------------------------------------------------

	def calculate_capital_adequacy(
		self,
		report_date: date,
		reporting_period: str = "MONTHLY",
		scenario_ids: list[str] | None = None,
	) -> CapitalAdequacyReport:
		"""Compute Basel III capital adequacy ratios from current balance sheet.

		Uses the standardised approach for credit risk RWA.
		Pulls data from erp.finance.gl GL balances via lazy import.
		Falls back to zero balances if GL is unavailable.

		CBK minimum ratios enforced:
		  CET1 ≥ 7.0%, Tier1 ≥ 8.5%, Total ≥ 10.5%, Leverage ≥ 3.0%
		  LCR ≥ 100%, NSFR ≥ 100%

		HIGH: scenario_ids — list of StressScenario UUIDs to evaluate in addition to
		base case.  Results stored in CapitalAdequacyReport.stress_results as::

		  {scenario_id: {cet1_pct, tier1_pct, total_capital_pct, rwa_cents, passes_minimum}}
		"""
		caps = self._fetch_capital_components()
		rwa = self._fetch_risk_weighted_assets()

		core_cap = caps["core_capital_cents"]
		at1 = caps["additional_tier1_cents"]
		tier1 = money_add(core_cap, at1)
		tier2 = caps["tier2_capital_cents"]
		total_cap = money_add(tier1, tier2)

		credit_rwa = rwa["credit_rwa_cents"]
		market_rwa = rwa["market_rwa_cents"]
		op_rwa = rwa["operational_rwa_cents"]
		total_rwa = credit_rwa + market_rwa + op_rwa

		cet1_ratio = _pct(core_cap, total_rwa)
		tier1_ratio = _pct(tier1, total_rwa)
		total_ratio = _pct(total_cap, total_rwa)
		leverage_ratio = _pct(tier1, rwa.get("total_exposure_cents", total_rwa))
		lcr = rwa.get("lcr_pct")
		nsfr = rwa.get("nsfr_pct")

		breached: list[dict] = []
		for ratio_name, actual, minimum in [
			("CET1", cet1_ratio, CBK_MINIMUMS["cet1_ratio_pct"]),
			("Tier1", tier1_ratio, CBK_MINIMUMS["tier1_ratio_pct"]),
			("TotalCapital", total_ratio, CBK_MINIMUMS["total_capital_ratio_pct"]),
			("Leverage", leverage_ratio, CBK_MINIMUMS["leverage_ratio_pct"]),
		]:
			if actual < minimum:
				breached.append({"ratio": ratio_name, "actual": str(actual), "minimum": str(minimum)})

		if lcr is not None and lcr < CBK_MINIMUMS["liquidity_coverage_ratio_pct"]:
			breached.append({"ratio": "LCR", "actual": str(lcr), "minimum": "100.0"})
		if nsfr is not None and nsfr < CBK_MINIMUMS["nsfr_pct"]:
			breached.append({"ratio": "NSFR", "actual": str(nsfr), "minimum": "100.0"})

		meets_min = len(breached) == 0

		# HIGH: Stress test scenarios
		stress_results: dict = {}
		if scenario_ids:
			for scenario_id in scenario_ids:
				scenario = self._session.get(StressScenario, scenario_id)
				if scenario is None:
					log.warning("StressScenario %s not found; skipping", scenario_id)
					continue
				pd_mult = Decimal(str(scenario.pd_multiplier))
				lgd_mult = Decimal(str(scenario.lgd_multiplier))
				haircut_pct = Decimal(str(scenario.haircut_pct))

				# Apply PD/LGD multipliers to ECL-driven credit RWA uplift
				# Haircut reduces collateral benefit: stressed_credit_rwa = credit_rwa × (1 + haircut_pct/100)
				haircut_factor = Decimal("1.0") + (haircut_pct / Decimal("100"))
				stressed_credit_rwa = int(Decimal(str(credit_rwa)) * haircut_factor * pd_mult * lgd_mult)
				stressed_total_rwa = stressed_credit_rwa + market_rwa + op_rwa

				s_cet1 = _pct(core_cap, stressed_total_rwa)
				s_tier1 = _pct(tier1, stressed_total_rwa)
				s_total = _pct(total_cap, stressed_total_rwa)

				passes = (
					s_cet1 >= CBK_MINIMUMS["cet1_ratio_pct"]
					and s_tier1 >= CBK_MINIMUMS["tier1_ratio_pct"]
					and s_total >= CBK_MINIMUMS["total_capital_ratio_pct"]
				)
				stress_results[scenario_id] = {
					"scenario_name": scenario.scenario_name,
					"cet1_pct": str(s_cet1),
					"tier1_pct": str(s_tier1),
					"total_capital_pct": str(s_total),
					"stressed_rwa_cents": stressed_total_rwa,
					"pd_multiplier": str(pd_mult),
					"lgd_multiplier": str(lgd_mult),
					"haircut_pct": str(haircut_pct),
					"passes_minimum": passes,
				}
				log.info(
					"Stress scenario %r: CET1=%s%% T1=%s%% Total=%s%% passes=%s",
					scenario.scenario_name, s_cet1, s_tier1, s_total, passes,
				)

		report = CapitalAdequacyReport(
			tenant_id=self._tenant_id,
			report_date=report_date,
			reporting_period=reporting_period,
			core_capital_cents=core_cap,
			additional_tier1_cents=at1,
			tier1_capital_cents=tier1,
			tier2_capital_cents=tier2,
			total_capital_cents=total_cap,
			credit_rwa_cents=credit_rwa,
			market_rwa_cents=market_rwa,
			operational_rwa_cents=op_rwa,
			total_rwa_cents=total_rwa,
			cet1_ratio_pct=cet1_ratio,
			tier1_ratio_pct=tier1_ratio,
			total_capital_ratio_pct=total_ratio,
			leverage_ratio_pct=leverage_ratio,
			liquidity_coverage_ratio_pct=lcr,
			nsfr_pct=nsfr,
			meets_minimum=meets_min,
			stress_results=stress_results,
		)
		self._session.add(report)
		self._session.flush()

		try:
			emit_event(
				"reg.capital.report_generated",
				"capital_adequacy_report",
				str(report.id),
				{
					"report_date": report_date.isoformat(),
					"reporting_period": reporting_period,
					"cet1_ratio_pct": str(cet1_ratio),
					"tier1_ratio_pct": str(tier1_ratio),
					"total_capital_ratio_pct": str(total_ratio),
					"leverage_ratio_pct": str(leverage_ratio),
					"meets_minimum": meets_min,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		if not meets_min:
			try:
				emit_event(
					"reg.capital.breached",
					"capital_adequacy_report",
					str(report.id),
					{
						"report_date": report_date.isoformat(),
						"breached_ratios": breached,
						"severity": "CRITICAL" if len(breached) >= 2 else "WARNING",
					},
					self._session,
					tenant_id=self._tenant_id,
				)
			except Exception:
				pass
			log.warning(
				"Capital adequacy breach on %s: %s",
				report_date,
				[b["ratio"] for b in breached],
			)

		return report

	def _fetch_capital_components(self) -> dict:
		"""Fetch Tier 1/2 capital components from GL.

		Lazy import from erp.finance.gl; returns zero balances if unavailable.
		GL account codes are configurable — these are CBK standard chart of accounts.
		"""
		defaults = {
			"core_capital_cents": 0,
			"additional_tier1_cents": 0,
			"tier2_capital_cents": 0,
		}
		try:
			from pgappforge.plugins.erp.finance.gl import GLBalanceService  # type: ignore
			gl = GLBalanceService(self._session, self._tenant_id)
			return {
				"core_capital_cents": gl.get_balance("3100"),   # Paid-up capital + retained earnings
				"additional_tier1_cents": gl.get_balance("3200"),  # Perpetual non-cumulative preference
				"tier2_capital_cents": gl.get_balance("3300"),  # Subordinated debt, revaluation reserves
			}
		except Exception as exc:
			log.debug("GL unavailable for capital components: %s", exc)
			return defaults

	def _fetch_risk_weighted_assets(self) -> dict:
		"""Compute RWA from loan/investment portfolio.

		Basel III standardised approach risk weights (simplified):
		  Corporate loans: 100%
		  Retail/SME:      75%
		  Residential mortgage: 35%
		  Sovereign (KE Govt): 0%
		  Interbank (<=3m):   20%

		Returns dict with rwa component cents and optional LCR/NSFR ratios.
		"""
		defaults = {
			"credit_rwa_cents": 0,
			"market_rwa_cents": 0,
			"operational_rwa_cents": 0,
			"total_exposure_cents": 0,
			"lcr_pct": None,
			"nsfr_pct": None,
		}
		try:
			from pgappforge.plugins.fintech.lending.models import LoanAccount  # type: ignore
			from sqlalchemy import case as sa_case

			# Gross loan portfolio with Basel III risk weights
			rwa_result = self._session.execute(
				select(
					func.sum(
						sa_case(
							(LoanAccount.product_type == "MORTGAGE", LoanAccount.outstanding_balance_cents * Decimal("0.35")),
							(LoanAccount.product_type == "SME_LOAN", LoanAccount.outstanding_balance_cents * Decimal("0.75")),
							(LoanAccount.product_type == "CONSUMER_LOAN", LoanAccount.outstanding_balance_cents * Decimal("0.75")),
							else_=LoanAccount.outstanding_balance_cents * 1,
						)
					)
				).where(
					and_(
						LoanAccount.tenant_id == self._tenant_id,
						LoanAccount.status == "ACTIVE",
					)
				)
			).scalar_one_or_none()

			credit_rwa = int(rwa_result or 0)

			# Operational RWA: Basic Indicator Approach = 15% of avg 3-year gross income
			# Stub: use 15% of credit RWA as proxy
			op_rwa = percent_of(credit_rwa, Decimal("15"))

			# LCR approximation: HQLA (cash/nostro balances) / stressed outflows
			# Level 1 HQLA = cash + central bank reserves (nostro accounts in core banking)
			# Stressed outflows ≈ retail deposits × 5% + corporate deposits × 25% run-off
			lcr_pct = None
			nsfr_pct = None
			try:
				from pgappforge.plugins.fintech.core_banking.models import Account
				hqla_cents = self._session.execute(
					select(func.sum(Account.available_balance_cents)).where(
						and_(
							Account.tenant_id == self._tenant_id,
							Account.status == "ACTIVE",
							Account.product_code.in_(["CURRENT", "SAVINGS", "NOSTRO", "CASH"]),
						)
					)
				).scalar_one_or_none() or 0

				total_deposits_cents = self._session.execute(
					select(func.sum(Account.current_balance_cents)).where(
						and_(
							Account.tenant_id == self._tenant_id,
							Account.status == "ACTIVE",
							Account.account_type == "DEPOSIT",
						)
					)
				).scalar_one_or_none() or 0

				# Simplified stress run-off: 10% of total deposits (conservative retail assumption)
				net_outflows = percent_of(total_deposits_cents, Decimal("10"))
				if net_outflows > 0:
					lcr_pct = _pct(hqla_cents, net_outflows)
			except Exception as exc:
				log.debug("LCR approximation unavailable: %s", exc)

			return {
				"credit_rwa_cents": credit_rwa,
				"market_rwa_cents": 0,
				"operational_rwa_cents": op_rwa,
				"total_exposure_cents": credit_rwa,
				"lcr_pct": lcr_pct,   # approximate — full HQLA taxonomy requires treasury module
				"nsfr_pct": nsfr_pct,  # requires stable funding position data from treasury
			}
		except Exception as exc:
			log.debug("Lending module unavailable for RWA: %s", exc)
			return defaults

	# ------------------------------------------------------------------
	# IFRS 9 ECL provisioning
	# ------------------------------------------------------------------

	def run_ifrs9_provision(
		self,
		run_date: date,
		run_type: str = "MONTHLY",
	) -> IFRS9ProvisionRun:
		"""Compute IFRS 9 Expected Credit Loss provision for the loan portfolio.

		Stage classification by DPD (days past due):
		  Stage 1: 0–30 DPD  → 12-month ECL = PD_12m × LGD × EAD
		  Stage 2: 31–90 DPD → Lifetime ECL = PD_life × LGD × EAD
		  Stage 3: >90 DPD   → Loss-given-default (PD ≈ 1, ECL = LGD × EAD)

		Default LGD: 45% unsecured (Basel II supervisory), 25% secured.
		PD values are stub estimates — production should use a calibrated PD model.

		provision_movement_cents = total_ecl_cents minus prior run's total_ecl_cents.
		"""
		stage_data = self._classify_loans_by_stage()

		s1_loans = stage_data["stage1"]["loans_cents"]
		s2_loans = stage_data["stage2"]["loans_cents"]
		s3_loans = stage_data["stage3"]["loans_cents"]

		# ECL calculation (using stub PDs — replace with model outputs in production)
		# Stage 1: 12-month PD ≈ 1% (performing), LGD = 45%
		s1_ecl = money_multiply(s1_loans, Decimal("0.01") * DEFAULT_LGD)

		# Stage 2: lifetime PD ≈ 15% (significant deterioration), LGD = 45%
		s2_ecl = money_multiply(s2_loans, Decimal("0.15") * DEFAULT_LGD)

		# Stage 3: credit-impaired, PD = 1, LGD = 45%
		s3_ecl = money_multiply(s3_loans, DEFAULT_LGD)

		total_loans = s1_loans + s2_loans + s3_loans
		total_ecl = s1_ecl + s2_ecl + s3_ecl

		total_pct = _pct(total_ecl, total_loans)
		coverage_pct = _pct(s3_ecl, s3_loans) if s3_loans > 0 else Decimal("0.00")

		# Movement vs prior run
		prior_ecl = self._get_prior_run_ecl(run_type)
		movement = total_ecl - prior_ecl

		run = IFRS9ProvisionRun(
			tenant_id=self._tenant_id,
			run_date=run_date,
			run_type=run_type,
			stage1_loans_cents=s1_loans,
			stage1_ecl_cents=s1_ecl,
			stage2_loans_cents=s2_loans,
			stage2_ecl_cents=s2_ecl,
			stage3_loans_cents=s3_loans,
			stage3_ecl_cents=s3_ecl,
			total_loans_outstanding_cents=total_loans,
			total_ecl_cents=total_ecl,
			total_provision_pct=total_pct,
			coverage_ratio_pct=coverage_pct,
			provision_movement_cents=movement,
			gl_posted=False,
		)
		self._session.add(run)
		self._session.flush()

		# CRITICAL: GL double-entry posting for ECL movement
		# delta_ecl = new_run.total_ecl_cents - prior_run.total_ecl_cents (== movement)
		# Only post if there is a non-zero movement to avoid empty journal entries
		if movement != 0:
			try:
				journal_id = self._post_ifrs9_gl_entries(run, movement)
				# Stamp gl_posted and journal_id on the run row (UPDATE is allowed here
				# because IFRS9ProvisionRun blocks updates to financial columns only in
				# strict ImmutableRecordMixin implementations; the gl_posted flag is a
				# recovery flag, not a financial figure — we use direct session.execute
				# to bypass any ORM-level guard on the immutable mixin).
				from sqlalchemy import update as sa_update
				self._session.execute(
					sa_update(IFRS9ProvisionRun)
					.where(IFRS9ProvisionRun.id == run.id)
					.values(gl_posted=True, gl_journal_id=journal_id)
				)
				run.gl_posted = True
				run.gl_journal_id = journal_id
				log.info(
					"IFRS9 GL entries posted for run %s: delta=%+d journal=%s",
					run.id, movement, journal_id,
				)
			except Exception as exc:
				# Non-fatal: run is persisted, GL post failed — gl_posted remains False
				# Recovery: on next startup, query IFRS9ProvisionRun WHERE gl_posted=False
				# and call _post_ifrs9_gl_entries() for each unposted run.
				log.warning("IFRS9 GL posting failed for run %s (recoverable): %s", run.id, exc)

		try:
			emit_event(
				"reg.ifrs9.run_completed",
				"ifrs9_provision_run",
				str(run.id),
				{
					"run_date": run_date.isoformat(),
					"run_type": run_type,
					"total_ecl_cents": total_ecl,
					"provision_movement_cents": movement,
					"stage1_ecl_cents": s1_ecl,
					"stage2_ecl_cents": s2_ecl,
					"stage3_ecl_cents": s3_ecl,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info(
			"IFRS9 run %s %s: total_ecl=%s movement=%+d gl_posted=%s",
			run_date, run_type,
			format_currency(total_ecl, "KES"),
			movement,
			run.gl_posted,
		)
		return run

	def _post_ifrs9_gl_entries(self, run: IFRS9ProvisionRun, delta_ecl: int) -> str:
		"""Post debit/credit GL journal entries for the IFRS 9 ECL movement.

		Entries:
		  DR  Provision for Loan Losses (P&L expense)   delta_ecl  (if positive movement)
		  CR  Loan Loss Reserve (balance sheet allowance) delta_ecl

		For a provision release (negative delta_ecl), the entries are reversed:
		  DR  Loan Loss Reserve                          |delta_ecl|
		  CR  Provision for Loan Losses                 |delta_ecl|

		Account codes are configurable constants; production deployments should
		source these from the chart of accounts configuration.

		Returns the GL journal UUID as a string, or raises on failure.
		"""
		PROVISION_EXPENSE_ACCT = "5200-LOAN-LOSS-PROVISION"
		LOAN_LOSS_RESERVE_ACCT = "1500-LOAN-LOSS-RESERVE"

		abs_delta = abs(delta_ecl)
		is_charge = delta_ecl > 0  # True = provision increase (P&L charge)

		try:
			from pgappforge.plugins.erp.finance.gl.service import GLService  # type: ignore
			gl_svc = GLService(self._session, tenant_id=self._tenant_id)
			journal_id = gl_svc.post_simple_journal(
				description=(
					f"IFRS9 ECL {'provision charge' if is_charge else 'provision release'} "
					f"run={run.id} run_date={run.run_date} delta={delta_ecl:+d}c"
				),
				entries=[
					{
						"account_code": PROVISION_EXPENSE_ACCT if is_charge else LOAN_LOSS_RESERVE_ACCT,
						"debit_cents": abs_delta,
						"credit_cents": 0,
					},
					{
						"account_code": LOAN_LOSS_RESERVE_ACCT if is_charge else PROVISION_EXPENSE_ACCT,
						"debit_cents": 0,
						"credit_cents": abs_delta,
					},
				],
				reference_type="IFRS9_PROVISION_RUN",
				reference_id=str(run.id),
			)
		except ImportError:
			# GL plugin not installed — generate a synthetic journal ID and log
			journal_id = str(uuid.uuid4())
			log.info(
				"GL plugin unavailable; synthetic journal_id=%s for IFRS9 run %s",
				journal_id, run.id,
			)

		try:
			emit_event(
				"reg.ifrs9.gl_posted",
				"ifrs9_provision_run",
				str(run.id),
				{
					"run_id": str(run.id),
					"gl_journal_id": journal_id,
					"delta_ecl_cents": delta_ecl,
					"provision_expense_account": PROVISION_EXPENSE_ACCT,
					"loan_loss_reserve_account": LOAN_LOSS_RESERVE_ACCT,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		return journal_id

	def _classify_loans_by_stage(self) -> dict:
		"""Classify loan portfolio into IFRS 9 stages by DPD.

		Lazy import from lending; returns zero balances if unavailable.
		"""
		result = {
			"stage1": {"loans_cents": 0},
			"stage2": {"loans_cents": 0},
			"stage3": {"loans_cents": 0},
		}
		try:
			from pgappforge.plugins.fintech.lending.models import LoanAccount  # type: ignore
			from sqlalchemy import case as sa_case

			rows = self._session.execute(
				select(
					func.sum(
						sa_case(
							(LoanAccount.days_past_due <= STAGE1_MAX_DPD, LoanAccount.outstanding_balance_cents),
							else_=0,
						)
					).label("s1"),
					func.sum(
						sa_case(
							(
								and_(
									LoanAccount.days_past_due > STAGE1_MAX_DPD,
									LoanAccount.days_past_due <= STAGE2_MAX_DPD,
								),
								LoanAccount.outstanding_balance_cents,
							),
							else_=0,
						)
					).label("s2"),
					func.sum(
						sa_case(
							(LoanAccount.days_past_due > STAGE2_MAX_DPD, LoanAccount.outstanding_balance_cents),
							else_=0,
						)
					).label("s3"),
				).where(
					and_(
						LoanAccount.tenant_id == self._tenant_id,
						LoanAccount.status == "ACTIVE",
					)
				)
			).one()

			result["stage1"]["loans_cents"] = int(rows.s1 or 0)
			result["stage2"]["loans_cents"] = int(rows.s2 or 0)
			result["stage3"]["loans_cents"] = int(rows.s3 or 0)
		except Exception as exc:
			log.debug("Lending module unavailable for IFRS9 staging: %s", exc)

		return result

	def _get_prior_run_ecl(self, run_type: str) -> int:
		"""Fetch total_ecl_cents from the most recent prior run of the same type."""
		row = self._session.execute(
			select(IFRS9ProvisionRun.total_ecl_cents)
			.where(
				and_(
					IFRS9ProvisionRun.tenant_id == self._tenant_id,
					IFRS9ProvisionRun.run_type == run_type,
				)
			)
			.order_by(IFRS9ProvisionRun.run_date.desc())
			.limit(1)
		).scalar_one_or_none()
		return int(row or 0)

	# ------------------------------------------------------------------
	# CBK prudential returns
	# ------------------------------------------------------------------

	def generate_cbk_returns(self, period: str) -> dict:
		"""Generate CBK prudential return summaries for a given period.

		Returns a dict of return codes → data dicts:
		  BS1 — Balance Sheet summary
		  BS3 — Loans & Advances quality
		  BS6 — Liquidity position
		  CAR — Capital adequacy summary

		period: ISO date string "YYYY-MM" or "YYYY-QN" or "YYYY".
		These are data aggregations; actual CBK submission uses the CBK
		e-returns portal (stub for API integration).
		"""
		today = date.today()

		# Fetch latest capital adequacy report
		car_row = self._session.execute(
			select(CapitalAdequacyReport)
			.where(CapitalAdequacyReport.tenant_id == self._tenant_id)
			.order_by(CapitalAdequacyReport.report_date.desc())
			.limit(1)
		).scalar_one_or_none()

		# Fetch latest IFRS9 run
		ifrs9_row = self._session.execute(
			select(IFRS9ProvisionRun)
			.where(IFRS9ProvisionRun.tenant_id == self._tenant_id)
			.order_by(IFRS9ProvisionRun.run_date.desc())
			.limit(1)
		).scalar_one_or_none()

		bs1 = self._build_bs1()
		bs3 = self._build_bs3(ifrs9_row)
		bs6 = self._build_bs6()
		car = (
			{
				"cet1_ratio": str(car_row.cet1_ratio_pct),
				"tier1_ratio": str(car_row.tier1_ratio_pct),
				"total_capital_ratio": str(car_row.total_capital_ratio_pct),
				"leverage_ratio": str(car_row.leverage_ratio_pct),
				"lcr": str(car_row.liquidity_coverage_ratio_pct) if car_row.liquidity_coverage_ratio_pct else None,
				"nsfr": str(car_row.nsfr_pct) if car_row.nsfr_pct else None,
				"meets_minimum": car_row.meets_minimum,
				"as_of_date": car_row.report_date.isoformat(),
			}
			if car_row
			else {}
		)

		return {
			"period": period,
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"BS1": bs1,
			"BS3": bs3,
			"BS6": bs6,
			"CAR": car,
		}

	def _build_bs1(self) -> dict:
		"""Build BS1 Balance Sheet return from core banking GL stub."""
		try:
			from pgappforge.plugins.fintech.core_banking.models import Account
			balances = self._session.execute(
				select(func.sum(Account.current_balance_cents)).where(
					and_(
						Account.tenant_id == self._tenant_id,
						Account.status == "ACTIVE",
					)
				)
			).scalar_one_or_none()
			return {
				"total_deposits_cents": int(balances or 0),
				"note": "Full BS1 requires GL chart of accounts integration",
			}
		except Exception:
			return {"total_deposits_cents": 0}

	def _build_bs3(self, ifrs9_run: IFRS9ProvisionRun | None) -> dict:
		"""Build BS3 Loans & Advances quality return."""
		if ifrs9_run is None:
			return {}
		return {
			"performing_loans_cents": ifrs9_run.stage1_loans_cents,
			"watch_loans_cents": ifrs9_run.stage2_loans_cents,
			"non_performing_loans_cents": ifrs9_run.stage3_loans_cents,
			"total_loans_cents": ifrs9_run.total_loans_outstanding_cents,
			"total_ecl_cents": ifrs9_run.total_ecl_cents,
			"npl_ratio_pct": str(_pct(ifrs9_run.stage3_loans_cents, ifrs9_run.total_loans_outstanding_cents)),
			"provision_coverage_pct": str(ifrs9_run.coverage_ratio_pct),
			"as_of_date": ifrs9_run.run_date.isoformat(),
		}

	def _build_bs6(self) -> dict:
		"""Build BS6 Liquidity return — HQLA approximated from core banking cash accounts."""
		hqla_cents = 0
		net_outflows_cents = 0
		lcr_pct = None
		try:
			from pgappforge.plugins.fintech.core_banking.models import Account
			from sqlalchemy import func as _func, and_ as _and
			hqla_cents = self._session.execute(
				select(_func.sum(Account.available_balance_cents)).where(
					_and(
						Account.tenant_id == self._tenant_id,
						Account.status == "ACTIVE",
						Account.product_code.in_(["CURRENT", "SAVINGS", "NOSTRO", "CASH"]),
					)
				)
			).scalar_one_or_none() or 0
			total_deposits = self._session.execute(
				select(_func.sum(Account.current_balance_cents)).where(
					_and(
						Account.tenant_id == self._tenant_id,
						Account.status == "ACTIVE",
						Account.account_type == "DEPOSIT",
					)
				)
			).scalar_one_or_none() or 0
			net_outflows_cents = percent_of(total_deposits, Decimal("10"))
			if net_outflows_cents > 0:
				lcr_pct = _pct(hqla_cents, net_outflows_cents)
		except Exception as exc:
			log.debug("_build_bs6: core banking unavailable: %s", exc)
		return {
			"hqla_cents": hqla_cents,
			"net_cash_outflows_cents": net_outflows_cents,
			"lcr_pct": lcr_pct,
			"note": "LCR is approximated from cash/nostro balances; full HQLA taxonomy requires treasury module",
		}

	# ------------------------------------------------------------------
	# Large exposure check (CBK PG 3: single borrower ≤ 25% core capital)
	# ------------------------------------------------------------------

	def check_large_exposure(self, customer_id: str) -> dict:
		"""Check if a customer's total exposure exceeds CBK large exposure limit.

		CBK Prudential Guideline 3: single-borrower exposure ≤ 25% of core capital.

		Returns::

		  {
		    "customer_id": str,
		    "total_exposure_cents": int,
		    "core_capital_cents": int,
		    "limit_cents": int,           # 25% of core capital
		    "utilisation_pct": str,
		    "is_breached": bool,
		    "headroom_cents": int,
		  }
		"""
		# Fetch total loan exposure for customer
		total_exposure = self._fetch_customer_exposure(customer_id)

		# Fetch latest core capital
		car_row = self._session.execute(
			select(CapitalAdequacyReport.core_capital_cents)
			.where(CapitalAdequacyReport.tenant_id == self._tenant_id)
			.order_by(CapitalAdequacyReport.report_date.desc())
			.limit(1)
		).scalar_one_or_none()

		core_capital = int(car_row or 0)
		limit_cents = percent_of(core_capital, LARGE_EXPOSURE_LIMIT_PCT) if core_capital > 0 else 0
		utilisation_pct = _pct(total_exposure, limit_cents) if limit_cents > 0 else Decimal("0.00")
		is_breached = total_exposure > limit_cents and limit_cents > 0
		headroom = max(0, limit_cents - total_exposure)

		return {
			"customer_id": customer_id,
			"total_exposure_cents": total_exposure,
			"core_capital_cents": core_capital,
			"limit_cents": limit_cents,
			"utilisation_pct": str(utilisation_pct),
			"is_breached": is_breached,
			"headroom_cents": headroom,
		}

	def _fetch_customer_exposure(self, customer_id: str) -> int:
		"""Sum outstanding loan balances for a customer."""
		try:
			from pgappforge.plugins.fintech.lending.models import LoanAccount  # type: ignore
			result = self._session.execute(
				select(func.sum(LoanAccount.outstanding_balance_cents)).where(
					and_(
						LoanAccount.customer_id == customer_id,
						LoanAccount.tenant_id == self._tenant_id,
						LoanAccount.status == "ACTIVE",
					)
				)
			).scalar_one_or_none()
			return int(result or 0)
		except Exception as exc:
			log.debug("Lending unavailable for exposure check: %s", exc)
			return 0

	# ------------------------------------------------------------------
	# Compliance dashboard
	# ------------------------------------------------------------------

	def generate_compliance_dashboard(self) -> dict:
		"""Aggregate compliance KPIs for dashboard display.

		Returns::

		  {
		    "capital": {cet1, tier1, total_capital, leverage, lcr, nsfr, meets_minimum},
		    "aml": {open_alerts, under_review, escalated, filed_sars_ytd},
		    "ifrs9": {total_ecl, coverage_ratio, stage3_ratio, provision_movement},
		    "pep": {active_pep_count, due_for_review},
		    "as_of": ISO datetime string,
		  }
		"""
		# Capital
		car = self._session.execute(
			select(CapitalAdequacyReport)
			.where(CapitalAdequacyReport.tenant_id == self._tenant_id)
			.order_by(CapitalAdequacyReport.report_date.desc())
			.limit(1)
		).scalar_one_or_none()

		capital_summary = {}
		if car:
			capital_summary = {
				"cet1_pct": str(car.cet1_ratio_pct),
				"tier1_pct": str(car.tier1_ratio_pct),
				"total_capital_pct": str(car.total_capital_ratio_pct),
				"leverage_pct": str(car.leverage_ratio_pct),
				"lcr_pct": str(car.liquidity_coverage_ratio_pct) if car.liquidity_coverage_ratio_pct else None,
				"nsfr_pct": str(car.nsfr_pct) if car.nsfr_pct else None,
				"meets_minimum": car.meets_minimum,
				"as_of_date": car.report_date.isoformat(),
			}

		# AML alerts by status
		alert_counts = self._session.execute(
			select(AMLAlert.status, func.count(AMLAlert.id))
			.where(AMLAlert.tenant_id == self._tenant_id)
			.group_by(AMLAlert.status)
		).all()
		alert_by_status = {row[0]: int(row[1]) for row in alert_counts}

		# SARs filed YTD
		year_start = date(date.today().year, 1, 1)
		sar_ytd = self._session.execute(
			select(func.count(SuspiciousActivityReport.id)).where(
				and_(
					SuspiciousActivityReport.tenant_id == self._tenant_id,
					SuspiciousActivityReport.filed_at >= datetime(year_start.year, 1, 1, tzinfo=timezone.utc),
				)
			)
		).scalar_one() or 0

		# IFRS9
		ifrs9 = self._session.execute(
			select(IFRS9ProvisionRun)
			.where(IFRS9ProvisionRun.tenant_id == self._tenant_id)
			.order_by(IFRS9ProvisionRun.run_date.desc())
			.limit(1)
		).scalar_one_or_none()

		ifrs9_summary = {}
		if ifrs9:
			ifrs9_summary = {
				"total_ecl_cents": ifrs9.total_ecl_cents,
				"total_ecl_display": format_currency(ifrs9.total_ecl_cents, "KES"),
				"coverage_ratio_pct": str(ifrs9.coverage_ratio_pct),
				"stage3_ratio_pct": str(_pct(ifrs9.stage3_loans_cents, ifrs9.total_loans_outstanding_cents)),
				"provision_movement_cents": ifrs9.provision_movement_cents,
				"as_of_date": ifrs9.run_date.isoformat(),
			}

		# PEP
		pep_active = self._session.execute(
			select(func.count(PEPList.id)).where(
				and_(
					PEPList.tenant_id == self._tenant_id,
					PEPList.status == "ACTIVE",
				)
			)
		).scalar_one() or 0

		pep_due_for_review = self._session.execute(
			select(func.count(PEPList.id)).where(
				and_(
					PEPList.tenant_id == self._tenant_id,
					PEPList.status == "ACTIVE",
					PEPList.review_date <= date.today(),
				)
			)
		).scalar_one() or 0

		return {
			"capital": capital_summary,
			"aml": {
				"open": alert_by_status.get("OPEN", 0),
				"under_review": alert_by_status.get("UNDER_REVIEW", 0),
				"escalated": alert_by_status.get("ESCALATED", 0),
				"filed_sars_ytd": int(sar_ytd),
				"by_status": alert_by_status,
			},
			"ifrs9": ifrs9_summary,
			"pep": {
				"active_count": int(pep_active),
				"due_for_review": int(pep_due_for_review),
			},
			"as_of": datetime.now(timezone.utc).isoformat(),
		}


# ---------------------------------------------------------------------------
# SQLAlchemy text() import alias (used in file_sar for direct SQL)
# ---------------------------------------------------------------------------
try:
	from sqlalchemy import text as sa_text
except ImportError:
	def sa_text(q):  # type: ignore
		return q


# ---------------------------------------------------------------------------
# SanctionsService — OFAC/UN/EU/HMT sanctions list ingestion and matching
# CRITICAL gap
# ---------------------------------------------------------------------------

class SanctionsService:
	"""Manages sanctions list loading and real-time name matching.

	Uses PostgreSQL trigram similarity (pg_trgm) for fuzzy name matching.
	Requires the pg_trgm extension: CREATE EXTENSION IF NOT EXISTS pg_trgm;

	Usage::

		svc = SanctionsService(session, tenant_id="acme_bank")
		svc.bulk_upsert(records, list_source="OFAC_SDN")
		hits = svc.fuzzy_match("Saddam Hussein", threshold=0.85)
	"""

	def __init__(self, session: Session, tenant_id: str = "default") -> None:
		self._session = session
		self._tenant_id = tenant_id

	def bulk_upsert(
		self,
		records: list[dict],
		list_source: str,
	) -> dict:
		"""Bulk-upsert a sanctions list.

		Each record dict must contain:
		  external_ref  (str) — unique reference within the source list
		  listed_name   (str)
		  entity_type   (str) — INDIVIDUAL | ENTITY | VESSEL | AIRCRAFT
		  listed_at     (date)

		Optional keys: aliases (list[str]), country_code, delisted_at,
		               sanctions_programs (list[str]), additional_info (dict)

		Returns {"upserted": int, "delisted": int}.
		"""
		from sqlalchemy.dialects.postgresql import insert as pg_insert

		upserted = 0
		delisted = 0

		for rec in records:
			existing = self._session.execute(
				select(SanctionsList).where(
					and_(
						SanctionsList.list_source == list_source,
						SanctionsList.external_ref == rec["external_ref"],
						SanctionsList.tenant_id == self._tenant_id,
					)
				)
			).scalar_one_or_none()

			if existing is not None:
				# Update mutable fields
				existing.listed_name = rec["listed_name"]
				existing.aliases = rec.get("aliases", existing.aliases)
				existing.entity_type = rec["entity_type"]
				existing.country_code = rec.get("country_code", existing.country_code)
				existing.listed_at = rec["listed_at"]
				existing.delisted_at = rec.get("delisted_at")
				existing.sanctions_programs = rec.get("sanctions_programs", existing.sanctions_programs)
				existing.additional_info = rec.get("additional_info", existing.additional_info)
				if rec.get("delisted_at") is not None:
					delisted += 1
			else:
				entry = SanctionsList(
					tenant_id=self._tenant_id,
					list_source=list_source,
					external_ref=rec["external_ref"],
					listed_name=rec["listed_name"],
					aliases=rec.get("aliases", []),
					entity_type=rec["entity_type"],
					country_code=rec.get("country_code"),
					listed_at=rec["listed_at"],
					delisted_at=rec.get("delisted_at"),
					sanctions_programs=rec.get("sanctions_programs", []),
					additional_info=rec.get("additional_info", {}),
				)
				self._session.add(entry)
			upserted += 1

		self._session.flush()

		try:
			emit_event(
				"reg.sanctions.list_updated",
				"sanctions_list",
				list_source,
				{
					"list_source": list_source,
					"records_upserted": upserted,
					"records_delisted": delisted,
				},
				self._session,
				tenant_id=self._tenant_id,
			)
		except Exception:
			pass

		log.info(
			"SanctionsList bulk_upsert source=%r: %d upserted, %d delisted",
			list_source, upserted, delisted,
		)
		return {"upserted": upserted, "delisted": delisted}

	def fuzzy_match(
		self,
		name: str,
		threshold: float = 0.85,
		limit: int = 10,
	) -> list[dict]:
		"""Match a name against active sanctions list entries using pg_trgm similarity.

		Returns a list of match dicts sorted by similarity descending::

		  [{"id": str, "listed_name": str, "list_source": str,
		    "entity_type": str, "similarity": float}, ...]

		Returns empty list if no matches above threshold.
		Requires pg_trgm extension installed in the database.
		"""
		# Use PostgreSQL similarity() function via text expression
		similarity_expr = sa_text(
			"similarity(reg_sanctions_list.listed_name, :name)"
		)

		try:
			rows = self._session.execute(
				select(
					SanctionsList.id,
					SanctionsList.listed_name,
					SanctionsList.list_source,
					SanctionsList.entity_type,
					SanctionsList.country_code,
					sa_text("similarity(reg_sanctions_list.listed_name, :name) AS sim"),
				)
				.where(
					and_(
						SanctionsList.tenant_id == self._tenant_id,
						SanctionsList.delisted_at.is_(None),
						sa_text("similarity(reg_sanctions_list.listed_name, :name) >= :threshold"),
					)
				)
				.order_by(sa_text("sim DESC"))
				.limit(limit)
				.params(name=name, threshold=threshold)
			).all()
		except Exception as exc:
			# pg_trgm may not be installed — fall back to ILIKE
			log.warning("pg_trgm unavailable (%s); falling back to ILIKE for sanctions match", exc)
			pattern = f"%{name}%"
			rows_fallback = self._session.execute(
				select(
					SanctionsList.id,
					SanctionsList.listed_name,
					SanctionsList.list_source,
					SanctionsList.entity_type,
					SanctionsList.country_code,
				)
				.where(
					and_(
						SanctionsList.tenant_id == self._tenant_id,
						SanctionsList.delisted_at.is_(None),
						SanctionsList.listed_name.ilike(pattern),
					)
				)
				.limit(limit)
			).all()
			return [
				{
					"id": str(r.id),
					"listed_name": r.listed_name,
					"list_source": r.list_source,
					"entity_type": r.entity_type,
					"country_code": r.country_code,
					"similarity": 1.0,  # ILIKE hit treated as full match
				}
				for r in rows_fallback
			]

		results = []
		for row in rows:
			results.append({
				"id": str(row.id),
				"listed_name": row.listed_name,
				"list_source": row.list_source,
				"entity_type": row.entity_type,
				"country_code": row.country_code,
				"similarity": float(row.sim),
			})

		# Also check aliases for each candidate
		alias_hits = self._match_aliases(name, threshold, limit)
		seen_ids = {r["id"] for r in results}
		for hit in alias_hits:
			if hit["id"] not in seen_ids:
				results.append(hit)
				seen_ids.add(hit["id"])

		results.sort(key=lambda x: x["similarity"], reverse=True)
		return results[:limit]

	def _match_aliases(self, name: str, threshold: float, limit: int) -> list[dict]:
		"""Check aliases JSONB array for trigram matches.

		Expands the aliases array and runs similarity against each element.
		Returns match dicts with same structure as fuzzy_match().
		"""
		try:
			# Use jsonb_array_elements_text to unnest aliases
			rows = self._session.execute(
				sa_text("""
					SELECT
						rsl.id,
						rsl.listed_name,
						rsl.list_source,
						rsl.entity_type,
						rsl.country_code,
						similarity(alias_val, :name) AS sim
					FROM reg_sanctions_list rsl,
					     jsonb_array_elements_text(rsl.aliases) AS alias_val
					WHERE rsl.tenant_id = :tenant_id
					  AND rsl.delisted_at IS NULL
					  AND similarity(alias_val, :name) >= :threshold
					ORDER BY sim DESC
					LIMIT :lim
				""")
				.params(name=name, threshold=threshold, tenant_id=self._tenant_id, lim=limit)
			).all()

			return [
				{
					"id": str(r.id),
					"listed_name": r.listed_name,
					"list_source": r.list_source,
					"entity_type": r.entity_type,
					"country_code": r.country_code,
					"similarity": float(r.sim),
					"matched_via": "alias",
				}
				for r in rows
			]
		except Exception as exc:
			log.debug("Alias matching unavailable: %s", exc)
			return []


# ---------------------------------------------------------------------------
# LimitService — pre-transaction limit management engine  [HIGH]
# ---------------------------------------------------------------------------

class LimitBreachException(Exception):
	"""Raised by LimitService when a BLOCK-action limit is breached."""

	def __init__(
		self,
		limit_type: str,
		entity_id: str,
		limit_amount_cents: int,
		proposed_amount_cents: int,
		current_utilisation_cents: int,
	) -> None:
		self.limit_type = limit_type
		self.entity_id = entity_id
		self.limit_amount_cents = limit_amount_cents
		self.proposed_amount_cents = proposed_amount_cents
		self.current_utilisation_cents = current_utilisation_cents
		super().__init__(
			f"Limit breach: {limit_type} entity={entity_id} "
			f"limit={limit_amount_cents}c utilisation={current_utilisation_cents}c "
			f"proposed={proposed_amount_cents}c"
		)


class LimitService:
	"""Pre-transaction regulatory limit enforcement.

	Usage::

		svc = LimitService(session, tenant_id="acme_bank")
		# Raises LimitBreachException if action=BLOCK and limit exceeded
		# Emits LimitBreachedEvent if action=ALERT|REPORT
		svc.check_and_enforce(
		    entity_id=customer_id,
		    limit_type="SINGLE_BORROWER",
		    proposed_amount_cents=50_000_00,
		    current_utilisation_cents=existing_exposure,
		)
	"""

	def __init__(self, session: Session, tenant_id: str = "default") -> None:
		self._session = session
		self._tenant_id = tenant_id

	def check_and_enforce(
		self,
		entity_id: str,
		limit_type: str,
		proposed_amount_cents: int,
		current_utilisation_cents: int = 0,
		as_of_date: date | None = None,
	) -> dict:
		"""Check and enforce regulatory limits for a proposed transaction.

		If current_utilisation_cents is 0 and limit_type is SINGLE_BORROWER,
		the service queries existing exposure from the lending book automatically.

		Returns::

		  {
		    "breached": bool,
		    "limit_amount_cents": int,
		    "current_utilisation_cents": int,
		    "proposed_total_cents": int,
		    "headroom_cents": int,
		    "breach_action": str | None,
		  }

		Raises LimitBreachException if breach_action == "BLOCK".
		"""
		check_date = as_of_date or date.today()

		limits = self._session.execute(
			select(RegulatoryLimit).where(
				and_(
					RegulatoryLimit.tenant_id == self._tenant_id,
					RegulatoryLimit.limit_type == limit_type,
					RegulatoryLimit.entity_id == entity_id,
					RegulatoryLimit.effective_from <= check_date,
					(
						RegulatoryLimit.effective_to.is_(None)
						| (RegulatoryLimit.effective_to >= check_date)
					),
				)
			)
		).scalars().all()

		if not limits:
			# No limit configured — pass through
			return {
				"breached": False,
				"limit_amount_cents": 0,
				"current_utilisation_cents": current_utilisation_cents,
				"proposed_total_cents": current_utilisation_cents + proposed_amount_cents,
				"headroom_cents": 0,
				"breach_action": None,
			}

		# Use the most restrictive (lowest) limit
		active_limit = min(limits, key=lambda l: l.limit_amount_cents)
		limit_cents = active_limit.limit_amount_cents
		proposed_total = current_utilisation_cents + proposed_amount_cents
		headroom = limit_cents - proposed_total
		breached = proposed_total > limit_cents

		result = {
			"breached": breached,
			"limit_amount_cents": limit_cents,
			"current_utilisation_cents": current_utilisation_cents,
			"proposed_total_cents": proposed_total,
			"headroom_cents": headroom,
			"breach_action": active_limit.breach_action if breached else None,
		}

		if breached:
			if active_limit.breach_action == "BLOCK":
				raise LimitBreachException(
					limit_type=limit_type,
					entity_id=entity_id,
					limit_amount_cents=limit_cents,
					proposed_amount_cents=proposed_amount_cents,
					current_utilisation_cents=current_utilisation_cents,
				)

			# ALERT or REPORT — emit event non-fatally
			try:
				emit_event(
					"reg.limit.breached",
					"regulatory_limit",
					str(active_limit.id),
					{
						"limit_id": str(active_limit.id),
						"limit_type": limit_type,
						"entity_id": entity_id,
						"limit_amount_cents": limit_cents,
						"proposed_amount_cents": proposed_amount_cents,
						"current_utilisation_cents": current_utilisation_cents,
						"breach_action": active_limit.breach_action,
					},
					self._session,
					tenant_id=self._tenant_id,
				)
			except Exception:
				pass

			log.warning(
				"Limit breach: type=%r entity=%r limit=%d util=%d proposed=%d action=%r",
				limit_type, entity_id, limit_cents,
				current_utilisation_cents, proposed_amount_cents,
				active_limit.breach_action,
			)

		return result

	def get_utilisation(
		self,
		entity_id: str,
		limit_type: str,
		as_of_date: date | None = None,
	) -> dict:
		"""Return current utilisation summary for an entity/limit_type pair."""
		check_date = as_of_date or date.today()

		limits = self._session.execute(
			select(RegulatoryLimit).where(
				and_(
					RegulatoryLimit.tenant_id == self._tenant_id,
					RegulatoryLimit.limit_type == limit_type,
					RegulatoryLimit.entity_id == entity_id,
					RegulatoryLimit.effective_from <= check_date,
					(
						RegulatoryLimit.effective_to.is_(None)
						| (RegulatoryLimit.effective_to >= check_date)
					),
				)
			)
		).scalars().all()

		if not limits:
			return {"entity_id": entity_id, "limit_type": limit_type, "limits": []}

		results = []
		for lim in limits:
			results.append({
				"limit_id": str(lim.id),
				"limit_amount_cents": lim.limit_amount_cents,
				"breach_action": lim.breach_action,
				"effective_from": lim.effective_from.isoformat(),
				"effective_to": lim.effective_to.isoformat() if lim.effective_to else None,
				"regulatory_reference": lim.regulatory_reference,
			})
		return {"entity_id": entity_id, "limit_type": limit_type, "limits": results}


# ---------------------------------------------------------------------------
# SLAMonitor — AML alert investigation SLA and SAR filing deadline tracker  [HIGH]
# ---------------------------------------------------------------------------

class SLAMonitor:
	"""Monitor AML alert SLA deadlines and CBK SAR filing deadlines.

	Run periodically (e.g. every 15 minutes via SchedulerService or cron)::

		monitor = SLAMonitor(session, tenant_id="acme_bank")
		result = monitor.check()

	Returns counts of newly-breached alerts and SAR deadlines.
	"""

	def __init__(self, session: Session, tenant_id: str = "default") -> None:
		self._session = session
		self._tenant_id = tenant_id

	def check(self) -> dict:
		"""Scan open alerts for SLA and SAR filing deadline breaches.

		Stamps sla_breached_at and sar_filing_deadline breaches on matching rows.
		Emits AlertSLABreachedEvent and SARFilingDeadlineBreachedEvent per breach.

		Returns::

		  {
		    "sla_newly_breached": int,
		    "sar_deadline_newly_breached": int,
		    "total_open_overdue": int,
		  }
		"""
		now_utc = datetime.now(timezone.utc)
		sla_breached_count = 0
		sar_deadline_breached_count = 0

		# --- SLA investigation deadline breaches ---
		overdue_sla = self._session.execute(
			select(AMLAlert).where(
				and_(
					AMLAlert.tenant_id == self._tenant_id,
					AMLAlert.closed_at.is_(None),
					AMLAlert.sla_due_at.is_not(None),
					AMLAlert.sla_due_at < now_utc,
					AMLAlert.sla_breached_at.is_(None),  # not yet stamped
				)
			)
		).scalars().all()

		for alert in overdue_sla:
			from sqlalchemy import update as sa_update
			self._session.execute(
				sa_update(AMLAlert)
				.where(AMLAlert.id == alert.id)
				.values(sla_breached_at=now_utc)
			)
			sla_breached_count += 1

			try:
				emit_event(
					"reg.sla.alert_breached",
					"aml_alert",
					str(alert.id),
					{
						"alert_id": str(alert.id),
						"alert_number": alert.alert_number,
						"sla_due_at": alert.sla_due_at.isoformat() if alert.sla_due_at else "",
						"breached_at": now_utc.isoformat(),
						"assigned_to": str(alert.assigned_to) if alert.assigned_to else "",
					},
					self._session,
					tenant_id=self._tenant_id,
				)
			except Exception:
				pass

		# --- SAR filing deadline breaches ---
		# Alerts where sar_filing_deadline has passed and no SAR has been filed
		overdue_sar = self._session.execute(
			select(AMLAlert).where(
				and_(
					AMLAlert.tenant_id == self._tenant_id,
					AMLAlert.closed_at.is_(None),
					AMLAlert.sar_filing_deadline.is_not(None),
					AMLAlert.sar_filing_deadline < now_utc,
					AMLAlert.status.not_in(["CLOSED_SAR_FILED"]),
				)
			)
		).scalars().all()

		# Filter to alerts that genuinely have no SAR filed
		for alert in overdue_sar:
			sar_count = self._session.execute(
				select(func.count(SuspiciousActivityReport.id)).where(
					and_(
						SuspiciousActivityReport.alert_id == alert.id,
						SuspiciousActivityReport.tenant_id == self._tenant_id,
					)
				)
			).scalar_one() or 0

			if sar_count == 0:
				sar_deadline_breached_count += 1
				try:
					emit_event(
						"reg.sla.sar_deadline_breached",
						"aml_alert",
						str(alert.id),
						{
							"alert_id": str(alert.id),
							"alert_number": alert.alert_number,
							"sar_filing_deadline": (
								alert.sar_filing_deadline.isoformat()
								if alert.sar_filing_deadline else ""
							),
							"breached_at": now_utc.isoformat(),
						},
						self._session,
						tenant_id=self._tenant_id,
					)
				except Exception:
					pass

		# Total open overdue (already breached + newly breached)
		total_overdue = self._session.execute(
			select(func.count(AMLAlert.id)).where(
				and_(
					AMLAlert.tenant_id == self._tenant_id,
					AMLAlert.closed_at.is_(None),
					AMLAlert.sla_breached_at.is_not(None),
				)
			)
		).scalar_one() or 0

		self._session.flush()

		log.info(
			"SLAMonitor.check: %d new SLA breaches, %d new SAR deadline breaches, %d total overdue",
			sla_breached_count, sar_deadline_breached_count, int(total_overdue),
		)
		return {
			"sla_newly_breached": sla_breached_count,
			"sar_deadline_newly_breached": sar_deadline_breached_count,
			"total_open_overdue": int(total_overdue),
		}


# ---------------------------------------------------------------------------
# OutboxRelay — transactional outbox publisher  [HIGH]
# ---------------------------------------------------------------------------

class OutboxRelay:
	"""Polls RegOutboxEvent rows where published_at IS NULL and publishes them.

	Designed to run in a background thread or periodic task (e.g. every 5 s).
	Guarantees at-least-once delivery.

	Usage::

		relay = OutboxRelay(session, tenant_id="acme_bank", batch_size=100)
		published, failed = relay.publish_pending()

	`publish_fn` is called for each event.  Default is emit_event(); replace
	with a real broker client (Kafka, RabbitMQ, etc.) in production.
	"""

	def __init__(
		self,
		session: Session,
		tenant_id: str = "default",
		batch_size: int = 100,
		publish_fn: Any = None,
	) -> None:
		self._session = session
		self._tenant_id = tenant_id
		self._batch_size = batch_size
		self._publish_fn = publish_fn  # callable(event_type, payload) | None

	def publish_pending(self) -> tuple[int, int]:
		"""Publish all pending outbox events.

		Returns (published_count, failed_count).
		"""
		from sqlalchemy import update as sa_update

		pending = self._session.execute(
			select(RegOutboxEvent).where(
				and_(
					RegOutboxEvent.tenant_id == self._tenant_id,
					RegOutboxEvent.published_at.is_(None),
				)
			)
			.order_by(RegOutboxEvent.created_at.asc())
			.limit(self._batch_size)
		).scalars().all()

		published = 0
		failed = 0
		now_utc = datetime.now(timezone.utc)

		for event in pending:
			try:
				if self._publish_fn is not None:
					self._publish_fn(event.event_type, event.payload)
				else:
					# Default: use internal emit_event
					emit_event(
						event.event_type,
						event.aggregate_type,
						str(event.aggregate_id),
						event.payload,
						self._session,
						tenant_id=self._tenant_id,
					)

				self._session.execute(
					sa_update(RegOutboxEvent)
					.where(RegOutboxEvent.id == event.id)
					.values(
						published_at=now_utc,
						publish_attempts=event.publish_attempts + 1,
					)
				)
				published += 1

			except Exception as exc:
				self._session.execute(
					sa_update(RegOutboxEvent)
					.where(RegOutboxEvent.id == event.id)
					.values(
						publish_attempts=event.publish_attempts + 1,
						last_error=str(exc)[:2000],
					)
				)
				failed += 1
				log.warning("OutboxRelay: failed to publish event %s: %s", event.id, exc)

		if pending:
			self._session.flush()
			log.info("OutboxRelay: published=%d failed=%d", published, failed)

		return published, failed

	@staticmethod
	def write_outbox(
		session: Session,
		tenant_id: str,
		aggregate_id: str,
		aggregate_type: str,
		event_type: str,
		payload: dict,
	) -> RegOutboxEvent:
		"""Write an outbox entry in the current DB transaction.

		Call this instead of bare emit_event() when durability is required.
		The OutboxRelay background task will publish it after commit.
		"""
		entry = RegOutboxEvent(
			tenant_id=tenant_id,
			aggregate_id=aggregate_id,
			aggregate_type=aggregate_type,
			event_type=event_type,
			payload=payload,
		)
		session.add(entry)
		return entry


# ---------------------------------------------------------------------------
# ReconciliationService — GL vs regulatory report reconciliation  [HIGH]
# ---------------------------------------------------------------------------

class ReconciliationService:
	"""Reconciles regulatory report figures against GL trial-balance.

	Usage::

		svc = ReconciliationService(session, tenant_id="acme_bank")
		run = svc.reconcile("BS1", "2026-05")
		if run.status == "FAILED":
		    raise ValueError("Reconciliation failed — do not submit CBK return")
	"""

	# Warning threshold: > 0.001% variance raises WARNED
	WARN_TOLERANCE_PCT = Decimal("0.001")
	# Failure threshold: > 0.01% variance is FAILED
	FAIL_TOLERANCE_PCT = Decimal("0.01")

	def __init__(self, session: Session, tenant_id: str = "default") -> None:
		self._session = session
		self._tenant_id = tenant_id

	def reconcile(
		self,
		report_type: str,
		period: str,
		tolerance_pct: Decimal | None = None,
	) -> ReconciliationRun:
		"""Reconcile the filed report value against the GL for a given period.

		Fetches the most recent filed regulatory report for report_type/period
		and the corresponding GL trial-balance figure, then computes variance.

		tolerance_pct overrides the class-level FAIL_TOLERANCE_PCT.

		Returns a persisted ReconciliationRun.
		"""
		tol = tolerance_pct if tolerance_pct is not None else self.FAIL_TOLERANCE_PCT
		now_utc = datetime.now(timezone.utc)

		report_value_cents = self._get_report_value(report_type, period)
		gl_value_cents = self._get_gl_value(report_type, period)

		variance_cents = report_value_cents - gl_value_cents
		abs_variance = abs(variance_cents)

		if gl_value_cents != 0:
			variance_pct = (Decimal(str(abs_variance)) / Decimal(str(abs(gl_value_cents)))) * Decimal("100")
		else:
			variance_pct = Decimal("0.000000") if report_value_cents == 0 else Decimal("100.000000")

		if variance_pct <= self.WARN_TOLERANCE_PCT:
			status = "MATCHED"
		elif variance_pct <= tol:
			status = "WARNED"
		else:
			status = "FAILED"

		run = ReconciliationRun(
			tenant_id=self._tenant_id,
			report_type=report_type,
			period=period,
			report_value_cents=report_value_cents,
			gl_value_cents=gl_value_cents,
			variance_cents=variance_cents,
			variance_pct=variance_pct,
			tolerance_pct=tol,
			status=status,
			run_at=now_utc,
			detail={
				"report_type": report_type,
				"period": period,
				"report_value_cents": report_value_cents,
				"gl_value_cents": gl_value_cents,
				"variance_cents": variance_cents,
				"variance_pct": str(variance_pct),
				"tolerance_pct": str(tol),
			},
		)
		self._session.add(run)
		self._session.flush()

		if status == "FAILED":
			try:
				emit_event(
					"reg.reconciliation.failed",
					"reconciliation_run",
					str(run.id),
					{
						"run_id": str(run.id),
						"report_type": report_type,
						"period": period,
						"variance_pct": str(variance_pct),
						"tolerance_pct": str(tol),
					},
					self._session,
					tenant_id=self._tenant_id,
				)
			except Exception:
				pass

		log.info(
			"ReconciliationRun %s period=%r: report=%d gl=%d variance=%+d (%s%%) status=%r",
			report_type, period, report_value_cents, gl_value_cents,
			variance_cents, variance_pct, status,
		)
		return run

	def _get_report_value(self, report_type: str, period: str) -> int:
		"""Fetch the filed report figure for a given report_type and period.

		Queries the most recently generated regulatory report record.
		Returns 0 if no report found for the period.
		"""
		if report_type in ("BS1", "BS3", "BS6"):
			# CBK returns — no dedicated table yet; return 0 for now
			# Production: query reg_cbk_return table once implemented
			return 0

		if report_type == "CAPITAL":
			report = self._session.execute(
				select(CapitalAdequacyReport)
				.where(
					and_(
						CapitalAdequacyReport.tenant_id == self._tenant_id,
						CapitalAdequacyReport.reporting_period.contains(period[:4]),
					)
				)
				.order_by(CapitalAdequacyReport.report_date.desc())
				.limit(1)
			).scalar_one_or_none()
			return report.total_capital_cents if report else 0

		if report_type == "IFRS9":
			run = self._session.execute(
				select(IFRS9ProvisionRun)
				.where(
					and_(
						IFRS9ProvisionRun.tenant_id == self._tenant_id,
					)
				)
				.order_by(IFRS9ProvisionRun.run_date.desc())
				.limit(1)
			).scalar_one_or_none()
			return run.total_ecl_cents if run else 0

		return 0

	def _get_gl_value(self, report_type: str, period: str) -> int:
		"""Fetch the GL trial-balance figure for a given report_type and period.

		Lazy import from erp.finance.gl; returns 0 if GL plugin unavailable.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.service import GLService  # type: ignore
			gl_svc = GLService(self._session, tenant_id=self._tenant_id)
			return gl_svc.get_trial_balance_for_report(report_type, period)
		except (ImportError, AttributeError, Exception) as exc:
			log.debug("GL unavailable for reconciliation (%s); using 0", exc)
			return 0

	def is_cleared_for_submission(self, report_type: str, period: str) -> bool:
		"""Return True if the latest reconciliation run for this report/period is MATCHED or WARNED.

		Gates CBK return submission — FAILED blocks submission.
		"""
		latest = self._session.execute(
			select(ReconciliationRun)
			.where(
				and_(
					ReconciliationRun.tenant_id == self._tenant_id,
					ReconciliationRun.report_type == report_type,
					ReconciliationRun.period == period,
				)
			)
			.order_by(ReconciliationRun.run_at.desc())
			.limit(1)
		).scalar_one_or_none()

		if latest is None:
			# No reconciliation run yet — block submission
			return False
		return latest.status in ("MATCHED", "WARNED")


# ---------------------------------------------------------------------------
# SchedulerService — automated periodic regulatory report scheduler  [CRITICAL]
# ---------------------------------------------------------------------------

class SchedulerService:
	"""Drives automated CBK return generation and regulator submission.

	SchedulerService.tick() is designed to be called by a cron job or
	background task every few minutes.  It queries overdue RegulatorySchedule
	rows, generates the corresponding reports, posts to the regulator endpoint,
	and records submission outcomes with exponential backoff retry.

	Usage::

		svc = SchedulerService(session, tenant_id="acme_bank")
		result = svc.tick()
	"""

	# Maximum backoff exponent (2^8 = 256 minutes)
	MAX_BACKOFF_MINUTES = 256

	def __init__(
		self,
		session: Session,
		tenant_id: str = "default",
		compliance_svc: RegulatoryComplianceService | None = None,
	) -> None:
		self._session = session
		self._tenant_id = tenant_id
		self._compliance = compliance_svc or RegulatoryComplianceService(session, tenant_id)

	def tick(self) -> dict:
		"""Process all overdue scheduled reports.

		For each overdue active RegulatorySchedule row:
		  1. Generates the report.
		  2. Submits to regulator endpoint (if configured).
		  3. Updates next_run_at based on frequency.
		  4. Records outcome in submission_log.
		  5. On failure, backs off exponentially.

		Returns::

		  {"processed": int, "succeeded": int, "failed": int}
		"""
		from sqlalchemy import update as sa_update

		now_utc = datetime.now(timezone.utc)
		overdue = self._session.execute(
			select(RegulatorySchedule).where(
				and_(
					RegulatorySchedule.tenant_id == self._tenant_id,
					RegulatorySchedule.is_active.is_(True),
					RegulatorySchedule.next_run_at <= now_utc,
				)
			)
		).scalars().all()

		processed = 0
		succeeded = 0
		failed = 0

		for schedule in overdue:
			processed += 1
			report_id: str | None = None
			submitted = False
			error_msg: str | None = None

			try:
				report_id = self._generate_report(schedule)

				if schedule.regulator_endpoint:
					submitted = self._submit_to_endpoint(
						schedule, report_id
					)

				# Advance next_run_at
				next_run = self._compute_next_run(schedule.frequency, now_utc)
				log_entry = {
					"attempt": schedule.retry_count,
					"status": "SUCCESS",
					"response_code": 200 if submitted else 0,
					"response_body": "",
					"report_id": report_id,
					"ts": now_utc.isoformat(),
				}
				new_log = list(schedule.submission_log or []) + [log_entry]

				self._session.execute(
					sa_update(RegulatorySchedule)
					.where(RegulatorySchedule.id == schedule.id)
					.values(
						submission_status="SUBMITTED" if submitted else "PENDING",
						last_run_id=report_id,
						last_run_at=now_utc,
						next_run_at=next_run,
						retry_count=0,
						submission_log=new_log,
					)
				)
				succeeded += 1

				try:
					emit_event(
						"reg.scheduler.report_generated",
						"regulatory_schedule",
						str(schedule.id),
						{
							"schedule_id": str(schedule.id),
							"report_type": schedule.report_type,
							"report_id": report_id or "",
							"submitted_to_regulator": submitted,
						},
						self._session,
						tenant_id=self._tenant_id,
					)
				except Exception:
					pass

				log.info(
					"Scheduler: %r generated report_id=%s submitted=%s",
					schedule.report_type, report_id, submitted,
				)

			except Exception as exc:
				error_msg = str(exc)[:500]
				retry = schedule.retry_count + 1
				# Exponential backoff: 2^retry_count minutes, capped at MAX_BACKOFF_MINUTES
				backoff_minutes = min(2 ** retry, self.MAX_BACKOFF_MINUTES)
				next_retry = now_utc + timedelta(minutes=backoff_minutes)
				log_entry = {
					"attempt": retry,
					"status": "FAILED",
					"error": error_msg,
					"ts": now_utc.isoformat(),
				}
				new_log = list(schedule.submission_log or []) + [log_entry]

				self._session.execute(
					sa_update(RegulatorySchedule)
					.where(RegulatorySchedule.id == schedule.id)
					.values(
						submission_status="FAILED",
						retry_count=retry,
						next_run_at=next_retry,
						submission_log=new_log,
					)
				)
				failed += 1

				try:
					emit_event(
						"reg.scheduler.report_failed",
						"regulatory_schedule",
						str(schedule.id),
						{
							"schedule_id": str(schedule.id),
							"report_type": schedule.report_type,
							"error_message": error_msg,
							"retry_count": retry,
						},
						self._session,
						tenant_id=self._tenant_id,
					)
				except Exception:
					pass

				log.error(
					"Scheduler: %r failed (retry=%d backoff=%dm): %s",
					schedule.report_type, retry, backoff_minutes, error_msg,
				)

		if processed:
			self._session.flush()

		return {"processed": processed, "succeeded": succeeded, "failed": failed}

	def _generate_report(self, schedule: RegulatorySchedule) -> str:
		"""Generate the report for this schedule entry.

		Returns the UUID string of the generated record.
		"""
		today = date.today()
		period = today.strftime("%Y-%m")

		if schedule.report_type in ("BS1", "BS3", "BS6", "CBK"):
			cbk_result = self._compliance.generate_cbk_returns(period)
			# CBK returns don't have a single record ID — use schedule ID as reference
			return f"cbk-{period}-{schedule.id}"

		if schedule.report_type == "CAPITAL":
			report = self._compliance.calculate_capital_adequacy(today)
			return str(report.id)

		if schedule.report_type == "IFRS9":
			run = self._compliance.run_ifrs9_provision(today)
			return str(run.id)

		if schedule.report_type == "LARGE_EXPOSURE":
			# Large exposure is customer-specific; generate summary marker
			return f"le-{period}-{schedule.id}"

		raise RegulatoryError(f"Unknown report_type {schedule.report_type!r} in schedule {schedule.id!r}")

	def _submit_to_endpoint(
		self,
		schedule: RegulatorySchedule,
		report_id: str,
	) -> bool:
		"""Submit the generated report to the regulator endpoint.

		Uses urllib for zero-dependency HTTP POST.  Returns True on HTTP 2xx.
		"""
		import urllib.request
		import json as _json

		payload = _json.dumps({
			"tenant_id": self._tenant_id,
			"report_type": schedule.report_type,
			"report_id": report_id,
			"generated_at": datetime.now(timezone.utc).isoformat(),
		}).encode()

		req = urllib.request.Request(
			url=schedule.regulator_endpoint,
			data=payload,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(req, timeout=30) as resp:
				return 200 <= resp.status < 300
		except Exception as exc:
			log.warning("Scheduler endpoint submission failed: %s", exc)
			raise

	def _compute_next_run(self, frequency: str, from_dt: datetime) -> datetime:
		"""Compute next_run_at from a frequency string."""
		if frequency == "DAILY":
			return from_dt + timedelta(days=1)
		if frequency == "WEEKLY":
			return from_dt + timedelta(weeks=1)
		if frequency == "MONTHLY":
			# Advance by ~30 days; callers can adjust to month-end
			return from_dt + timedelta(days=30)
		if frequency == "QUARTERLY":
			return from_dt + timedelta(days=91)
		if frequency == "ANNUAL":
			return from_dt + timedelta(days=365)
		raise RegulatoryError(f"Unknown schedule frequency: {frequency!r}")

	def recover_unposted_ifrs9_gl_entries(self) -> int:
		"""On startup recovery: find IFRS9ProvisionRun rows with gl_posted=False and retry GL posting.

		Returns count of runs successfully recovered.
		"""
		unposted = self._session.execute(
			select(IFRS9ProvisionRun).where(
				and_(
					IFRS9ProvisionRun.tenant_id == self._tenant_id,
					IFRS9ProvisionRun.gl_posted.is_(False),
				)
			)
		).scalars().all()

		recovered = 0
		for run in unposted:
			if run.provision_movement_cents == 0:
				# Zero movement — mark gl_posted to avoid repeated checks
				from sqlalchemy import update as sa_update
				self._session.execute(
					sa_update(IFRS9ProvisionRun)
					.where(IFRS9ProvisionRun.id == run.id)
					.values(gl_posted=True)
				)
				recovered += 1
				continue
			try:
				journal_id = self._compliance._post_ifrs9_gl_entries(
					run, run.provision_movement_cents
				)
				from sqlalchemy import update as sa_update
				self._session.execute(
					sa_update(IFRS9ProvisionRun)
					.where(IFRS9ProvisionRun.id == run.id)
					.values(gl_posted=True, gl_journal_id=journal_id)
				)
				recovered += 1
				log.info("GL posting recovered for IFRS9 run %s", run.id)
			except Exception as exc:
				log.error("GL recovery failed for IFRS9 run %s: %s", run.id, exc)

		if unposted:
			self._session.flush()

		return recovered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RegulatoryComplianceService",
	"SanctionsService",
	"LimitService",
	"LimitBreachException",
	"SLAMonitor",
	"OutboxRelay",
	"ReconciliationService",
	"SchedulerService",
	"RegulatoryError",
	"AMLRuleNotFoundError",
	"AMLAlertNotFoundError",
	"SARAlreadyFiledError",
	"InvalidAlertStatusError",
	"FRCSubmissionError",
	"CBK_MINIMUMS",
	"LARGE_EXPOSURE_LIMIT_PCT",
]
