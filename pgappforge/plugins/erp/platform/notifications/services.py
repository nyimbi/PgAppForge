"""
pgappforge/plugins/erp/platform/notifications/services.py

KPI threshold evaluation and alert dispatch.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.erp.platform.notifications.models import KPIAlertRule

log = logging.getLogger(__name__)


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _decimal(value: Any) -> Decimal:
	try:
		return Decimal(str(value or "0"))
	except (InvalidOperation, ValueError, TypeError):
		return Decimal("0")


def _json_value(value: Decimal) -> int | float:
	return int(value) if value == value.to_integral_value() else float(value)


class KPIAlertService:
	"""Evaluate active KPI alert rules and notify configured recipients."""

	def evaluate_all_rules(self, tenant_id: str, session: Any) -> list[dict[str, Any]]:
		"""Evaluate every active rule for a tenant and trigger breached alerts."""
		now = _now()
		triggered: list[dict[str, Any]] = []
		rules = session.execute(
			select(KPIAlertRule).where(
				KPIAlertRule.tenant_id == tenant_id,
				KPIAlertRule.is_active.is_(True),
			)
		).scalars().all()

		for rule in rules:
			if self._in_cooldown(rule, now):
				continue
			evaluator = self._evaluator_map().get(rule.kpi_key)
			if evaluator is None:
				log.warning("KPIAlertService: no evaluator registered for %r", rule.kpi_key)
				continue

			current_value = _decimal(evaluator(tenant_id, session))
			threshold = _decimal(rule.threshold_value)
			if not self._check_condition(current_value, rule.condition, threshold):
				continue

			self._trigger_alert(rule, current_value, session)
			triggered.append({
				"rule_id": rule.id,
				"name": rule.name,
				"kpi_key": rule.kpi_key,
				"condition": rule.condition,
				"threshold_value": rule.threshold_value,
				"current_value": _json_value(current_value),
				"triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
			})

		return triggered

	@classmethod
	def create_default_rules(cls, tenant_id: str, session: Any) -> list[KPIAlertRule]:
		"""Create the standard KPI alert-rule set for a tenant, idempotently."""
		defaults: list[dict[str, Any]] = [
			{
				"name": "AR Overdue Spike",
				"kpi_key": "ar_overdue_cents",
				"condition": "gt",
				"threshold_value": "1000000",
				"recipients": ["finance_manager"],
			},
			{
				"name": "Critical Risks Open",
				"kpi_key": "open_risks_critical",
				"condition": "gt",
				"threshold_value": "5",
				"recipients": ["risk_manager"],
			},
			{
				"name": "Compliance Overdue",
				"kpi_key": "compliance_overdue",
				"condition": "gt",
				"threshold_value": "3",
				"recipients": ["compliance_manager"],
			},
			{
				"name": "Overdue Invoice Count",
				"kpi_key": "overdue_invoice_count",
				"condition": "gt",
				"threshold_value": "20",
				"recipients": ["finance_manager"],
			},
			{
				"name": "Payroll Variance",
				"kpi_key": "payroll_variance_pct",
				"condition": "gt",
				"threshold_value": "10",
				"recipients": ["payroll_manager"],
			},
		]
		created: list[KPIAlertRule] = []

		for rule_def in defaults:
			existing = session.execute(
				select(KPIAlertRule).where(
					KPIAlertRule.tenant_id == tenant_id,
					KPIAlertRule.name == rule_def["name"],
				)
			).scalar_one_or_none()
			if existing is not None:
				continue
			rule = KPIAlertRule(
				tenant_id=tenant_id,
				name=rule_def["name"],
				kpi_key=rule_def["kpi_key"],
				condition=rule_def["condition"],
				threshold_value=rule_def["threshold_value"],
				notification_channels=["in_app"],
				recipients=rule_def["recipients"],
				is_active=True,
				cooldown_minutes=60,
			)
			session.add(rule)
			created.append(rule)

		if created:
			session.flush()
		return created

	def _evaluator_map(self) -> dict[str, Callable[[str, Any], Decimal | int | float]]:
		return {
			"ar_overdue_cents": self._eval_ar_overdue,
			"open_risks_critical": self._eval_open_critical_risks,
			"payroll_variance_pct": self._eval_payroll_variance,
			"overdue_invoice_count": self._eval_overdue_invoice_count,
			"procurement_savings_pct": self._eval_procurement_savings,
			"compliance_overdue": self._eval_compliance_overdue,
		}

	def _eval_ar_overdue(self, tenant_id: str, session: Any) -> Decimal:
		"""Sum outstanding AR more than 30 days overdue, returned in currency units."""
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		cutoff = date.today() - timedelta(days=30)
		cents = session.execute(
			select(sa.func.coalesce(sa.func.sum(ARInvoice.balance_due_cents), 0)).where(
				ARInvoice.tenant_id == tenant_id,
				ARInvoice.due_date <= cutoff,
				ARInvoice.balance_due_cents > 0,
				ARInvoice.status.in_(("ISSUED", "PARTIAL", "OVERDUE", "DISPUTED")),
			)
		).scalar_one()
		return Decimal(int(cents or 0)) / Decimal("100")

	def _eval_open_critical_risks(self, tenant_id: str, session: Any) -> int:
		"""Count open risks with likelihood times impact at or above 15."""
		from pgappforge.plugins.erp.grc.erm.models import RiskRegister

		return int(session.execute(
			select(sa.func.count()).select_from(RiskRegister).where(
				RiskRegister.tenant_id == tenant_id,
				~RiskRegister.status.in_(("CLOSED", "RESOLVED", "RETIRED", "CANCELLED")),
				(RiskRegister.likelihood_score * RiskRegister.impact_score) >= 15,
			)
		).scalar_one() or 0)

	def _eval_payroll_variance(self, tenant_id: str, session: Any) -> Decimal:
		"""Return absolute net payroll variance percentage between latest two runs."""
		from pgappforge.plugins.erp.hcm.payroll.models import PayrollRun

		runs = session.execute(
			select(PayrollRun)
			.where(
				PayrollRun.tenant_id == tenant_id,
				PayrollRun.status.in_(("CALCULATED", "APPROVED", "PAID")),
			)
			.order_by(PayrollRun.period_end.desc(), PayrollRun.created_at.desc())
			.limit(2)
		).scalars().all()
		if len(runs) < 2:
			return Decimal("0")

		current = Decimal(int(runs[0].total_net_cents or 0))
		prior = Decimal(int(runs[1].total_net_cents or 0))
		if prior == 0:
			return Decimal("100") if current else Decimal("0")
		return (abs(current - prior) / abs(prior) * Decimal("100")).quantize(Decimal("0.0001"))

	def _eval_overdue_invoice_count(self, tenant_id: str, session: Any) -> int:
		"""Count overdue AR invoices with an outstanding balance."""
		from pgappforge.plugins.erp.finance.ar.models import ARInvoice

		today = date.today()
		return int(session.execute(
			select(sa.func.count()).select_from(ARInvoice).where(
				ARInvoice.tenant_id == tenant_id,
				ARInvoice.due_date < today,
				ARInvoice.balance_due_cents > 0,
				ARInvoice.status.in_(("ISSUED", "PARTIAL", "OVERDUE", "DISPUTED")),
			)
		).scalar_one() or 0)

	def _eval_procurement_savings(self, tenant_id: str, session: Any) -> Decimal:
		"""Return weighted procurement savings percentage across savings records."""
		from pgappforge.plugins.erp.procurement.sourcing.models import ProcurementSavings

		row = session.execute(
			select(
				sa.func.coalesce(sa.func.sum(ProcurementSavings.savings_cents), 0),
				sa.func.coalesce(sa.func.sum(ProcurementSavings.baseline_price_cents), 0),
			).where(ProcurementSavings.tenant_id == tenant_id)
		).one()
		total_savings = Decimal(int(row[0] or 0))
		total_baseline = Decimal(int(row[1] or 0))
		if total_baseline <= 0:
			return Decimal("0")
		return (total_savings / total_baseline * Decimal("100")).quantize(Decimal("0.0001"))

	def _eval_compliance_overdue(self, tenant_id: str, session: Any) -> int:
		"""Count overdue compliance items using tax returns as filing obligations."""
		from pgappforge.plugins.erp.finance.tax.models import TaxReturn

		today = date.today()
		return int(session.execute(
			select(sa.func.count()).select_from(TaxReturn).where(
				TaxReturn.tenant_id == tenant_id,
				TaxReturn.status == "DRAFT",
				TaxReturn.due_date.isnot(None),
				TaxReturn.due_date < today,
			)
		).scalar_one() or 0)

	def _check_condition(self, value: Any, condition: str, threshold: Any) -> bool:
		current = _decimal(value)
		limit = _decimal(threshold)
		condition = (condition or "").lower()
		comparisons: dict[str, Callable[[Decimal, Decimal], bool]] = {
			"gt": lambda a, b: a > b,
			"lt": lambda a, b: a < b,
			"gte": lambda a, b: a >= b,
			"lte": lambda a, b: a <= b,
			"eq": lambda a, b: a == b,
		}
		if condition not in comparisons:
			log.warning("KPIAlertService: unsupported condition %r", condition)
			return False
		return comparisons[condition](current, limit)

	def _trigger_alert(self, rule: KPIAlertRule, current_value: Decimal, session: Any) -> None:
		now = _now()
		subject = f"KPI threshold breached: {rule.name}"
		body = (
			f"{rule.name} breached: {rule.kpi_key} is {_json_value(current_value)} "
			f"and rule is {rule.condition} {rule.threshold_value}."
		)
		channels = list(rule.notification_channels or ["in_app"])
		recipients = list(rule.recipients or [])
		metadata = {
			"event_type": "platform.kpi_alert.triggered",
			"rule_id": rule.id,
			"kpi_key": rule.kpi_key,
			"current_value": str(current_value),
			"threshold_value": rule.threshold_value,
			"condition": rule.condition,
		}

		for recipient in recipients:
			self._send_notification(
				recipient_id=str(recipient),
				subject=subject,
				body=body,
				channels=channels,
				metadata=metadata,
			)

		rule.last_triggered_at = now
		rule.updated_at = now
		session.add(rule)
		session.flush()

	def _send_notification(
		self,
		*,
		recipient_id: str,
		subject: str,
		body: str,
		channels: list[str],
		metadata: dict[str, Any],
	) -> None:
		"""Dispatch one alert through the PgAppForge notification service."""
		try:
			from pgappforge.alerting.notification_service import (
				NotificationChannel,
				NotificationPriority,
				NotificationRecipient,
				NotificationService,
			)
		except Exception as exc:
			log.debug("KPIAlertService: notification service unavailable: %s", exc)
			return

		try:
			service = self._notification_service(NotificationService)
			generic_sender = getattr(service, "send_notification", None)
			if callable(generic_sender):
				generic_sender(
					recipient_id=recipient_id,
					subject=subject,
					body=body,
					channels=channels,
					metadata=metadata,
				)
				return

			channel_enums: list[Any] = []
			for channel_name in channels or ["in_app"]:
				try:
					channel_enums.append(NotificationChannel(str(channel_name)))
				except ValueError:
					log.warning("KPIAlertService: unsupported notification channel %r", channel_name)
			if not channel_enums:
				channel_enums = [NotificationChannel.IN_APP]

			if hasattr(service, "_providers") and not service._providers and hasattr(service, "_init_default_providers"):
				service._init_default_providers()

			channel_configs: dict[str, dict[str, Any]] = {}
			if "@" in recipient_id:
				channel_configs["email"] = {"address": recipient_id}
			if recipient_id.startswith(("http://", "https://")):
				channel_configs["webhook"] = {"url": recipient_id}

			recipient = NotificationRecipient(
				id=recipient_id,
				name=recipient_id,
				channels=channel_enums,
				channel_configs=channel_configs,
			)
			for channel in channel_enums:
				provider = getattr(service, "_providers", {}).get(channel)
				if provider is None:
					log.debug("KPIAlertService: no provider for channel %s", channel.value)
					continue
				provider.send_notification(
					recipient=recipient,
					subject=subject,
					content=body,
					priority=NotificationPriority.HIGH,
					metadata=metadata,
				)
		except Exception as exc:
			log.debug("KPIAlertService: notification dispatch failed: %s", exc)

	def _notification_service(self, service_cls: type[Any]) -> Any:
		try:
			from flask import current_app

			app = current_app._get_current_object()
			existing = getattr(app, "extensions", {}).get("notification_service")
			if existing is not None:
				return existing
			return service_cls(app)
		except RuntimeError:
			return service_cls()

	def _in_cooldown(self, rule: KPIAlertRule, now: datetime) -> bool:
		if rule.last_triggered_at is None:
			return False
		cooldown_minutes = int(rule.cooldown_minutes or 0)
		if cooldown_minutes <= 0:
			return False
		last_triggered = rule.last_triggered_at
		if last_triggered.tzinfo is None:
			last_triggered = last_triggered.replace(tzinfo=timezone.utc)
		return now - last_triggered < timedelta(minutes=cooldown_minutes)


__all__ = ["KPIAlertService"]
