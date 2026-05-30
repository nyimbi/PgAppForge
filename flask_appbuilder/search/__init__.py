"""App-wide unified search across all registered Flask-AppBuilder models."""
from .manager import GlobalSearchManager, SearchResult

__all__ = ["GlobalSearchManager", "SearchResult"]
