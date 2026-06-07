from __future__ import annotations
import logging
from typing import Any
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.finance.multi_book.models import AccountingBook, BookJournalEntry
from pgappforge.plugins.erp.finance.multi_book.services import MultiBookService, MultiBookError, BookNotFoundError

log = logging.getLogger(__name__)


class MultiBookPlugin(BasePlugin):
	name = "multi_book"
	domain = "finance"
	depends_on: list[str] = ["foundation", "gl"]
	metadata = PluginMetadata(
		name="multi_book",
		version="1.0.0",
		description=(
			"Multi-book accounting — IFRS, LOCAL GAAP, TAX, MANAGEMENT parallel ledgers "
			"from a single transaction. Auto-generates IFRS vs local differences report."
		),
		author="PgAppForge Contributors",
		tags=["finance", "multi-book", "ifrs", "local-gaap", "parallel-ledger", "accounting"],
		priority=PluginPriority.NORMAL,
	)

	def get_events(self) -> list[str]:
		return [
			"finance.multi_book.book.created",
			"finance.multi_book.journal.posted",
			"finance.multi_book.difference.detected",
			"finance.multi_book.reconciliation.run",
			"finance.multi_book.book.closed",
		]

	def subscribe_to(self) -> list[str]:
		return ["finance.gl.journal.posted"]

	def initialize(self) -> None:
		self.config.setdefault("MULTI_BOOK_MENU_CATEGORY", "Multi-Book Accounting")

	def register_models(self) -> list:
		return [AccountingBook, BookJournalEntry]

	def register_views(self) -> None:
		log.info("MultiBookPlugin: views pending implementation")

	def setup_rules(self, session: Any) -> None:
		pass


def create_plugin(appbuilder, config=None) -> MultiBookPlugin:
	return MultiBookPlugin(appbuilder, config=config or {})


__all__ = [
	"MultiBookPlugin",
	"create_plugin",
	"AccountingBook",
	"BookJournalEntry",
	"MultiBookService",
	"MultiBookError",
	"BookNotFoundError",
]
