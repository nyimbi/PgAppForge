"""FABSecurityManager — default, uses FAB built-in security unchanged."""
from pgappforge.security.sqla.manager import SecurityManager


class FABSecurityManager(SecurityManager):
	"""No-op subclass. Uses FAB's built-in security. Zero configuration required."""


__all__ = ["FABSecurityManager"]
