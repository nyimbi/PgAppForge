from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.crm.service_contracts.events import (
	ContractExpiryAlertEvent,
	ServiceContractCancelledEvent,
	ServiceContractCreatedEvent,
	ServiceContractInvoiceGeneratedEvent,
	ServiceContractRenewedEvent,
	SLABreachEvent,
)
from pgappforge.plugins.erp.crm.service_contracts.models import (
	ContractRenewal,
	ServiceContract,
)
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception:
		log.debug("emit skipped: %s", type(event).__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(tz=timezone.utc)


class ServiceContractError(Exception):
	pass


class ContractNotFoundError(ServiceContractError):
	pass


class ContractStateError(ServiceContractError):
	pass


class ServiceContractService:

	def create_contract(
		self,
		customer_id: str,
		title: str,
		billing_frequency: str,
		contract_value_cents: int,
		start_date: date,
		end_date: date,
		tenant_id: str,
		session: Any,
		*,
		contract_type: str = "MAINTENANCE",
		sla_response_hours: int = 8,
		sla_resolution_hours: int = 48,
		covered_assets: list | None = None,
		currency_code: str = "USD",
	) -> ServiceContract:
		freq_divisors = {"MONTHLY": 12, "QUARTERLY": 4, "ANNUAL": 1, "WEEKLY": 52}
		divisor = freq_divisors.get(billing_frequency, 12)
		billing_amount = int(Decimal(contract_value_cents) / Decimal(divisor))
		ref = f"SVC-{_uuid4()[:8].upper()}"
		contract = ServiceContract(
			tenant_id=tenant_id,
			customer_id=customer_id,
			contract_ref=ref,
			title=title,
			contract_type=contract_type,
			status="ACTIVE",
			start_date=start_date,
			end_date=end_date,
			billing_frequency=billing_frequency,
			contract_value_cents=contract_value_cents,
			billing_amount_cents=billing_amount,
			currency_code=currency_code,
			sla_response_hours=sla_response_hours,
			sla_resolution_hours=sla_resolution_hours,
			covered_assets=covered_assets or [],
			next_billing_date=start_date,
		)
		session.add(contract)
		session.flush()
		_emit(
			ServiceContractCreatedEvent(
				contract_id=str(contract.id),
				customer_id=customer_id,
				value_cents=contract_value_cents,
				tenant_id=tenant_id,
			),
			session,
		)
		return contract

	def generate_invoice(
		self,
		contract_id: str,
		period: str,
		session: Any,
	) -> dict:
		contract = session.execute(
			sa.select(ServiceContract).where(ServiceContract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id!r} not found")
		if contract.status != "ACTIVE":
			raise ContractStateError(
				f"Cannot invoice contract in status {contract.status!r}"
			)
		invoice_id = ""
		ar_created = False
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice

			invoice_number = f"INV-SVC-{_uuid4()[:8].upper()}"
			inv = ARInvoice(
				tenant_id=contract.tenant_id,
				customer_id=contract.customer_id,
				invoice_number=invoice_number,
				invoice_type="SERVICE_CONTRACT",
				invoice_date=date.today(),
				due_date=date.today() + timedelta(days=30),
				subtotal_cents=contract.billing_amount_cents,
				tax_cents=0,
				total_cents=contract.billing_amount_cents,
				balance_due_cents=contract.billing_amount_cents,
				status="ISSUED",
				currency_code=contract.currency_code,
				description=f"Service contract {contract.contract_ref} — {period}",
			)
			session.add(inv)
			session.flush()
			invoice_id = str(inv.id)
			ar_created = True
		except ImportError:
			log.debug("generate_invoice: AR plugin not loaded; invoice skipped for contract %s", contract_id)
			ar_created = True  # not an error — AR plugin optional
		except Exception as exc:
			log.error("generate_invoice: AR invoice creation failed for contract %s: %s", contract_id, exc)
			raise ServiceContractError(f"AR invoice creation failed: {exc}") from exc

		# Only advance billing cycle after a successful (or gracefully skipped) invoice creation
		if ar_created:
			freq_days = {"MONTHLY": 30, "QUARTERLY": 91, "ANNUAL": 365, "WEEKLY": 7}
			contract.last_invoiced_at = date.today()
			days = freq_days.get(contract.billing_frequency, 30)
			contract.next_billing_date = date.today() + timedelta(days=days)
		session.flush()
		_emit(
			ServiceContractInvoiceGeneratedEvent(
				contract_id=contract_id,
				invoice_id=invoice_id,
				period=period,
				amount_cents=contract.billing_amount_cents,
			),
			session,
		)
		return {
			"contract_id": contract_id,
			"invoice_id": invoice_id,
			"amount_cents": contract.billing_amount_cents,
			"period": period,
		}

	def renew_contract(
		self,
		contract_id: str,
		new_end_date: date,
		session: Any,
		*,
		renewed_by: str | None = None,
		new_value_cents: int | None = None,
	) -> ServiceContract:
		contract = session.execute(
			sa.select(ServiceContract).where(ServiceContract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id!r} not found")
		old_end = contract.end_date
		session.add(
			ContractRenewal(
				tenant_id=contract.tenant_id,
				contract_id=contract.id,
				old_end_date=old_end,
				new_end_date=new_end_date,
				renewal_value_cents=new_value_cents or contract.contract_value_cents,
				renewed_by=renewed_by,
			)
		)
		contract.end_date = new_end_date
		if new_value_cents:
			contract.contract_value_cents = new_value_cents
		contract.status = "ACTIVE"
		session.flush()
		_emit(
			ServiceContractRenewedEvent(
				contract_id=contract_id,
				old_end_date=str(old_end),
				new_end_date=str(new_end_date),
			),
			session,
		)
		return contract

	def cancel_contract(
		self,
		contract_id: str,
		reason: str,
		session: Any,
	) -> ServiceContract:
		contract = session.execute(
			sa.select(ServiceContract).where(ServiceContract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			raise ContractNotFoundError(f"Contract {contract_id!r} not found")
		contract.status = "CANCELLED"
		session.flush()
		_emit(
			ServiceContractCancelledEvent(contract_id=contract_id, reason=reason),
			session,
		)
		return contract

	def check_expiry_alerts(self, tenant_id: str, session: Any) -> list:
		results = []
		contracts = session.execute(
			sa.select(ServiceContract).where(
				ServiceContract.tenant_id == tenant_id,
				ServiceContract.status == "ACTIVE",
			)
		).scalars().all()
		for c in contracts:
			days_left = (c.end_date - date.today()).days
			if 0 <= days_left <= c.renewal_notice_days:
				_emit(
					ContractExpiryAlertEvent(
						contract_id=str(c.id),
						days_until_expiry=days_left,
					),
					session,
				)
				results.append({
					"contract_id": str(c.id),
					"title": c.title,
					"end_date": str(c.end_date),
					"days_until_expiry": days_left,
				})
		return results

	def generate_all_due_invoices(self, tenant_id: str, session: Any) -> int:
		today = date.today()
		contracts = session.execute(
			sa.select(ServiceContract).where(
				ServiceContract.tenant_id == tenant_id,
				ServiceContract.status == "ACTIVE",
				ServiceContract.next_billing_date <= today,
			)
		).scalars().all()
		count = 0
		for c in contracts:
			try:
				period = today.strftime("%Y-%m")
				self.generate_invoice(str(c.id), period, session)
				count += 1
			except Exception as exc:
				log.warning(
					"generate_all_due_invoices: contract %s failed: %s", c.id, exc
				)
		return count

	def check_sla_breach(
		self,
		contract_id: str,
		work_order_id: str,
		response_hours: int,
		session: Any,
	) -> bool:
		contract = session.execute(
			sa.select(ServiceContract).where(ServiceContract.id == contract_id)
		).scalar_one_or_none()
		if contract is None:
			return False
		if response_hours > contract.sla_response_hours:
			_emit(
				SLABreachEvent(
					contract_id=contract_id,
					work_order_id=work_order_id,
					response_hours=response_hours,
					sla_hours=contract.sla_response_hours,
				),
				session,
			)
			return True
		return False


@BPMActionRegistry.register(
	"crm.service_contracts.generate_invoice",
	"Generate service contract invoice for period",
)
def _bpm_generate_invoice(
	record_ctx: Any,
	session: Any,
	contract_id: str,
	period: str,
	**kw: Any,
) -> dict:
	return ServiceContractService().generate_invoice(contract_id, period, session)


@BPMActionRegistry.register(
	"crm.service_contracts.check_sla",
	"Check SLA breach for service work order",
)
def _bpm_check_sla(
	record_ctx: Any,
	session: Any,
	contract_id: str,
	work_order_id: str,
	response_hours: int,
	**kw: Any,
) -> bool:
	return ServiceContractService().check_sla_breach(
		contract_id, work_order_id, int(response_hours), session
	)


__all__ = [
	"ServiceContractError",
	"ContractNotFoundError",
	"ContractStateError",
	"ServiceContractService",
]
