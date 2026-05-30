"""
Multi-Tenant Performance Optimization Module.

This module provides database performance optimizations, caching strategies,
and resource isolation for multi-tenant SaaS applications.
"""

import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from typing import Dict, Optional, Any, List, Callable
from datetime import datetime, timedelta
from decimal import Decimal

from flask import current_app, g
from sqlalchemy import Index, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool
from sqlalchemy.orm import sessionmaker, scoped_session
import redis
from cachetools import TTLCache
import json

log = logging.getLogger(__name__)


class TenantDatabaseOptimizer:
    """Database performance optimization for multi-tenant operations."""
    
    def __init__(self):
        self._tenant_connection_pools = {}
        self._query_cache = TTLCache(maxsize=1000, ttl=300)  # 5 minute TTL
        self._stats_cache = TTLCache(maxsize=100, ttl=60)     # 1 minute TTL
        self._lock = threading.RLock()
    
    def setup_tenant_indexes(self, db):
        """Set up optimized indexes for multi-tenant queries."""
        log.info("Setting up optimized tenant indexes...")
        
        # Core tenant table indexes
        indexes_to_create = [
            # Tenant table optimizations
            Index('ix_ab_tenants_slug_status', 'slug', 'status'),
            Index('ix_ab_tenants_custom_domain_active', 'custom_domain', 'status'),
            Index('ix_ab_tenants_plan_status', 'plan_id', 'status'),
            
            # Tenant users with composite indexes
            Index('ix_ab_tenant_users_tenant_active', 'tenant_id', 'is_active'),
            Index('ix_ab_tenant_users_tenant_role', 'tenant_id', 'role_within_tenant'),
            Index('ix_ab_tenant_users_user_tenant', 'user_id', 'tenant_id'),
            
            # Tenant configuration optimizations
            Index('ix_ab_tenant_configs_tenant_key_cat', 'tenant_id', 'config_key', 'category'),
            Index('ix_ab_tenant_configs_category_sensitive', 'category', 'is_sensitive'),
            
            # Usage tracking with time-series optimization
            Index('ix_ab_tenant_usage_tenant_date_type', 'tenant_id', 'usage_date', 'usage_type'),
            Index('ix_ab_tenant_usage_subscription_date', 'subscription_id', 'usage_date'),
            Index('ix_ab_tenant_usage_date_tenant', 'usage_date', 'tenant_id'),  # For reporting
            
            # Subscription management
            Index('ix_ab_tenant_subs_tenant_status', 'tenant_id', 'status'),
            Index('ix_ab_tenant_subs_stripe_id', 'stripe_subscription_id'),
            Index('ix_ab_tenant_subs_period_end', 'current_period_end'),  # For renewals
        ]
        
        # Create indexes that don't exist
        with db.engine.connect() as conn:
            for index in indexes_to_create:
                try:
                    index.create(conn, checkfirst=True)
                    log.debug(f"Created index: {index.name}")
                except Exception as e:
                    log.warning(f"Could not create index {index.name}: {e}")
    
    def optimize_tenant_queries(self, db):
        """Set up query optimization for tenant-aware operations."""
        
        @event.listens_for(Engine, "before_cursor_execute")
        def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            """Add query timing and optimization hints."""
            if not hasattr(g, 'tenant_id'):
                return
            
            # Add tenant context to query if it's a SELECT on tenant-aware tables
            if statement.strip().upper().startswith('SELECT'):
                tenant_aware_tables = [
                    'ab_tenant_users', 'ab_tenant_configs', 'ab_tenant_usage',
                    'ab_tenant_subscriptions'
                ]
                
                # Check if query involves tenant-aware tables
                for table in tenant_aware_tables:
                    if table in statement.lower():
                        # Log slow tenant queries
                        context._fab_query_start_time = time.time()
                        context._fab_is_tenant_query = True
                        break
        
        @event.listens_for(Engine, "after_cursor_execute")
        def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            """Track query performance for tenant operations."""
            if hasattr(context, '_fab_query_start_time'):
                execution_time = time.time() - context._fab_query_start_time
                
                if execution_time > 0.5:  # Log queries slower than 500ms
                    tenant_id = getattr(g, 'tenant_id', 'unknown')
                    log.warning(f"Slow tenant query ({execution_time:.2f}s) for tenant {tenant_id}: "
                              f"{statement[:200]}...")
                
                # Store query statistics
                if hasattr(context, '_fab_is_tenant_query'):
                    self._track_query_performance(statement, execution_time)
    
    def setup_connection_pooling(self, app):
        """Configure optimized connection pooling for tenant operations."""
        database_url = app.config.get('SQLALCHEMY_DATABASE_URI')
        
        if not database_url:
            log.warning("No database URL configured, skipping connection pool setup")
            return
        
        # Enhanced pool configuration for multi-tenant workloads
        pool_config = {
            'poolclass': QueuePool,
            'pool_size': app.config.get('TENANT_DB_POOL_SIZE', 20),
            'max_overflow': app.config.get('TENANT_DB_MAX_OVERFLOW', 30),
            'pool_pre_ping': True,
            'pool_recycle': app.config.get('TENANT_DB_POOL_RECYCLE', 3600),  # 1 hour
            'pool_timeout': app.config.get('TENANT_DB_POOL_TIMEOUT', 30),
            'echo': app.config.get('TENANT_DB_ECHO_QUERIES', False),
        }
        
        # Apply pool configuration with proper Flask-SQLAlchemy compatibility
        try:
            # Check if Flask-SQLAlchemy is already initialized
            if hasattr(app, 'extensions') and 'sqlalchemy' in app.extensions:
                # SQLAlchemy extension already initialized - need to update existing engine
                db_ext = app.extensions['sqlalchemy']
                
                # For Flask-SQLAlchemy 3.x, update engine options if possible
                if hasattr(db_ext, 'engines') and db_ext.engines:
                    log.warning("Flask-SQLAlchemy already initialized. Pool config may require app restart to take full effect.")
                
                # Try to apply configuration to existing engine
                if hasattr(db_ext, 'get_engine'):
                    engine = db_ext.get_engine()
                    if hasattr(engine, 'pool'):
                        current_pool = engine.pool
                        log.info(f"Current pool: size={getattr(current_pool, 'size', 'unknown')}, "
                               f"overflow={getattr(current_pool, 'overflow', 'unknown')}")
            
            # Update Flask app config for future engine creation
            # Merge with existing engine options instead of replacing
            existing_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
            updated_options = {**existing_options, **pool_config}
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = updated_options
            
            # Also set individual Flask-SQLAlchemy config keys for compatibility
            app.config.setdefault('SQLALCHEMY_POOL_SIZE', pool_config['pool_size'])
            app.config.setdefault('SQLALCHEMY_POOL_TIMEOUT', pool_config['pool_timeout'])
            app.config.setdefault('SQLALCHEMY_POOL_RECYCLE', pool_config['pool_recycle'])
            app.config.setdefault('SQLALCHEMY_MAX_OVERFLOW', pool_config['max_overflow'])
            app.config.setdefault('SQLALCHEMY_POOL_PRE_PING', pool_config['pool_pre_ping'])
            
            # Validate configuration was applied
            final_options = app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})
            if 'pool_size' in final_options:
                log.info(f"Successfully configured tenant database connection pool: "
                        f"size={final_options['pool_size']}, "
                        f"max_overflow={final_options['max_overflow']}, "
                        f"timeout={final_options['pool_timeout']}s, "
                        f"recycle={final_options['pool_recycle']}s")
            else:
                log.error("Failed to apply database connection pool configuration")
            
        except Exception as e:
            log.error(f"Error configuring database connection pool: {e}")
            # Fallback to basic configuration
            app.config['SQLALCHEMY_ENGINE_OPTIONS'] = pool_config
            log.info("Applied fallback connection pool configuration")
    
    def setup_table_partitioning(self, db):
        """Set up table partitioning for large tenant datasets."""
        # Note: This is PostgreSQL-specific partitioning
        if 'postgresql' not in str(db.engine.url):
            log.info("Table partitioning only supported for PostgreSQL")
            return
        
        # Check if partitioning is enabled
        if not current_app.config.get('TENANT_ENABLE_PARTITIONING', False):
            return
        
        partitioning_sql = [
            # Partition tenant usage table by date (monthly partitions)
            """
            DO $$ 
            BEGIN
                -- Check if table is already partitioned
                IF NOT EXISTS (
                    SELECT 1 FROM pg_tables 
                    WHERE tablename = 'ab_tenant_usage_partitioned'
                ) THEN
                    -- Create partitioned table
                    CREATE TABLE ab_tenant_usage_partitioned (
                        LIKE ab_tenant_usage INCLUDING ALL
                    ) PARTITION BY RANGE (usage_date);
                    
                    -- Create monthly partitions for current year
                    FOR i IN 1..12 LOOP
                        EXECUTE format('
                            CREATE TABLE IF NOT EXISTS ab_tenant_usage_y%s_m%s 
                            PARTITION OF ab_tenant_usage_partitioned
                            FOR VALUES FROM (%L) TO (%L)',
                            EXTRACT(YEAR FROM CURRENT_DATE),
                            LPAD(i::text, 2, '0'),
                            DATE_TRUNC('month', CURRENT_DATE) + (i-1) * INTERVAL '1 month',
                            DATE_TRUNC('month', CURRENT_DATE) + i * INTERVAL '1 month'
                        );
                    END LOOP;
                END IF;
            END $$;
            """,
            
            # Partition large tenant-aware tables by tenant_id hash
            """
            DO $$ 
            BEGIN
                -- Only partition if we have a large number of tenants
                IF (SELECT COUNT(*) FROM ab_tenants) > 100 THEN
                    -- Create hash-partitioned tenant configs
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_tables 
                        WHERE tablename = 'ab_tenant_configs_partitioned'
                    ) THEN
                        CREATE TABLE ab_tenant_configs_partitioned (
                            LIKE ab_tenant_configs INCLUDING ALL
                        ) PARTITION BY HASH (tenant_id);
                        
                        -- Create 4 hash partitions
                        FOR i IN 0..3 LOOP
                            EXECUTE format('
                                CREATE TABLE ab_tenant_configs_p%s 
                                PARTITION OF ab_tenant_configs_partitioned
                                FOR VALUES WITH (modulus 4, remainder %s)',
                                i, i
                            );
                        END LOOP;
                    END IF;
                END IF;
            END $$;
            """
        ]
        
        # Execute partitioning SQL
        try:
            with db.engine.connect() as conn:
                for sql in partitioning_sql:
                    conn.execute(text(sql))
                    log.info("Applied table partitioning setup")
        except Exception as e:
            log.error(f"Failed to set up table partitioning: {e}")
    
    def _track_query_performance(self, statement: str, execution_time: float):
        """Track query performance metrics."""
        try:
            # Extract table name from query for categorization
            table_name = 'unknown'
            if 'FROM ab_tenant' in statement.upper():
                # Extract tenant table name
                import re
                match = re.search(r'FROM (ab_tenant_\w+)', statement.upper())
                if match:
                    table_name = match.group(1).lower()
            
            # Store in stats cache with thread safety
            with self._lock:
                stats_key = f"query_stats:{table_name}"
                if stats_key not in self._stats_cache:
                    self._stats_cache[stats_key] = {
                        'count': 0,
                        'total_time': 0.0,
                        'avg_time': 0.0,
                        'max_time': 0.0
                    }
                
                stats = self._stats_cache[stats_key]
                stats['count'] += 1
                stats['total_time'] += execution_time
                stats['avg_time'] = stats['total_time'] / stats['count']
                stats['max_time'] = max(stats['max_time'], execution_time)
            
        except Exception as e:
            log.debug(f"Error tracking query performance: {e}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get database performance statistics."""
        with self._lock:
            return dict(self._stats_cache)


class TenantCacheManager:
    """Advanced caching system for tenant configurations and data."""
    
    def __init__(self, redis_url: str = None):
        self.redis_client = None
        self.local_cache = TTLCache(maxsize=500, ttl=300)  # 5 minute local cache
        self._lock = threading.RLock()
        self._redis_available = False
        
        # Initialize Redis if available
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                self._redis_available = True
                log.info("Connected to Redis for tenant caching")
            except Exception as e:
                log.warning(f"Failed to connect to Redis: {e}, using local cache only")
                self._setup_memory_fallback()
        else:
            self._setup_memory_fallback()
    
    def _setup_memory_fallback(self):
        """Set up enhanced memory-only caching when Redis is unavailable."""
        # Increase local cache size when Redis is not available
        self.local_cache = TTLCache(maxsize=2000, ttl=600)  # 10 minute TTL, larger cache
        log.info("Redis unavailable, configured enhanced memory-only caching")
    
    def get_tenant_config(self, tenant_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """Get cached tenant configuration."""
        cache_key = f"tenant_config:{tenant_id}"
        
        if not force_refresh:
            # Try local cache first
            with self._lock:
                cached = self.local_cache.get(cache_key)
                if cached is not None:
                    return cached
            
            # Try Redis cache
            if self.redis_client:
                try:
                    cached_data = self.redis_client.get(cache_key)
                    if cached_data:
                        config = json.loads(cached_data)
                        # Update local cache
                        with self._lock:
                            self.local_cache[cache_key] = config
                        return config
                except Exception as e:
                    log.debug(f"Redis cache error: {e}")
        
        # Load from database
        config = self._load_tenant_config_from_db(tenant_id)
        
        # Cache the result
        self._cache_tenant_config(cache_key, config)
        
        return config
    
    def invalidate_tenant_config(self, tenant_id: int):
        """Invalidate cached tenant configuration."""
        cache_key = f"tenant_config:{tenant_id}"
        
        # Remove from local cache
        with self._lock:
            self.local_cache.pop(cache_key, None)
        
        # Remove from Redis
        if self.redis_client:
            try:
                self.redis_client.delete(cache_key)
            except Exception as e:
                log.debug(f"Redis cache invalidation error: {e}")
    
    def cache_tenant_branding(self, tenant_id: int, branding_data: Dict[str, Any], 
                             ttl: int = 3600):
        """Cache tenant branding data with TTL."""
        cache_key = f"tenant_branding:{tenant_id}"
        
        # Cache locally
        with self._lock:
            self.local_cache[cache_key] = branding_data
        
        # Cache in Redis with TTL
        if self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key, 
                    ttl, 
                    json.dumps(branding_data, default=str)
                )
            except Exception as e:
                log.debug(f"Redis branding cache error: {e}")
    
    def get_tenant_branding(self, tenant_id: int) -> Dict[str, Any]:
        """Get cached tenant branding data."""
        cache_key = f"tenant_branding:{tenant_id}"
        
        # Try local cache first
        with self._lock:
            cached = self.local_cache.get(cache_key)
            if cached is not None:
                return cached
        
        # Try Redis cache
        if self.redis_client:
            try:
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    branding = json.loads(cached_data)
                    # Update local cache
                    with self._lock:
                        self.local_cache[cache_key] = branding
                    return branding
            except Exception as e:
                log.debug(f"Redis branding cache error: {e}")
        
        return {}
    
    def cache_query_result(self, query_key: str, result: Any, ttl: int = 300):
        """Cache query results with tenant-aware keys."""
        tenant_id = getattr(g, 'current_tenant_id', None)
        if tenant_id:
            cache_key = f"query:{tenant_id}:{query_key}"
        else:
            cache_key = f"query:global:{query_key}"
        
        # Serialize result for caching
        try:
            if isinstance(result, list):
                # Handle SQLAlchemy model lists
                cache_data = [self._serialize_model(item) for item in result]
            else:
                cache_data = self._serialize_model(result)
            
            # Cache locally
            with self._lock:
                self.local_cache[cache_key] = cache_data
            
            # Cache in Redis
            if self.redis_client:
                try:
                    self.redis_client.setex(
                        cache_key, 
                        ttl, 
                        json.dumps(cache_data, default=str)
                    )
                except Exception as e:
                    log.debug(f"Redis query cache error: {e}")
                    
        except Exception as e:
            log.debug(f"Query result caching error: {e}")
    
    def get_cached_query_result(self, query_key: str) -> Optional[Any]:
        """Get cached query result."""
        tenant_id = getattr(g, 'current_tenant_id', None)
        if tenant_id:
            cache_key = f"query:{tenant_id}:{query_key}"
        else:
            cache_key = f"query:global:{query_key}"
        
        # Try local cache first
        with self._lock:
            cached = self.local_cache.get(cache_key)
            if cached is not None:
                return cached
        
        # Try Redis cache
        if self.redis_client:
            try:
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    result = json.loads(cached_data)
                    # Update local cache
                    with self._lock:
                        self.local_cache[cache_key] = result
                    return result
            except Exception as e:
                log.debug(f"Redis query cache error: {e}")
        
        return None
    
    def invalidate_tenant_cache(self, tenant_id: int):
        """Invalidate all cache entries for a tenant."""
        patterns = [
            f"tenant_config:{tenant_id}",
            f"tenant_branding:{tenant_id}", 
            f"query:{tenant_id}:*"
        ]
        
        # Clear local cache
        with self._lock:
            keys_to_remove = []
            for key in self.local_cache.keys():
                for pattern in patterns:
                    if pattern.replace('*', '') in key:
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                self.local_cache.pop(key, None)
        
        # Clear Redis cache
        if self.redis_client:
            try:
                for pattern in patterns:
                    keys = self.redis_client.keys(pattern)
                    if keys:
                        self.redis_client.delete(*keys)
            except Exception as e:
                log.debug(f"Redis cache invalidation error: {e}")
    
    def _load_tenant_config_from_db(self, tenant_id: int) -> Dict[str, Any]:
        """Load tenant configuration from database."""
        from pgappforge.models.tenant_models import Tenant, TenantConfig
        
        try:
            tenant = Tenant.query.get(tenant_id)
            if not tenant:
                return {}
            
            # Load all tenant configurations
            configs = TenantConfig.query.filter_by(tenant_id=tenant_id).all()
            
            config_dict = {
                'tenant_id': tenant.id,
                'slug': tenant.slug,
                'name': tenant.name,
                'status': tenant.status,
                'plan_id': tenant.plan_id,
                'resource_limits': tenant.resource_limits or {},
                'branding_config': tenant.branding_config or {},
                'custom_domain': tenant.custom_domain,
                'configs': {}
            }
            
            # Add individual configurations
            for config in configs:
                config_dict['configs'][config.config_key] = {
                    'value': config.config_value,
                    'type': config.config_type,
                    'category': config.category,
                    'is_sensitive': config.is_sensitive
                }
            
            return config_dict
            
        except Exception as e:
            log.error(f"Failed to load tenant config for {tenant_id}: {e}")
            return {}
    
    def _cache_tenant_config(self, cache_key: str, config: Dict[str, Any]):
        """Cache tenant configuration data."""
        # Cache locally
        with self._lock:
            self.local_cache[cache_key] = config
        
        # Cache in Redis with 1 hour TTL
        if self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key, 
                    3600, 
                    json.dumps(config, default=str)
                )
            except Exception as e:
                log.debug(f"Redis config cache error: {e}")
    
    def _serialize_model(self, model) -> Dict[str, Any]:
        """Serialize SQLAlchemy model for caching."""
        if model is None:
            return None
        
        try:
            # Handle simple models
            if hasattr(model, '__table__'):
                result = {}
                for column in model.__table__.columns:
                    value = getattr(model, column.name)
                    if isinstance(value, (datetime, Decimal)):
                        value = str(value)
                    result[column.name] = value
                return result
            else:
                # Handle non-model objects
                return str(model)
        except Exception as e:
            log.debug(f"Model serialization error: {e}")
            return str(model)


# Decorators for performance optimization
def cached_query(cache_key: str, ttl: int = 300):
    """Decorator to cache query results."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_manager = get_cache_manager()
            
            # Try to get cached result
            cached_result = cache_manager.get_cached_query_result(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache_manager.cache_query_result(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


def tenant_cache_invalidator(cache_patterns: List[str]):
    """Decorator to invalidate cache after function execution."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Invalidate cache patterns
            cache_manager = get_cache_manager()
            tenant_id = getattr(g, 'current_tenant_id', None)
            
            if tenant_id:
                for pattern in cache_patterns:
                    if 'tenant_config' in pattern:
                        cache_manager.invalidate_tenant_config(tenant_id)
                    elif 'tenant_branding' in pattern:
                        cache_key = f"tenant_branding:{tenant_id}"
                        if cache_manager.redis_client:
                            try:
                                cache_manager.redis_client.delete(cache_key)
                            except Exception as e:
                                log.debug(f"Cache invalidation error: {e}")
            
            return result
        return wrapper
    return decorator


# Global instances
_db_optimizer = None
_cache_manager = None
_optimizer_lock = threading.Lock()


def get_db_optimizer() -> TenantDatabaseOptimizer:
    """Get global database optimizer instance."""
    global _db_optimizer
    if _db_optimizer is None:
        with _optimizer_lock:
            if _db_optimizer is None:
                _db_optimizer = TenantDatabaseOptimizer()
    return _db_optimizer


def get_cache_manager() -> TenantCacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        with _optimizer_lock:
            if _cache_manager is None:
                redis_url = current_app.config.get('REDIS_URL') if current_app else None
                _cache_manager = TenantCacheManager(redis_url)
    return _cache_manager


def initialize_performance_optimizations(app, db):
    """Initialize all performance optimizations for multi-tenant system."""
    log.info("Initializing multi-tenant performance optimizations...")
    
    # Database optimizations
    db_optimizer = get_db_optimizer()
    
    # Setup connection pooling first (before other DB operations)
    db_optimizer.setup_connection_pooling(app)
    
    # Verify connection pool is working
    try:
        if hasattr(db, 'engine') and hasattr(db.engine, 'pool'):
            pool = db.engine.pool
            log.info(f"Database connection pool status: "
                   f"size={getattr(pool, 'size', lambda: 'unknown')()}, "
                   f"checked_out={getattr(pool, 'checkedout', lambda: 'unknown')()}, "
                   f"overflow={getattr(pool, 'overflow', lambda: 'unknown')()}")
        else:
            log.warning("Could not verify database connection pool status")
    except Exception as e:
        log.debug(f"Error checking connection pool status: {e}")
    
    # Continue with other optimizations
    db_optimizer.setup_tenant_indexes(db)
    db_optimizer.optimize_tenant_queries(db)
    db_optimizer.setup_table_partitioning(db)
    
    # Cache manager initialization
    cache_manager = get_cache_manager()
    
    # Store instances in app context
    app.extensions['tenant_db_optimizer'] = db_optimizer
    app.extensions['tenant_cache_manager'] = cache_manager
    
    log.info("Multi-tenant performance optimizations initialized successfully")