"""App-wide unified search across all registered PgForge models."""
from .manager import GlobalSearchManager, SearchResult

__all__ = ["GlobalSearchManager", "SearchResult"]
