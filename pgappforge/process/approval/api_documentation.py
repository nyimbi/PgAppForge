"""
OpenAPI/Swagger Documentation for Approval System

Comprehensive API documentation generator with OpenAPI 3.0 specifications,
authentication schemas, and interactive Swagger UI integration.
"""

import json
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from flask import Blueprint, jsonify, render_template_string
from flask_restful import Api, Resource


class ApiVersion(Enum):
    """API version constants."""
    V1 = "1.0.0"
    V2 = "2.0.0"


@dataclass
class ApiEndpoint:
    """API endpoint definition."""
    path: str
    method: str
    summary: str
    description: str
    tags: List[str] = field(default_factory=list)
    parameters: List[Dict] = field(default_factory=list)
    request_body: Optional[Dict] = None
    responses: Dict[str, Dict] = field(default_factory=dict)
    security: List[Dict] = field(default_factory=list)
    deprecated: bool = False


class OpenAPIGenerator:
    """
    OpenAPI 3.0 specification generator for approval system APIs.
    
    Generates comprehensive API documentation with schemas, examples,
    authentication, and security specifications.
    """
    
    def __init__(self, app_name: str = "PgForge Approval System", 
                 version: str = ApiVersion.V1.value):
        self.app_name = app_name
        self.version = version
        self.endpoints: List[ApiEndpoint] = []
        self._base_spec = self._create_base_spec()
    
    def _create_base_spec(self) -> Dict[str, Any]:
        """Create base OpenAPI specification."""
        return {
            "openapi": "3.0.3",
            "info": {
                "title": self.app_name,
                "description": "Comprehensive REST API for approval workflows, chain management, and process automation",
                "version": self.version,
                "contact": {
                    "name": "API Support",
                    "email": "api-support@company.com"
                },
                "license": {
                    "name": "MIT",
                    "url": "https://opensource.org/licenses/MIT"
                },
                "termsOfService": "https://company.com/terms"
            },
            "servers": [
                {
                    "url": "https://api.company.com/v1",
                    "description": "Production server"
                },
                {
                    "url": "https://staging-api.company.com/v1", 
                    "description": "Staging server"
                },
                {
                    "url": "http://localhost:5000/api/v1",
                    "description": "Development server"
                }
            ],
            "paths": {},
            "components": {
                "schemas": self._get_schemas(),
                "securitySchemes": self._get_security_schemes(),
                "parameters": self._get_common_parameters(),
                "responses": self._get_common_responses(),
                "examples": self._get_examples()
            },
            "security": [
                {"bearerAuth": []},
                {"sessionAuth": []}
            ],
            "tags": self._get_tags()
        }
    
    def _get_schemas(self) -> Dict[str, Dict]:
        """Get all schema definitions."""
        return {
            "ApprovalRequest": {
                "type": "object",
                "required": ["instance_id", "step", "workflow_config"],
                "properties": {
                    "instance_id": {
                        "type": "integer",
                        "description": "Unique identifier for the workflow instance",
                        "example": 12345
                    },
                    "step": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Workflow step number",
                        "example": 0
                    },
                    "comments": {
                        "type": "string",
                        "maxLength": 1000,
                        "description": "Optional approval comments",
                        "example": "Approved with conditions"
                    },
                    "approval_data": {
                        "type": "object",
                        "description": "Additional approval metadata",
                        "additionalProperties": True
                    },
                    "workflow_config": {
                        "$ref": "#/components/schemas/WorkflowConfig"
                    }
                }
            },
            
            "ApprovalResponse": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "Whether the approval was successful"
                    },
                    "approval_id": {
                        "type": "integer",
                        "description": "Unique approval identifier"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["approved", "rejected", "pending", "escalated"],
                        "description": "Current approval status"
                    },
                    "message": {
                        "type": "string",
                        "description": "Human-readable status message"
                    },
                    "next_step": {
                        "type": "integer",
                        "description": "Next workflow step (if applicable)"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Approval timestamp"
                    }
                }
            },
            
            "WorkflowConfig": {
                "type": "object",
                "required": ["name", "steps", "initial_state", "approved_state"],
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                        "description": "Workflow name"
                    },
                    "description": {
                        "type": "string",
                        "maxLength": 500,
                        "description": "Workflow description"
                    },
                    "steps": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/WorkflowStep"},
                        "minItems": 1,
                        "description": "Workflow steps"
                    },
                    "initial_state": {
                        "type": "string",
                        "description": "Initial workflow state"
                    },
                    "approved_state": {
                        "type": "string",
                        "description": "Final approved state"
                    },
                    "rejected_state": {
                        "type": "string",
                        "description": "Final rejected state"
                    },
                    "workflow_type": {
                        "type": "string",
                        "enum": ["sequential", "parallel", "conditional"],
                        "default": "sequential"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "critical"],
                        "default": "normal"
                    }
                }
            },
            
            "WorkflowStep": {
                "type": "object",
                "required": ["name", "required_approvals"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Step name"
                    },
                    "description": {
                        "type": "string",
                        "description": "Step description"
                    },
                    "required_approvals": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Number of required approvals"
                    },
                    "approvers": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Approver"}
                    },
                    "timeout_hours": {
                        "type": "number",
                        "minimum": 0.1,
                        "description": "Step timeout in hours"
                    }
                }
            },
            
            "Approver": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["user", "role", "dynamic"]
                    },
                    "user_id": {
                        "type": "integer",
                        "description": "User ID (for type=user)"
                    },
                    "role": {
                        "type": "string",
                        "description": "Role name (for type=role)"
                    },
                    "expression": {
                        "type": "string",
                        "description": "Dynamic expression (for type=dynamic)"
                    },
                    "required": {
                        "type": "boolean",
                        "default": True
                    },
                    "order": {
                        "type": "integer",
                        "minimum": 0
                    }
                }
            },
            
            "ApprovalChain": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Chain identifier"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["sequential", "parallel", "unanimous", "majority"],
                        "description": "Chain execution type"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "approved", "rejected", "cancelled"],
                        "description": "Current chain status"
                    },
                    "created_at": {
                        "type": "string",
                        "format": "date-time"
                    },
                    "completed_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True
                    },
                    "approvers": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/ChainApprover"}
                    }
                }
            },
            
            "ChainApprover": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "integer"
                    },
                    "username": {
                        "type": "string"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "approved", "rejected", "delegated", "escalated"]
                    },
                    "responded_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True
                    },
                    "comments": {
                        "type": "string",
                        "nullable": True
                    }
                }
            },
            
            "ConnectionPoolMetrics": {
                "type": "object",
                "properties": {
                    "pool_size": {
                        "type": "integer",
                        "description": "Configured pool size"
                    },
                    "active_connections": {
                        "type": "integer",
                        "description": "Currently active connections"
                    },
                    "idle_connections": {
                        "type": "integer",
                        "description": "Idle connections in pool"
                    },
                    "utilization_percent": {
                        "type": "number",
                        "format": "float",
                        "description": "Pool utilization percentage"
                    },
                    "failed_connections": {
                        "type": "integer",
                        "description": "Total failed connection attempts"
                    },
                    "peak_connections": {
                        "type": "integer",
                        "description": "Peak concurrent connections"
                    }
                }
            },
            
            "SystemHealth": {
                "type": "object",
                "properties": {
                    "overall_status": {
                        "type": "string",
                        "enum": ["healthy", "warning", "critical"],
                        "description": "Overall system health status"
                    },
                    "connection_pool": {
                        "$ref": "#/components/schemas/ConnectionPoolHealth"
                    },
                    "approval_cache": {
                        "$ref": "#/components/schemas/CacheHealth"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time"
                    }
                }
            },
            
            "ConnectionPoolHealth": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["healthy", "warning", "critical"]
                    },
                    "metrics": {
                        "$ref": "#/components/schemas/ConnectionPoolMetrics"
                    },
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "recommendations": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            },
            
            "CacheHealth": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["healthy", "warning", "critical"]
                    },
                    "metrics": {
                        "type": "object",
                        "properties": {
                            "cache_entries": {"type": "integer"},
                            "memory_usage_estimate": {"type": "integer"},
                            "oldest_entry": {"type": "string", "format": "date-time"},
                            "newest_entry": {"type": "string", "format": "date-time"}
                        }
                    }
                }
            },
            
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "error": {
                        "type": "string",
                        "description": "Error message"
                    },
                    "error_code": {
                        "type": "string",
                        "description": "Error code identifier"
                    },
                    "details": {
                        "type": "object",
                        "description": "Additional error details"
                    },
                    "timestamp": {
                        "type": "string",
                        "format": "date-time"
                    }
                }
            }
        }
    
    def _get_security_schemes(self) -> Dict[str, Dict]:
        """Get security scheme definitions."""
        return {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT Bearer token authentication"
            },
            "sessionAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": "Session cookie authentication"
            },
            "csrfToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-CSRFToken",
                "description": "CSRF protection token"
            }
        }
    
    def _get_common_parameters(self) -> Dict[str, Dict]:
        """Get common parameter definitions."""
        return {
            "instance_id": {
                "name": "instance_id",
                "in": "path",
                "required": True,
                "schema": {"type": "integer"},
                "description": "Workflow instance identifier"
            },
            "chain_id": {
                "name": "chain_id",
                "in": "path",
                "required": True,
                "schema": {"type": "integer"},
                "description": "Approval chain identifier"
            },
            "user_id": {
                "name": "user_id",
                "in": "path",
                "required": True,
                "schema": {"type": "integer"},
                "description": "User identifier"
            },
            "page": {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
                "description": "Page number for pagination"
            },
            "per_page": {
                "name": "per_page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "description": "Items per page"
            },
            "status_filter": {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected", "escalated"]
                },
                "description": "Filter by approval status"
            }
        }
    
    def _get_common_responses(self) -> Dict[str, Dict]:
        """Get common response definitions."""
        return {
            "BadRequest": {
                "description": "Bad request - invalid parameters",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "error": "Invalid request parameters",
                            "error_code": "INVALID_PARAMS",
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    }
                }
            },
            "Unauthorized": {
                "description": "Authentication required",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "error": "Authentication required",
                            "error_code": "AUTH_REQUIRED",
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    }
                }
            },
            "Forbidden": {
                "description": "Insufficient permissions",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "error": "Insufficient permissions",
                            "error_code": "PERMISSION_DENIED",
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    }
                }
            },
            "NotFound": {
                "description": "Resource not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "error": "Resource not found",
                            "error_code": "NOT_FOUND",
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    }
                }
            },
            "InternalServerError": {
                "description": "Internal server error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                        "example": {
                            "error": "Internal server error",
                            "error_code": "INTERNAL_ERROR", 
                            "timestamp": "2024-01-15T10:30:00Z"
                        }
                    }
                }
            }
        }
    
    def _get_examples(self) -> Dict[str, Dict]:
        """Get example definitions."""
        return {
            "SimpleApprovalRequest": {
                "summary": "Simple approval request",
                "value": {
                    "instance_id": 12345,
                    "step": 0,
                    "comments": "Approved - all requirements met",
                    "workflow_config": {
                        "name": "Basic Approval",
                        "steps": [
                            {
                                "name": "Manager Approval",
                                "required_approvals": 1
                            }
                        ],
                        "initial_state": "pending",
                        "approved_state": "approved"
                    }
                }
            },
            "FinancialApprovalRequest": {
                "summary": "Financial approval request",
                "value": {
                    "instance_id": 67890,
                    "step": 1,
                    "comments": "Approved with spending limit conditions",
                    "approval_data": {
                        "amount": 25000.00,
                        "currency": "USD",
                        "category": "equipment_purchase"
                    },
                    "workflow_config": {
                        "name": "Financial Approval Workflow",
                        "steps": [
                            {
                                "name": "Finance Review",
                                "required_approvals": 1
                            },
                            {
                                "name": "Manager Approval",
                                "required_approvals": 1
                            }
                        ],
                        "initial_state": "finance_review",
                        "approved_state": "financially_approved"
                    }
                }
            }
        }
    
    def _get_tags(self) -> List[Dict]:
        """Get API tag definitions."""
        return [
            {
                "name": "Approvals",
                "description": "Approval workflow operations"
            },
            {
                "name": "Chains",
                "description": "Approval chain management"
            },
            {
                "name": "Monitoring",
                "description": "System monitoring and health checks"
            },
            {
                "name": "Configuration",
                "description": "Configuration management"
            },
            {
                "name": "Reports",
                "description": "Reporting and analytics"
            }
        ]
    
    def add_approval_endpoints(self):
        """Add approval workflow endpoints."""
        # Submit approval
        self.endpoints.append(ApiEndpoint(
            path="/approvals/submit",
            method="post",
            summary="Submit Approval Decision",
            description="Submit an approval decision for a workflow instance",
            tags=["Approvals"],
            request_body={
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApprovalRequest"},
                        "examples": {
                            "simple": {"$ref": "#/components/examples/SimpleApprovalRequest"},
                            "financial": {"$ref": "#/components/examples/FinancialApprovalRequest"}
                        }
                    }
                }
            },
            responses={
                "200": {
                    "description": "Approval submitted successfully",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ApprovalResponse"}
                        }
                    }
                },
                "400": {"$ref": "#/components/responses/BadRequest"},
                "401": {"$ref": "#/components/responses/Unauthorized"},
                "403": {"$ref": "#/components/responses/Forbidden"},
                "500": {"$ref": "#/components/responses/InternalServerError"}
            },
            security=[{"bearerAuth": []}, {"csrfToken": []}]
        ))
        
        # Get pending approvals
        self.endpoints.append(ApiEndpoint(
            path="/approvals/pending",
            method="get",
            summary="Get Pending Approvals",
            description="Retrieve pending approval requests for the current user",
            tags=["Approvals"],
            parameters=[
                {"$ref": "#/components/parameters/page"},
                {"$ref": "#/components/parameters/per_page"},
                {"$ref": "#/components/parameters/status_filter"}
            ],
            responses={
                "200": {
                    "description": "List of pending approvals",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "approvals": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/ApprovalRequest"}
                                    },
                                    "pagination": {
                                        "type": "object",
                                        "properties": {
                                            "page": {"type": "integer"},
                                            "per_page": {"type": "integer"},
                                            "total": {"type": "integer"},
                                            "pages": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "401": {"$ref": "#/components/responses/Unauthorized"},
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
        
        # Get approval history
        self.endpoints.append(ApiEndpoint(
            path="/approvals/history/{instance_id}",
            method="get",
            summary="Get Approval History",
            description="Retrieve approval history for a workflow instance",
            tags=["Approvals"],
            parameters=[
                {"$ref": "#/components/parameters/instance_id"}
            ],
            responses={
                "200": {
                    "description": "Approval history",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "instance_id": {"type": "integer"},
                                    "history": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "user_id": {"type": "integer"},
                                                "user_name": {"type": "string"},
                                                "step": {"type": "integer"},
                                                "status": {"type": "string"},
                                                "comments": {"type": "string"},
                                                "timestamp": {"type": "string", "format": "date-time"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "404": {"$ref": "#/components/responses/NotFound"},
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
    
    def add_chain_endpoints(self):
        """Add approval chain endpoints."""
        # Create approval chain
        self.endpoints.append(ApiEndpoint(
            path="/chains",
            method="post",
            summary="Create Approval Chain",
            description="Create a new approval chain for a workflow step",
            tags=["Chains"],
            request_body={
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "step_id": {"type": "integer"},
                                "chain_config": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string"},
                                        "approvers": {"type": "array"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            responses={
                "201": {
                    "description": "Chain created successfully",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ApprovalChain"}
                        }
                    }
                },
                "400": {"$ref": "#/components/responses/BadRequest"},
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
        
        # Get chain status
        self.endpoints.append(ApiEndpoint(
            path="/chains/{chain_id}",
            method="get",
            summary="Get Chain Status",
            description="Retrieve detailed status of an approval chain",
            tags=["Chains"],
            parameters=[
                {"$ref": "#/components/parameters/chain_id"}
            ],
            responses={
                "200": {
                    "description": "Chain status details",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ApprovalChain"}
                        }
                    }
                },
                "404": {"$ref": "#/components/responses/NotFound"},
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
    
    def add_monitoring_endpoints(self):
        """Add monitoring and health check endpoints."""
        # System health
        self.endpoints.append(ApiEndpoint(
            path="/health",
            method="get",
            summary="System Health Check",
            description="Get comprehensive system health status",
            tags=["Monitoring"],
            responses={
                "200": {
                    "description": "System health status",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/SystemHealth"}
                        }
                    }
                },
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
        
        # Connection pool metrics
        self.endpoints.append(ApiEndpoint(
            path="/metrics/connection-pool",
            method="get",
            summary="Connection Pool Metrics",
            description="Get database connection pool metrics",
            tags=["Monitoring"],
            responses={
                "200": {
                    "description": "Connection pool metrics",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ConnectionPoolMetrics"}
                        }
                    }
                },
                "500": {"$ref": "#/components/responses/InternalServerError"}
            }
        ))
    
    def generate_openapi_spec(self) -> Dict[str, Any]:
        """Generate complete OpenAPI specification."""
        # Add all endpoint categories
        self.add_approval_endpoints()
        self.add_chain_endpoints()
        self.add_monitoring_endpoints()
        
        # Build paths from endpoints
        spec = self._base_spec.copy()
        
        for endpoint in self.endpoints:
            if endpoint.path not in spec["paths"]:
                spec["paths"][endpoint.path] = {}
            
            operation = {
                "summary": endpoint.summary,
                "description": endpoint.description,
                "tags": endpoint.tags,
                "operationId": f"{endpoint.method}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}",
                "responses": endpoint.responses
            }
            
            if endpoint.parameters:
                operation["parameters"] = endpoint.parameters
            
            if endpoint.request_body:
                operation["requestBody"] = endpoint.request_body
            
            if endpoint.security:
                operation["security"] = endpoint.security
            
            if endpoint.deprecated:
                operation["deprecated"] = True
            
            spec["paths"][endpoint.path][endpoint.method] = operation
        
        return spec
    
    def generate_swagger_ui_html(self) -> str:
        """Generate Swagger UI HTML page."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} - API Documentation</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui.css" />
    <style>
        html {
            box-sizing: border-box;
            overflow: -moz-scrollbars-vertical;
            overflow-y: scroll;
        }
        *, *:before, *:after {
            box-sizing: inherit;
        }
        body {
            margin:0;
            background: #fafafa;
        }
        .custom-header {
            background: #2c5aa0;
            color: white;
            padding: 20px;
            text-align: center;
        }
        .custom-header h1 {
            margin: 0;
            font-size: 24px;
        }
        .custom-header p {
            margin: 5px 0 0 0;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <div class="custom-header">
        <h1>{{ title }}</h1>
        <p>Comprehensive REST API Documentation</p>
    </div>
    <div id="swagger-ui"></div>
    
    <script src="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {
            const ui = SwaggerUIBundle({
                url: '/api/docs/openapi.json',
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                defaultModelsExpandDepth: 2,
                defaultModelExpandDepth: 2,
                docExpansion: "list",
                filter: true,
                showRequestHeaders: true,
                showCommonExtensions: true,
                tryItOutEnabled: true
            });
        };
    </script>
</body>
</html>
        """.strip()


def create_api_documentation_blueprint(app_name: str = "Approval System API") -> Blueprint:
    """Create Flask blueprint for API documentation."""
    
    bp = Blueprint('api_docs', __name__, url_prefix='/api/docs')
    
    @bp.route('/openapi.json')
    def openapi_spec():
        """Serve OpenAPI specification as JSON."""
        generator = OpenAPIGenerator(app_name)
        spec = generator.generate_openapi_spec()
        return jsonify(spec)
    
    @bp.route('/')
    def swagger_ui():
        """Serve Swagger UI documentation page."""
        generator = OpenAPIGenerator(app_name)
        html = generator.generate_swagger_ui_html()
        return render_template_string(html, title=app_name)
    
    @bp.route('/redoc')
    def redoc():
        """Serve ReDoc documentation page."""
        redoc_html = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - API Documentation</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body { margin: 0; padding: 0; }
    </style>
</head>
<body>
    <redoc spec-url='/api/docs/openapi.json'></redoc>
    <script src="https://cdn.jsdelivr.net/npm/redoc@2.0.0/bundles/redoc.standalone.js"></script>
</body>
</html>
        """
        return render_template_string(redoc_html, title=app_name)
    
    return bp


def generate_postman_collection(app_name: str = "Approval System API") -> Dict[str, Any]:
    """Generate Postman collection from OpenAPI spec."""
    generator = OpenAPIGenerator(app_name)
    spec = generator.generate_openapi_spec()
    
    collection = {
        "info": {
            "name": spec["info"]["title"],
            "description": spec["info"]["description"],
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": [],
        "auth": {
            "type": "bearer",
            "bearer": [
                {
                    "key": "token",
                    "value": "{{bearer_token}}",
                    "type": "string"
                }
            ]
        },
        "variable": [
            {
                "key": "base_url",
                "value": "https://api.company.com/v1",
                "type": "string"
            },
            {
                "key": "bearer_token",
                "value": "your_jwt_token_here",
                "type": "string"
            }
        ]
    }
    
    # Convert OpenAPI paths to Postman requests
    for path, methods in spec["paths"].items():
        folder = {
            "name": path.split('/')[1].title(),
            "item": []
        }
        
        for method, operation in methods.items():
            request = {
                "name": operation["summary"],
                "request": {
                    "method": method.upper(),
                    "header": [
                        {
                            "key": "Content-Type",
                            "value": "application/json"
                        }
                    ],
                    "url": {
                        "raw": "{{base_url}}" + path,
                        "host": ["{{base_url}}"],
                        "path": path.split('/')[1:]
                    },
                    "description": operation["description"]
                }
            }
            
            # Add request body if present
            if "requestBody" in operation:
                request["request"]["body"] = {
                    "mode": "raw",
                    "raw": json.dumps({}, indent=2)
                }
            
            folder["item"].append(request)
        
        if folder["item"]:
            collection["item"].append(folder)
    
    return collection


# Global API documentation generator
_api_generator: Optional[OpenAPIGenerator] = None


def get_api_generator(app_name: str = "Approval System API") -> OpenAPIGenerator:
    """Get or create global API documentation generator."""
    global _api_generator
    if _api_generator is None:
        _api_generator = OpenAPIGenerator(app_name)
    return _api_generator