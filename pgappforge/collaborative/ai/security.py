"""
AI Security Manager for PgForge Collaborative Features

Provides secure credential management, prompt sanitization, and input validation
for AI integrations to prevent API key exposure and injection attacks.
"""
import os
import re
import logging
import hashlib
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache


class SecurityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PromptValidationResult:
    """Result of prompt validation."""
    is_valid: bool
    sanitized_prompt: str
    security_level: SecurityLevel
    violations: List[str]
    metadata: Dict[str, Any]


class PromptSanitizer:
    """Sanitizes user prompts to prevent injection attacks."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Dangerous patterns that could be injection attempts
        self.injection_patterns = [
            r'ignore\s+all\s+previous\s+instructions',
            r'forget\s+everything\s+above',
            r'system\s*:\s*you\s+are\s+now',
            r'jailbreak|prompt\s+injection',
            r'\\x[0-9a-f]{2}',  # Hex encoded characters
            r'[^\x20-\x7E]',    # Non-printable ASCII
            r'(?:assistant|ai|model)\s*:\s*i\s+will\s+now',
            r'override\s+previous\s+instructions',
            r'disregard\s+safety\s+guidelines',
            r'act\s+as\s+if\s+you\s+are'
        ]

        # Compile patterns for performance
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.injection_patterns]

        # Content filtering
        self.max_prompt_length = 4000
        self.max_tokens_estimate = 1000

    def sanitize_prompt(self, prompt: str) -> PromptValidationResult:
        """
        Sanitize user prompt and detect potential injection attempts.

        Args:
            prompt: Raw user prompt to sanitize

        Returns:
            PromptValidationResult with validation status and sanitized content
        """
        violations = []
        security_level = SecurityLevel.LOW

        if not prompt or not isinstance(prompt, str):
            return PromptValidationResult(
                is_valid=False,
                sanitized_prompt="",
                security_level=SecurityLevel.CRITICAL,
                violations=["Empty or invalid prompt"],
                metadata={}
            )

        # Strip leading/trailing whitespace
        sanitized = prompt.strip()

        # Check length limits
        if len(sanitized) > self.max_prompt_length:
            violations.append(f"Prompt too long: {len(sanitized)} > {self.max_prompt_length}")
            sanitized = sanitized[:self.max_prompt_length]
            security_level = SecurityLevel.MEDIUM

        # Check for injection patterns
        for i, pattern in enumerate(self.compiled_patterns):
            if pattern.search(sanitized):
                violations.append(f"Potential injection pattern detected: {self.injection_patterns[i]}")
                security_level = SecurityLevel.HIGH

                # Remove or mask suspicious content
                sanitized = pattern.sub("[CONTENT_FILTERED]", sanitized)

        # Remove null bytes and control characters (except tab, newline, carriage return)
        sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', sanitized)

        # Normalize excessive whitespace
        sanitized = re.sub(r'\s+', ' ', sanitized)

        # Check for attempts to break out of context
        context_breaking_patterns = [
            r'"""',
            r"'''",
            r'```',
            r'<\s*script\s*>',
            r'<\s*iframe\s*>',
            r'javascript\s*:',
            r'data\s*:\s*text/html'
        ]

        for pattern in context_breaking_patterns:
            if re.search(pattern, sanitized, re.IGNORECASE):
                violations.append(f"Context breaking pattern detected: {pattern}")
                security_level = SecurityLevel.HIGH
                sanitized = re.sub(pattern, "[FILTERED]", sanitized, flags=re.IGNORECASE)

        # Estimate token count (rough approximation)
        estimated_tokens = len(sanitized.split()) * 1.3  # Average tokens per word
        if estimated_tokens > self.max_tokens_estimate:
            violations.append(f"Estimated tokens too high: {estimated_tokens}")
            security_level = SecurityLevel.MEDIUM

        # Final validation
        is_valid = security_level != SecurityLevel.CRITICAL and len(sanitized.strip()) > 0

        # Log security violations
        if violations:
            self.logger.warning(f"Prompt sanitization violations: {violations}")

        return PromptValidationResult(
            is_valid=is_valid,
            sanitized_prompt=sanitized,
            security_level=security_level,
            violations=violations,
            metadata={
                "original_length": len(prompt),
                "sanitized_length": len(sanitized),
                "estimated_tokens": estimated_tokens,
                "violations_count": len(violations)
            }
        )


class SecureCredentialManager:
    """Manages secure storage and retrieval of API credentials."""

    def __init__(self, app=None):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self._credentials_cache = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamps = {}

    def get_api_key(self, provider: str) -> Optional[str]:
        """
        Retrieve API key for provider from secure storage.

        Priority order:
        1. Environment variables
        2. Flask app config
        3. External key vault (if configured)

        Args:
            provider: Provider name (openai, anthropic, etc.)

        Returns:
            API key string or None if not found
        """
        provider = provider.lower()
        cache_key = f"{provider}_api_key"

        # Check cache first
        if self._is_cache_valid(cache_key):
            return self._credentials_cache.get(cache_key)

        # Try environment variables first (most secure)
        env_key = f"{provider.upper()}_API_KEY"
        api_key = os.getenv(env_key)

        if not api_key and self.app:
            # Fallback to Flask config
            config_key = f"{provider.upper()}_API_KEY"
            api_key = self.app.config.get(config_key)

        if not api_key:
            # Try external key vault if configured
            api_key = self._get_from_key_vault(provider)

        if api_key:
            # Cache the credential
            self._credentials_cache[cache_key] = api_key
            self._cache_timestamps[cache_key] = time.time()

            self.logger.info(f"Retrieved API key for provider: {provider}")
        else:
            self.logger.warning(f"No API key found for provider: {provider}")

        return api_key

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached credential is still valid."""
        if cache_key not in self._credentials_cache:
            return False

        timestamp = self._cache_timestamps.get(cache_key, 0)
        return (time.time() - timestamp) < self._cache_ttl

    def _get_from_key_vault(self, provider: str) -> Optional[str]:
        """
        Retrieve API key from external key vault.

        Supported key vaults:
        - Azure Key Vault (set AZURE_KEY_VAULT_URL)
        - AWS Secrets Manager (set AWS_REGION)
        - HashiCorp Vault (set VAULT_URL and VAULT_TOKEN)
        """
        vault_backend = os.getenv('KEY_VAULT_BACKEND')

        if not vault_backend:
            self.logger.debug(f"No key vault backend configured for {provider}")
            return None

        if vault_backend == 'azure':
            return self._get_from_azure_key_vault(provider)
        elif vault_backend == 'aws':
            return self._get_from_aws_secrets_manager(provider)
        elif vault_backend == 'hashicorp':
            return self._get_from_hashicorp_vault(provider)
        else:
            self.logger.warning(f"Unsupported key vault backend: {vault_backend}")
            return None

    def _get_from_azure_key_vault(self, provider: str) -> Optional[str]:
        """Get API key from Azure Key Vault."""
        try:
            from azure.keyvault.secrets import SecretClient
            from azure.identity import DefaultAzureCredential

            vault_url = os.getenv('AZURE_KEY_VAULT_URL')
            if not vault_url:
                self.logger.error("AZURE_KEY_VAULT_URL not configured for Azure Key Vault")
                return None

            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)

            secret_name = f"{provider}-api-key"
            secret = client.get_secret(secret_name)
            return secret.value

        except ImportError:
            self.logger.error("Azure Key Vault not available. Install: pip install azure-keyvault-secrets azure-identity")
            return None
        except Exception as e:
            self.logger.error(f"Azure Key Vault error: {e}")
            return None

    def _get_from_aws_secrets_manager(self, provider: str) -> Optional[str]:
        """Get API key from AWS Secrets Manager."""
        try:
            import boto3

            region = os.getenv('AWS_REGION', 'us-east-1')
            client = boto3.client('secretsmanager', region_name=region)

            secret_name = f"{provider}-api-key"
            response = client.get_secret_value(SecretId=secret_name)
            return response['SecretString']

        except ImportError:
            self.logger.error("AWS SDK not available. Install: pip install boto3")
            return None
        except Exception as e:
            self.logger.error(f"AWS Secrets Manager error: {e}")
            return None

    def _get_from_hashicorp_vault(self, provider: str) -> Optional[str]:
        """Get API key from HashiCorp Vault."""
        try:
            import hvac

            vault_url = os.getenv('VAULT_URL', 'http://localhost:8200')
            vault_token = os.getenv('VAULT_TOKEN')

            if not vault_token:
                self.logger.error("VAULT_TOKEN not configured for HashiCorp Vault")
                return None

            client = hvac.Client(url=vault_url, token=vault_token)

            secret_path = f"secret/{provider}-api-key"
            response = client.secrets.kv.v2.read_secret_version(path=secret_path)
            return response['data']['data']['api_key']

        except ImportError:
            self.logger.error("HashiCorp Vault client not available. Install: pip install hvac")
            return None
        except Exception as e:
            self.logger.error(f"HashiCorp Vault error: {e}")
            return None

    def validate_api_key(self, provider: str, api_key: str) -> bool:
        """
        Validate API key format and basic security requirements.

        Args:
            provider: Provider name
            api_key: API key to validate

        Returns:
            True if key appears valid, False otherwise
        """
        if not api_key or not isinstance(api_key, str):
            return False

        # Remove whitespace
        api_key = api_key.strip()

        # Basic length and format checks
        if len(api_key) < 20:
            self.logger.warning(f"API key too short for {provider}")
            return False

        # Provider-specific validation
        if provider.lower() == 'openai':
            return api_key.startswith('sk-') and len(api_key) > 40
        elif provider.lower() == 'anthropic':
            return api_key.startswith('sk-ant-') and len(api_key) > 50

        # Generic validation for unknown providers
        return len(api_key) >= 20 and api_key.isalnum()


class AISecurityManager:
    """Main security manager for AI operations."""

    def __init__(self, app=None):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.credential_manager = SecureCredentialManager(app)
        self.prompt_sanitizer = PromptSanitizer()
        self._rate_limits = {}
        self._rate_limit_window = 60  # 1 minute
        self._max_requests_per_window = 100

    def get_secure_api_key(self, provider: str) -> str:
        """
        Get API key with additional security validation.

        Args:
            provider: AI provider name

        Returns:
            Validated API key

        Raises:
            SecurityError: If API key is missing or invalid
            RateLimitError: If rate limit exceeded
        """
        # Check rate limits
        if not self._check_rate_limit(f"api_key_request_{provider}"):
            raise RateLimitError(f"Rate limit exceeded for {provider} API key requests")

        api_key = self.credential_manager.get_api_key(provider)

        if not api_key:
            self.logger.error(f"Missing API key for provider: {provider}")
            raise SecurityError(f"API key not configured for {provider}")

        if not self.credential_manager.validate_api_key(provider, api_key):
            self.logger.error(f"Invalid API key format for provider: {provider}")
            raise SecurityError(f"Invalid API key for {provider}")

        return api_key

    def validate_and_sanitize_prompt(self, prompt: str, user_id: Optional[int] = None) -> PromptValidationResult:
        """
        Validate and sanitize user prompt with rate limiting.

        Args:
            prompt: User prompt to validate
            user_id: Optional user ID for rate limiting

        Returns:
            PromptValidationResult with sanitized content

        Raises:
            RateLimitError: If rate limit exceeded
        """
        # Rate limiting per user
        rate_limit_key = f"prompt_validation_{user_id or 'anonymous'}"
        if not self._check_rate_limit(rate_limit_key):
            raise RateLimitError("Prompt validation rate limit exceeded")

        result = self.prompt_sanitizer.sanitize_prompt(prompt)

        # Log security events
        if result.violations:
            self.logger.warning(
                f"Prompt security violations for user {user_id}: {result.violations}"
            )

        return result

    def _check_rate_limit(self, key: str) -> bool:
        """Check if operation is within rate limits."""
        current_time = time.time()
        window_start = current_time - self._rate_limit_window

        # Clean old entries
        if key in self._rate_limits:
            self._rate_limits[key] = [
                timestamp for timestamp in self._rate_limits[key]
                if timestamp > window_start
            ]
        else:
            self._rate_limits[key] = []

        # Check current count
        if len(self._rate_limits[key]) >= self._max_requests_per_window:
            return False

        # Add current request
        self._rate_limits[key].append(current_time)
        return True

    @lru_cache(maxsize=1000)
    def get_prompt_hash(self, prompt: str) -> str:
        """Generate hash for prompt deduplication and caching."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]


# Custom exceptions
class SecurityError(Exception):
    """Raised when security validation fails."""
    pass


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass


# Global security manager instance
_security_manager = None


def get_security_manager(app=None) -> AISecurityManager:
    """Get or create global security manager instance."""
    global _security_manager

    if _security_manager is None or (app and _security_manager.app != app):
        _security_manager = AISecurityManager(app)

    return _security_manager