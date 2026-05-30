# AI Security System Deployment Guide

## Overview

The enhanced AI security system provides comprehensive security controls, rate limiting, and monitoring for AI operations in PgAppForge. This guide covers deployment and configuration.

## Key Features Implemented

### ✅ Enhanced Rate Limiting
- **Multi-Strategy**: Memory-based and Redis-distributed rate limiting
- **Burst Protection**: Prevents rapid-fire requests that could abuse AI APIs
- **Configurable Limits**: Per-operation rate limits (chat, embeddings, expensive operations)

### ✅ Quota Management
- **Per-User Quotas**: Requests per hour, tokens per day, cost per month
- **Workspace-Aware**: Optional workspace-specific quota enforcement
- **Real-time Tracking**: Usage tracking with Redis for fast access

### ✅ Security Monitoring
- **Event Logging**: Comprehensive logging of AI security events
- **Anomaly Detection**: Automatic detection of suspicious patterns
- **Real-time Alerts**: Critical security alerts for immediate attention

### ✅ Content Filtering
- **Prompt Sanitization**: Detection and filtering of injection attempts
- **Content Validation**: Multiple validation layers for AI inputs/outputs
- **Security Levels**: Risk-based security level classification

## Configuration

### Environment Variables
```bash
# AI Rate Limiting
AI_CHAT_RATE_LIMIT=20                    # Chat requests per minute
AI_EMBEDDING_RATE_LIMIT=1000             # Embedding requests per hour
AI_EXPENSIVE_RATE_LIMIT=10               # Expensive operations per hour

# AI Quotas
AI_DEFAULT_TOKENS_PER_DAY=50000          # Default token quota per user per day
AI_DEFAULT_COST_PER_MONTH=50.0           # Default cost limit per user per month

# AI Monitoring
AI_LOG_ALL_REQUESTS=true                 # Log all AI requests
AI_CONTENT_FILTERING=true                # Enable content filtering

# Redis Configuration (for distributed rate limiting)
RATE_LIMIT_STORAGE_URL=redis://localhost:6379/0
```

### Flask App Configuration
```python
# config.py
class Config:
    # AI Security Configuration
    AI_CHAT_RATE_LIMIT = 20
    AI_EMBEDDING_RATE_LIMIT = 1000
    AI_EXPENSIVE_RATE_LIMIT = 10

    AI_DEFAULT_TOKENS_PER_DAY = 50000
    AI_DEFAULT_COST_PER_MONTH = 50.0

    AI_LOG_ALL_REQUESTS = True
    AI_CONTENT_FILTERING = True

    # Rate Limiting Backend
    RATE_LIMIT_STORAGE_URL = "redis://localhost:6379/0"
```

## Usage Examples

### Securing AI Operations with Decorators

```python
from pgappforge.collaborative.ai.enhanced_security import ai_rate_limited

@ai_rate_limited('chat_request', estimated_tokens=500)
def process_chat_request(prompt: str):
    # Your AI processing logic here
    response = ai_model.generate(prompt)
    return response

@ai_rate_limited('embedding_generation', estimated_tokens=100)
def generate_embeddings(text: str):
    # Embedding generation logic
    embeddings = ai_model.embed(text)
    return embeddings
```

### Manual Security Enforcement

```python
from pgappforge.collaborative.ai.enhanced_security import get_enhanced_security_manager

security_manager = get_enhanced_security_manager()

# Check rate limits manually
rate_limiter = security_manager.rate_limiter
is_allowed, metadata = rate_limiter.is_allowed(f"user:{user_id}", 10, 60)

if not is_allowed:
    raise RateLimitError("Too many requests")

# Check quotas manually
quota_manager = security_manager.quota_manager
within_quota, quota_info = quota_manager.check_quota(
    user_id, QuotaType.TOKENS_PER_DAY, estimated_tokens
)

if not within_quota:
    raise QuotaExceededError("Daily token quota exceeded")
```

## Monitoring and Alerts

### Security Event Monitoring
The system automatically logs security events to:
- Application logs (via Python logging)
- Redis for real-time monitoring
- Database for long-term storage (when configured)

### Alert Conditions
- **Suspicious Prompts**: >10 per hour triggers alert
- **Rapid Requests**: >30 per minute triggers alert
- **High Cost**: >$10 per hour triggers alert
- **Quota Violations**: >5 per day triggers alert

### Accessing Monitoring Data
```python
from pgappforge.collaborative.ai.enhanced_security import get_enhanced_security_manager

security_manager = get_enhanced_security_manager()
monitor = security_manager.security_monitor

# Log a security event
monitor.log_security_event(
    SecurityEvent.SUSPICIOUS_PROMPT,
    user_id=123,
    event_data={'prompt': 'detected_malicious_content'},
    severity='warning'
)
```

## Integration Points

### Existing AI Services
The enhanced security system integrates with:
- `ChatbotService`: Automatic rate limiting and quota enforcement
- `RAGEngine`: Content filtering and usage tracking
- `AIModelAdapter`: Provider-specific security controls

### Database Models
Security events and usage data can be stored in database models:
- `AIUsageRecord`: Track usage metrics
- `AISecurityEvent`: Log security violations
- `AIQuotaConfig`: User-specific quota configurations

## Production Deployment

### Redis Requirements
For production deployments, Redis is required for:
- Distributed rate limiting across multiple application instances
- Real-time usage tracking and quota enforcement
- Security event storage and monitoring

### Performance Considerations
- Rate limiting adds ~1-2ms overhead per request
- Redis operations are cached locally for 5 minutes
- Quota checking uses efficient Redis aggregation

### Security Best Practices
1. **Environment Variables**: Store API keys in environment variables, not config files
2. **Redis Security**: Use Redis AUTH and network isolation
3. **Monitoring**: Set up alerting for critical security events
4. **Quotas**: Set conservative quotas initially, adjust based on usage patterns

## Troubleshooting

### Common Issues

**Rate Limiting Not Working**
- Check Redis connectivity
- Verify configuration values
- Check application logs for errors

**High Memory Usage**
- Reduce cache TTL values
- Enable Redis for distributed storage
- Monitor Redis memory usage

**False Positive Security Alerts**
- Adjust alert thresholds in configuration
- Review prompt sanitization rules
- Check user behavior patterns

### Debugging
```python
# Enable debug logging
logging.getLogger('pgappforge.collaborative.ai.enhanced_security').setLevel(logging.DEBUG)

# Check current rate limit status
rate_limiter = get_enhanced_security_manager().rate_limiter
is_allowed, metadata = rate_limiter.is_allowed('debug_key', 10, 60)
print(f"Rate limit status: {metadata}")
```

## Performance Metrics

The enhanced AI security system provides:
- **Rate Limiting**: <2ms overhead per request
- **Quota Checking**: <5ms overhead per request
- **Content Filtering**: <10ms overhead per request
- **Memory Usage**: ~10MB base + 1KB per active user
- **Redis Storage**: ~1KB per user per day

## Upgrade Path

When upgrading existing PgAppForge installations:

1. Install Redis if not already available
2. Add configuration variables to your config file
3. Update AI service imports to use enhanced security
4. Test rate limiting and quota enforcement
5. Monitor security events and adjust thresholds as needed

This enhanced AI security system provides enterprise-grade protection for AI operations while maintaining high performance and ease of use.