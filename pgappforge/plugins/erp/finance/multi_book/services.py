from __future__ import annotations
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import sqlalchemy as sa
from pgappforge.plugins.erp.finance.multi_book.events import (
	AccountingBookCreatedEvent,
	BookJournalPostedEvent,
	BookDifferenceDetectedEvent,
	MultiBookReconciliationRunEvent,
	BookClosedEvent,
)
from pgappforge.plugins.erp.finance.multi_book.models import AccountingBook, BookJournalEntry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event, session=None):
	try:
		_emit_event(event, session)
	except Exception:
		log.debug("emit skipped for %s", type(event).__name__)


class MultiBookError(Exception):
	pass


class BookNotFoundError(MultiBookError):
	pass


class MultiBookService:
	def create_book(
		self,
		name,
		book_type,
		tenant_id,
		session,
		*,
		currency_code="USD",
		entity_id=None,
		is_primary=False,
	) -> AccountingBook:
		if is_primary:
			existing = session.execute(
				sa.select(AccountingBook).where(
					AccountingBook.tenant_id == tenant_id,
					AccountingBook.is_primary == True,
				)
			).scalar_one_or_none()
			if existing is not None:
				raise MultiBookError(
					f"Primary book already exists: {existing.name!r}. "
					"Set is_primary=False or deactivate the existing primary book."
				)
		book = AccountingBook(
			tenant_id=tenant_id,
			name=name,
			book_type=book_type,
			currency_code=currency_code,
			is_primary=is_primary,
			entity_id=entity_id,
		)
		session.add(book)
		session.flush()
		_emit(
			AccountingBookCreatedEvent(
				book_id=str(book.id),
				name=name,
				book_type=book_type,
				tenant_id=tenant_id,
			),
			session,
		)
		return book

	def post_to_books(
		self,
		source_journal_id,
		debit_cents,
		credit_cents,
		gl_account,
		period,
		tenant_id,
		session,
		*,
		book_overrides=None,
		description=None,
	):
		books = (
			session.execute(
				sa.select(AccountingBook).where(
					AccountingBook.tenant_id == tenant_id,
					AccountingBook.is_active == True,
				)
			)
			.scalars()
			.all()
		)
		for book in books:
			override = (book_overrides or {}).get(str(book.id), {})
			entry = BookJournalEntry(
				tenant_id=tenant_id,
				book_id=book.id,
				source_journal_id=source_journal_id,
				gl_account=override.get("gl_account", gl_account),
				debit_cents=override.get("debit_cents", debit_cents),
				credit_cents=override.get("credit_cents", credit_cents),
				period=period,
				description=description,
				is_override=bool(override),
			)
			session.add(entry)
			session.flush()
			_emit(
				BookJournalPostedEvent(
					entry_id=str(entry.id),
					book_id=str(book.id),
					source_journal_id=source_journal_id,
					debit_cents=entry.debit_cents,
					credit_cents=entry.credit_cents,
				),
				session,
			)

	def get_trial_balance(self, book_id, period, tenant_id, session) -> dict:
		rows = session.execute(
			sa.select(
				BookJournalEntry.gl_account,
				sa.func.sum(BookJournalEntry.debit_cents).label("debit"),
				sa.func.sum(BookJournalEntry.credit_cents).label("credit"),
			)
			.where(
				BookJournalEntry.book_id == book_id,
				BookJournalEntry.period == period,
				BookJournalEntry.tenant_id == tenant_id,
			)
			.group_by(BookJournalEntry.gl_account)
		).all()
		accounts = [
			{
				"account": r.gl_account,
				"debit_cents": r.debit or 0,
				"credit_cents": r.credit or 0,
				"balance_cents": (r.debit or 0) - (r.credit or 0),
			}
			for r in rows
		]
		return {
			"period": period,
			"book_id": book_id,
			"accounts": accounts,
			"total_debit": sum(a["debit_cents"] for a in accounts),
			"total_credit": sum(a["credit_cents"] for a in accounts),
		}

	def get_book_differences(
		self,
		period,
		tenant_id,
		session,
		*,
		book_type_a="IFRS",
		book_type_b="LOCAL_GAAP",
	) -> dict:
		book_a = session.execute(
			sa.select(AccountingBook).where(
				AccountingBook.tenant_id == tenant_id,
				AccountingBook.book_type == book_type_a,
				AccountingBook.is_active == True,
			)
		).scalar_one_or_none()
		book_b = session.execute(
			sa.select(AccountingBook).where(
				AccountingBook.tenant_id == tenant_id,
				AccountingBook.book_type == book_type_b,
				AccountingBook.is_active == True,
			)
		).scalar_one_or_none()
		if not book_a or not book_b:
			return {"error": f"Could not find active books for {book_type_a!r} and {book_type_b!r}"}
		tb_a = {
			r["account"]: r["balance_cents"]
			for r in self.get_trial_balance(str(book_a.id), period, tenant_id, session)["accounts"]
		}
		tb_b = {
			r["account"]: r["balance_cents"]
			for r in self.get_trial_balance(str(book_b.id), period, tenant_id, session)["accounts"]
		}
		all_accounts = set(tb_a) | set(tb_b)
		diffs = [
			{
				"account": a,
				"book_a_balance_cents": tb_a.get(a, 0),
				"book_b_balance_cents": tb_b.get(a, 0),
				"difference_cents": tb_a.get(a, 0) - tb_b.get(a, 0),
			}
			for a in sorted(all_accounts)
			if tb_a.get(a, 0) != tb_b.get(a, 0)
		]
		_emit(
			MultiBookReconciliationRunEvent(
				tenant_id=tenant_id,
				period=period,
				books_compared=2,
				differences_count=len(diffs),
			),
			session,
		)
		return {
			"period": period,
			"book_a": {"id": str(book_a.id), "name": book_a.name, "type": book_type_a},
			"book_b": {"id": str(book_b.id), "name": book_b.name, "type": book_type_b},
			"differences": diffs,
			"total_differences": len(diffs),
		}

	def close_book_period(self, book_id, period, closed_by, session) -> dict:
		import datetime

		_emit(BookClosedEvent(book_id=book_id, period=period, closed_by=closed_by), session)
		return {
			"book_id": book_id,
			"period": period,
			"closed_by": closed_by,
			"closed_at": datetime.datetime.now().isoformat(),
		}


@BPMActionRegistry.register("finance.multi_book.post", "Post transaction to all accounting books")
def _bpm_post(record_ctx, session, source_journal_id, debit_cents, credit_cents, gl_account, period, tenant_id, **kw):
	svc = MultiBookService()
	svc.post_to_books(source_journal_id, int(debit_cents), int(credit_cents), gl_account, period, tenant_id, session)


@BPMActionRegistry.register("finance.multi_book.get_differences", "Get IFRS vs local GAAP differences for period")
def _bpm_diff(record_ctx, session, period, tenant_id, **kw):
	return MultiBookService().get_book_differences(period, tenant_id, session)


__all__ = ["MultiBookError", "BookNotFoundError", "MultiBookService"]
