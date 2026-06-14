"""Decorator for subscribing plugin methods to event patterns.

Usage
-----
    from pgappforge.events import on_event

    class MyPlugin(BasePlugin):

        @on_event('finance.ar.invoice.approved')
        def handle_invoice_approved(self, event_type, payload, tenant_id):
            ...

    # Module-level handlers (outside a class) also work:
    @on_event('crm.customer.*')
    def log_customer_events(event_type, payload, tenant_id):
        log.info('%s tenant=%s', event_type, tenant_id)
"""
from __future__ import annotations

import functools
from typing import Callable


def on_event(pattern: str) -> Callable:
	"""Decorator that registers a function/method as an event handler.

	For module-level functions: registered immediately at import time.
	For class methods: registration is deferred — call
	  ``EventRouter.subscribe(pattern, bound_method)`` in ``post_initialize()``,
	  or rely on BasePlugin.post_initialize() which reads ``subscribe_to()``.

	The decorated callable must accept keyword arguments:
	  event_type: str, payload: dict, tenant_id: str
	"""
	def decorator(fn: Callable) -> Callable:
		# Mark the function with the pattern so BasePlugin.post_initialize
		# can discover and register it automatically.
		if not hasattr(fn, '_event_patterns'):
			fn._event_patterns = []
		fn._event_patterns.append(pattern)

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			return fn(*args, **kwargs)
		wrapper._event_patterns = fn._event_patterns

		# Register immediately for module-level (non-method) functions.
		# Methods are detected by checking whether the first parameter is 'self'.
		import inspect
		params = list(inspect.signature(fn).parameters)
		if not params or params[0] != 'self':
			from pgappforge.events.router import get_router
			get_router().subscribe(pattern, fn)

		return wrapper
	return decorator


__all__ = ['on_event']
