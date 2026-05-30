"""
Enhanced AI Security and Rate Limiting System for PgForge

Provides comprehensive security controls, usage monitoring, and resource management
for AI operations including advanced rate limiting, quota management, and audit logging.
"""

import time
import json
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, NamedTuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import threading
from functools import wraps

from flask import request, current_app, g
from flask_login import current_user

logger = logging.getLogger(__name__)


class QuotaType(Enum):
    """Types of AI usage quotas."""
    REQUESTS_PER_HOUR = "requests_per_hour"
    TOKENS_PER_DAY = "tokens_per_day"
    COST_PER_MONTH = "cost_per_month"
    CONCURRENT_REQUESTS = "concurrent_requests"


class SecurityEvent(Enum):
    """AI security event types."""
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"
    SUSPICIOUS_PROMPT = "suspicious_prompt"
    API_KEY_UNAUTHORIZED = "api_key_unauthorized"
    CONTENT_FILTERED = "content_filtered"
    COST_THRESHOLD_EXCEEDED = "cost_threshold_exceeded"


@dataclass
class AIQuota:
    """AI usage quota configuration."""
    quota_type: QuotaType
    limit: int
    window_minutes: int = 60
    cost_per_token: float = 0.0001
    burst_allowance: int = 0


@dataclass
class AIUsageMetrics:
    """AI usage metrics tracking."""
    user_id: int
    workspace_id: Optional[int]
    requests_count: int = 0
    tokens_used: int = 0
    cost_incurred: float = 0.0
    last_request: Optional[datetime] = None
    concurrent_requests: int = 0
    quota_violations: int = 0


class AIRateLimiter:
    """Advanced rate limiter for AI operations with multiple strategies."""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.local_storage = defaultdict(lambda: defaultdict(deque))
        self.lock = threading.RLock()

    def is_allowed(self, key: str, limit: int, window_seconds: int,
                   burst_limit: Optional[int] = None) -> tuple[bool, dict]:
        """
        Check if request is allowed under rate limiting rules.

        Returns:
            (is_allowed, metadata) tuple with rate limit status and metadata
        """
        current_time = time.time()

        if self.redis_client:
            return self._redis_rate_limit(key, limit, window_seconds, burst_limit, current_time)
        else:
            return self._memory_rate_limit(key, limit, window_seconds, burst_limit, current_time)

    def _redis_rate_limit(self, key: str, limit: int, window_seconds: int,
                         burst_limit: Optional[int], current_time: float) -> tuple[bool, dict]:
        """Redis-based distributed rate limiting."""
        try:
            pipe = self.redis_client.pipeline()

            # Use sliding window log with Redis
            window_key = f"rl:{key}:{int(current_time // window_seconds)}"
            burst_key = f"rl_burst:{key}"

            # Remove old entries
            cutoff_time = current_time - window_seconds
            pipe.zremrangebyscore(window_key, 0, cutoff_time)

            # Count current requests
            pipe.zcard(window_key)

            # Check burst limit if specified
            if burst_limit:
                pipe.get(burst_key)

            results = pipe.execute()
            current_count = results[1]
            burst_count = int(results[2] or 0) if burst_limit else 0

            # Check limits
            if current_count >= limit:
                return False, {
                    'limit': limit,
                    'current': current_count,
                    'window_seconds': window_seconds,
                    'reset_time': (int(current_time // window_seconds) + 1) * window_seconds
                }

            if burst_limit and burst_count >= burst_limit:
                return False, {
                    'burst_limit': burst_limit,
                    'burst_current': burst_count,
                    'type': 'burst_limit'
                }

            # Allow request and record it
            pipe = self.redis_client.pipeline()
            pipe.zadd(window_key, {str(current_time): current_time})
            pipe.expire(window_key, window_seconds + 1)

            if burst_limit:
                pipe.incr(burst_key)
                pipe.expire(burst_key, 60)  # 1 minute burst window

            pipe.execute()

            return True, {
                'limit': limit,
                'current': current_count + 1,
                'remaining': limit - current_count - 1,
                'window_seconds': window_seconds
            }

        except Exception as e:
            logger.error(f"Redis rate limiting error: {e}")
            # Fallback to memory-based limiting
            return self._memory_rate_limit(key, limit, window_seconds, burst_limit, current_time)

    def _memory_rate_limit(self, key: str, limit: int, window_seconds: int,
                          burst_limit: Optional[int], current_time: float) -> tuple[bool, dict]:
        """Memory-based rate limiting for single instance."""
        with self.lock:
            requests = self.local_storage[key]['requests']
            burst_requests = self.local_storage[key]['burst']

            # Clean old requests
            cutoff_time = current_time - window_seconds
            while requests and requests[0] < cutoff_time:
                requests.popleft()

            # Clean burst requests (1 minute window)
            burst_cutoff = current_time - 60
            while burst_requests and burst_requests[0] < burst_cutoff:
                burst_requests.popleft()

            current_count = len(requests)
            burst_count = len(burst_requests)

            # Check limits
            if current_count >= limit:
                return False, {
                    'limit': limit,
                    'current': current_count,
                    'window_seconds': window_seconds,
                    'reset_time': requests[0] + window_seconds if requests else current_time + window_seconds
                }

            if burst_limit and burst_count >= burst_limit:
                return False, {
                    'burst_limit': burst_limit,
                    'burst_current': burst_count,
                    'type': 'burst_limit'
                }

            # Allow request
            requests.append(current_time)
            if burst_limit:
                burst_requests.append(current_time)

            return True, {
                'limit': limit,
                'current': current_count + 1,
                'remaining': limit - current_count - 1,
                'window_seconds': window_seconds
            }


class AIQuotaManager:
    """Manages AI usage quotas and enforcement."""

    def __init__(self, db_session, redis_client=None):
        self.db_session = db_session
        self.redis_client = redis_client
        self.usage_cache = {}
        self.lock = threading.RLock()

        # Default quotas
        self.default_quotas = {
            QuotaType.REQUESTS_PER_HOUR: AIQuota(QuotaType.REQUESTS_PER_HOUR, 100, 60),
            QuotaType.TOKENS_PER_DAY: AIQuota(QuotaType.TOKENS_PER_DAY, 50000, 1440),
            QuotaType.COST_PER_MONTH: AIQuota(QuotaType.COST_PER_MONTH, 50, 43200),
            QuotaType.CONCURRENT_REQUESTS: AIQuota(QuotaType.CONCURRENT_REQUESTS, 5, 1)
        }

    def check_quota(self, user_id: int, quota_type: QuotaType,
                   usage_amount: int = 1, workspace_id: Optional[int] = None) -> tuple[bool, dict]:
        """
        Check if user is within quota limits.

        Returns:
            (within_quota, metadata) tuple
        """
        quota = self.get_user_quota(user_id, quota_type)
        current_usage = self.get_current_usage(user_id, quota_type, quota.window_minutes, workspace_id)

        projected_usage = current_usage + usage_amount

        if projected_usage > quota.limit:
            return False, {
                'quota_type': quota_type.value,
                'limit': quota.limit,
                'current': current_usage,
                'requested': usage_amount,
                'projected': projected_usage,
                'window_minutes': quota.window_minutes
            }

        return True, {
            'quota_type': quota_type.value,
            'limit': quota.limit,
            'current': current_usage,
            'remaining': quota.limit - projected_usage,
            'window_minutes': quota.window_minutes
        }

    def record_usage(self, user_id: int, tokens_used: int, cost: float,
                    workspace_id: Optional[int] = None, request_metadata: Optional[dict] = None):
        """Record AI usage for quota tracking."""
        timestamp = datetime.now(tz=timezone.utc)

        usage_record = {
            'user_id': user_id,
            'workspace_id': workspace_id,
            'timestamp': timestamp.isoformat(),
            'tokens_used': tokens_used,
            'cost': cost,
            'metadata': request_metadata or {}
        }

        # Store in Redis for fast access
        if self.redis_client:
            key = f"ai_usage:{user_id}:{timestamp.strftime('%Y%m%d%H')}"
            self.redis_client.lpush(key, json.dumps(usage_record))
            self.redis_client.expire(key, 86400 * 31)  # Keep for 31 days

        # Store in database for persistence
        try:
            # This would integrate with your actual database models
            logger.info(f"Recording AI usage: {usage_record}")
        except Exception as e:
            logger.error(f"Failed to record AI usage: {e}")

    def get_user_quota(self, user_id: int, quota_type: QuotaType) -> AIQuota:
        """Get quota configuration for user."""
        # This could be enhanced to support per-user quotas from database
        return self.default_quotas.get(quota_type, self.default_quotas[QuotaType.REQUESTS_PER_HOUR])

    def get_current_usage(self, user_id: int, quota_type: QuotaType,
                         window_minutes: int, workspace_id: Optional[int] = None) -> int:
        """Get current usage for the specified time window."""
        if not self.redis_client:
            return 0

        try:
            now = datetime.now(tz=timezone.utc)
            start_time = now - timedelta(minutes=window_minutes)

            # Aggregate usage from Redis
            pattern = f"ai_usage:{user_id}:*"
            keys = self.redis_client.keys(pattern)

            total_usage = 0
            for key in keys:
                records = self.redis_client.lrange(key, 0, -1)
                for record_json in records:
                    record = json.loads(record_json)
                    record_time = datetime.fromisoformat(record['timestamp'])

                    if record_time >= start_time:
                        if workspace_id is None or record.get('workspace_id') == workspace_id:
                            if quota_type == QuotaType.REQUESTS_PER_HOUR:
                                total_usage += 1
                            elif quota_type == QuotaType.TOKENS_PER_DAY:
                                total_usage += record.get('tokens_used', 0)
                            elif quota_type == QuotaType.COST_PER_MONTH:
                                total_usage += record.get('cost', 0)

            return total_usage

        except Exception as e:
            logger.error(f"Error getting current usage: {e}")
            return 0


class AISecurityMonitor:
    """Monitors AI operations for security events and anomalies."""

    def __init__(self, db_session, redis_client=None):
        self.db_session = db_session
        self.redis_client = redis_client
        self.alert_thresholds = {
            'suspicious_prompts_per_hour': 10,
            'rapid_requests_per_minute': 30,
            'high_cost_per_hour': 10.0,
            'quota_violations_per_day': 5
        }

    def log_security_event(self, event_type: SecurityEvent, user_id: int,
                          event_data: dict, severity: str = "warning"):
        """Log security events for monitoring and alerting."""
        timestamp = datetime.now(tz=timezone.utc)

        security_event = {
            'event_type': event_type.value,
            'user_id': user_id,
            'timestamp': timestamp.isoformat(),
            'severity': severity,
            'data': event_data,
            'ip_address': request.remote_addr if request else None,
            'user_agent': request.user_agent.string if request else None
        }

        # Log to application logger
        logger.warning(f"AI Security Event: {security_event}")

        # Store in Redis for real-time monitoring
        if self.redis_client:
            key = f"ai_security_events:{timestamp.strftime('%Y%m%d')}"
            self.redis_client.lpush(key, json.dumps(security_event))
            self.redis_client.expire(key, 86400 * 7)  # Keep for 7 days

        # Check for alert conditions
        self._check_alert_conditions(user_id, event_type, timestamp)

    def _check_alert_conditions(self, user_id: int, event_type: SecurityEvent, timestamp: datetime):
        """Check if security event triggers any alerts."""
        if not self.redis_client:
            return

        hour_key = f"ai_security_events:{timestamp.strftime('%Y%m%d%H')}"
        day_key = f"ai_security_events:{timestamp.strftime('%Y%m%d')}"

        try:
            # Count events in last hour
            hour_events = self.redis_client.lrange(hour_key, 0, -1)
            user_events_hour = [
                json.loads(event) for event in hour_events
                if json.loads(event).get('user_id') == user_id
            ]

            # Check suspicious prompts threshold
            if event_type == SecurityEvent.SUSPICIOUS_PROMPT:
                suspicious_count = len([e for e in user_events_hour if e['event_type'] == 'suspicious_prompt'])
                if suspicious_count >= self.alert_thresholds['suspicious_prompts_per_hour']:
                    self._trigger_security_alert(user_id, 'high_suspicious_activity', {
                        'suspicious_prompts_count': suspicious_count,
                        'threshold': self.alert_thresholds['suspicious_prompts_per_hour']
                    })

            # Check rapid requests
            minute_events = [e for e in user_events_hour
                           if datetime.fromisoformat(e['timestamp']) > timestamp - timedelta(minutes=1)]
            if len(minute_events) >= self.alert_thresholds['rapid_requests_per_minute']:
                self._trigger_security_alert(user_id, 'rapid_requests', {
                    'requests_per_minute': len(minute_events),
                    'threshold': self.alert_thresholds['rapid_requests_per_minute']
                })

        except Exception as e:
            logger.error(f"Error checking alert conditions: {e}")

    def _trigger_security_alert(self, user_id: int, alert_type: str, alert_data: dict):
        """Trigger security alert for immediate attention."""
        alert = {
            'alert_type': alert_type,
            'user_id': user_id,
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'data': alert_data,
            'status': 'active'
        }

        logger.critical(f"AI Security Alert: {alert}")

        # Store alert for dashboard display
        if self.redis_client:
            self.redis_client.lpush("ai_security_alerts", json.dumps(alert))
            self.redis_client.ltrim("ai_security_alerts", 0, 99)  # Keep last 100 alerts


class EnhancedAISecurityManager:
    """Enhanced AI security manager with comprehensive controls."""

    def __init__(self, app=None, redis_client=None):
        self.app = app
        self.redis_client = redis_client
        self.rate_limiter = AIRateLimiter(redis_client)
        self.quota_manager = AIQuotaManager(None, redis_client)  # DB session would be injected
        self.security_monitor = AISecurityMonitor(None, redis_client)

        # Load configuration
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load AI security configuration."""
        if self.app:
            return {
                'rate_limits': {
                    'chat_requests_per_minute': self.app.config.get('AI_CHAT_RATE_LIMIT', 20),
                    'embedding_requests_per_hour': self.app.config.get('AI_EMBEDDING_RATE_LIMIT', 1000),
                    'expensive_requests_per_hour': self.app.config.get('AI_EXPENSIVE_RATE_LIMIT', 10)
                },
                'quotas': {
                    'default_tokens_per_day': self.app.config.get('AI_DEFAULT_TOKENS_PER_DAY', 50000),
                    'default_cost_per_month': self.app.config.get('AI_DEFAULT_COST_PER_MONTH', 50.0)
                },
                'monitoring': {
                    'log_all_requests': self.app.config.get('AI_LOG_ALL_REQUESTS', True),
                    'content_filtering_enabled': self.app.config.get('AI_CONTENT_FILTERING', True)
                }
            }
        return {}

    def enforce_ai_security(self, operation_type: str, user_id: Optional[int] = None,
                           workspace_id: Optional[int] = None, **kwargs):
        """Comprehensive AI security enforcement decorator."""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **func_kwargs):
                # Get user ID from context if not provided
                effective_user_id = user_id or (current_user.id if current_user.is_authenticated else None)

                if not effective_user_id:
                    raise SecurityError("Authentication required for AI operations")

                # Rate limiting check
                rate_limit_key = f"ai:{operation_type}:user:{effective_user_id}"
                rate_limit_config = self.config.get('rate_limits', {})
                limit = rate_limit_config.get(f"{operation_type}_per_minute", 10)

                is_allowed, rate_metadata = self.rate_limiter.is_allowed(
                    rate_limit_key, limit, 60, burst_limit=limit * 2
                )

                if not is_allowed:
                    self.security_monitor.log_security_event(
                        SecurityEvent.RATE_LIMIT_EXCEEDED,
                        effective_user_id,
                        {
                            'operation_type': operation_type,
                            'rate_limit_metadata': rate_metadata
                        }
                    )
                    raise RateLimitError(f"Rate limit exceeded for {operation_type}")

                # Quota checking
                estimated_tokens = kwargs.get('estimated_tokens', 100)
                quota_allowed, quota_metadata = self.quota_manager.check_quota(
                    effective_user_id, QuotaType.TOKENS_PER_DAY, estimated_tokens, workspace_id
                )

                if not quota_allowed:
                    self.security_monitor.log_security_event(
                        SecurityEvent.QUOTA_EXCEEDED,
                        effective_user_id,
                        {
                            'operation_type': operation_type,
                            'quota_metadata': quota_metadata
                        }
                    )
                    raise QuotaExceededError(f"Token quota exceeded: {quota_metadata}")

                # Execute the operation
                start_time = time.time()
                try:
                    result = func(*args, **func_kwargs)

                    # Record successful usage
                    execution_time = time.time() - start_time
                    actual_tokens = kwargs.get('actual_tokens', estimated_tokens)
                    actual_cost = kwargs.get('actual_cost', actual_tokens * 0.0001)

                    self.quota_manager.record_usage(
                        effective_user_id, actual_tokens, actual_cost, workspace_id,
                        {
                            'operation_type': operation_type,
                            'execution_time': execution_time,
                            'rate_limit_metadata': rate_metadata
                        }
                    )

                    return result

                except Exception as e:
                    # Log failed operations
                    self.security_monitor.log_security_event(
                        SecurityEvent.API_KEY_UNAUTHORIZED if "unauthorized" in str(e).lower()
                        else SecurityEvent.CONTENT_FILTERED,
                        effective_user_id,
                        {
                            'operation_type': operation_type,
                            'error': str(e),
                            'execution_time': time.time() - start_time
                        },
                        severity="error"
                    )
                    raise

            return wrapper
        return decorator


# Custom exceptions
class QuotaExceededError(Exception):
    """Raised when AI usage quota is exceeded."""
    pass


class SecurityError(Exception):
    """Raised when AI security validation fails."""
    pass


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


# Global instance
_enhanced_security_manager = None


def get_enhanced_security_manager(app=None, redis_client=None) -> EnhancedAISecurityManager:
    """Get or create enhanced AI security manager."""
    global _enhanced_security_manager

    if _enhanced_security_manager is None:
        _enhanced_security_manager = EnhancedAISecurityManager(app, redis_client)

    return _enhanced_security_manager


# Convenience decorators
def ai_rate_limited(operation_type: str, **kwargs):
    """Decorator for rate-limited AI operations."""
    def decorator(func):
        security_manager = get_enhanced_security_manager()
        return security_manager.enforce_ai_security(operation_type, **kwargs)(func)
    return decorator


def ai_quota_enforced(operation_type: str, **kwargs):
    """Decorator for quota-enforced AI operations."""
    return ai_rate_limited(operation_type, **kwargs)  # Same implementation for now