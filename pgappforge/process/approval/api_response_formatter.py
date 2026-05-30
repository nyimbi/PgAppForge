"""
Standardized API Response Formatter for PgAppForge Approval System

Provides consistent API response formatting across all approval system endpoints
with proper error handling, metadata, and backwards compatibility.

STANDARDS IMPLEMENTED:
- Consistent response structure across all endpoints
- Proper HTTP status codes and error messages
- Request metadata for debugging and audit trails
- Backwards compatibility with existing API consumers
- RESTful API best practices
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from dataclasses import dataclass, asdict

from flask import request, current_app
from pgappforge.api import BaseApi

log = logging.getLogger(__name__)


class ResponseStatus(Enum):
    """Standard response status values."""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    PARTIAL = "partial"


class ErrorCode(Enum):
    """Standard error codes for approval system."""
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"  
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    NOT_FOUND_ERROR = "NOT_FOUND_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    DATABASE_ERROR = "DATABASE_ERROR"
    WORKFLOW_ERROR = "WORKFLOW_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BUSINESS_LOGIC_ERROR = "BUSINESS_LOGIC_ERROR"


@dataclass
class ApiResponseMetadata:
    """Metadata included in all API responses."""
    request_id: str
    timestamp: str
    endpoint: str
    method: str
    user_id: Optional[int] = None
    execution_time_ms: Optional[float] = None
    api_version: str = "v1"


@dataclass
class ApiError:
    """Standardized error information."""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    field: Optional[str] = None  # For validation errors


@dataclass
class ApiResponse:
    """Standardized API response structure."""
    status: str
    data: Optional[Union[Dict, List]] = None
    message: Optional[str] = None
    errors: Optional[List[ApiError]] = None
    metadata: Optional[ApiResponseMetadata] = None
    pagination: Optional[Dict[str, Any]] = None


class ApprovalApiResponseFormatter:
    """
    Centralized API response formatter for approval system endpoints.
    
    Provides consistent response formatting with proper error handling,
    metadata inclusion, and backwards compatibility support.
    """
    
    def __init__(self, api_instance: BaseApi):
        self.api = api_instance
        self._request_start_time = datetime.now(tz=timezone.utc)
        
    def _generate_request_id(self) -> str:
        """Generate unique request ID for tracking."""
        return str(uuid.uuid4())[:8]
        
    def _get_current_user_id(self) -> Optional[int]:
        """Get current user ID if authenticated."""
        try:
            current_user = self.api.appbuilder.sm.current_user
            return current_user.id if current_user and current_user.is_authenticated else None
        except Exception:
            return None
            
    def _calculate_execution_time(self) -> float:
        """Calculate request execution time in milliseconds."""
        end_time = datetime.now(tz=timezone.utc)
        duration = (end_time - self._request_start_time).total_seconds() * 1000
        return round(duration, 2)
        
    def _create_metadata(self, request_id: str) -> ApiResponseMetadata:
        """Create response metadata."""
        return ApiResponseMetadata(
            request_id=request_id,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            endpoint=request.endpoint or "unknown",
            method=request.method,
            user_id=self._get_current_user_id(),
            execution_time_ms=self._calculate_execution_time()
        )
        
    def success_response(
        self,
        data: Optional[Union[Dict, List]] = None,
        message: Optional[str] = None,
        status_code: int = 200,
        pagination: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Create standardized success response.
        
        Args:
            data: Response data (dict or list)
            message: Success message
            status_code: HTTP status code (default 200)
            pagination: Pagination metadata for list responses
            
        Returns:
            tuple: (response_dict, status_code)
        """
        request_id = self._generate_request_id()
        
        response = ApiResponse(
            status=ResponseStatus.SUCCESS.value,
            data=data,
            message=message,
            metadata=self._create_metadata(request_id),
            pagination=pagination
        )
        
        # Convert to dict and remove None values
        response_dict = {k: v for k, v in asdict(response).items() if v is not None}
        
        # Log successful API call
        log.info(f"API Success [{request_id}]: {request.method} {request.endpoint} - {status_code}")
        
        return response_dict, status_code
        
    def error_response(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        field: Optional[str] = None
    ) -> tuple:
        """
        Create standardized error response.
        
        Args:
            error_code: Standard error code
            message: Human-readable error message
            status_code: HTTP status code
            details: Additional error details
            field: Field name for validation errors
            
        Returns:
            tuple: (response_dict, status_code)
        """
        request_id = self._generate_request_id()
        
        error = ApiError(
            code=error_code.value,
            message=message,
            details=details,
            field=field
        )
        
        response = ApiResponse(
            status=ResponseStatus.ERROR.value,
            errors=[error],
            metadata=self._create_metadata(request_id)
        )
        
        # Convert to dict and remove None values
        response_dict = {k: v for k, v in asdict(response).items() if v is not None}
        
        # Log error
        log.error(f"API Error [{request_id}]: {error_code.value} - {message}")
        
        return response_dict, status_code
        
    def validation_error_response(
        self,
        errors: List[Dict[str, str]],
        message: str = "Validation failed"
    ) -> tuple:
        """
        Create standardized validation error response.
        
        Args:
            errors: List of validation errors with field and message
            message: Overall validation error message
            
        Returns:
            tuple: (response_dict, status_code)
        """
        request_id = self._generate_request_id()
        
        api_errors = [
            ApiError(
                code=ErrorCode.VALIDATION_ERROR.value,
                message=error.get('message', 'Invalid value'),
                field=error.get('field')
            )
            for error in errors
        ]
        
        response = ApiResponse(
            status=ResponseStatus.ERROR.value,
            message=message,
            errors=api_errors,
            metadata=self._create_metadata(request_id)
        )
        
        response_dict = {k: v for k, v in asdict(response).items() if v is not None}
        
        log.warning(f"API Validation Error [{request_id}]: {len(errors)} validation errors")
        
        return response_dict, 422
        
    def unauthorized_response(
        self,
        message: str = "Authentication required"
    ) -> tuple:
        """Create standardized 401 unauthorized response."""
        return self.error_response(
            ErrorCode.AUTHENTICATION_ERROR,
            message,
            401
        )
        
    def forbidden_response(
        self,
        message: str = "Access denied"
    ) -> tuple:
        """Create standardized 403 forbidden response."""
        return self.error_response(
            ErrorCode.AUTHORIZATION_ERROR,
            message,
            403
        )
        
    def not_found_response(
        self,
        resource: str = "Resource",
        resource_id: Optional[Union[str, int]] = None
    ) -> tuple:
        """Create standardized 404 not found response."""
        if resource_id:
            message = f"{resource} with ID '{resource_id}' not found"
        else:
            message = f"{resource} not found"
            
        return self.error_response(
            ErrorCode.NOT_FOUND_ERROR,
            message,
            404
        )
        
    def rate_limit_response(
        self,
        retry_after: Optional[int] = None
    ) -> tuple:
        """Create standardized 429 rate limit response."""
        details = {"retry_after_seconds": retry_after} if retry_after else None
        
        return self.error_response(
            ErrorCode.RATE_LIMIT_ERROR,
            "Rate limit exceeded. Please try again later.",
            429,
            details=details
        )
        
    def internal_error_response(
        self,
        message: str = "Internal server error",
        error_id: Optional[str] = None
    ) -> tuple:
        """Create standardized 500 internal error response."""
        details = {"error_id": error_id} if error_id else None
        
        return self.error_response(
            ErrorCode.INTERNAL_ERROR,
            message,
            500,
            details=details
        )
        
    def business_logic_error_response(
        self,
        message: str,
        error_context: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """Create standardized business logic error response."""
        return self.error_response(
            ErrorCode.BUSINESS_LOGIC_ERROR,
            message,
            422,
            details=error_context
        )


class ApprovalApiMixin:
    """
    Mixin class for PgAppForge API views to use standardized responses.
    
    Usage:
        class MyApiView(BaseApi, ApprovalApiMixin):
            def my_endpoint(self):
                formatter = self.get_response_formatter()
                return formatter.success_response({"result": "success"})
    """
    
    def get_response_formatter(self) -> ApprovalApiResponseFormatter:
        """Get response formatter instance for this API view."""
        return ApprovalApiResponseFormatter(self)
        
    def standard_success(
        self,
        data: Optional[Union[Dict, List]] = None,
        message: Optional[str] = None,
        status_code: int = 200
    ):
        """Shortcut for success response using PgAppForge response format."""
        formatter = self.get_response_formatter()
        response_dict, _ = formatter.success_response(data, message, status_code)
        return self.response(status_code, **response_dict)
        
    def standard_error(
        self,
        error_code: ErrorCode,
        message: str,
        status_code: int = 400
    ):
        """Shortcut for error response using PgAppForge response format."""
        formatter = self.get_response_formatter()
        response_dict, _ = formatter.error_response(error_code, message, status_code)
        
        # Use appropriate PgAppForge response method
        if status_code == 401:
            return self.response_401(message)
        elif status_code == 403:
            return self.response_403(message)
        elif status_code == 404:
            return self.response_404(message)
        elif status_code == 422:
            return self.response_422(message)
        elif status_code == 500:
            return self.response_500(message)
        else:
            return self.response(status_code, **response_dict)


def create_paginated_response(
    items: List[Dict],
    page: int,
    per_page: int,
    total_count: int,
    endpoint: str
) -> Dict[str, Any]:
    """
    Create standardized pagination metadata.
    
    Args:
        items: List of items for current page
        page: Current page number (1-based)
        per_page: Items per page
        total_count: Total number of items
        endpoint: API endpoint for building navigation links
        
    Returns:
        dict: Standardized pagination data
    """
    total_pages = (total_count + per_page - 1) // per_page
    has_next = page < total_pages
    has_prev = page > 1
    
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
        "has_next": has_next,
        "has_prev": has_prev
    }
    
    # Add navigation links if endpoint provided
    if endpoint:
        base_url = request.url_root.rstrip('/') + endpoint
        pagination.update({
            "next_url": f"{base_url}?page={page + 1}&per_page={per_page}" if has_next else None,
            "prev_url": f"{base_url}?page={page - 1}&per_page={per_page}" if has_prev else None,
            "first_url": f"{base_url}?page=1&per_page={per_page}",
            "last_url": f"{base_url}?page={total_pages}&per_page={per_page}"
        })
    
    return {
        "data": items,
        "pagination": pagination
    }