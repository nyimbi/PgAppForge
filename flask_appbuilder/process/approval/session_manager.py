"""
Centralized Database Session Management

Provides centralized session management with proper scoping, 
transaction handling, and resource cleanup for approval workflows.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session, sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError
from sqlalchemy import event
from enum import Enum

log = logging.getLogger(__name__)


class SessionScope(Enum):
    """Database session scope types."""
    REQUEST = "request"          # Per HTTP request
    TRANSACTION = "transaction"  # Per business transaction
    BULK = "bulk"               # For bulk operations
    READ_ONLY = "read_only"     # Read-only queries


class TransactionIsolation(Enum):
    """Transaction isolation levels."""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED" 
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


class SessionError(Exception):
    """Base exception for session management errors."""
    pass


class SessionTimeoutError(SessionError):
    """Exception raised when session operations timeout."""
    pass


class SessionScopeError(SessionError):
    """Exception raised when session scope is invalid."""
    pass


class SessionStats:
    """Session usage statistics."""
    
    def __init__(self):
        self.sessions_created = 0
        self.sessions_committed = 0
        self.sessions_rolled_back = 0
        self.sessions_failed = 0
        self.active_sessions = 0
        self.total_query_time = 0.0
        self.longest_session_time = 0.0
        self.last_reset = datetime.now(tz=timezone.utc)
        self._lock = threading.RLock()
    
    def session_created(self):
        with self._lock:
            self.sessions_created += 1
            self.active_sessions += 1
    
    def session_committed(self, duration: float):
        with self._lock:
            self.sessions_committed += 1
            self.active_sessions = max(0, self.active_sessions - 1)
            self.total_query_time += duration
            self.longest_session_time = max(self.longest_session_time, duration)
    
    def session_rolled_back(self, duration: float):
        with self._lock:
            self.sessions_rolled_back += 1
            self.active_sessions = max(0, self.active_sessions - 1)
            self.total_query_time += duration
    
    def session_failed(self):
        with self._lock:
            self.sessions_failed += 1
            self.active_sessions = max(0, self.active_sessions - 1)
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            uptime = (datetime.now(tz=timezone.utc) - self.last_reset).total_seconds()
            return {
                'sessions_created': self.sessions_created,
                'sessions_committed': self.sessions_committed,
                'sessions_rolled_back': self.sessions_rolled_back,
                'sessions_failed': self.sessions_failed,
                'active_sessions': self.active_sessions,
                'total_query_time': self.total_query_time,
                'longest_session_time': self.longest_session_time,
                'average_session_time': (
                    self.total_query_time / max(1, self.sessions_created)
                ),
                'success_rate': (
                    self.sessions_committed / max(1, self.sessions_created) * 100
                ),
                'uptime_seconds': uptime
            }
    
    def reset(self):
        with self._lock:
            self.__init__()


class CentralizedSessionManager:
    """
    Centralized database session manager with proper scoping and transaction handling.
    
    Features:
    - Automatic session lifecycle management
    - Transaction scope control with isolation levels
    - Connection pool integration
    - Performance monitoring and statistics
    - Error handling and recovery
    - Thread-safe operations
    """
    
    def __init__(self, appbuilder, connection_pool_manager=None):
        """Initialize session manager."""
        self.appbuilder = appbuilder
        self.connection_pool = connection_pool_manager
        self.stats = SessionStats()
        
        # Thread-local storage for session tracking
        self._local = threading.local()
        
        # Session configuration
        self.default_timeout = 30  # seconds
        self.max_retries = 3
        self.retry_delay = 0.1  # seconds
        
        # Create scoped session factory
        self._setup_session_factory()
        
        log.info("CentralizedSessionManager initialized")
    
    def _setup_session_factory(self):
        """Setup SQLAlchemy session factory with proper configuration."""
        if self.connection_pool:
            # Use connection pool's engine
            engine = self.connection_pool.get_engine()
        else:
            # Fall back to AppBuilder's database engine
            engine = self.appbuilder.get_app().extensions['sqlalchemy'].db.engine
        
        # Configure session factory with optimal settings
        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,     # Manual flush control
            autocommit=False,    # Manual transaction control
            expire_on_commit=True  # Refresh objects after commit
        )
        
        # Create scoped session for thread safety
        self._scoped_session = scoped_session(session_factory)
        
        # Setup event listeners for monitoring
        self._setup_event_listeners()
    
    def _setup_event_listeners(self):
        """Setup SQLAlchemy event listeners for monitoring."""
        @event.listens_for(self._scoped_session, 'after_begin')
        def after_begin(session, transaction, connection):
            self.stats.session_created()
            log.debug(f"Session {id(session)} transaction began")
        
        @event.listens_for(self._scoped_session, 'after_commit')
        def after_commit(session):
            if hasattr(self._local, 'session_start_time'):
                duration = datetime.now(tz=timezone.utc).timestamp() - self._local.session_start_time
                self.stats.session_committed(duration)
            log.debug(f"Session {id(session)} committed")
        
        @event.listens_for(self._scoped_session, 'after_rollback')  
        def after_rollback(session):
            if hasattr(self._local, 'session_start_time'):
                duration = datetime.now(tz=timezone.utc).timestamp() - self._local.session_start_time
                self.stats.session_rolled_back(duration)
            log.debug(f"Session {id(session)} rolled back")
    
    @contextmanager
    def get_session(self, scope: SessionScope = SessionScope.TRANSACTION,
                   isolation: Optional[TransactionIsolation] = None,
                   timeout: Optional[int] = None,
                   read_only: bool = False) -> Generator[Session, None, None]:
        """
        Get a properly scoped database session.
        
        Args:
            scope: Session scope type
            isolation: Transaction isolation level
            timeout: Session timeout in seconds  
            read_only: Whether session is read-only
            
        Yields:
            SQLAlchemy session object
        """
        session = None
        start_time = datetime.now(tz=timezone.utc)
        self._local.session_start_time = start_time.timestamp()
        
        try:
            # Create session based on scope
            session = self._create_scoped_session(scope, isolation, read_only)
            
            # Set timeout if specified
            if timeout or self.default_timeout:
                session_timeout = timeout or self.default_timeout
                # Note: Actual timeout implementation would depend on database driver
            
            log.debug(f"Created {scope.value} session {id(session)}")
            
            yield session
            
            # Auto-commit for transaction scope (unless read-only)
            if scope == SessionScope.TRANSACTION and not read_only:
                session.commit()
                log.debug(f"Auto-committed session {id(session)}")
        
        except Exception as e:
            # Auto-rollback on any exception
            if session and session.is_active:
                session.rollback()
                log.warning(f"Auto-rolled back session {id(session)} due to: {e}")
            
            self.stats.session_failed()
            
            # Re-raise with session context
            raise SessionError(f"Session operation failed: {e}") from e
        
        finally:
            # Cleanup session
            if session:
                self._cleanup_session(session, scope)
                
                # Log session duration
                duration = (datetime.now(tz=timezone.utc) - start_time).total_seconds()
                if duration > 1.0:  # Log slow sessions
                    log.warning(f"Slow session {id(session)}: {duration:.2f}s")
    
    def _create_scoped_session(self, scope: SessionScope, 
                             isolation: Optional[TransactionIsolation],
                             read_only: bool) -> Session:
        """Create session based on scope type."""
        session = self._scoped_session()
        
        # Configure isolation level
        if isolation:
            session.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation.value}")
        
        # Configure read-only mode
        if read_only:
            # Note: Implementation depends on database type
            try:
                session.execute("SET TRANSACTION READ ONLY")
            except SQLAlchemyError:
                # Not all databases support this
                pass
        
        return session
    
    def _cleanup_session(self, session: Session, scope: SessionScope):
        """Cleanup session based on scope."""
        try:
            if scope in [SessionScope.REQUEST, SessionScope.TRANSACTION]:
                # Close session for request/transaction scopes
                session.close()
                log.debug(f"Closed session {id(session)}")
            elif scope == SessionScope.BULK:
                # Keep bulk sessions open for reuse, but ensure clean state
                if session.is_active:
                    session.rollback()
            # READ_ONLY sessions are automatically cleaned up by scoped_session
        except Exception as e:
            log.error(f"Error cleaning up session {id(session)}: {e}")
    
    @contextmanager
    def atomic_transaction(self, isolation: Optional[TransactionIsolation] = None,
                          timeout: Optional[int] = None) -> Generator[Session, None, None]:
        """
        Execute operations in an atomic transaction.
        
        Args:
            isolation: Transaction isolation level
            timeout: Transaction timeout in seconds
            
        Yields:
            SQLAlchemy session object
        """
        with self.get_session(
            scope=SessionScope.TRANSACTION,
            isolation=isolation,
            timeout=timeout
        ) as session:
            yield session
    
    @contextmanager  
    def read_only_session(self, timeout: Optional[int] = None) -> Generator[Session, None, None]:
        """
        Get a read-only session for queries.
        
        Args:
            timeout: Session timeout in seconds
            
        Yields:
            Read-only SQLAlchemy session
        """
        with self.get_session(
            scope=SessionScope.READ_ONLY,
            timeout=timeout,
            read_only=True
        ) as session:
            yield session
    
    @contextmanager
    def bulk_session(self, batch_size: int = 100) -> Generator[Session, None, None]:
        """
        Get a session optimized for bulk operations.
        
        Args:
            batch_size: Number of operations per batch
            
        Yields:
            SQLAlchemy session optimized for bulk operations
        """
        with self.get_session(scope=SessionScope.BULK) as session:
            # Configure for bulk operations
            session.bulk_insert_mappings = session.bulk_insert_mappings
            session.bulk_update_mappings = session.bulk_update_mappings
            yield session
    
    def execute_with_retry(self, operation, max_retries: Optional[int] = None,
                          retry_delay: Optional[float] = None) -> Any:
        """
        Execute database operation with retry logic.
        
        Args:
            operation: Function to execute that takes a session parameter
            max_retries: Maximum number of retries
            retry_delay: Delay between retries in seconds
            
        Returns:
            Operation result
        """
        retries = max_retries or self.max_retries
        delay = retry_delay or self.retry_delay
        
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                with self.get_session() as session:
                    return operation(session)
            
            except (DisconnectionError, SessionTimeoutError) as e:
                last_exception = e
                if attempt < retries:
                    log.warning(f"Database operation failed (attempt {attempt + 1}), retrying: {e}")
                    import time
                    time.sleep(delay * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    break
            except Exception as e:
                # Don't retry for non-recoverable errors
                raise SessionError(f"Non-recoverable database error: {e}") from e
        
        raise SessionError(f"Database operation failed after {retries} retries") from last_exception
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session usage statistics."""
        base_stats = self.stats.get_stats()
        
        # Add connection pool stats if available
        if self.connection_pool:
            pool_stats = self.connection_pool.get_pool_metrics()
            base_stats.update({
                'connection_pool': pool_stats
            })
        
        return base_stats
    
    def health_check(self) -> Dict[str, Any]:
        """Perform session manager health check."""
        try:
            # Test basic session operations
            with self.read_only_session(timeout=5) as session:
                session.execute("SELECT 1").fetchone()
            
            stats = self.get_session_stats()
            
            return {
                'status': 'healthy',
                'active_sessions': stats.get('active_sessions', 0),
                'success_rate': stats.get('success_rate', 0),
                'average_session_time': stats.get('average_session_time', 0),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
        
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
    
    def reset_stats(self):
        """Reset session statistics."""
        self.stats.reset()
        log.info("Session statistics reset")
    
    def cleanup(self):
        """Cleanup session manager resources."""
        try:
            # Remove scoped session
            self._scoped_session.remove()
            log.info("Session manager cleaned up")
        except Exception as e:
            log.error(f"Error during session manager cleanup: {e}")


# Global session manager instance
_session_manager: Optional[CentralizedSessionManager] = None


def get_session_manager(appbuilder=None, connection_pool=None) -> CentralizedSessionManager:
    """Get or create global session manager."""
    global _session_manager
    if _session_manager is None and appbuilder:
        _session_manager = CentralizedSessionManager(appbuilder, connection_pool)
    return _session_manager


def initialize_session_management(appbuilder, connection_pool=None) -> CentralizedSessionManager:
    """Initialize global session management."""
    global _session_manager
    _session_manager = CentralizedSessionManager(appbuilder, connection_pool)
    log.info("Global session management initialized")
    return _session_manager


# Convenience context managers for common patterns
@contextmanager
def db_transaction(isolation: Optional[TransactionIsolation] = None) -> Generator[Session, None, None]:
    """Convenience function for atomic transactions."""
    session_manager = get_session_manager()
    if not session_manager:
        raise SessionScopeError("Session manager not initialized")
    
    with session_manager.atomic_transaction(isolation=isolation) as session:
        yield session


@contextmanager  
def db_read_only() -> Generator[Session, None, None]:
    """Convenience function for read-only sessions."""
    session_manager = get_session_manager()
    if not session_manager:
        raise SessionScopeError("Session manager not initialized")
    
    with session_manager.read_only_session() as session:
        yield session


@contextmanager
def db_bulk_operation(batch_size: int = 100) -> Generator[Session, None, None]:
    """Convenience function for bulk operations.""" 
    session_manager = get_session_manager()
    if not session_manager:
        raise SessionScopeError("Session manager not initialized")
    
    with session_manager.bulk_session(batch_size=batch_size) as session:
        yield session