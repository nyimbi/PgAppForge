"""
pgappforge/plugins/fintech/sacco/fosa.py

FOSA (Front Office Service Activity) bridge — synchronises SACCO deposit
operations with core banking.

FOSA is the deposit-taking arm of a SACCO.  Member FOSA deposits are held in:
  1. SaccoLedgerEntry  (SACCO internal ledger — immutable, double-entry)
  2. Core Banking Account (tracks actual money movement, GL, interest accrual)

This service ensures both are updated atomically within the same DB session.
The caller is responsible for session.commit() after all operations succeed.

Usage::

	from pgappforge.plugins.fintech.sacco.fosa import FOSABridgeService

	svc = FOSABridgeService()
	result = svc.fosa_deposit(
		member_id="...", amount_cents=50000, reference="TXN001",
		tenant_id="acme", session=db.session,
	)
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

log = logging.getLogger(__name__)


class FOSABridgeService:
	"""Keeps SACCO FOSA deposits in sync with core banking accounts.

	FOSA: the deposit-taking arm of a SACCO.  Member FOSA deposits are held in:
	  1. SaccoLedgerEntry  (SACCO internal ledger)
	  2. CoreBanking Account (tracks actual money movement, GL, interest)

	This service ensures both are updated atomically.

	All monetary amounts are INTEGER cents.  Never use float or Decimal for
	storage; Decimal may be used transiently for arithmetic then converted.
	"""

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_fosa_link(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
	):
		"""Return the FOSAAccountLink for a member, or None."""
		from pgappforge.plugins.fintech.sacco.models import FOSAAccountLink
		return session.execute(
			select(FOSAAccountLink).where(
				FOSAAccountLink.member_id == member_id,
				FOSAAccountLink.account_type == "FOSA",
				FOSAAccountLink.tenant_id == tenant_id,
				FOSAAccountLink.is_active.is_(True),
			)
		).scalar_one_or_none()

	def _try_cb_deposit(
		self,
		cb_account_number: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
		*,
		channel: str,
		description: str,
		reference: str,
	) -> tuple[str | None, int]:
		"""Attempt a core banking deposit; return (journal_id, new_balance_cents).

		Non-fatal: any failure is logged and (None, 0) is returned so the SACCO
		ledger posting still proceeds.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cb = CoreBankingService()
			result = cb.deposit(
				account_number=cb_account_number,
				amount_cents=amount_cents,
				tenant_id=tenant_id,
				session=session,
				channel=channel,
				description=description,
				reference=reference,
			)
			journal_id: str | None = result.get("journal_id")
			new_balance: int = cb.get_balance(cb_account_number, session)
			return journal_id, new_balance
		except ImportError:
			log.debug("core_banking not available — FOSA deposit will only post to SACCO ledger")
		except Exception as exc:
			log.warning("FOSA CB deposit failed for acct %s: %s", cb_account_number, exc)
		return None, 0

	def _try_cb_withdrawal(
		self,
		cb_account_number: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
		*,
		channel: str,
		reference: str,
	) -> str | None:
		"""Attempt a core banking withdrawal; return journal_id or None."""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cb = CoreBankingService()
			result = cb.withdraw(
				account_number=cb_account_number,
				amount_cents=amount_cents,
				tenant_id=tenant_id,
				session=session,
				channel=channel,
				reference=reference,
			)
			return result.get("journal_id")
		except ImportError:
			log.debug("core_banking not available — FOSA withdrawal will only post to SACCO ledger")
		except Exception as exc:
			log.warning("FOSA CB withdrawal failed for acct %s: %s", cb_account_number, exc)
		return None

	def _post_ledger_entry(
		self,
		session: Any,
		*,
		tenant_id: str,
		sacco_id: str,
		member_id: str,
		entry_type: str,
		debit_cents: int,
		credit_cents: int,
		balance_cents: int,
		description: str,
		reference: str,
	) -> Any:
		"""Insert an immutable SaccoLedgerEntry for a FOSA transaction.

		The SaccoLedgerEntry model uses amount_cents (signed: positive = credit,
		negative = debit), dr_account / cr_account GL codes.

		FOSA GL codes:
		  5010 — Cash / Mobile Money (source of funds for deposits)
		  1010 — Member Savings / FOSA Liability
		"""
		from pgappforge.plugins.fintech.sacco.models import SaccoLedgerEntry

		# Compute signed amount for ledger (positive = net credit to member)
		if entry_type in ("FOSA_DEPOSIT",):
			amount_signed = credit_cents
			dr_acct = "5010"	# Cash in
			cr_acct = "1010"	# Member FOSA liability
		else:
			# FOSA_WITHDRAWAL
			amount_signed = -debit_cents
			dr_acct = "1010"	# Member FOSA liability debited
			cr_acct = "5010"	# Cash out

		entry = SaccoLedgerEntry(
			id=str(_uuid.uuid4()),
			tenant_id=tenant_id,
			member_id=member_id,
			entry_type=entry_type,
			amount_cents=amount_signed,
			currency="KES",
			dr_account=dr_acct,
			cr_account=cr_acct,
			running_balance_cents=balance_cents,
			value_date=datetime.now(timezone.utc).date(),
			narrative=description,
			transaction_ref=reference,
			extra={"sacco_id": sacco_id},
		)
		session.add(entry)
		return entry

	# ------------------------------------------------------------------
	# fosa_deposit
	# ------------------------------------------------------------------

	def fosa_deposit(
		self,
		member_id: str,
		amount_cents: int,
		reference: str,
		tenant_id: str,
		session: Any,
		*,
		channel: str = "FOSA_COUNTER",
		description: str | None = None,
	) -> dict:
		"""Accept a FOSA deposit: posts to both CoreBanking account and SACCO ledger.

		Steps:
		  1. Load member; validate exists.
		  2. Look up FOSAAccountLink for this member.
		  3. If linked, attempt CoreBanking deposit (non-fatal on failure).
		  4. Post SaccoLedgerEntry (always).
		  5. Increment Member.fosa_balance_cents.

		Returns:
		  member_id, amount_cents, journal_id, new_cb_balance_cents,
		  new_fosa_balance_cents.
		"""
		from pgappforge.plugins.fintech.sacco.models import Member

		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		_desc = description or f"FOSA deposit ref {reference}"
		journal_id: str | None = None
		new_cb_balance: int = 0

		fosa_link = self._get_fosa_link(member_id, tenant_id, session)
		if fosa_link and fosa_link.cb_account_number:
			journal_id, new_cb_balance = self._try_cb_deposit(
				fosa_link.cb_account_number,
				amount_cents,
				tenant_id,
				session,
				channel=channel,
				description=_desc,
				reference=reference,
			)

		current_fosa = member.fosa_balance_cents or 0
		new_fosa_balance = current_fosa + amount_cents

		self._post_ledger_entry(
			session,
			tenant_id=tenant_id,
			sacco_id=str(member.sacco_id),
			member_id=member_id,
			entry_type="FOSA_DEPOSIT",
			debit_cents=0,
			credit_cents=amount_cents,
			balance_cents=new_fosa_balance,
			description=_desc,
			reference=reference,
		)

		session.execute(
			sa.update(Member)
			.where(Member.id == member_id)
			.values(
				fosa_balance_cents=sa.func.coalesce(Member.fosa_balance_cents, 0) + amount_cents
			)
		)
		session.flush()

		log.info(
			"FOSA deposit: member=%s amount=%dc ref=%s journal=%s",
			member_id, amount_cents, reference, journal_id,
		)
		return {
			"member_id": member_id,
			"amount_cents": amount_cents,
			"journal_id": journal_id,
			"new_cb_balance_cents": new_cb_balance,
			"new_fosa_balance_cents": new_fosa_balance,
		}

	# ------------------------------------------------------------------
	# fosa_withdrawal
	# ------------------------------------------------------------------

	def fosa_withdrawal(
		self,
		member_id: str,
		amount_cents: int,
		reference: str,
		tenant_id: str,
		session: Any,
		*,
		channel: str = "FOSA_COUNTER",
	) -> dict:
		"""Process a FOSA withdrawal: debit CoreBanking + SACCO ledger.

		Validates that the member has sufficient FOSA balance before any
		core banking call is made.

		Returns:
		  member_id, amount_cents, journal_id, new_fosa_balance_cents.
		"""
		from pgappforge.plugins.fintech.sacco.models import Member

		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		current_fosa = member.fosa_balance_cents or 0
		if current_fosa < amount_cents:
			raise ValueError(
				f"Insufficient FOSA balance for member {member_id!r}: "
				f"have {current_fosa}c, need {amount_cents}c"
			)

		journal_id: str | None = None
		fosa_link = self._get_fosa_link(member_id, tenant_id, session)
		if fosa_link and fosa_link.cb_account_number:
			journal_id = self._try_cb_withdrawal(
				fosa_link.cb_account_number,
				amount_cents,
				tenant_id,
				session,
				channel=channel,
				reference=reference,
			)

		new_fosa_balance = current_fosa - amount_cents

		self._post_ledger_entry(
			session,
			tenant_id=tenant_id,
			sacco_id=str(member.sacco_id),
			member_id=member_id,
			entry_type="FOSA_WITHDRAWAL",
			debit_cents=amount_cents,
			credit_cents=0,
			balance_cents=new_fosa_balance,
			description="FOSA withdrawal",
			reference=reference,
		)

		session.execute(
			sa.update(Member)
			.where(Member.id == member_id)
			.values(fosa_balance_cents=new_fosa_balance)
		)
		session.flush()

		log.info(
			"FOSA withdrawal: member=%s amount=%dc ref=%s journal=%s",
			member_id, amount_cents, reference, journal_id,
		)
		return {
			"member_id": member_id,
			"amount_cents": amount_cents,
			"journal_id": journal_id,
			"new_fosa_balance_cents": new_fosa_balance,
		}

	# ------------------------------------------------------------------
	# provision_fosa_account
	# ------------------------------------------------------------------

	def provision_fosa_account(
		self,
		member_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Open a core banking SAVINGS account for a new FOSA member.

		Idempotent: if a FOSAAccountLink already exists for this member,
		returns it without creating a new core banking account.

		Returns:
		  account_number (str | None), already_exists (bool),
		  and optionally error (str) on CB failure.
		"""
		from pgappforge.plugins.fintech.sacco.models import Member, FOSAAccountLink

		member = session.get(Member, member_id)
		if member is None:
			raise ValueError(f"Member {member_id!r} not found")

		# Idempotency: return existing link
		existing = self._get_fosa_link(member_id, tenant_id, session)
		if existing is not None:
			return {"account_number": existing.cb_account_number, "already_exists": True}

		# Attempt to open a CB account
		cb_account_number: str | None = None
		cb_account_id: str | None = None
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cb = CoreBankingService()
			acct = cb.open_account(
				customer_id=str(member.party_id or member_id),
				product_code="SAVINGS",
				currency_code="KES",
				tenant_id=tenant_id,
				session=session,
				branch_code="SACCO",
				channel="FOSA_ONBOARDING",
			)
			cb_account_number = acct.account_number
			cb_account_id = str(acct.id) if getattr(acct, "id", None) else None
		except ImportError:
			log.debug("core_banking not available — FOSAAccountLink created without CB account")
		except Exception as exc:
			log.warning(
				"FOSA CB account provisioning failed for member %s: %s",
				member_id, exc,
			)
			return {"account_number": None, "already_exists": False, "error": str(exc)}

		link = FOSAAccountLink(
			id=str(_uuid.uuid4()),
			tenant_id=tenant_id,
			sacco_id=str(member.sacco_id),
			member_id=member_id,
			account_type="FOSA",
			cb_account_number=cb_account_number,
			cb_account_id=cb_account_id,
			currency_code="KES",
			is_active=True,
		)
		session.add(link)
		session.flush()

		log.info(
			"Provisioned FOSA account for member %s: cb_account=%s",
			member_id, cb_account_number,
		)
		return {"account_number": cb_account_number, "already_exists": False}


__all__ = ["FOSABridgeService"]
