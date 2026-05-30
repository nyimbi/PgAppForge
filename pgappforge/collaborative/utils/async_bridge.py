"""
Async/sync bridge utilities for PgForge integration.

Provides utilities to bridge async service calls with synchronous Flask endpoints,
handling event loop management and error propagation.
"""

import asyncio
import logging
import functools
from typing import Any, Callable, TypeVar, Awaitable, Optional
from concurrent.futures import ThreadPoolExecutor
import threading


logger = logging.getLogger(__name__)

# Type variables for generic functions
T = TypeVar('T')


class AsyncBridge:
    """
    Simplified bridge for running async code in sync PgForge contexts.
    
    Provides a simple way to call async services from synchronous API endpoints
    without complex thread pool management.
    """
    
    @classmethod
    def run_async(cls, coro: Awaitable[T]) -> T:
        """
        Run async coroutine from sync context using asyncio.run().
        
        Args:
            coro: Coroutine to execute
            
        Returns:
            Coroutine result
            
        Raises:
            Exception: Any exception raised by the coroutine
        """
        try:
            # For PgForge context, simply use asyncio.run()
            return asyncio.run(coro)
        except Exception as e:
            logger.error(f"Async bridge error: {e}")
            raise
    
    @classmethod
    def sync_wrapper(cls, async_func: Callable[..., Awaitable[T]]) -> Callable[..., T]:
        """
        Decorator to convert async function to sync.
        
        Args:
            async_func: Async function to wrap
            
        Returns:
            Synchronous wrapper function
        """
        @functools.wraps(async_func)
        def sync_func(*args, **kwargs):
            coro = async_func(*args, **kwargs)
            return cls.run_async(coro)
        
        return sync_func


class AsyncServiceMixin:
    """
    Mixin for API classes that need to call async services.
    
    Provides convenience methods for calling async services from
    synchronous PgForge API endpoints.
    """
    
    def run_async_service_call(self, coro: Awaitable[T]) -> T:
        """
        Run async service call from sync API method.
        
        Args:
            coro: Async service method call
            
        Returns:
            Service method result
            
        Raises:
            Exception: Any exception from the service call
        """
        return AsyncBridge.run_async(coro)
    
    def call_async_service(self, service_method: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """
        Call async service method with arguments.
        
        Args:
            service_method: Async service method
            *args: Method arguments
            **kwargs: Method keyword arguments
            
        Returns:
            Service method result
        """
        coro = service_method(*args, **kwargs)
        return self.run_async_service_call(coro)


def sync_from_async(async_func: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """
    Decorator to create sync version of async function.
    
    Args:
        async_func: Async function to convert
        
    Returns:
        Synchronous version of the function
    """
    return AsyncBridge.sync_wrapper(async_func)


def run_async_in_sync(coro: Awaitable[T]) -> T:
    """
    Convenience function to run async coroutine from sync context.
    
    Args:
        coro: Coroutine to run
        
    Returns:
        Coroutine result
    """
    return AsyncBridge.run_async(coro)


# Cleanup function for application shutdown
def cleanup_async_bridge():
    """Clean up async bridge resources."""
    # Current AsyncBridge implementation doesn't maintain persistent resources
    # that require cleanup. asyncio.run() handles event loop lifecycle automatically.
    logger.debug("AsyncBridge cleanup completed (no resources to clean)")