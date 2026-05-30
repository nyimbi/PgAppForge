"""
Shared transaction management utilities for collaborative features.

Provides standardized transaction handling, deadlock detection and retry logic,
and savepoint management across all collaborative modules.
"""

import logging
import time
import random
from typing import Any, Callable, Optional, List, Dict, Type, Union
from functools import wraps
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class TransactionScope(Enum):
    """Transaction scope levels."""

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    EXCLUSIVE = "exclusive"


class TransactionState(Enum):
    """Transaction state tracking."""

    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    ERROR = "error"


@dataclass
class TransactionMetrics:
    """Transaction performance and error metrics."""

    start_time: datetime
    end_time: Optional[datetime] = None
    retry_count: int = 0
    deadlock_count: int = 0
    error_count: int = 0
    state: TransactionState = TransactionState.ACTIVE

    @property
    def duration(self) -> Optional[timedelta]:
        """Get transaction duration."""
        if self.end_time:
            return self.end_time - self.start_time
        return None


class TransactionManager:
    """
    Centralized transaction management for collaborative services.

    Provides consistent transaction handling, automatic retry logic for deadlocks,
    savepoint management, and transaction performance monitoring.
    """

    def __init__(self, session: Any = None, app_builder: Any = None):
        """
        Initialize transaction manager.

        Args:
            session: SQLAlchemy session (optional, will use app_builder.get_session if not provided)
            app_builder: PgForge instance for configuration and session access
        """
        self.app_builder = app_builder
        self._session = session

        # Configuration
        self.max_retry_attempts = 3
        self.base_retry_delay = 0.1  # 100ms
        self.max_retry_delay = 5.0  # 5 seconds
        self.deadlock_retry_enabled = True
        self.savepoint_enabled = True
        self.metrics_enabled = True

        # Load configuration
        if app_builder and app_builder.app:
            self._load_configuration()

        # Metrics tracking
        self._transaction_metrics: Dict[str, TransactionMetrics] = {}
        self._active_transactions: Dict[str, Any] = {}

        # Deadlock detection patterns
        self._deadlock_error_patterns = [
            "deadlock",
            "lock timeout",
            "resource busy",
            "could not serialize",
            "serialization failure",
        ]

    @property
    def session(self) -> Any:
        """
        Get the database session, with PgForge integration.
        
        Returns:
            SQLAlchemy session from app_builder or explicit session
        """
        if self._session is not None:
            return self._session
        
        if self.app_builder is not None:
            # Use PgForge's session management
            if hasattr(self.app_builder, 'get_session'):
                return self.app_builder.get_session
            elif hasattr(self.app_builder, 'session'):
                return self.app_builder.session
        
        raise ValueError(
            "No database session available. Provide session explicitly or "
            "ensure app_builder has session management configured."
        )
    
    @session.setter
    def session(self, value: Any) -> None:
        """Set the database session."""
        self._session = value

    def _load_configuration(self) -> None:
        """Load transaction configuration from Flask app."""
        config = self.app_builder.app.config

        self.max_retry_attempts = config.get("TRANSACTION_MAX_RETRY_ATTEMPTS", 3)
        self.base_retry_delay = config.get("TRANSACTION_BASE_RETRY_DELAY", 0.1)
        self.max_retry_delay = config.get("TRANSACTION_MAX_RETRY_DELAY", 5.0)
        self.deadlock_retry_enabled = config.get(
            "TRANSACTION_DEADLOCK_RETRY_ENABLED", True
        )
        self.savepoint_enabled = config.get("TRANSACTION_SAVEPOINT_ENABLED", True)
        self.metrics_enabled = config.get("TRANSACTION_METRICS_ENABLED", True)

    def _generate_transaction_id(self) -> str:
        """Generate unique transaction ID."""
        import uuid

        return f"tx_{uuid.uuid4().hex[:8]}"

    def _is_deadlock_error(self, error: Exception) -> bool:
        """
        Check if error is a deadlock-related error.

        Args:
            error: Exception to check

        Returns:
            True if error appears to be deadlock-related
        """
        error_message = str(error).lower()
        return any(
            pattern in error_message for pattern in self._deadlock_error_patterns
        )

    def _calculate_retry_delay(self, attempt: int) -> float:
        """
        Calculate retry delay with exponential backoff and jitter.

        Args:
            attempt: Current retry attempt number

        Returns:
            Delay in seconds
        """
        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_retry_delay * (2**attempt)

        # Add jitter to prevent thundering herd
        jitter = random.uniform(0.5, 1.5)
        delay *= jitter

        # Cap at maximum delay
        return min(delay, self.max_retry_delay)

    @contextmanager
    def transaction(
        self,
        scope: TransactionScope = TransactionScope.READ_WRITE,
        isolation_level: Optional[str] = None,
        retry_on_deadlock: bool = None,
        transaction_id: Optional[str] = None,
    ):
        """
        Context manager for database transactions with automatic retry logic.

        Args:
            scope: Transaction scope level
            isolation_level: Database isolation level
            retry_on_deadlock: Whether to retry on deadlock errors
            transaction_id: Optional transaction ID for tracking

        Yields:
            Transaction context
        """
        if retry_on_deadlock is None:
            retry_on_deadlock = self.deadlock_retry_enabled

        transaction_id = transaction_id or self._generate_transaction_id()
        attempt = 0

        # Initialize metrics
        if self.metrics_enabled:
            self._transaction_metrics[transaction_id] = TransactionMetrics(
                start_time=datetime.now()
            )

        while attempt <= self.max_retry_attempts:
            try:
                with self._single_transaction(
                    scope, isolation_level, transaction_id
                ) as tx_context:
                    yield tx_context

                # Success - update metrics and return
                if self.metrics_enabled and transaction_id in self._transaction_metrics:
                    metrics = self._transaction_metrics[transaction_id]
                    metrics.end_time = datetime.now()
                    metrics.state = TransactionState.COMMITTED

                logger.debug(f"Transaction {transaction_id} completed successfully")
                return

            except Exception as e:
                attempt += 1

                # Update metrics
                if self.metrics_enabled and transaction_id in self._transaction_metrics:
                    metrics = self._transaction_metrics[transaction_id]
                    metrics.error_count += 1

                    if self._is_deadlock_error(e):
                        metrics.deadlock_count += 1

                # Check if we should retry
                if (
                    retry_on_deadlock
                    and self._is_deadlock_error(e)
                    and attempt <= self.max_retry_attempts
                ):
                    retry_delay = self._calculate_retry_delay(attempt - 1)

                    logger.warning(
                        f"Deadlock detected in transaction {transaction_id}, "
                        f"retrying in {retry_delay:.2f}s (attempt {attempt}/{self.max_retry_attempts + 1})"
                    )

                    # Update retry metrics
                    if (
                        self.metrics_enabled
                        and transaction_id in self._transaction_metrics
                    ):
                        self._transaction_metrics[transaction_id].retry_count += 1

                    time.sleep(retry_delay)
                    continue
                else:
                    # Update final metrics state
                    if (
                        self.metrics_enabled
                        and transaction_id in self._transaction_metrics
                    ):
                        metrics = self._transaction_metrics[transaction_id]
                        metrics.end_time = datetime.now()
                        metrics.state = TransactionState.ERROR

                    logger.error(
                        f"Transaction {transaction_id} failed after {attempt} attempts: {e}"
                    )
                    raise

        # Should not reach here, but just in case
        raise RuntimeError(
            f"Transaction {transaction_id} exceeded maximum retry attempts"
        )

    @contextmanager
    def _single_transaction(
        self,
        scope: TransactionScope,
        isolation_level: Optional[str],
        transaction_id: str,
    ):
        """
        Context manager for a single transaction attempt.

        Args:
            scope: Transaction scope level
            isolation_level: Database isolation level
            transaction_id: Transaction ID for tracking

        Yields:
            Transaction context
        """
        if not self.session:
            raise ValueError("No database session available for transaction")

        # Set isolation level if specified
        original_isolation = None
        if isolation_level:
            try:
                # Handle different session types (PgForge vs raw SQLAlchemy)
                connection = None
                if hasattr(self.session, 'connection'):
                    connection = self.session.connection()
                elif hasattr(self.session, 'bind') and hasattr(self.session.bind, 'connect'):
                    connection = self.session.bind.connect()
                
                if connection and hasattr(connection, 'get_isolation_level'):
                    original_isolation = connection.get_isolation_level()
                    connection.set_isolation_level(isolation_level)
            except Exception as e:
                logger.warning(f"Failed to set isolation level {isolation_level}: {e}")

        # Track active transaction
        self._active_transactions[transaction_id] = {
            "scope": scope,
            "start_time": datetime.now(),
            "isolation_level": isolation_level,
        }

        try:
            # Begin transaction
            if scope == TransactionScope.READ_ONLY:
                # For read-only, we don't need explicit transaction management
                yield self.session
            else:
                # Begin explicit transaction
                yield self.session
                self.session.commit()

        except Exception as e:
            # Rollback on any error
            try:
                self.session.rollback()
                logger.debug(
                    f"Transaction {transaction_id} rolled back due to error: {e}"
                )
            except Exception as rollback_error:
                logger.error(
                    f"Failed to rollback transaction {transaction_id}: {rollback_error}"
                )
            raise

        finally:
            # Restore original isolation level
            if original_isolation is not None:
                try:
                    self.session.connection().set_isolation_level(original_isolation)
                except Exception as e:
                    logger.warning(f"Failed to restore isolation level: {e}")

            # Remove from active transactions
            self._active_transactions.pop(transaction_id, None)

    @contextmanager
    def savepoint(self, name: Optional[str] = None):
        """
        Context manager for database savepoints.

        Args:
            name: Optional savepoint name

        Yields:
            Savepoint context
        """
        if not self.savepoint_enabled:
            # If savepoints disabled, just yield session
            yield self.session
            return

        if not self.session:
            raise ValueError("No database session available for savepoint")

        # Generate savepoint name if not provided
        if name is None:
            import uuid

            name = f"sp_{uuid.uuid4().hex[:8]}"

        savepoint = None
        try:
            # Create savepoint
            savepoint = self.session.begin_nested()
            logger.debug(f"Created savepoint: {name}")
            yield self.session

        except Exception as e:
            # Rollback to savepoint
            if savepoint:
                try:
                    savepoint.rollback()
                    logger.debug(f"Rolled back to savepoint: {name}")
                except Exception as rollback_error:
                    logger.error(
                        f"Failed to rollback savepoint {name}: {rollback_error}"
                    )
            raise

        finally:
            # Commit savepoint if still active
            if savepoint and savepoint.is_active:
                try:
                    savepoint.commit()
                    logger.debug(f"Committed savepoint: {name}")
                except Exception as commit_error:
                    logger.error(f"Failed to commit savepoint {name}: {commit_error}")

    def get_transaction_metrics(self) -> Dict[str, TransactionMetrics]:
        """
        Get transaction performance metrics.

        Returns:
            Dictionary of transaction metrics by transaction ID
        """
        return self._transaction_metrics.copy()

    def get_active_transactions(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about currently active transactions.

        Returns:
            Dictionary of active transaction information
        """
        return self._active_transactions.copy()

    def clear_metrics(self) -> None:
        """Clear transaction metrics history."""
        self._transaction_metrics.clear()


# Decorator for automatic transaction management
def transaction_required(
    scope: TransactionScope = TransactionScope.READ_WRITE,
    retry_on_deadlock: bool = True,
    isolation_level: Optional[str] = None,
):
    """
    Decorator for automatic transaction management.

    Args:
        scope: Transaction scope level
        retry_on_deadlock: Whether to retry on deadlock errors
        isolation_level: Database isolation level

    Returns:
        Decorated function with transaction management
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Try to get transaction manager from self
            transaction_manager = None
            if args and hasattr(args[0], "transaction_manager"):
                transaction_manager = args[0].transaction_manager
            elif args and hasattr(args[0], "session"):
                # Create temporary transaction manager
                session = args[0].session
                app_builder = getattr(args[0], "app_builder", None)
                transaction_manager = TransactionManager(session, app_builder)

            if not transaction_manager:
                raise ValueError(
                    "No transaction manager available for transaction_required decorator"
                )

            with transaction_manager.transaction(
                scope, isolation_level, retry_on_deadlock
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


# Decorator for deadlock retry logic
def retry_on_deadlock(max_attempts: int = 3, base_delay: float = 0.1):
    """
    Decorator for automatic deadlock retry logic.

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Base delay between retries

    Returns:
        Decorated function with deadlock retry logic
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0

            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    attempt += 1

                    # Check if it's a deadlock error
                    error_message = str(e).lower()
                    deadlock_patterns = ["deadlock", "lock timeout", "resource busy"]
                    is_deadlock = any(
                        pattern in error_message for pattern in deadlock_patterns
                    )

                    if is_deadlock and attempt <= max_attempts:
                        delay = base_delay * (2 ** (attempt - 1))  # Exponential backoff
                        delay *= random.uniform(0.5, 1.5)  # Add jitter

                        logger.warning(
                            f"Deadlock detected in {func.__name__}, "
                            f"retrying in {delay:.2f}s (attempt {attempt}/{max_attempts + 1})"
                        )

                        time.sleep(delay)
                        continue
                    else:
                        raise

            raise RuntimeError(
                f"Function {func.__name__} exceeded maximum retry attempts"
            )

        return wrapper

    return decorator


class TransactionMixin:
    """
    Mixin class for adding transaction management capabilities.

    Provides transaction management methods that can be mixed into any
    collaborative service class.
    """

    def __init__(self, *args, **kwargs):
        """Initialize transaction mixin."""
        super().__init__(*args, **kwargs)
        self._transaction_manager: Optional[TransactionManager] = None

    @property
    def transaction_manager(self) -> TransactionManager:
        """Get or create transaction manager instance with PgForge integration."""
        if self._transaction_manager is None:
            # First try to get session from PgForge integration
            session = None
            app_builder = getattr(self, "app_builder", None)
            
            # Try different ways to get session
            if hasattr(self, "session"):
                session = self.session
            elif app_builder:
                if hasattr(app_builder, "get_session"):
                    session = app_builder.get_session
                elif hasattr(app_builder, "session"):
                    session = app_builder.session

            # Create transaction manager with PgForge integration
            self._transaction_manager = TransactionManager(session, app_builder)

        return self._transaction_manager

    def with_transaction(
        self, scope: TransactionScope = TransactionScope.READ_WRITE, **kwargs
    ):
        """
        Context manager for transactions.

        Args:
            scope: Transaction scope level
            **kwargs: Additional transaction parameters

        Returns:
            Transaction context manager
        """
        return self.transaction_manager.transaction(scope, **kwargs)

    def with_savepoint(self, name: Optional[str] = None):
        """
        Context manager for savepoints.

        Args:
            name: Optional savepoint name

        Returns:
            Savepoint context manager
        """
        return self.transaction_manager.savepoint(name)

    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with automatic deadlock retry.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """

        @retry_on_deadlock()
        def wrapper():
            return func(*args, **kwargs)

        return wrapper()
