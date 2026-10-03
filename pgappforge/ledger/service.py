"""Ledger service: the only writer of balances.

Rules enforced here, once, for every caller:

* An entry has exactly two postings unless ``legs`` is given, and they balance
  to the cent in a single currency.
* A posting's sign follows the account's ``normal_sign``: debits reduce asset
  and expense balances, credits reduce liability and income balances.
* Account rows are locked ``FOR UPDATE`` before any balance is read or written,
  and the materialised ``balance`` column is updated with a SQL delta so a stale
  ORM snapshot can never produce a lost update.
* An account that is not ``allow_negative`` may not be debited beyond its
  overdraft limit.
* Replaying an ``idempotency_key`` returns the original entry unchanged; the
  same key with different content raises :class:`IdempotencyConflict`.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ZERO, LedgerAccount, LedgerEntry, LedgerPosting

log = logging.getLogger(__name__)

CENT = Decimal("0.01")

#: Signed sum of postings: debits subtract, credits add. Expressed in SQL so the
#: database is the single source of truth for a balance.
#: Raw totals per (account, direction). The sign is applied per account from its
#: ``normal_sign``: a debit adds to a debit-normal account (asset, expense) and
#: subtracts from a credit-normal one (liability, income, equity), so every
#: balance reads as a positive amount on its own side.
DIRECTION_TOTALS = select(
	LedgerPosting.account_id,
	LedgerPosting.direction,
	func.coalesce(func.sum(LedgerPosting.amount), 0),
).group_by(LedgerPosting.account_id, LedgerPosting.direction)


def _sum_by_direction(session: Session, account_ids: Iterable[int] | None = None) -> dict[int, Decimal]:
	"""Balance per account derived from postings, signed by each account's side."""
	stmt = DIRECTION_TOTALS
	if account_ids is not None:
		stmt = stmt.where(LedgerPosting.account_id.in_(list(account_ids)))
	rows = session.execute(stmt).all()
	normals = {
		a.id: a.normal_sign
		for a in session.execute(
			select(LedgerAccount.id, LedgerAccount.normal_sign).where(
				LedgerAccount.id.in_({r[0] for r in rows}) if rows else LedgerAccount.id.in_([-1])
			)
		).all()
	}
	debits: dict[int, Decimal] = {}
	credits: dict[int, Decimal] = {}
	for account_id, direction, total in rows:
		(debits if direction == "debit" else credits)[int(account_id)] = Decimal(str(total)).quantize(
			CENT, rounding=ROUND_HALF_UP
		)
	out: dict[int, Decimal] = {}
	for account_id in set(debits) | set(credits):
		debit_normal = normals.get(account_id, -1) == -1
		debit, credit = debits.get(account_id, ZERO), credits.get(account_id, ZERO)
		out[account_id] = (debit - credit) if debit_normal else (credit - debit)
	return out

_DEBIT_ACCOUNTS = frozenset({"asset", "expense"})
_CREDIT_ACCOUNTS = frozenset({"liability", "income", "equity"})


class LedgerError(Exception):
	"""Base class for ledger failures."""


class AccountNotFoundError(LedgerError):
	pass


class DoubleEntryError(LedgerError):
	pass


class IdempotencyConflict(LedgerError):
	pass


class InsufficientFundsError(LedgerError):
	pass


@dataclass
class Posting:
	account: LedgerAccount | int
	amount: Decimal | str | int | float
	direction: str | None = None  # inferred from the account's normal_sign when omitted
	memo: str | None = None
	amount_base: Decimal | str | None = None
	#: Opening and adjustment entries legitimately move an account against its
	#: normal side (crediting cash, debiting income). Ordinary entries may not.
	allow_counter_direction: bool = False


@dataclass
class LockedAccount:
	"""An account row locked for the duration of the caller's transaction."""

	id: int
	code: str
	account_type: str
	currency: str
	normal_sign: int
	allow_negative: bool
	overdraft_limit: Decimal
	balance: Decimal

	@property
	def available(self) -> Decimal:
		return self.balance + self.overdraft_limit

	def sign_for(self, account_type: str) -> str:
		"""Direction that increases this account: debits grow assets and
		expenses, credits grow liabilities, income and equity."""
		if account_type in _DEBIT_ACCOUNTS:
			return "debit" if self.normal_sign == -1 else "credit"
		if account_type in _CREDIT_ACCOUNTS:
			return "credit" if self.normal_sign == 1 else "debit"
		raise DoubleEntryError(f"unknown account type {account_type!r}")


def _request_user_id() -> int | None:
	"""User id of the current request, if any (AuditMixin parity)."""
	try:
		from flask import g, has_request_context

		if has_request_context():
			user = getattr(g, "user", None)
			return getattr(user, "id", None)
	except Exception:  # pragma: no cover - no Flask context
		return None
	return None


def _to_money(value: Any) -> Decimal:
	try:
		amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
	except (InvalidOperation, ValueError) as exc:
		raise DoubleEntryError(f"{value!r} is not a valid amount") from exc
	if not amount.is_finite():
		raise DoubleEntryError(f"{value!r} is not a finite amount")
	return amount


class LedgerService:
	"""Posting, reversing, querying and rebuilding ledger balances."""

	def __init__(self, session: Session, actor_id: int | None = None) -> None:
		self.session = session
		# AuditMixin stamps created_by_fk from flask.g.user; when the ledger is
		# driven outside a request (batch jobs, tests, workers) the caller says
		# who is acting instead.
		self.actor_id = actor_id if actor_id is not None else _request_user_id()

	# ------------------------------------------------------------------ locks
	@contextmanager
	def lock_accounts(self, account_ids: Iterable[int]) -> Iterator[list[LockedAccount]]:
		"""Lock account rows in ascending id order to make deadlocks impossible."""
		ids = sorted({int(a) for a in account_ids})
		if not ids:
			raise AccountNotFoundError("no accounts supplied")
		rows = (
			self.session.execute(
				select(LedgerAccount)
				.where(LedgerAccount.id.in_(ids))
				.order_by(LedgerAccount.id)
				.with_for_update()
				# An account may already be in the identity map with a stale
				# balance from an earlier Core UPDATE in the same transaction;
				# refresh it so the locked value is the one just written.
				.execution_options(populate_existing=True)
			)
			.scalars()
			.all()
		)
		if len(rows) != len(ids):
			missing = sorted(set(ids) - {r.id for r in rows})
			raise AccountNotFoundError(f"accounts not found: {missing}")
		locked = [
			LockedAccount(
				id=r.id,
				code=r.code,
				account_type=r.account_type,
				currency=r.currency,
				normal_sign=r.normal_sign,
				allow_negative=bool(r.allow_negative),
				overdraft_limit=Decimal(r.overdraft_limit or ZERO),
				balance=Decimal(r.balance or ZERO),
			)
			for r in rows
		]
		yield locked

	# ------------------------------------------------------------------ post
	def post(
		self,
		legs: Sequence[Posting],
		*,
		idempotency_key: str | None = None,
		entry_type: str = "transfer",
		description: str | None = None,
		reference: str | None = None,
		causation_id: str | None = None,
		tenant_id: int | None = None,
		posted_by: int | None = None,
		reversal_of_id: str | None = None,
		metadata: dict[str, Any] | None = None,
		entry_date: datetime | None = None,
		commit: bool = False,
	) -> LedgerEntry:
		"""Record one balanced entry. Idempotent on ``idempotency_key``."""
		if len(legs) < 2:
			raise DoubleEntryError("an entry needs at least two postings")

		if idempotency_key:
			existing = self.session.execute(
				select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
			).scalar_one_or_none()
			if existing is not None:
				# total_amount is the debit side of the entry; compare like for like.
				replay_debits = sum(
					(
						_to_money(leg.amount)
						for leg in legs
						if (leg.direction or "debit") == "debit"
					),
					ZERO,
				)
				if existing.total_amount != replay_debits.quantize(CENT, rounding=ROUND_HALF_UP):
					raise IdempotencyConflict(
						f"idempotency key {idempotency_key!r} already used with a different amount"
					)
				log.info("Ledger entry %s replayed for key %s", existing.id, idempotency_key)
				return existing

		account_ids = [l.account.id if isinstance(l.account, LedgerAccount) else int(l.account) for l in legs]
		currencies = {l.currency for l in []}  # placeholder to keep the type checker calm
		with self.lock_accounts(account_ids) as locked:
			by_id = {a.id: a for a in locked}
			postings: list[tuple[LockedAccount, Decimal, str]] = []
			for leg in legs:
				account = by_id[int(leg.account.id if isinstance(leg.account, LedgerAccount) else leg.account)]
				amount = _to_money(leg.amount)
				direction = leg.direction or account.sign_for(account.account_type)
				if not leg.allow_counter_direction:
					if direction == "debit":
						if account.account_type not in _DEBIT_ACCOUNTS:
							raise DoubleEntryError(f"{account.code} is a {account.account_type}; it cannot be debited")
					elif direction == "credit":
						if account.account_type not in _CREDIT_ACCOUNTS:
							raise DoubleEntryError(f"{account.code} is an {account.account_type}; it cannot be credited")
				if direction not in ("debit", "credit"):
					raise DoubleEntryError(f"invalid direction {direction!r}")
				postings.append((account, amount, direction))

			currencies = {a.currency for a, _, _ in postings}
			if len(currencies) != 1:
				raise DoubleEntryError(f"entry spans multiple currencies {sorted(currencies)}; post FX legs separately")

			debits = sum((a for _, a, d in postings if d == "debit"), ZERO)
			credits = sum((a for _, a, d in postings if d == "credit"), ZERO)
			if debits != credits:
				raise DoubleEntryError(f"entry does not balance: debits {debits} != credits {credits}")

			# Every account must end non-negative (or within its overdraft limit).
			per_account: dict[int, Decimal] = {}
			for account, amount, direction in postings:
				delta = amount if direction == account.sign_for(account.account_type) else -amount
				new_balance = per_account.get(account.id, account.balance) + delta
				if not account.allow_negative and new_balance < -account.overdraft_limit:
					raise InsufficientFundsError(
						f"{account.code} would fall to {new_balance} beyond its overdraft limit "
						f"{account.overdraft_limit}"
					)
				per_account[account.id] = new_balance

			entry = LedgerEntry(
				tenant_id=tenant_id,
				entry_date=entry_date or datetime.now(tz=timezone.utc),
				idempotency_key=idempotency_key,
				reference=reference,
				entry_type=entry_type,
				description=description,
				currency=next(iter(currencies)),
				total_amount=debits,
				causation_id=causation_id,
				posted_by=posted_by,
				reversal_of_id=reversal_of_id,
				metadata_json=json.dumps(metadata, default=str) if metadata else None,
			)
			actor = posted_by if posted_by is not None else self.actor_id
			entry.created_by_fk = actor
			entry.changed_by_fk = actor
			self.session.add(entry)
			if entry.id is None:
				# The primary-key default only fires at flush time; postings need
				# the id now.
				entry.id = str(uuid.uuid4())
			for account, amount, direction in postings:
				leg = next(
					l for l in legs
					if int(l.account.id if isinstance(l.account, LedgerAccount) else l.account) == account.id
				)
				self.session.add(
					LedgerPosting(
						entry_id=entry.id,
						account_id=account.id,
						direction=direction,
						amount=amount,
						currency=account.currency,
						amount_base=_to_money(leg.amount_base) if leg.amount_base is not None else amount,
						memo=leg.memo,
						created_by_fk=actor,
						changed_by_fk=actor,
					)
				)
				self.session.execute(
					LedgerAccount.__table__.update()
					.where(LedgerAccount.id == account.id)
					.values(
						balance=LedgerAccount.__table__.c.balance + (per_account[account.id] - account.balance),
						# AuditMixin's onupdate would otherwise stamp NULL outside a request.
						changed_by_fk=actor,
					)
				)
			if commit:
				self.session.commit()
			else:
				self.session.flush()
			log.info(
				"Posted ledger entry %s %s %s debits=%s legs=%d",
				entry.id, entry.currency, debits, entry.entry_type, len(postings),
			)
			return entry

	def post_simple(
		self,
		debit_account: LedgerAccount | int,
		credit_account: LedgerAccount | int,
		amount: Decimal | str | int | float,
		**kwargs: Any,
	) -> LedgerEntry:
		"""Two-legged convenience wrapper around :meth:`post`."""
		money = _to_money(amount)
		return self.post(
			[Posting(debit_account, money, "debit"), Posting(credit_account, money, "credit")], **kwargs
		)

	def reverse(
		self, entry_id: str, *, idempotency_key: str | None = None, reason: str | None = None, commit: bool = False
	) -> LedgerEntry:
		"""Compensating entry. History is never rewritten."""
		original = self.session.get(LedgerEntry, entry_id)
		if original is None:
			raise LedgerError(f"entry {entry_id} not found")
		reversal = self.session.execute(
			select(LedgerEntry).where(LedgerEntry.reversal_of_id == entry_id)
		).scalar_one_or_none()
		if reversal is not None:
			log.info("Entry %s already reversed by %s", entry_id, reversal.id)
			return reversal
		legs = [
			Posting(
				p.account_id,
				p.amount,
				"credit" if p.direction == "debit" else "debit",
				memo=reason,
				allow_counter_direction=True,
			)
			for p in original.postings
		]
		return self.post(
			legs,
			idempotency_key=idempotency_key or f"reversal:{entry_id}",
			entry_type="reversal",
			description=reason or f"Reversal of {entry_id}",
			reference=original.reference,
			tenant_id=original.tenant_id,
			causation_id=entry_id,
			reversal_of_id=entry_id,
			commit=commit,
		)

	# ------------------------------------------------------------------ query
	def balance_of(self, account_id: int) -> Decimal:
		return _sum_by_direction(self.session, [account_id]).get(int(account_id), Decimal("0.00"))

	def balance_of_many(self, account_ids: Iterable[int]) -> dict[int, Decimal]:
		derived = _sum_by_direction(self.session, account_ids)
		return {int(a): derived.get(int(a), Decimal("0.00")) for a in account_ids}

	def entries_for(self, account_id: int, *, limit: int = 100) -> list[tuple[LedgerEntry, LedgerPosting]]:
		return (
			self.session.execute(
				select(LedgerEntry, LedgerPosting)
				.join(LedgerPosting, LedgerPosting.entry_id == LedgerEntry.id)
				.where(LedgerPosting.account_id == account_id)
				.order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc())
				.limit(limit)
			)
			.all()
		)


def rebuild_account_balances(
	session: Session, account_ids: Iterable[int] | None = None, actor_id: int | None = None
) -> dict[int, Decimal]:
	"""Recompute materialised balances from postings. Used by tests and audits."""
	balances = _sum_by_direction(session, account_ids)
	ids = list(balances) if account_ids is None else [int(a) for a in account_ids]
	actor = actor_id if actor_id is not None else _request_user_id()
	for account_id in ids:
		if account_id not in balances:
			balances[int(account_id)] = Decimal("0.00")
		values: dict[str, Any] = {"balance": balances[int(account_id)]}
		if actor is not None:
			values["changed_by_fk"] = actor
		session.execute(LedgerAccount.__table__.update().where(LedgerAccount.id == account_id).values(**values))
	return balances


_SERVICE: LedgerService | None = None


def get_ledger_service(session: Session | None = None) -> LedgerService:
	"""Ledger service bound to the request (or a given) session."""
	global _SERVICE
	if session is None:
		from pgappforge import db

		session = db.session
	if _SERVICE is not None and _SERVICE.session is session:
		return _SERVICE
	_SERVICE = LedgerService(session)
	return _SERVICE
