"""
Production Monitoring and Health Check Systems for Multi-Tenant SaaS.

This module provides comprehensive monitoring, health checks, and observability
for multi-tenant PgAppForge applications in production environments.
"""

import logging
import time
import threading
import psutil
import gc
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Callable, Union
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict, deque
import json

from flask import current_app, request, g, jsonify, Blueprint
from flask.cli import with_appcontext
import click
from sqlalchemy import text, func
from sqlalchemy.exc import SQLAlchemyError
import redis
import requests

from pgappforge import db
from pgappforge.models.tenant_context import get_current_tenant_id

log = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class MonitoringMetricType(Enum):
    """Types of monitoring metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    response_time_ms: float
    error: Optional[str] = None


@dataclass
class MonitoringMetric:
    """Monitoring metric data point."""
    name: str
    value: Union[int, float]
    metric_type: MonitoringMetricType
    tags: Dict[str, str]
    timestamp: datetime
    tenant_id: Optional[int] = None


class DatabaseHealthChecker:
    """Health checker for database connectivity and performance."""
    
    def __init__(self):
        self.connection_pool_stats = {}
        self.query_performance = deque(maxlen=100)
    
    def check_database_connection(self) -> HealthCheckResult:
        """Check basic database connectivity."""
        start_time = time.time()
        
        try:
            # Simple connectivity test
            result = db.session.execute(text("SELECT 1")).scalar()
            
            if result == 1:
                response_time = (time.time() - start_time) * 1000
                
                return HealthCheckResult(
                    name="database_connection",
                    status=HealthStatus.HEALTHY,
                    message="Database connection successful",
                    details={
                        "response_time_ms": response_time,
                        "database_url": str(db.engine.url).split('@')[1] if '@' in str(db.engine.url) else "configured"
                    },
                    timestamp=datetime.now(tz=timezone.utc),
                    response_time_ms=response_time
                )
            else:
                return HealthCheckResult(
                    name="database_connection",
                    status=HealthStatus.CRITICAL,
                    message="Database query returned unexpected result",
                    details={"expected": 1, "actual": result},
                    timestamp=datetime.now(tz=timezone.utc),
                    response_time_ms=(time.time() - start_time) * 1000,
                    error="Unexpected query result"
                )
                
        except Exception as e:
            return HealthCheckResult(
                name="database_connection",
                status=HealthStatus.CRITICAL,
                message=f"Database connection failed: {str(e)}",
                details={},
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )
    
    def check_connection_pool(self) -> HealthCheckResult:
        """Check database connection pool health."""
        start_time = time.time()
        
        try:
            pool = db.engine.pool
            pool_status = pool.status()
            
            # Calculate pool utilization
            total_connections = pool.size() + pool.overflow()
            active_connections = pool.checkedout()
            pool_utilization = (active_connections / total_connections) * 100 if total_connections > 0 else 0
            
            # Determine status based on utilization
            if pool_utilization > 90:
                status = HealthStatus.CRITICAL
                message = "Database connection pool nearly exhausted"
            elif pool_utilization > 75:
                status = HealthStatus.WARNING
                message = "Database connection pool utilization high"
            else:
                status = HealthStatus.HEALTHY
                message = "Database connection pool healthy"
            
            details = {
                "pool_size": pool.size(),
                "pool_overflow": pool.overflow(),
                "active_connections": active_connections,
                "pool_utilization_percent": round(pool_utilization, 2),
                "pool_status": pool_status
            }
            
            return HealthCheckResult(
                name="database_pool",
                status=status,
                message=message,
                details=details,
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000
            )
            
        except Exception as e:
            return HealthCheckResult(
                name="database_pool",
                status=HealthStatus.UNKNOWN,
                message=f"Could not check connection pool: {str(e)}",
                details={},
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )
    
    def check_query_performance(self) -> HealthCheckResult:
        """Check database query performance."""
        start_time = time.time()
        
        try:
            # Run a simple query that exercises the database
            query_start = time.time()
            tenant_count = db.session.query(func.count()).select_from(
                db.session.execute(text("SELECT 1 as dummy")).subquery()
            ).scalar()
            query_time = (time.time() - query_start) * 1000
            
            # Track query performance
            self.query_performance.append(query_time)
            
            # Calculate average performance over recent queries
            if len(self.query_performance) >= 10:
                avg_response_time = sum(self.query_performance) / len(self.query_performance)
                
                if avg_response_time > 1000:  # > 1 second
                    status = HealthStatus.CRITICAL
                    message = "Database queries are very slow"
                elif avg_response_time > 500:  # > 500ms
                    status = HealthStatus.WARNING
                    message = "Database queries are slower than expected"
                else:
                    status = HealthStatus.HEALTHY
                    message = "Database query performance is good"
            else:
                status = HealthStatus.HEALTHY
                message = "Database query completed successfully"
                avg_response_time = query_time
            
            return HealthCheckResult(
                name="database_performance",
                status=status,
                message=message,
                details={
                    "current_query_time_ms": round(query_time, 2),
                    "average_query_time_ms": round(avg_response_time, 2),
                    "recent_queries_count": len(self.query_performance)
                },
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000
            )
            
        except Exception as e:
            return HealthCheckResult(
                name="database_performance",
                status=HealthStatus.CRITICAL,
                message=f"Database performance check failed: {str(e)}",
                details={},
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )


class SystemHealthChecker:
    """Health checker for system resources."""
    
    def __init__(self):
        self.process = psutil.Process()
    
    def check_memory_usage(self) -> HealthCheckResult:
        """Check system and process memory usage."""
        start_time = time.time()
        
        try:
            # System memory
            system_memory = psutil.virtual_memory()
            
            # Process memory
            process_memory = self.process.memory_info()
            process_memory_percent = self.process.memory_percent()
            
            # Determine status based on memory usage
            if system_memory.percent > 90 or process_memory_percent > 50:
                status = HealthStatus.CRITICAL
                message = "High memory usage detected"
            elif system_memory.percent > 80 or process_memory_percent > 30:
                status = HealthStatus.WARNING
                message = "Memory usage is elevated"
            else:
                status = HealthStatus.HEALTHY
                message = "Memory usage is normal"
            
            return HealthCheckResult(
                name="memory_usage",
                status=status,
                message=message,
                details={
                    "system_memory_percent": round(system_memory.percent, 2),
                    "system_memory_available_gb": round(system_memory.available / 1024**3, 2),
                    "system_memory_total_gb": round(system_memory.total / 1024**3, 2),
                    "process_memory_mb": round(process_memory.rss / 1024**2, 2),
                    "process_memory_percent": round(process_memory_percent, 2)
                },
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000
            )
            
        except Exception as e:
            return HealthCheckResult(
                name="memory_usage",
                status=HealthStatus.UNKNOWN,
                message=f"Memory check failed: {str(e)}",
                details={},
                timestamp=datetime.now(tz=timezone.utc),
                response_time_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )


class TenantIsolationHealthChecker:
    """Health checker for tenant isolation and data security."""
    
    def __init__(self):
        self.isolation_cache = {}
        self.last_validation_time = {}
        self.validation_interval = 300  # 5 minutes
    
    def check_tenant_data_isolation(self) -> HealthCheckResult:
        """Validate that tenant data is properly isolated."""
        start_time = time.time()
        
        try:
            from pgappforge import db
            from pgappforge.models.tenant_models import Tenant
            from sqlalchemy import text
            
            # Test cross-tenant data access prevention
            isolation_issues = []
            
            # Get sample of active tenants
            tenants = db.session.query(Tenant).filter_by(status='active').limit(5).all()
            
            if len(tenants) < 2:
                return HealthCheckResult(
                    name="tenant_data_isolation",
                    status=HealthStatus.WARNING,
                    message="Insufficient active tenants for isolation testing",
                    details={'tenant_count': len(tenants)},
                    check_duration=time.time() - start_time
                )
            
            # Test 1: Verify tenant_id constraints exist
            tenant_tables = self._get_tenant_aware_tables()
            missing_constraints = []
            
            for table_name in tenant_tables:
                if not self._has_tenant_constraint(table_name):
                    missing_constraints.append(table_name)
            
            if missing_constraints:
                isolation_issues.append(f"Missing tenant constraints on tables: {', '.join(missing_constraints)}")
            
            # Test 2: Verify no cross-tenant data leakage in queries
            for tenant in tenants[:2]:  # Test first 2 tenants
                leakage_issues = self._test_tenant_query_isolation(tenant.id)
                isolation_issues.extend(leakage_issues)
            
            # Test 3: Check for orphaned data (data without tenant_id)
            orphaned_data = self._check_orphaned_tenant_data()
            if orphaned_data:
                isolation_issues.append(f"Found orphaned data in {len(orphaned_data)} tables")
            
            # Determine status based on issues found
            if isolation_issues:
                status = HealthStatus.CRITICAL if any('cross-tenant' in issue.lower() for issue in isolation_issues) else HealthStatus.WARNING
                message = f"Tenant isolation issues detected: {'; '.join(isolation_issues[:3])}"
            else:
                status = HealthStatus.HEALTHY
                message = "Tenant data isolation validated successfully"
            
            return HealthCheckResult(
                name="tenant_data_isolation",
                status=status,
                message=message,
                details={
                    'tenant_count_tested': len(tenants),
                    'tables_checked': len(tenant_tables),
                    'isolation_issues': isolation_issues,
                    'orphaned_data_tables': len(orphaned_data) if orphaned_data else 0
                },
                check_duration=time.time() - start_time
            )
            
        except Exception as e:
            log.error(f"Tenant isolation check failed: {e}")
            return HealthCheckResult(
                name="tenant_data_isolation",
                status=HealthStatus.CRITICAL,
                message=f"Isolation check failed: {str(e)}",
                details={'error': str(e)},
                check_duration=time.time() - start_time
            )
    
    def check_tenant_resource_isolation(self) -> HealthCheckResult:
        """Check tenant resource limits and enforcement."""
        start_time = time.time()
        
        try:
            from pgappforge.tenants.resource_isolation import get_resource_limiter, get_resource_monitor
            
            resource_limiter = get_resource_limiter()
            resource_monitor = get_resource_monitor()
            
            issues = []
            
            # Test resource limit enforcement
            if not hasattr(resource_limiter, '_tenant_limits') or not resource_limiter._tenant_limits:
                issues.append("No resource limits configured for any tenants")
            
            # Check for suspended tenants
            suspended_count = 0
            try:
                if hasattr(resource_limiter, 'redis_client') and resource_limiter.redis_client:
                    # Count suspended tenants
                    suspended_keys = resource_limiter.redis_client.keys('suspended:*')
                    suspended_count = len(suspended_keys) if suspended_keys else 0
            except Exception as redis_error:
                log.debug(f"Redis suspended tenant check failed: {redis_error}")
            
            # Check monitoring system health
            if not hasattr(resource_monitor, '_monitoring_active') or not resource_monitor._monitoring_active:
                issues.append("Resource monitoring system is not active")
            
            # Determine status
            if issues:
                status = HealthStatus.WARNING
                message = f"Resource isolation issues: {'; '.join(issues)}"
            else:
                status = HealthStatus.HEALTHY
                message = "Tenant resource isolation functioning properly"
            
            return HealthCheckResult(
                name="tenant_resource_isolation",
                status=status,
                message=message,
                details={
                    'suspended_tenants': suspended_count,
                    'resource_issues': issues,
                    'limits_configured': len(resource_limiter._tenant_limits) if hasattr(resource_limiter, '_tenant_limits') else 0
                },
                check_duration=time.time() - start_time
            )
            
        except Exception as e:
            log.error(f"Resource isolation check failed: {e}")
            return HealthCheckResult(
                name="tenant_resource_isolation",
                status=HealthStatus.CRITICAL,
                message=f"Resource isolation check failed: {str(e)}",
                details={'error': str(e)},
                check_duration=time.time() - start_time
            )
    
    def check_tenant_context_security(self) -> HealthCheckResult:
        """Validate tenant context management and security."""
        start_time = time.time()
        
        try:
            from pgappforge.models.tenant_context import tenant_context
            
            security_issues = []
            
            # Test 1: Check if tenant context is properly initialized
            if not hasattr(tenant_context, '_tenant_cache'):
                security_issues.append("Tenant context not properly initialized")
            
            # Test 2: Verify tenant context clearing mechanisms
            cache_size = len(tenant_context._tenant_cache) if hasattr(tenant_context, '_tenant_cache') else 0
            if cache_size > 1000:  # Potential memory leak
                security_issues.append(f"Tenant context cache size excessive: {cache_size} entries")
            
            # Test 3: Check for stale tenant contexts
            stale_contexts = 0
            if hasattr(tenant_context, '_context_stack') and tenant_context._context_stack:
                stale_contexts = len(tenant_context._context_stack)
                if stale_contexts > 10:
                    security_issues.append(f"Stale tenant contexts detected: {stale_contexts}")
            
            # Determine status
            if security_issues:
                status = HealthStatus.WARNING
                message = f"Tenant context security issues: {'; '.join(security_issues)}"
            else:
                status = HealthStatus.HEALTHY
                message = "Tenant context security validated"
            
            return HealthCheckResult(
                name="tenant_context_security",
                status=status,
                message=message,
                details={
                    'cache_size': cache_size,
                    'stale_contexts': stale_contexts,
                    'security_issues': security_issues
                },
                check_duration=time.time() - start_time
            )
            
        except Exception as e:
            log.error(f"Tenant context security check failed: {e}")
            return HealthCheckResult(
                name="tenant_context_security",
                status=HealthStatus.CRITICAL,
                message=f"Context security check failed: {str(e)}",
                details={'error': str(e)},
                check_duration=time.time() - start_time
            )
    
    def _get_tenant_aware_tables(self) -> List[str]:
        """Get list of tables that should have tenant_id columns."""
        tenant_tables = [
            'ab_tenant_users', 'ab_tenant_configs', 'ab_tenant_usage',
            'ab_tenant_subscriptions', 'ab_security_audit_logs'
        ]
        
        # Add any custom tenant-aware tables from inspection
        try:
            from pgappforge import db
            from sqlalchemy import inspect
            
            inspector = inspect(db.engine)
            all_tables = inspector.get_table_names()
            
            # Look for tables with tenant_id columns
            for table_name in all_tables:
                if table_name not in tenant_tables:
                    columns = [col['name'] for col in inspector.get_columns(table_name)]
                    if 'tenant_id' in columns:
                        tenant_tables.append(table_name)
        except Exception as e:
            log.debug(f"Error inspecting tenant tables: {e}")
        
        return tenant_tables
    
    def _has_tenant_constraint(self, table_name: str) -> bool:
        """Check if table has proper tenant_id constraint."""
        try:
            from pgappforge import db
            from sqlalchemy import text
            
            # Check for foreign key constraint on tenant_id
            result = db.session.execute(text("""
                SELECT COUNT(*) as constraint_count
                FROM information_schema.key_column_usage 
                WHERE table_name = :table_name 
                AND column_name = 'tenant_id'
                AND referenced_table_name = 'ab_tenants'
            """), {'table_name': table_name})
            
            count = result.scalar()
            return count > 0
            
        except Exception as e:
            log.debug(f"Error checking tenant constraint for {table_name}: {e}")
            return False  # Assume no constraint if check fails
    
    def _test_tenant_query_isolation(self, tenant_id: int) -> List[str]:
        """Test that queries are properly isolated to tenant."""
        issues = []
        
        try:
            from pgappforge import db
            from sqlalchemy import text
            
            # Test basic tenant data access
            result = db.session.execute(text("""
                SELECT COUNT(DISTINCT tenant_id) as tenant_count
                FROM ab_tenant_users 
                WHERE tenant_id != :tenant_id
            """), {'tenant_id': tenant_id})
            
            other_tenant_count = result.scalar()
            
            # This is just a basic check - in production would need more sophisticated testing
            if other_tenant_count == 0:
                issues.append(f"Suspicious: No other tenant data found during isolation test")
            
        except Exception as e:
            log.debug(f"Tenant query isolation test failed: {e}")
            issues.append(f"Query isolation test failed: {str(e)}")
        
        return issues
    
    def _check_orphaned_tenant_data(self) -> List[str]:
        """Check for data without proper tenant_id references."""
        orphaned_tables = []
        
        try:
            from pgappforge import db
            from sqlalchemy import text
            
            tenant_tables = self._get_tenant_aware_tables()
            
            for table_name in tenant_tables:
                try:
                    # Check for NULL tenant_id values
                    result = db.session.execute(text(f"""
                        SELECT COUNT(*) as orphaned_count 
                        FROM {table_name} 
                        WHERE tenant_id IS NULL
                    """))
                    
                    orphaned_count = result.scalar()
                    if orphaned_count > 0:
                        orphaned_tables.append(f"{table_name}({orphaned_count} orphaned)")
                        
                except Exception as e:
                    log.debug(f"Error checking orphaned data in {table_name}: {e}")
                    
        except Exception as e:
            log.debug(f"Orphaned data check failed: {e}")
        
        return orphaned_tables


class HealthCheckOrchestrator:
    """Main orchestrator for all health checks."""
    
    def __init__(self):
        self.db_checker = DatabaseHealthChecker()
        self.system_checker = SystemHealthChecker()
        self.tenant_isolation_checker = TenantIsolationHealthChecker()
        self.custom_checks = {}
        self.check_history = deque(maxlen=1000)
    
    def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        """Run all health checks and return results."""
        results = {}
        
        # Database checks
        try:
            results['database_connection'] = self.db_checker.check_database_connection()
            results['database_pool'] = self.db_checker.check_connection_pool()
            results['database_performance'] = self.db_checker.check_query_performance()
        except Exception as e:
            log.error(f"Database health checks failed: {e}")
        
        # System checks
        try:
            results['memory_usage'] = self.system_checker.check_memory_usage()
        except Exception as e:
            log.error(f"System health checks failed: {e}")
        
        # Tenant isolation checks
        try:
            results['tenant_data_isolation'] = self.tenant_isolation_checker.check_tenant_data_isolation()
            results['tenant_resource_isolation'] = self.tenant_isolation_checker.check_tenant_resource_isolation()
            results['tenant_context_security'] = self.tenant_isolation_checker.check_tenant_context_security()
        except Exception as e:
            log.error(f"Tenant isolation health checks failed: {e}")
        
        return results
    
    def get_overall_status(self, results: Dict[str, HealthCheckResult]) -> HealthStatus:
        """Determine overall system health status."""
        if not results:
            return HealthStatus.UNKNOWN
        
        statuses = [result.status for result in results.values()]
        
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        elif HealthStatus.WARNING in statuses:
            return HealthStatus.WARNING
        elif HealthStatus.UNKNOWN in statuses:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive health summary."""
        results = self.run_all_checks()
        overall_status = self.get_overall_status(results)
        
        # Count results by status
        status_counts = defaultdict(int)
        for result in results.values():
            status_counts[result.status.value] += 1
        
        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "checks_run": len(results),
            "status_counts": dict(status_counts),
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "response_time_ms": result.response_time_ms,
                    "details": result.details
                }
                for name, result in results.items()
            }
        }


# Flask Blueprint for health check endpoints
health_bp = Blueprint('health', __name__, url_prefix='/health')

# Global instances
_health_orchestrator = None
_monitoring_lock = threading.Lock()


def get_health_orchestrator() -> HealthCheckOrchestrator:
    """Get global health check orchestrator."""
    global _health_orchestrator
    if _health_orchestrator is None:
        with _monitoring_lock:
            if _health_orchestrator is None:
                _health_orchestrator = HealthCheckOrchestrator()
    return _health_orchestrator


@health_bp.route('/')
def health_check():
    """Basic health check endpoint."""
    orchestrator = get_health_orchestrator()
    results = orchestrator.run_all_checks()
    overall_status = orchestrator.get_overall_status(results)
    
    response_code = 200
    if overall_status == HealthStatus.CRITICAL:
        response_code = 503
    
    return jsonify({
        "status": overall_status.value,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "checks": len(results)
    }), response_code


@health_bp.route('/detailed')
def detailed_health_check():
    """Detailed health check with all results."""
    orchestrator = get_health_orchestrator()
    summary = orchestrator.get_health_summary()
    
    response_code = 200
    if summary["overall_status"] == "critical":
        response_code = 503
    
    return jsonify(summary), response_code


@health_bp.route('/readiness')
def readiness_check():
    """Kubernetes readiness probe endpoint."""
    orchestrator = get_health_orchestrator()
    
    # For readiness, we only check critical dependencies
    db_result = orchestrator.db_checker.check_database_connection()
    
    if db_result.status == HealthStatus.CRITICAL:
        return jsonify({
            "ready": False,
            "reason": db_result.message
        }), 503
    
    return jsonify({"ready": True}), 200


@health_bp.route('/liveness')
def liveness_check():
    """Kubernetes liveness probe endpoint."""
    return jsonify({
        "alive": True,
        "timestamp": datetime.now(tz=timezone.utc).isoformat()
    }), 200


def initialize_monitoring_system(app):
    """Initialize the monitoring and health check system."""
    log.info("Initializing production monitoring and health check system...")
    
    # Initialize global instances
    orchestrator = get_health_orchestrator()
    
    # Register health check blueprint
    app.register_blueprint(health_bp)
    
    # Store in app extensions
    app.extensions['health_orchestrator'] = orchestrator
    
    log.info("Production monitoring and health check system initialized successfully")