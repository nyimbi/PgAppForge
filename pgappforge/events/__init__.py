"""PgAppForge durable event router.

Upgrade from the simple in-process _EVENT_BUS to a glob-pattern,
multi-worker-safe, retry-capable event routing system.

Usage
-----
    from pgappforge.events import on_event, emit, EventRouter

    # Register a handler in any plugin
    @on_event('finance.ar.invoice.*')
    def sync_to_tax_system(event_type: str, payload: dict, tenant_id: str) -> None:
        ...

    # Emit from any service
    emit('finance.ar.invoice.approved', {'invoice_id': inv.id}, tenant_id=tid, session=session)
"""
from pgappforge.events.router import EventRouter, emit, get_router
from pgappforge.events.decorators import on_event

__all__ = ['EventRouter', 'emit', 'get_router', 'on_event']
