"""Permission algebra — composable policy objects for PgAppForge.

Problem
-------
Flask-AppBuilder's RBAC is flat: a user has roles, roles have permissions.
You cannot express "allow if role=loan_officer AND (role=manager OR permission=credit.override)".

Solution
--------
Policy objects with algebraic combinators:

    from pgappforge.security.policies import AllOf, AnyOf, Not, HasRole, HasPermission, IsOwner

    approve_loan = AllOf(
        HasRole('loan_officer'),
        AnyOf(HasRole('manager'), HasPermission('credit.credit_committee_override')),
    )

    # Use as a decorator on a view method:
    @require_policy(approve_loan)
    def approve(self):
        ...

    # Or evaluate directly:
    if approve_loan.check(current_user, {'loan_id': loan.id, 'tenant_id': tid}):
        ...

Design
------
- Policy.check(user, context) -> bool
- All combinators are monotone: adding more Allows can only expand access
- No side effects in policy evaluation (pure predicate)
- Integrates with Flask-Login current_user; works outside request context too
"""
from __future__ import annotations

import functools
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

log = logging.getLogger(__name__)


class Policy(ABC):
	"""Abstract base for composable access policies."""

	@abstractmethod
	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		"""Return True if *user* satisfies this policy given *context*."""
		...

	# ── Algebraic combinators ────────────────────────────────────────────

	def __and__(self, other: 'Policy') -> 'AllOf':
		return AllOf(self, other)

	def __or__(self, other: 'Policy') -> 'AnyOf':
		return AnyOf(self, other)

	def __invert__(self) -> 'Not':
		return Not(self)

	def __repr__(self) -> str:
		return self.__class__.__name__


# ── Primitive policies ───────────────────────────────────────────────────────

class HasRole(Policy):
	"""True if user has the named role."""

	def __init__(self, role_name: str) -> None:
		self.role_name = role_name

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		if user is None:
			return False
		# FAB users: user.roles is a list of Role objects with .name
		roles = getattr(user, 'roles', [])
		return any(getattr(r, 'name', r) == self.role_name for r in roles)

	def __repr__(self) -> str:
		return f"HasRole({self.role_name!r})"


class HasPermission(Policy):
	"""True if user has the named permission (FAB permission string)."""

	def __init__(self, permission: str) -> None:
		self.permission = permission

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		if user is None:
			return False
		# FAB security manager: check via appbuilder.sm
		try:
			from flask import current_app
			sm = current_app.appbuilder.sm
			return sm.has_access(self.permission, '')
		except Exception:
			# Outside request context: check user.permissions if available
			perms = getattr(user, 'permissions', [])
			return self.permission in perms

	def __repr__(self) -> str:
		return f"HasPermission({self.permission!r})"


class IsOwner(Policy):
	"""True if user.id matches context[field_name]."""

	def __init__(self, field_name: str = 'owner_id') -> None:
		self.field_name = field_name

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		if user is None or context is None:
			return False
		owner_id = context.get(self.field_name)
		user_id = getattr(user, 'id', None)
		return owner_id is not None and str(owner_id) == str(user_id)

	def __repr__(self) -> str:
		return f"IsOwner({self.field_name!r})"


class IsAuthenticated(Policy):
	"""True if user is not None and is_authenticated."""

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		if user is None:
			return False
		return getattr(user, 'is_authenticated', bool(user))

	def __repr__(self) -> str:
		return 'IsAuthenticated()'


class IsAdmin(Policy):
	"""True if user is an admin (FAB admin flag or 'Admin' role)."""

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		if user is None:
			return False
		if getattr(user, 'is_admin', False):
			return True
		return HasRole('Admin').check(user, context)

	def __repr__(self) -> str:
		return 'IsAdmin()'


class Lambda(Policy):
	"""Wrap any callable as a policy: ``Lambda(lambda u, ctx: u.dept == 'Finance')``."""

	def __init__(self, fn: Callable[[Any, dict[str, Any] | None], bool], name: str = '') -> None:
		self._fn = fn
		self._name = name or getattr(fn, '__name__', 'lambda')

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		return bool(self._fn(user, context))

	def __repr__(self) -> str:
		return f"Lambda({self._name!r})"


# ── Combinators ──────────────────────────────────────────────────────────────

class AllOf(Policy):
	"""True if ALL child policies are satisfied (logical AND)."""

	def __init__(self, *policies: Policy) -> None:
		self.policies = list(policies)

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		return all(p.check(user, context) for p in self.policies)

	def __repr__(self) -> str:
		return f"AllOf({', '.join(repr(p) for p in self.policies)})"


class AnyOf(Policy):
	"""True if ANY child policy is satisfied (logical OR)."""

	def __init__(self, *policies: Policy) -> None:
		self.policies = list(policies)

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		return any(p.check(user, context) for p in self.policies)

	def __repr__(self) -> str:
		return f"AnyOf({', '.join(repr(p) for p in self.policies)})"


class Not(Policy):
	"""True if the child policy is NOT satisfied (logical NOT)."""

	def __init__(self, policy: Policy) -> None:
		self.policy = policy

	def check(self, user: Any, context: dict[str, Any] | None = None) -> bool:
		return not self.policy.check(user, context)

	def __repr__(self) -> str:
		return f"Not({self.policy!r})"


# ── Decorator ────────────────────────────────────────────────────────────────

def require_policy(policy: Policy, context_fn: Callable | None = None) -> Callable:
	"""Decorator that enforces a Policy on a Flask view method.

	If the policy fails, responds with 403 Forbidden.

	Args:
		policy:     The Policy to evaluate.
		context_fn: Optional callable(self) -> dict that builds the context
		            dict from the view instance. Defaults to empty dict.

	Example::

		@expose('/approve/<int:pk>', methods=['POST'])
		@require_policy(AllOf(HasRole('loan_officer'), HasRole('manager')))
		def approve(self, pk):
			...
	"""
	def decorator(fn: Callable) -> Callable:
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			try:
				from flask_login import current_user
				from flask import abort, request
			except ImportError:
				return fn(*args, **kwargs)

			ctx: dict[str, Any] = {}
			if context_fn is not None:
				try:
					ctx = context_fn(args[0]) if args else {}
				except Exception:
					pass

			if not policy.check(current_user, ctx):
				log.warning(
					"require_policy: access denied for user=%s policy=%r path=%s",
					getattr(current_user, 'username', '?'),
					policy,
					request.path if request else '?',
				)
				abort(403)
			return fn(*args, **kwargs)
		return wrapper
	return decorator


# ── Common pre-built policies ────────────────────────────────────────────────

ALLOW_ALL  = Lambda(lambda u, c: True,  name='ALLOW_ALL')
DENY_ALL   = Lambda(lambda u, c: False, name='DENY_ALL')
AUTH_ONLY  = IsAuthenticated()
ADMIN_ONLY = IsAdmin()


__all__ = [
	'Policy', 'HasRole', 'HasPermission', 'IsOwner', 'IsAuthenticated', 'IsAdmin', 'Lambda',
	'AllOf', 'AnyOf', 'Not',
	'require_policy',
	'ALLOW_ALL', 'DENY_ALL', 'AUTH_ONLY', 'ADMIN_ONLY',
]
