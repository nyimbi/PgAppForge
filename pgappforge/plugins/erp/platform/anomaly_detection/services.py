from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	AnomalyBatchRunCompletedEvent,
	AnomalyResolvedEvent,
	APDuplicateDetectedEvent,
	GLAnomalyDetectedEvent,
	LargeTransactionFlaggedEvent,
	WeekendJournalFlaggedEvent,
)
from .models import Anomaly, AnomalyDetectionRun

__all__ = [
	"AnomalyDetectionService",
	"AnomalyDetectionServiceError",
	"AnomalyNotFoundError",
	"InvalidAnomalyResolutionError",
]

log = logging.getLogger(__name__)

_VALID_RESOLVE_STATUSES = {"RESOLVED", "FALSE_POSITIVE"}
_WEEKEND_DAYS = {5, 6}  # Saturday=5, Sunday=6


class AnomalyDetectionServiceError(Exception):
	"""Base error for anomaly detection service violations."""


class InvalidAnomalyResolutionError(AnomalyDetectionServiceError):
	"""Anomaly resolution input is invalid."""


class AnomalyNotFoundError(AnomalyDetectionServiceError):
	"""No anomaly exists for the requested id."""


def _emit(event: Any, session: Session | None = None) -> None:
	try:
		_emit_event(event, session)
	except Exception:
		log.debug("Event emission skipped: %s", type(event).__name__, exc_info=True)


def _decimal(value: Any) -> Decimal:
	try:
		return Decimal(str(value))
	except (InvalidOperation, TypeError):
		return Decimal("0")


def _mean(values: list[Decimal]) -> Decimal:
	if not values:
		return Decimal("0")
	return sum(values, Decimal("0")) / Decimal(len(values))


def _std_dev(values: list[Decimal], mean: Decimal) -> Decimal:
	if len(values) < 2:
		return Decimal("0")
	variance = sum((v - mean) ** 2 for v in values) / Decimal(len(values))
	return variance.sqrt()


def _new_run_id() -> str:
	return str(uuid.uuid4())


def _new_anomaly_id() -> str:
	return str(uuid.uuid4())


class AnomalyDetectionService:
	"""Statistical and rule-based anomaly detection across GL and AP modules."""

	@BPMActionRegistry.register(
		"platform.anomaly.run_gl_detection",
		"Run GL statistical anomaly detection",
	)
	def run_gl_statistical_detection(
		self,
		tenant_id: str,
		session: Session,
		*,
		period: str | None = None,
		z_score_threshold: Decimal = Decimal("3.0"),
	) -> AnomalyDetectionRun:
		run = AnomalyDetectionRun(
			id=_new_run_id(),
			run_type="GL_STATISTICAL",
			period=period,
			status="COMPLETED",
			anomalies_found=0,
			tenant_id=tenant_id,
		)
		session.add(run)
		session.flush()

		try:
			from pgappforge.plugins.erp.finance.gl.models import JournalEntry
		except ImportError:
			log.debug("GL JournalEntry model unavailable; skipping GL detection")
			_emit(
				AnomalyBatchRunCompletedEvent(
					run_id=run.id,
					tenant_id=tenant_id,
					anomalies_found=0,
				),
				session,
			)
			return run

		stmt = select(JournalEntry).where(JournalEntry.tenant_id == tenant_id)
		if period:
			stmt = stmt.where(JournalEntry.period == period)
		entries = list(session.execute(stmt).scalars())

		# Group amounts by account
		by_account: dict[str, list[tuple[Any, Decimal]]] = {}
		for entry in entries:
			acct = str(getattr(entry, "account_id", "") or "")
			amt = _decimal(getattr(entry, "amount_cents", 0))
			by_account.setdefault(acct, []).append((entry, amt))

		anomalies: list[Anomaly] = []

		for acct, pairs in by_account.items():
			if len(pairs) < 5:
				continue
			amounts = [p[1] for p in pairs]
			mean = _mean(amounts)
			std = _std_dev(amounts, mean)
			if std == Decimal("0"):
				continue

			for entry, amt in pairs:
				z = abs(amt - mean) / std
				if z > z_score_threshold:
					severity = "CRITICAL" if z > Decimal("5") else "HIGH"
					anomaly_id = _new_anomaly_id()
					a = Anomaly(
						id=anomaly_id,
						run_id=run.id,
						anomaly_type="GL_OUTLIER",
						severity=severity,
						source_module="GL",
						source_record_id=str(entry.id),
						description=(
							f"GL entry amount {amt} on account {acct} is a statistical "
							f"outlier (z={z:.2f}, mean={mean:.2f}, std={std:.2f})"
						),
						evidence={
							"account_id": acct,
							"amount_cents": int(amt),
							"mean_cents": str(mean),
							"std_dev_cents": str(std),
							"z_score": str(z),
						},
						status="OPEN",
						tenant_id=tenant_id,
					)
					session.add(a)
					anomalies.append(a)
					_emit(
						GLAnomalyDetectedEvent(
							anomaly_id=anomaly_id,
							journal_id=str(entry.id),
							anomaly_type="GL_OUTLIER",
							severity=severity,
							tenant_id=tenant_id,
						),
						session,
					)

		# Weekend postings
		for entry in entries:
			posted_at = getattr(entry, "posted_at", None) or getattr(
				entry, "created_at", None
			)
			if posted_at is None:
				continue
			if hasattr(posted_at, "weekday") and posted_at.weekday() in _WEEKEND_DAYS:
				amount_cents = int(
					_decimal(getattr(entry, "amount_cents", 0))
				)
				anomaly_id = _new_anomaly_id()
				a = Anomaly(
					id=anomaly_id,
					run_id=run.id,
					anomaly_type="WEEKEND_POSTING",
					severity="MEDIUM",
					source_module="GL",
					source_record_id=str(entry.id),
					description=(
						f"GL journal entry posted on a weekend ({posted_at.strftime('%A %Y-%m-%d')})"
					),
					evidence={
						"posted_at": posted_at.isoformat(),
						"weekday": posted_at.weekday(),
						"amount_cents": amount_cents,
					},
					status="OPEN",
					tenant_id=tenant_id,
				)
				session.add(a)
				anomalies.append(a)
				_emit(
					WeekendJournalFlaggedEvent(
						journal_id=str(entry.id),
						posted_at=posted_at.isoformat(),
						amount_cents=amount_cents,
					),
					session,
				)

		# Round numbers
		for entry in entries:
			amt_cents = int(_decimal(getattr(entry, "amount_cents", 0)))
			if amt_cents > 1_000_000 and amt_cents % 100_000 == 0:
				anomaly_id = _new_anomaly_id()
				a = Anomaly(
					id=anomaly_id,
					run_id=run.id,
					anomaly_type="ROUND_NUMBER",
					severity="LOW",
					source_module="GL",
					source_record_id=str(entry.id),
					description=(
						f"GL entry has a suspiciously round amount: {amt_cents} cents"
					),
					evidence={"amount_cents": amt_cents},
					status="OPEN",
					tenant_id=tenant_id,
				)
				session.add(a)
				anomalies.append(a)

		run.anomalies_found = len(anomalies)
		session.flush()

		_emit(
			AnomalyBatchRunCompletedEvent(
				run_id=run.id,
				tenant_id=tenant_id,
				anomalies_found=len(anomalies),
			),
			session,
		)
		return run

	@BPMActionRegistry.register(
		"platform.anomaly.run_ap_duplicate",
		"Run AP duplicate invoice detection",
	)
	def run_ap_duplicate_detection(
		self,
		tenant_id: str,
		session: Session,
	) -> AnomalyDetectionRun:
		run = AnomalyDetectionRun(
			id=_new_run_id(),
			run_type="AP_DUPLICATE",
			status="COMPLETED",
			anomalies_found=0,
			tenant_id=tenant_id,
		)
		session.add(run)
		session.flush()

		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
		except ImportError:
			log.debug("AP Invoice model unavailable; skipping AP duplicate detection")
			_emit(
				AnomalyBatchRunCompletedEvent(
					run_id=run.id,
					tenant_id=tenant_id,
					anomalies_found=0,
				),
				session,
			)
			return run

		stmt = select(APInvoice).where(APInvoice.tenant_id == tenant_id)
		invoices = list(session.execute(stmt).scalars())

		anomalies: list[Anomaly] = []
		seen_pairs: set[frozenset[str]] = set()

		for i, inv_a in enumerate(invoices):
			for inv_b in invoices[i + 1 :]:
				pair_key = frozenset({str(inv_a.id), str(inv_b.id)})
				if pair_key in seen_pairs:
					continue
				if str(inv_a.vendor_id) != str(inv_b.vendor_id):
					continue

				amt_a = _decimal(getattr(inv_a, "total_cents", 0))
				amt_b = _decimal(getattr(inv_b, "total_cents", 0))
				if amt_a != amt_b:
					continue

				date_a = getattr(inv_a, "invoice_date", None)
				date_b = getattr(inv_b, "invoice_date", None)
				within_30_days = False
				if date_a and date_b:
					delta = abs((date_a - date_b).days) if hasattr(date_a, "days") else abs(
						(date_a - date_b).days
					)
					within_30_days = delta <= 30

				if not within_30_days:
					continue

				seen_pairs.add(pair_key)

				num_a = str(getattr(inv_a, "invoice_number", "") or "")
				num_b = str(getattr(inv_b, "invoice_number", "") or "")
				exact_number_match = bool(num_a and num_b and num_a == num_b)
				severity = "CRITICAL" if exact_number_match else "HIGH"

				anomaly_id = _new_anomaly_id()
				a = Anomaly(
					id=anomaly_id,
					run_id=run.id,
					anomaly_type="AP_DUPLICATE",
					severity=severity,
					source_module="AP",
					source_record_id=str(inv_a.id),
					description=(
						f"Possible duplicate AP invoice: {inv_a.id} and {inv_b.id} "
						f"share vendor {inv_a.vendor_id}, amount {amt_a} cents"
						+ (f", invoice_number={num_a}" if exact_number_match else "")
					),
					evidence={
						"invoice_a_id": str(inv_a.id),
						"invoice_b_id": str(inv_b.id),
						"vendor_id": str(inv_a.vendor_id),
						"total_cents": int(amt_a),
						"invoice_number_a": num_a,
						"invoice_number_b": num_b,
						"exact_number_match": exact_number_match,
					},
					status="OPEN",
					tenant_id=tenant_id,
				)
				session.add(a)
				anomalies.append(a)
				_emit(
					APDuplicateDetectedEvent(
						anomaly_id=anomaly_id,
						invoice_id=str(inv_a.id),
						duplicate_invoice_id=str(inv_b.id),
						vendor_id=str(inv_a.vendor_id),
					),
					session,
				)

		run.anomalies_found = len(anomalies)
		session.flush()
		_emit(
			AnomalyBatchRunCompletedEvent(
				run_id=run.id,
				tenant_id=tenant_id,
				anomalies_found=len(anomalies),
			),
			session,
		)
		return run

	def run_large_transaction_detection(
		self,
		tenant_id: str,
		session: Session,
		*,
		percentile_threshold: Decimal = Decimal("99"),
	) -> AnomalyDetectionRun:
		from datetime import timedelta

		run = AnomalyDetectionRun(
			id=_new_run_id(),
			run_type="LARGE_TRANSACTION",
			status="COMPLETED",
			anomalies_found=0,
			tenant_id=tenant_id,
		)
		session.add(run)
		session.flush()

		try:
			from pgappforge.plugins.erp.finance.gl.models import JournalEntry
		except ImportError:
			log.debug("GL JournalEntry model unavailable; skipping large transaction detection")
			_emit(
				AnomalyBatchRunCompletedEvent(
					run_id=run.id,
					tenant_id=tenant_id,
					anomalies_found=0,
				),
				session,
			)
			return run

		cutoff = datetime.now(tz=timezone.utc) - timedelta(days=90)
		stmt = (
			select(JournalEntry)
			.where(JournalEntry.tenant_id == tenant_id)
			.where(JournalEntry.created_at >= cutoff)
		)
		entries = list(session.execute(stmt).scalars())

		if len(entries) < 2:
			run.anomalies_found = 0
			session.flush()
			return run

		amounts = [_decimal(getattr(e, "amount_cents", 0)) for e in entries]
		mean = _mean(amounts)
		std = _std_dev(amounts, mean)
		threshold = mean + Decimal("3") * std

		anomalies: list[Anomaly] = []
		for entry, amt in zip(entries, amounts):
			if amt > threshold and std > Decimal("0"):
				z = (amt - mean) / std
				anomaly_id = _new_anomaly_id()
				a = Anomaly(
					id=anomaly_id,
					run_id=run.id,
					anomaly_type="THRESHOLD_BREACH",
					severity="HIGH",
					source_module="GL",
					source_record_id=str(entry.id),
					description=(
						f"Large transaction detected: {int(amt)} cents exceeds "
						f"mean+3σ threshold of {int(threshold)} cents (z={z:.2f})"
					),
					evidence={
						"amount_cents": int(amt),
						"threshold_cents": int(threshold),
						"mean_cents": str(mean),
						"std_dev_cents": str(std),
						"z_score": str(z),
					},
					status="OPEN",
					tenant_id=tenant_id,
				)
				session.add(a)
				anomalies.append(a)
				_emit(
					LargeTransactionFlaggedEvent(
						journal_id=str(entry.id),
						amount_cents=int(amt),
						z_score=str(z),
					),
					session,
				)

		run.anomalies_found = len(anomalies)
		session.flush()
		_emit(
			AnomalyBatchRunCompletedEvent(
				run_id=run.id,
				tenant_id=tenant_id,
				anomalies_found=len(anomalies),
			),
			session,
		)
		return run

	def resolve_anomaly(
		self,
		anomaly_id: str,
		resolved_by: str,
		resolution: str,
		status: str,
		session: Session,
	) -> Anomaly:
		anomaly_id = self._require_text(anomaly_id, "anomaly_id", max_length=36)
		resolved_by = self._require_text(resolved_by, "resolved_by", max_length=50)
		resolution = self._require_text(resolution, "resolution", max_length=5000)
		status = self._normalize_resolution_status(status)

		stmt = select(Anomaly).where(Anomaly.id == anomaly_id)
		anomaly = session.execute(stmt).scalar_one_or_none()
		if anomaly is None:
			raise AnomalyNotFoundError(f"Anomaly {anomaly_id!r} not found")
		if getattr(anomaly, "status", "OPEN") not in {"OPEN", status}:
			raise InvalidAnomalyResolutionError(
				f"Anomaly {anomaly_id!r} is already {anomaly.status!r}"
			)

		anomaly.status = status
		anomaly.resolved_by = resolved_by
		anomaly.resolved_at = datetime.now(tz=timezone.utc)
		anomaly.resolution = resolution
		session.flush()

		_emit(
			AnomalyResolvedEvent(
				anomaly_id=anomaly_id,
				resolved_by=resolved_by,
				resolution=resolution,
			),
			session,
		)
		return anomaly

	@staticmethod
	def _require_text(value: str, field_name: str, max_length: int) -> str:
		if not isinstance(value, str):
			raise InvalidAnomalyResolutionError(f"{field_name} must be a string")
		text = value.strip()
		if not text:
			raise InvalidAnomalyResolutionError(f"{field_name} is required")
		if len(text) > max_length:
			raise InvalidAnomalyResolutionError(
				f"{field_name} must be at most {max_length} characters"
			)
		return text

	@staticmethod
	def _normalize_resolution_status(value: str) -> str:
		if not isinstance(value, str):
			raise InvalidAnomalyResolutionError("status must be a string")
		status = value.strip().upper()
		if status not in _VALID_RESOLVE_STATUSES:
			allowed = ", ".join(sorted(_VALID_RESOLVE_STATUSES))
			raise InvalidAnomalyResolutionError(
				f"Invalid anomaly resolution status {value!r}; expected one of {allowed}"
			)
		return status

	def get_anomaly_dashboard(self, tenant_id: str, session: Session) -> dict[str, Any]:
		stmt = (
			select(Anomaly)
			.where(Anomaly.tenant_id == tenant_id)
			.order_by(Anomaly.created_at.desc())
		)
		all_anomalies = list(session.execute(stmt).scalars())

		open_anomalies = [a for a in all_anomalies if a.status == "OPEN"]
		critical = [a for a in open_anomalies if a.severity == "CRITICAL"]
		high = [a for a in open_anomalies if a.severity == "HIGH"]

		by_type: dict[str, int] = {}
		by_module: dict[str, int] = {}
		for a in open_anomalies:
			by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1
			by_module[a.source_module] = by_module.get(a.source_module, 0) + 1

		recent = [
			{
				"id": a.id,
				"anomaly_type": a.anomaly_type,
				"severity": a.severity,
				"source_module": a.source_module,
				"source_record_id": a.source_record_id,
				"description": a.description,
				"status": a.status,
				"created_at": a.created_at.isoformat() if a.created_at else None,
			}
			for a in all_anomalies[:20]
		]

		return {
			"open_count": len(open_anomalies),
			"critical_count": len(critical),
			"high_count": len(high),
			"by_type": by_type,
			"by_module": by_module,
			"recent_anomalies": recent,
		}
