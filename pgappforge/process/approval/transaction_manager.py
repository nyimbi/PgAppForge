"""
Database Transaction Manager for Approval System

Provides robust transaction boundaries, optimistic locking, and concurrent
operation safety for approval workflow database operations.

SECURITY IMPROVEMENTS:
- Atomic transaction boundaries to prevent data inconsistency
- Optimistic locking to handle concurrent modifications
- Deadlock detection and retry logic
- Comprehensive error handling and recovery
"""

import logging
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Callable, List
from enum import Enum
from dataclasses import dataclass
from functools import wraps

from flask import current_app
from pgappforge import db
from sqlalchemy.exc import (
    IntegrityError, 
    OperationalError, 
    DatabaseError, 
    DisconnectionError,
    InvalidRequestError,
    TimeoutError as SQLTimeoutError
)
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy import text

from .audit_logger import ApprovalAuditLogger

log = logging.getLogger(__name__)


class TransactionIsolationLevel(Enum):
    """Database transaction isolation levels."""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED" 
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


class RetryStrategy(Enum):
    """Retry strategies for transient failures."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    IMMEDIATE = "immediate"
    NO_RETRY = "no_retry"


@dataclass
class TransactionConfig:
    """Configuration for database transactions."""
    max_retries: int = 3
    retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    base_delay: float = 0.1
    max_delay: float = 2.0
    timeout_seconds: int = 30
    isolation_level: TransactionIsolationLevel = TransactionIsolationLevel.READ_COMMITTED
    enable_optimistic_locking: bool = True
    deadlock_retry_attempts: int = 5


class TransactionError(Exception):
    """Base exception for transaction-related errors."""
    pass


class DeadlockError(TransactionError):
    """Raised when a database deadlock is detected."""
    pass


class OptimisticLockError(TransactionError):
    """Raised when optimistic locking conflict occurs."""
    pass


class TransactionTimeoutError(TransactionError):
    """Raised when transaction exceeds timeout."""
    pass


class DatabaseTransactionManager:
    """
    Manages database transactions with robust error handling and concurrency control.
    
    SECURITY FEATURES:
    - Atomic transaction boundaries
    - Optimistic locking for concurrent safety
    - Deadlock detection and recovery
    - Comprehensive audit logging
    - Timeout protection against long-running operations
    """
    
    def __init__(self, config: Optional[TransactionConfig] = None):
        self.config = config or TransactionConfig()
        self.audit_logger = ApprovalAuditLogger()
        self._local = threading.local()
    
    @contextmanager
    def transaction(self, operation_name: str = "database_operation", 
                   config: Optional[TransactionConfig] = None):
        """
        Context manager for atomic database transactions.
        
        Args:
            operation_name: Name of the operation for audit logging
            config: Optional transaction configuration override
            
        Yields:
            Database session with transaction active
            
        Raises:
            TransactionError: If transaction fails after all retries
        """
        effective_config = config or self.config
        session = db.session
        transaction_id = self._generate_transaction_id()
        start_time = datetime.now(tz=timezone.utc)
        
        # Log transaction start
        self.audit_logger.log_security_event('transaction_started', {
            'transaction_id': transaction_id,
            'operation_name': operation_name,
            'isolation_level': effective_config.isolation_level.value,
            'max_retries': effective_config.max_retries
        })
        
        retry_count = 0
        last_error = None
        
        while retry_count <= effective_config.max_retries:
            try:
                # Set isolation level if needed - SECURITY FIX: Use SQLAlchemy's native isolation setting
                if effective_config.isolation_level != TransactionIsolationLevel.READ_COMMITTED:
                    # CRITICAL SECURITY FIX: Use SQLAlchemy's native isolation level setting
                    # instead of raw SQL to completely prevent SQL injection
                    try:
                        # SQLAlchemy provides safe isolation level setting via connection.execution_options
                        if effective_config.isolation_level == TransactionIsolationLevel.READ_UNCOMMITTED:
                            session.connection().execution_options(isolation_level="READ_uncommitted")
                        elif effective_config.isolation_level == TransactionIsolationLevel.REPEATABLE_READ:
                            session.connection().execution_options(isolation_level="repeatable_read")
                        elif effective_config.isolation_level == TransactionIsolationLevel.SERIALIZABLE:
                            session.connection().execution_options(isolation_level="serializable")
                        else:
                            # Log security violation for invalid isolation level with safe enum name
                            self.audit_logger.log_security_event('invalid_isolation_level', {
                                'transaction_id': transaction_id,
                                'operation_name': operation_name,
                                'isolation_level_name': effective_config.isolation_level.name,
                                'reason': 'Isolation level not supported by SQLAlchemy execution_options'
                            })
                            raise TransactionError("Invalid isolation level specified")
                    except Exception as isolation_error:
                        # Log failure to set isolation level with sanitized information only
                        self.audit_logger.log_security_event('isolation_level_set_failed', {
                            'transaction_id': transaction_id,
                            'operation_name': operation_name,
                            'isolation_level_name': effective_config.isolation_level.name,
                            'error_type': type(isolation_error).__name__
                        })
                        # Continue without custom isolation level rather than fail
                        log.warning(f"Failed to set isolation level {effective_config.isolation_level.name}: {type(isolation_error).__name__}")
                
                # Begin transaction
                transaction = session.begin()
                
                try:
                    # Check timeout
                    if (datetime.now(tz=timezone.utc) - start_time).total_seconds() > effective_config.timeout_seconds:
                        raise TransactionTimeoutError(f"Transaction timeout after {effective_config.timeout_seconds}s")
                    
                    # Store transaction context
                    self._set_transaction_context(transaction_id, operation_name, start_time)
                    
                    yield session
                    
                    # Commit transaction
                    transaction.commit()
                    
                    # Log successful completion
                    duration = (datetime.now(tz=timezone.utc) - start_time).total_seconds()
                    self.audit_logger.log_security_event('transaction_completed', {
                        'transaction_id': transaction_id,
                        'operation_name': operation_name,
                        'duration_seconds': duration,
                        'retry_count': retry_count
                    })
                    
                    return
                    
                except Exception as e:
                    # Rollback on any exception
                    transaction.rollback()
                    raise e
                    
            except (StaleDataError, OptimisticLockError) as e:
                last_error = e
                retry_count += 1
                
                if retry_count <= effective_config.max_retries:
                    delay = self._calculate_retry_delay(retry_count, effective_config)
                    
                    self.audit_logger.log_security_event('transaction_optimistic_lock_retry', {
                        'transaction_id': transaction_id,
                        'operation_name': operation_name,
                        'retry_count': retry_count,
                        'delay_seconds': delay,
                        'error': str(e)
                    })
                    
                    time.sleep(delay)
                    continue
                else:
                    self._log_transaction_failure(transaction_id, operation_name, e, retry_count)
                    raise OptimisticLockError(f"Optimistic locking failed after {retry_count} retries") from e
            
            except (OperationalError, DatabaseError) as e:
                last_error = e
                
                # Check if it's a deadlock
                if self._is_deadlock_error(e):
                    retry_count += 1
                    
                    if retry_count <= effective_config.deadlock_retry_attempts:
                        delay = self._calculate_retry_delay(retry_count, effective_config)
                        
                        self.audit_logger.log_security_event('transaction_deadlock_retry', {
                            'transaction_id': transaction_id,
                            'operation_name': operation_name,
                            'retry_count': retry_count,
                            'delay_seconds': delay,
                            'error': str(e)
                        })
                        
                        time.sleep(delay)
                        continue
                    else:
                        self._log_transaction_failure(transaction_id, operation_name, e, retry_count)
                        raise DeadlockError(f"Deadlock persisted after {retry_count} retries") from e
                else:
                    # Non-retryable database error
                    self._log_transaction_failure(transaction_id, operation_name, e, retry_count)
                    raise TransactionError(f"Database error in {operation_name}: {str(e)}") from e
            
            except Exception as e:
                # Non-retryable error
                last_error = e
                self._log_transaction_failure(transaction_id, operation_name, e, retry_count)
                raise TransactionError(f"Transaction failed in {operation_name}: {str(e)}") from e
        
        # If we get here, all retries were exhausted
        self._log_transaction_failure(transaction_id, operation_name, last_error, retry_count)
        raise TransactionError(f"Transaction failed after {retry_count} retries: {str(last_error)}")
    
    def execute_with_optimistic_locking(self, entity, update_func: Callable, 
                                       operation_name: str = "optimistic_update") -> Any:
        """
        Execute an update with optimistic locking protection.
        
        Args:
            entity: Database entity to update
            update_func: Function that performs the update
            operation_name: Name for audit logging
            
        Returns:
            Result of update_func
            
        Raises:
            OptimisticLockError: If concurrent modification detected
        """
        if not hasattr(entity, 'version') or not self.config.enable_optimistic_locking:
            # No version field or optimistic locking disabled
            return update_func(entity)
        
        original_version = entity.version
        
        with self.transaction(f"{operation_name}_with_locking"):
            # Refresh entity to get latest version
            db.session.refresh(entity)
            
            if entity.version != original_version:
                raise OptimisticLockError(
                    f"Entity {type(entity).__name__}:{entity.id} was modified concurrently"
                )
            
            # Perform update
            result = update_func(entity)
            
            # Increment version
            entity.version = (entity.version or 0) + 1
            entity.updated_at = datetime.now(tz=timezone.utc)
            
            return result
    
    def batch_operation(self, operations: List[Callable], 
                       operation_name: str = "batch_operation",
                       chunk_size: int = 100) -> List[Any]:
        """
        Execute multiple operations in batches with transaction safety.
        
        Args:
            operations: List of callable operations
            operation_name: Name for audit logging
            chunk_size: Number of operations per batch
            
        Returns:
            List of operation results
        """
        results = []
        
        for i in range(0, len(operations), chunk_size):
            chunk = operations[i:i + chunk_size]
            
            with self.transaction(f"{operation_name}_batch_{i//chunk_size + 1}"):
                chunk_results = []
                for operation in chunk:
                    try:
                        result = operation()
                        chunk_results.append(result)
                    except Exception as e:
                        self.audit_logger.log_security_event('batch_operation_item_failed', {
                            'operation_name': operation_name,
                            'batch_index': i//chunk_size + 1,
                            'item_index': len(chunk_results),
                            'error': str(e)
                        })
                        raise
                
                results.extend(chunk_results)
        
        return results
    
    def _generate_transaction_id(self) -> str:
        """Generate unique transaction ID for tracking."""
        from .crypto_config import SecureCryptoConfig
        return SecureCryptoConfig.generate_secure_token("txn")
    
    def _set_transaction_context(self, transaction_id: str, operation_name: str, start_time: datetime):
        """Set transaction context in thread-local storage."""
        if not hasattr(self._local, 'context'):
            self._local.context = {}
        
        self._local.context = {
            'transaction_id': transaction_id,
            'operation_name': operation_name,
            'start_time': start_time
        }
    
    def _calculate_retry_delay(self, retry_count: int, config: TransactionConfig) -> float:
        """Calculate delay for retry based on strategy."""
        if config.retry_strategy == RetryStrategy.NO_RETRY:
            return 0
        elif config.retry_strategy == RetryStrategy.IMMEDIATE:
            return 0
        elif config.retry_strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * retry_count
        elif config.retry_strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay * (2 ** (retry_count - 1))
        else:
            delay = config.base_delay
        
        return min(delay, config.max_delay)
    
    def _is_deadlock_error(self, error: Exception) -> bool:
        """Check if error is a database deadlock."""
        error_str = str(error).lower()
        deadlock_indicators = [
            'deadlock', 'lock wait timeout', 'lock timeout',
            'could not serialize', 'serialization failure'
        ]
        
        return any(indicator in error_str for indicator in deadlock_indicators)
    
    def _log_transaction_failure(self, transaction_id: str, operation_name: str, 
                                error: Exception, retry_count: int):
        """Log transaction failure for audit purposes."""
        self.audit_logger.log_security_event('transaction_failed', {
            'transaction_id': transaction_id,
            'operation_name': operation_name,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'retry_count': retry_count,
            'is_deadlock': self._is_deadlock_error(error)
        })


# Global instance for convenience
_global_transaction_manager = None


def get_transaction_manager() -> DatabaseTransactionManager:
    """Get global transaction manager instance."""
    global _global_transaction_manager
    if _global_transaction_manager is None:
        _global_transaction_manager = DatabaseTransactionManager()
    return _global_transaction_manager


def transactional(operation_name: str = None, config: TransactionConfig = None):
    """
    Decorator for automatic transaction management.
    
    Args:
        operation_name: Name for audit logging
        config: Transaction configuration
    
    Example:
        @transactional("update_approval_status")
        def update_status(self, approval_id, new_status):
            # Database operations here are automatically transactional
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            
            with get_transaction_manager().transaction(op_name, config):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator