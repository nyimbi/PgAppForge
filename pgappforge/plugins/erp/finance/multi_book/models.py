from __future__ import annotations
import uuid
import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin


def _uuid4():
	return str(uuid.uuid4())


class AccountingBook(AuditMixin, Model):
	__tablename__ = "mb_accounting_book"
	__allow_unmapped__ = True
	__table_args__ = (
		Index("ix_mb_book_tenant", "tenant_id"),
		Index("ix_mb_book_type", "tenant_id", "book_type"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	name = Column(String(200), nullable=False)
	book_type = Column(String(20), nullable=False)  # IFRS/LOCAL_GAAP/US_GAAP/TAX/MANAGEMENT
	description = Column(Text, nullable=True)
	currency_code = Column(String(3), nullable=False, default="USD")
	is_primary = Column(Boolean, nullable=False, default=False)
	is_active = Column(Boolean, nullable=False, default=True)
	entity_id = Column(String(50), nullable=True)


class BookJournalEntry(AuditMixin, Model):
	__tablename__ = "mb_journal_entry"
	__allow_unmapped__ = True
	__table_args__ = (
		Index("ix_mb_je_book_period", "book_id", "period"),
		Index("ix_mb_je_source", "source_journal_id"),
		Index("ix_mb_je_tenant_period", "tenant_id", "period"),
		{"extend_existing": True},
	)

	id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid4, server_default=sa.text("gen_random_uuid()"))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	book_id = Column(UUID(as_uuid=False), ForeignKey("mb_accounting_book.id", ondelete="CASCADE"), nullable=False)
	source_journal_id = Column(String(50), nullable=False)
	gl_account = Column(String(20), nullable=False)
	debit_cents = Column(BigInteger, nullable=False, default=0)
	credit_cents = Column(BigInteger, nullable=False, default=0)
	period = Column(String(20), nullable=False)
	description = Column(Text, nullable=True)
	is_override = Column(Boolean, nullable=False, default=False)

	book = relationship("AccountingBook", lazy="select")


__all__ = ["AccountingBook", "BookJournalEntry"]
