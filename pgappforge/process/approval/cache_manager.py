"""
Centralized Caching Manager for PgForge Approval System

Provides intelligent caching strategies for approval workflows to improve
performance and reduce database load while maintaining data consistency.

CACHING STRATEGIES:
1. User role caching - Cache user role lookups
2. Workflow configuration caching - Cache workflow definitions
3. Department/Cost center caching - Cache organizational data
4. Expression evaluation caching - Cache computed expressions
5. Approval history caching - Cache recent approval histories
6. Security validation caching - Cache permission checks

FEATURES:
- TTL-based expiration
- Memory pressure management
- Cache invalidation strategies
- Performance monitoring
- Redis backend support
"""

import logging
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable, Union
from enum import Enum
from dataclasses import dataclass, field
from functools import wraps
from threading import Lock
import json

from flask import current_app

from .constants import PerformanceConstants

log = logging.getLogger(__name__)


class CacheBackend(Enum):
    """Supported cache backends."""
    MEMORY = "memory"
    REDIS = "redis"
    DISABLED = "disabled"


class CacheKeyPrefix(Enum):
    """Cache key prefixes for different data types."""
    USER_ROLES = "user_roles"
    WORKFLOW_CONFIG = "workflow_config"
    DEPARTMENT_HEAD = "dept_head"
    COST_CENTER_MGR = "cc_mgr"
    EXPRESSION_RESULT = "expr_result"
    APPROVAL_HISTORY = "approval_hist"
    SECURITY_PERM = "security_perm"
    USER_PERMISSIONS = "user_perms"
    ORGANIZATION_DATA = "org_data"


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    value: Any
    created_at: float
    ttl: int
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return time.time() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """Access cache entry and update statistics."""
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value


@dataclass
class CacheStatistics:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    memory_usage_bytes: int = 0
    total_entries: int = 0
    last_cleanup: float = field(default_factory=time.time)
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0


class ApprovalCacheManager:
    """
    Centralized cache manager for approval workflow system.
    
    Provides intelligent caching with TTL management, memory pressure handling,
    and performance monitoring.
    """
    
    def __init__(self, backend: CacheBackend = CacheBackend.MEMORY, config: Optional[Dict] = None):
        self.backend = backend
        self.config = config or {}
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._stats = CacheStatistics()
        
        # Configuration
        self.default_ttl = self.config.get('default_ttl', PerformanceConstants.DEFAULT_CACHE_TTL_SECONDS)
        self.max_memory_mb = self.config.get('max_memory_mb', 128)
        self.cleanup_interval = self.config.get('cleanup_interval', 300)  # 5 minutes
        self.max_entries = self.config.get('max_entries', 10000)
        
        # Redis setup if using Redis backend
        self._redis = None
        if backend == CacheBackend.REDIS:
            self._setup_redis()
            
        log.info(f"ApprovalCacheManager initialized with {backend.value} backend")
    
    def _setup_redis(self):
        """Setup Redis connection if Redis backend is selected."""
        try:
            import redis
            redis_url = self.config.get('redis_url', 'redis://localhost:6379/0')
            self._redis = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self._redis.ping()
            log.info(f"Redis cache backend connected: {redis_url}")
        except ImportError:
            log.error("Redis not available. Install redis-py to use Redis caching.")
            self.backend = CacheBackend.MEMORY
        except Exception as e:
            log.error(f"Failed to connect to Redis: {e}. Falling back to memory cache.")
            self.backend = CacheBackend.MEMORY
    
    def _generate_cache_key(self, prefix: CacheKeyPrefix, *args) -> str:
        """Generate standardized cache key."""
        # Convert args to strings and hash for consistent keys
        key_parts = [str(arg) for arg in args]
        key_data = ":".join(key_parts)
        key_hash = hashlib.md5(key_data.encode()).hexdigest()[:8]
        return f"fab_approval:{prefix.value}:{key_hash}"
    
    def _serialize_value(self, value: Any) -> str:
        """Serialize value for Redis storage."""
        try:
            return json.dumps(value, default=str)
        except Exception as e:
            log.warning(f"Failed to serialize cache value: {e}")
            return json.dumps(str(value))
    
    def _deserialize_value(self, value: str) -> Any:
        """Deserialize value from Redis storage."""
        try:
            return json.loads(value)
        except Exception as e:
            log.warning(f"Failed to deserialize cache value: {e}")
            return value
    
    def get(self, prefix: CacheKeyPrefix, *args, default: Any = None) -> Any:
        """Get value from cache."""
        if self.backend == CacheBackend.DISABLED:
            return default
            
        cache_key = self._generate_cache_key(prefix, *args)
        
        if self.backend == CacheBackend.REDIS and self._redis:
            return self._get_redis(cache_key, default)
        else:
            return self._get_memory(cache_key, default)
    
    def _get_memory(self, cache_key: str, default: Any) -> Any:
        """Get value from memory cache."""
        with self._lock:
            entry = self._cache.get(cache_key)
            
            if entry is None:
                self._stats.misses += 1
                return default
            
            if entry.is_expired():
                del self._cache[cache_key]
                self._stats.misses += 1
                self._stats.evictions += 1
                return default
            
            self._stats.hits += 1
            return entry.access()
    
    def _get_redis(self, cache_key: str, default: Any) -> Any:
        """Get value from Redis cache."""
        try:
            value = self._redis.get(cache_key)
            if value is None:
                self._stats.misses += 1
                return default
            
            self._stats.hits += 1
            return self._deserialize_value(value)
        except Exception as e:
            log.error(f"Redis get error: {e}")
            self._stats.misses += 1
            return default
    
    def set(self, prefix: CacheKeyPrefix, *args, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache."""
        if self.backend == CacheBackend.DISABLED:
            return True
            
        cache_key = self._generate_cache_key(prefix, *args)
        cache_ttl = ttl or self.default_ttl
        
        if self.backend == CacheBackend.REDIS and self._redis:
            return self._set_redis(cache_key, value, cache_ttl)
        else:
            return self._set_memory(cache_key, value, cache_ttl)
    
    def _set_memory(self, cache_key: str, value: Any, ttl: int) -> bool:
        """Set value in memory cache."""
        with self._lock:
            # Check memory pressure and cleanup if needed
            if len(self._cache) >= self.max_entries:
                self._cleanup_memory_cache()
            
            self._cache[cache_key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl
            )
            
            self._stats.total_entries = len(self._cache)
            return True
    
    def _set_redis(self, cache_key: str, value: Any, ttl: int) -> bool:
        """Set value in Redis cache."""
        try:
            serialized_value = self._serialize_value(value)
            self._redis.setex(cache_key, ttl, serialized_value)
            return True
        except Exception as e:
            log.error(f"Redis set error: {e}")
            return False
    
    def delete(self, prefix: CacheKeyPrefix, *args) -> bool:
        """Delete value from cache."""
        if self.backend == CacheBackend.DISABLED:
            return True
            
        cache_key = self._generate_cache_key(prefix, *args)
        
        if self.backend == CacheBackend.REDIS and self._redis:
            return self._delete_redis(cache_key)
        else:
            return self._delete_memory(cache_key)
    
    def _delete_memory(self, cache_key: str) -> bool:
        """Delete value from memory cache."""
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                self._stats.total_entries = len(self._cache)
                return True
            return False
    
    def _delete_redis(self, cache_key: str) -> bool:
        """Delete value from Redis cache."""
        try:
            return bool(self._redis.delete(cache_key))
        except Exception as e:
            log.error(f"Redis delete error: {e}")
            return False
    
    def clear_prefix(self, prefix: CacheKeyPrefix) -> int:
        """Clear all cache entries with given prefix."""
        if self.backend == CacheBackend.DISABLED:
            return 0
            
        if self.backend == CacheBackend.REDIS and self._redis:
            return self._clear_prefix_redis(prefix)
        else:
            return self._clear_prefix_memory(prefix)
    
    def _clear_prefix_memory(self, prefix: CacheKeyPrefix) -> int:
        """Clear prefix from memory cache."""
        prefix_pattern = f"fab_approval:{prefix.value}:"
        cleared = 0
        
        with self._lock:
            keys_to_delete = [key for key in self._cache.keys() if key.startswith(prefix_pattern)]
            for key in keys_to_delete:
                del self._cache[key]
                cleared += 1
            
            self._stats.total_entries = len(self._cache)
            self._stats.evictions += cleared
        
        return cleared
    
    def _clear_prefix_redis(self, prefix: CacheKeyPrefix) -> int:
        """Clear prefix from Redis cache."""
        try:
            pattern = f"fab_approval:{prefix.value}:*"
            keys = self._redis.keys(pattern)
            if keys:
                return self._redis.delete(*keys)
            return 0
        except Exception as e:
            log.error(f"Redis clear prefix error: {e}")
            return 0
    
    def _cleanup_memory_cache(self):
        """Cleanup expired entries and apply LRU eviction if needed."""
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = [
            key for key, entry in self._cache.items() 
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
            
        self._stats.evictions += len(expired_keys)
        
        # Apply LRU eviction if still over limit
        if len(self._cache) >= self.max_entries:
            # Sort by last access time and remove oldest
            sorted_entries = sorted(
                self._cache.items(),
                key=lambda x: x[1].last_accessed
            )
            
            entries_to_remove = len(self._cache) - (self.max_entries // 2)
            for key, _ in sorted_entries[:entries_to_remove]:
                del self._cache[key]
                
            self._stats.evictions += entries_to_remove
        
        self._stats.total_entries = len(self._cache)
        self._stats.last_cleanup = current_time
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        with self._lock:
            stats = {
                'backend': self.backend.value,
                'hit_rate': self._stats.hit_rate,
                'hits': self._stats.hits,
                'misses': self._stats.misses,
                'evictions': self._stats.evictions,
                'total_entries': self._stats.total_entries,
                'memory_usage_mb': self._estimate_memory_usage(),
                'last_cleanup': datetime.fromtimestamp(self._stats.last_cleanup).isoformat(),
                'config': {
                    'default_ttl': self.default_ttl,
                    'max_memory_mb': self.max_memory_mb,
                    'max_entries': self.max_entries
                }
            }
            
            if self.backend == CacheBackend.REDIS and self._redis:
                try:
                    redis_info = self._redis.info('memory')
                    stats['redis_memory_mb'] = redis_info.get('used_memory', 0) / 1024 / 1024
                except Exception:
                    pass
            
            return stats
    
    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB for memory cache."""
        if not self._cache:
            return 0.0
        
        # Rough estimation
        total_size = 0
        sample_size = min(100, len(self._cache))
        sample_entries = list(self._cache.values())[:sample_size]
        
        for entry in sample_entries:
            # Estimate size of entry
            value_size = len(str(entry.value))
            total_size += value_size + 100  # Add overhead estimate
        
        # Extrapolate to full cache
        avg_entry_size = total_size / sample_size if sample_size > 0 else 0
        estimated_total = avg_entry_size * len(self._cache)
        
        return estimated_total / 1024 / 1024  # Convert to MB


def cache_result(
    prefix: CacheKeyPrefix,
    ttl: Optional[int] = None,
    key_args: Optional[List[str]] = None
):
    """
    Decorator for caching function results.
    
    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_args: List of argument names to include in cache key
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get cache manager from current app or create default
            cache_manager = getattr(current_app, '_approval_cache_manager', None)
            if not cache_manager:
                cache_manager = ApprovalCacheManager()
                current_app._approval_cache_manager = cache_manager
            
            # Build cache key from specified arguments
            if key_args:
                # Use specific arguments for cache key
                cache_key_parts = []
                func_args = func.__code__.co_varnames[:func.__code__.co_argcount]
                
                for i, arg_name in enumerate(func_args):
                    if arg_name in key_args and i < len(args):
                        cache_key_parts.append(str(args[i]))
                
                for arg_name in key_args:
                    if arg_name in kwargs:
                        cache_key_parts.append(str(kwargs[arg_name]))
            else:
                # Use all arguments for cache key
                cache_key_parts = [str(arg) for arg in args] + [f"{k}={v}" for k, v in kwargs.items()]
            
            # Check cache
            cached_result = cache_manager.get(prefix, func.__name__, *cache_key_parts)
            if cached_result is not None:
                return cached_result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache_manager.set(prefix, func.__name__, *cache_key_parts, value=result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


# Global cache manager instance
_global_cache_manager: Optional[ApprovalCacheManager] = None


def get_cache_manager() -> ApprovalCacheManager:
    """Get or create global cache manager instance."""
    global _global_cache_manager
    
    if _global_cache_manager is None:
        # Get configuration from Flask app if available
        config = {}
        try:
            if current_app:
                config = current_app.config.get('APPROVAL_CACHE_CONFIG', {})
        except RuntimeError:
            pass  # No application context
        
        backend_name = config.get('backend', 'memory')
        backend = CacheBackend(backend_name)
        
        _global_cache_manager = ApprovalCacheManager(backend, config)
    
    return _global_cache_manager


def clear_cache():
    """Clear all cache entries."""
    global _global_cache_manager
    if _global_cache_manager:
        for prefix in CacheKeyPrefix:
            _global_cache_manager.clear_prefix(prefix)