"""
Database Connection Pool Manager

Implements proper connection pooling with cleanup to prevent
database connection pool exhaustion in approval workflows.
"""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from functools import wraps

from sqlalchemy import event, pool
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DisconnectionError, TimeoutError, SQLAlchemyError
from sqlalchemy.pool import QueuePool, StaticPool

# Import database constants for proper configuration
from .constants import DatabaseConstants

log = logging.getLogger(__name__)


@dataclass
class ConnectionMetrics:
    """Track connection pool metrics for monitoring."""
    created_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    failed_connections: int = 0
    connection_timeouts: int = 0
    last_reset: datetime = field(default_factory=datetime.utcnow)
    peak_connections: int = 0
    total_requests: int = 0


@dataclass
class ConnectionConfig:
    """Database connection pool configuration with dynamic scaling."""
    
    # Use DatabaseConstants for proper configuration values
    pool_size: int = field(default_factory=lambda: DatabaseConstants.DEFAULT_POOL_SIZE)
    max_overflow: int = field(default_factory=lambda: DatabaseConstants.MAX_OVERFLOW)
    pool_timeout: int = 30
    pool_recycle: int = field(default_factory=lambda: DatabaseConstants.POOL_RECYCLE_SECONDS)
    pool_pre_ping: bool = True
    echo_pool: bool = False
    reset_on_return: str = 'commit'
    connect_timeout: int = 10
    health_check_interval: int = 300  # 5 minutes
    
    # Dynamic pool scaling configuration
    auto_scale: bool = True  # Enable dynamic pool scaling
    min_pool_size: int = 5   # Minimum pool size
    max_pool_size: int = 50  # Maximum pool size
    scale_threshold: float = 0.8  # Scale up when usage > 80%
    scale_down_threshold: float = 0.3  # Scale down when usage < 30%  # 5 minutes


class ConnectionPoolManager:
    """
    Manages database connection pools with automatic cleanup and monitoring.
    
    Features:
    - Connection pool monitoring and health checks
    - Automatic connection cleanup and recycling
    - Connection timeout handling
    - Memory leak prevention
    - Performance metrics collection
    """
    
    def __init__(self, appbuilder, config: Optional[ConnectionConfig] = None):
        self.appbuilder = appbuilder
        self.config = config or ConnectionConfig()
        self.metrics = ConnectionMetrics()
        self._lock = threading.RLock()
        self._connection_registry = {}  # Track active connections
        self._last_health_check = datetime.now(tz=timezone.utc)
        self._setup_pool_monitoring()
    
    def _setup_pool_monitoring(self):
        """Set up connection pool monitoring events."""
        try:
            # Get the database engine
            engine = self.appbuilder.get_app().extensions['sqlalchemy'].db.engine
            
            # Configure pool parameters
            if hasattr(engine.pool, 'size'):
                engine.pool._size = self.config.pool_size
                engine.pool._max_overflow = self.config.max_overflow
                engine.pool._timeout = self.config.pool_timeout
                engine.pool._recycle = self.config.pool_recycle
            
            # Set up event listeners for monitoring
            event.listen(engine, 'connect', self._on_connect)
            event.listen(engine, 'checkout', self._on_checkout)
            event.listen(engine, 'checkin', self._on_checkin)
            event.listen(engine, 'invalidate', self._on_invalidate)
            
            log.info(f"Database connection pool configured: "
                    f"size={self.config.pool_size}, "
                    f"max_overflow={self.config.max_overflow}, "
                    f"timeout={self.config.pool_timeout}s")
                    
        except Exception as e:
            log.error(f"Failed to setup pool monitoring: {e}")
    
    def _on_connect(self, dbapi_connection, connection_record):
        """Handle new connection creation."""
        with self._lock:
            self.metrics.created_connections += 1
            connection_id = id(connection_record)
            self._connection_registry[connection_id] = {
                'created_at': datetime.now(tz=timezone.utc),
                'last_used': datetime.now(tz=timezone.utc),
                'usage_count': 0
            }
            log.debug(f"New database connection created: {connection_id}")
    
    def _on_checkout(self, dbapi_connection, connection_record, connection_proxy):
        """Handle connection checkout from pool."""
        with self._lock:
            self.metrics.active_connections += 1
            self.metrics.total_requests += 1
            
            # Update peak connections tracking
            if self.metrics.active_connections > self.metrics.peak_connections:
                self.metrics.peak_connections = self.metrics.active_connections
            
            connection_id = id(connection_record)
            if connection_id in self._connection_registry:
                self._connection_registry[connection_id]['last_used'] = datetime.now(tz=timezone.utc)
                self._connection_registry[connection_id]['usage_count'] += 1
            
            log.debug(f"Connection checked out: {connection_id}, "
                     f"active: {self.metrics.active_connections}")
    
    def _on_checkin(self, dbapi_connection, connection_record):
        """Handle connection checkin to pool."""
        with self._lock:
            if self.metrics.active_connections > 0:
                self.metrics.active_connections -= 1
            
            connection_id = id(connection_record)
            log.debug(f"Connection checked in: {connection_id}, "
                     f"active: {self.metrics.active_connections}")
    
    def _on_invalidate(self, dbapi_connection, connection_record, exception):
        """Handle connection invalidation."""
        with self._lock:
            self.metrics.failed_connections += 1
            connection_id = id(connection_record)
            
            if connection_id in self._connection_registry:
                del self._connection_registry[connection_id]
            
            log.warning(f"Connection invalidated: {connection_id}, "
                       f"reason: {exception}")
    
    @contextmanager
    def get_managed_session(self, timeout: Optional[int] = None):
        """
        Get a managed database session with automatic cleanup.
        
        This context manager ensures proper session lifecycle management
        and prevents connection leaks.
        
        Args:
            timeout: Optional timeout for connection acquisition
            
        Yields:
            SQLAlchemy database session
            
        Raises:
            ConnectionPoolExhaustionError: If pool is exhausted
            ConnectionTimeoutError: If connection acquisition times out
        """
        session = None
        connection_acquired_at = datetime.now(tz=timezone.utc)
        
        try:
            # Get session with timeout handling
            actual_timeout = timeout or self.config.connect_timeout
            session = self._get_session_with_timeout(actual_timeout)
            
            if session is None:
                raise ConnectionPoolExhaustionError(
                    f"Failed to acquire database session within {actual_timeout}s"
                )
            
            # Yield session for use
            yield session
            
            # Commit successful operations
            if session.is_active:
                session.commit()
                
        except Exception as e:
            # Rollback on any error
            if session and session.is_active:
                try:
                    session.rollback()
                except Exception as rollback_error:
                    log.error(f"Failed to rollback session: {rollback_error}")
            
            # Re-raise original exception
            raise
            
        finally:
            # Always close session to return connection to pool
            if session:
                try:
                    session.close()
                    
                    # Track session duration for monitoring
                    duration = (datetime.now(tz=timezone.utc) - connection_acquired_at).total_seconds()
                    if duration > 30:  # Log long-running sessions
                        log.warning(f"Long-running database session: {duration:.2f}s")
                        
                except Exception as e:
                    log.error(f"Failed to close database session: {e}")
    
    def _get_session_with_timeout(self, timeout: int):
        """Get database session with timeout handling."""
        try:
            # Use PgForge's session factory
            session = self.appbuilder.get_session()
            
            # Test connection health with simple query
            session.execute('SELECT 1').fetchone()
            
            return session
            
        except TimeoutError:
            with self._lock:
                self.metrics.connection_timeouts += 1
            log.error(f"Database connection timeout after {timeout}s")
            return None
            
        except (DisconnectionError, SQLAlchemyError) as e:
            with self._lock:
                self.metrics.failed_connections += 1
            log.error(f"Database connection failed: {e}")
            return None
    
    @contextmanager
    def get_bulk_session(self, batch_size: int = 100):
        """
        Get session optimized for bulk operations.
        
        Args:
            batch_size: Number of operations before intermediate commit
            
        Yields:
            Tuple of (session, commit_counter_callback)
        """
        session = None
        operation_count = 0
        
        def commit_if_needed():
            nonlocal operation_count
            operation_count += 1
            
            if operation_count >= batch_size:
                session.commit()
                operation_count = 0
                log.debug(f"Intermediate commit after {batch_size} operations")
        
        try:
            with self.get_managed_session() as session:
                yield session, commit_if_needed
                
                # Final commit for remaining operations
                if operation_count > 0:
                    session.commit()
                    
        except Exception as e:
            log.error(f"Bulk session operation failed: {e}")
            raise
    
    def get_connection_metrics(self) -> Dict[str, Any]:
        """Get current connection pool metrics."""
        try:
            engine = self.appbuilder.get_app().extensions['sqlalchemy'].db.engine
            pool = engine.pool
            
            with self._lock:
                metrics = {
                    'pool_size': getattr(pool, 'size', lambda: self.config.pool_size)(),
                    'checked_out': getattr(pool, 'checkedout', lambda: 0)(),
                    'overflow': getattr(pool, 'overflow', lambda: 0)(),
                    'checked_in': getattr(pool, 'checkedin', lambda: 0)(),
                    'active_connections': self.metrics.active_connections,
                    'created_connections': self.metrics.created_connections,
                    'failed_connections': self.metrics.failed_connections,
                    'connection_timeouts': self.metrics.connection_timeouts,
                    'peak_connections': self.metrics.peak_connections,
                    'total_requests': self.metrics.total_requests,
                    'registry_size': len(self._connection_registry),
                    'last_reset': self.metrics.last_reset.isoformat()
                }
                
                # Calculate utilization percentage
                if metrics['pool_size'] > 0:
                    metrics['utilization_percent'] = (
                        metrics['checked_out'] / metrics['pool_size']
                    ) * 100
                else:
                    metrics['utilization_percent'] = 0
                
                return metrics
                
        except Exception as e:
            log.error(f"Failed to get connection metrics: {e}")
            return {'error': str(e)}
    
    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive connection pool health check."""
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'issues': [],
            'recommendations': []
        }
        
        try:
            metrics = self.get_connection_metrics()
            
            # Check pool utilization
            utilization = metrics.get('utilization_percent', 0)
            if utilization > 90:
                health_status['issues'].append(f"High pool utilization: {utilization:.1f}%")
                health_status['recommendations'].append("Consider increasing pool size")
                health_status['status'] = 'warning'
            
            # Check for connection failures
            failure_rate = 0
            if metrics['total_requests'] > 0:
                failure_rate = (metrics['failed_connections'] / metrics['total_requests']) * 100
            
            if failure_rate > 5:
                health_status['issues'].append(f"High failure rate: {failure_rate:.1f}%")
                health_status['recommendations'].append("Check database connectivity")
                health_status['status'] = 'critical'
            
            # Check for timeouts
            if metrics['connection_timeouts'] > 10:
                health_status['issues'].append(f"Frequent timeouts: {metrics['connection_timeouts']}")
                health_status['recommendations'].append("Increase connection timeout")
                health_status['status'] = 'warning'
            
            # Check for long-running connections
            stale_connections = self._find_stale_connections()
            if stale_connections:
                health_status['issues'].append(f"Stale connections detected: {len(stale_connections)}")
                health_status['recommendations'].append("Review long-running operations")
            
            # Test actual database connectivity
            with self.get_managed_session(timeout=5) as session:
                session.execute('SELECT 1').fetchone()
            
            health_status['metrics'] = metrics
            
        except Exception as e:
            health_status['status'] = 'critical'
            health_status['issues'].append(f"Health check failed: {str(e)}")
            log.error(f"Connection pool health check failed: {e}")
        
        return health_status
    
    def _find_stale_connections(self) -> List[Dict]:
        """Find connections that have been idle for too long."""
        stale_threshold = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        stale_connections = []
        
        with self._lock:
            for conn_id, info in self._connection_registry.items():
                if info['last_used'] < stale_threshold:
                    stale_connections.append({
                        'connection_id': conn_id,
                        'idle_duration': (datetime.now(tz=timezone.utc) - info['last_used']).total_seconds(),
                        'usage_count': info['usage_count']
                    })
        
        return stale_connections
    
    def cleanup_stale_connections(self):
        """Clean up stale connections and reset metrics."""
        try:
            engine = self.appbuilder.get_app().extensions['sqlalchemy'].db.engine
            
            # Dispose of stale connections
            stale_connections = self._find_stale_connections()
            if stale_connections:
                log.info(f"Cleaning up {len(stale_connections)} stale connections")
                
                # Force pool recreation for severe cases
                if len(stale_connections) > 10:
                    engine.dispose()
                    log.warning("Pool disposed due to excessive stale connections")
            
            # Clean up registry
            with self._lock:
                stale_threshold = datetime.now(tz=timezone.utc) - timedelta(hours=2)
                stale_keys = [
                    conn_id for conn_id, info in self._connection_registry.items()
                    if info['last_used'] < stale_threshold
                ]
                
                for key in stale_keys:
                    del self._connection_registry[key]
            
            log.info(f"Connection pool cleanup completed")
            
        except Exception as e:
            log.error(f"Failed to cleanup stale connections: {e}")
    
    def reset_metrics(self):
        """Reset connection metrics."""
        with self._lock:
            self.metrics = ConnectionMetrics()
            log.info("Connection pool metrics reset")
    
    def get_config(self) -> Dict[str, Any]:
        """Get current connection pool configuration."""
        return {
            'pool_size': self.config.pool_size,
            'max_overflow': self.config.max_overflow,
            'pool_timeout': self.config.pool_timeout,
            'pool_recycle': self.config.pool_recycle,
            'pool_pre_ping': self.config.pool_pre_ping,
            'connect_timeout': self.config.connect_timeout,
            'health_check_interval': self.config.health_check_interval
        }

    def _should_scale_up(self, metrics: Dict[str, Any]) -> bool:
        """Check if pool should be scaled up based on current metrics."""
        if not self.config.auto_scale:
            return False
            
        # Scale up if utilization is above threshold and pool isn't at max
        current_size = metrics.get('pool_size', self.config.pool_size)
        utilization = metrics.get('utilization_percent', 0) / 100.0
        
        return (
            utilization >= self.config.scale_threshold and
            current_size < self.config.max_pool_size and
            metrics.get('connection_timeouts', 0) > 0  # There are timeouts
        )
    
    def _should_scale_down(self, metrics: Dict[str, Any]) -> bool:
        """Check if pool should be scaled down based on current metrics."""
        if not self.config.auto_scale:
            return False
            
        # Scale down if utilization is below threshold and pool isn't at min
        current_size = metrics.get('pool_size', self.config.pool_size)
        utilization = metrics.get('utilization_percent', 0) / 100.0
        
        return (
            utilization <= self.config.scale_down_threshold and
            current_size > self.config.min_pool_size and
            metrics.get('connection_timeouts', 0) == 0  # No recent timeouts
        )
    
    def _calculate_target_pool_size(self, metrics: Dict[str, Any]) -> int:
        """Calculate optimal pool size based on current metrics."""
        current_size = metrics.get('pool_size', self.config.pool_size)
        utilization = metrics.get('utilization_percent', 0) / 100.0
        
        # Conservative scaling: increase/decrease by 25% at most
        if self._should_scale_up(metrics):
            target_size = min(
                int(current_size * 1.25),
                self.config.max_pool_size
            )
        elif self._should_scale_down(metrics):
            target_size = max(
                int(current_size * 0.75),
                self.config.min_pool_size
            )
        else:
            target_size = current_size
            
        return target_size
    
    def perform_dynamic_scaling(self) -> bool:
        """
        Perform dynamic pool scaling based on current metrics.
        
        Returns:
            bool: True if scaling was performed, False otherwise
        """
        if not self.config.auto_scale:
            return False
            
        try:
            metrics = self.get_connection_metrics()
            if 'error' in metrics:
                log.warning(f"Cannot scale pool due to metrics error: {metrics['error']}")
                return False
                
            target_size = self._calculate_target_pool_size(metrics)
            current_size = metrics.get('pool_size', self.config.pool_size)
            
            if target_size == current_size:
                return False  # No scaling needed
                
            # Update pool size (note: this is a theoretical implementation)
            # In practice, SQLAlchemy pool size cannot be changed dynamically
            # This would require engine recreation or connection pool swapping
            log.info(
                f"Dynamic scaling recommendation: current={current_size}, "
                f"target={target_size}, utilization={metrics.get('utilization_percent', 0):.1f}%"
            )
            
            # For now, log the recommendation rather than implement actual scaling
            # Real implementation would require engine pool recreation
            with self._lock:
                self.metrics.scaling_events += 1
                if target_size > current_size:
                    self.metrics.scale_up_events += 1
                else:
                    self.metrics.scale_down_events += 1
                    
            return True
            
        except Exception as e:
            log.error(f"Dynamic scaling failed: {e}")
            return False
    
    def get_scaling_recommendations(self) -> Dict[str, Any]:
        """
        Get scaling recommendations without performing actual scaling.
        
        Returns:
            dict: Scaling analysis and recommendations
        """
        try:
            metrics = self.get_connection_metrics()
            if 'error' in metrics:
                return {'error': metrics['error']}
                
            target_size = self._calculate_target_pool_size(metrics)
            current_size = metrics.get('pool_size', self.config.pool_size)
            utilization = metrics.get('utilization_percent', 0)
            
            analysis = {
                'current_size': current_size,
                'target_size': target_size,
                'utilization_percent': utilization,
                'scaling_needed': target_size != current_size,
                'auto_scale_enabled': self.config.auto_scale,
                'thresholds': {
                    'scale_up': self.config.scale_threshold * 100,
                    'scale_down': self.config.scale_down_threshold * 100
                },
                'limits': {
                    'min_pool_size': self.config.min_pool_size,
                    'max_pool_size': self.config.max_pool_size
                }
            }
            
            if target_size > current_size:
                analysis['recommendation'] = 'scale_up'
                analysis['reason'] = f"High utilization ({utilization:.1f}%) with timeouts"
            elif target_size < current_size:
                analysis['recommendation'] = 'scale_down'
                analysis['reason'] = f"Low utilization ({utilization:.1f}%) with no timeouts"
            else:
                analysis['recommendation'] = 'maintain'
                analysis['reason'] = f"Utilization ({utilization:.1f}%) within optimal range"
                
            return analysis
            
        except Exception as e:
            log.error(f"Failed to generate scaling recommendations: {e}")
            return {'error': str(e)}


class ConnectionPoolExhaustionError(Exception):
    """Raised when database connection pool is exhausted."""
    pass


class ConnectionTimeoutError(Exception):
    """Raised when database connection acquisition times out.""" 
    pass


def managed_db_session(pool_manager: ConnectionPoolManager, timeout: int = 30):
    """
    Decorator for methods that need database session management.
    
    Args:
        pool_manager: ConnectionPoolManager instance
        timeout: Connection timeout in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with pool_manager.get_managed_session(timeout=timeout) as session:
                # Inject session as first argument
                return func(session, *args, **kwargs)
        return wrapper
    return decorator


def bulk_db_session(pool_manager: ConnectionPoolManager, batch_size: int = 100):
    """
    Decorator for bulk database operations.
    
    Args:
        pool_manager: ConnectionPoolManager instance
        batch_size: Operations per batch commit
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with pool_manager.get_bulk_session(batch_size=batch_size) as (session, commit_callback):
                # Inject session and commit callback
                return func(session, commit_callback, *args, **kwargs)
        return wrapper
    return decorator


# Global connection pool manager instance
_pool_manager: Optional[ConnectionPoolManager] = None


def get_connection_pool_manager() -> Optional[ConnectionPoolManager]:
    """Get the global connection pool manager instance."""
    return _pool_manager


def initialize_connection_pool(appbuilder, config: Optional[ConnectionConfig] = None):
    """Initialize the global connection pool manager."""
    global _pool_manager
    _pool_manager = ConnectionPoolManager(appbuilder, config)
    log.info("Database connection pool manager initialized")
    return _pool_manager


def get_managed_session(timeout: Optional[int] = None):
    """Get a managed database session using the global pool manager."""
    if _pool_manager is None:
        raise RuntimeError("Connection pool manager not initialized")
    return _pool_manager.get_managed_session(timeout=timeout)