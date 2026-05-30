# Graph Analytics Platform API Documentation

## Overview

This document provides comprehensive API documentation for the enterprise-grade graph analytics platform built on PgForge with Apache AGE integration. The platform provides 10 major feature suites with over 100 API endpoints for graph management, analysis, and visualization.

## Base URL

```
http://localhost:8080/
```

## Authentication

All API endpoints require admin-level authentication. Include session cookies or API keys in requests.

### API Key Authentication
```http
Authorization: Bearer <api_key>
X-API-Secret: <api_secret>
```

---

## 1. Graph Management API

### Create Graph
```http
POST /graph/api/create-graph/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "description": "Description of the graph",
    "metadata": {
        "domain": "social_network",
        "version": "1.0"
    }
}
```

**Response:**
```json
{
    "success": true,
    "graph_id": "graph_12345",
    "message": "Graph created successfully"
}
```

### Get Graph Info
```http
GET /graph/api/graph-info/<graph_name>/
```

**Response:**
```json
{
    "success": true,
    "graph": {
        "name": "my_graph",
        "node_count": 150,
        "edge_count": 300,
        "created_at": "2024-01-01T00:00:00Z",
        "last_modified": "2024-01-02T12:00:00Z"
    }
}
```

---

## 2. Advanced Query Builder API

### Build Visual Query
```http
POST /graph/query-builder/api/build-visual-query/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "query_spec": {
        "nodes": [
            {
                "variable": "person",
                "labels": ["Person"],
                "properties": {"department": "Engineering"}
            }
        ],
        "edges": [
            {
                "variable": "works_for",
                "type": "WORKS_FOR",
                "from": "person",
                "to": "company"
            }
        ],
        "returns": ["person.name", "company.name"],
        "filters": [
            {
                "property": "person.age",
                "operator": ">",
                "value": 25
            }
        ]
    }
}
```

**Response:**
```json
{
    "success": true,
    "cypher_query": "MATCH (person:Person)-[works_for:WORKS_FOR]->(company:Company) WHERE person.department = 'Engineering' AND person.age > 25 RETURN person.name, company.name",
    "validation": {
        "is_valid": true,
        "estimated_complexity": "medium",
        "performance_score": 8.5
    }
}
```

### Execute Query
```http
POST /graph/query-builder/api/execute-query/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "cypher_query": "MATCH (n:Person) RETURN n LIMIT 10",
    "parameters": {}
}
```

**Response:**
```json
{
    "success": true,
    "results": [
        {"n.name": "Alice", "n.age": 30},
        {"n.name": "Bob", "n.age": 25}
    ],
    "execution_time": 0.045,
    "result_count": 2
}
```

---

## 3. Real-Time Streaming API

### Create Streaming Session
```http
POST /graph/streaming/api/create-session/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "event_types": ["node_created", "edge_created", "node_updated"],
    "filters": {
        "node_labels": ["Person", "Company"]
    }
}
```

**Response:**
```json
{
    "success": true,
    "session_id": "stream_abc123",
    "websocket_url": "ws://localhost:8080/graph/streaming/ws/stream_abc123/"
}
```

### Broadcast Event
```http
POST /graph/streaming/api/broadcast/<session_id>/
Content-Type: application/json

{
    "event": {
        "type": "node_created",
        "data": {
            "id": 123,
            "name": "New Node",
            "type": "Person"
        },
        "timestamp": "2024-01-01T12:00:00Z"
    }
}
```

---

## 4. Multi-Graph Management API

### List Graphs
```http
GET /graph/multi-graph/api/graphs/
```

**Response:**
```json
{
    "success": true,
    "graphs": [
        {
            "name": "graph1",
            "node_count": 100,
            "edge_count": 200,
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]
}
```

### Union Graphs
```http
POST /graph/multi-graph/api/union/
Content-Type: application/json

{
    "source_graphs": ["graph1", "graph2"],
    "target_graph": "union_graph",
    "merge_strategy": "union",
    "handle_conflicts": "prefer_first"
}
```

### Compare Graphs
```http
POST /graph/multi-graph/api/compare/
Content-Type: application/json

{
    "graph1": "social_network",
    "graph2": "corporate_network", 
    "comparison_metrics": ["node_overlap", "edge_similarity", "structure_diff"]
}
```

**Response:**
```json
{
    "success": true,
    "comparison": {
        "node_overlap": 0.75,
        "edge_similarity": 0.68,
        "unique_to_graph1": 50,
        "unique_to_graph2": 30,
        "common_nodes": 150
    }
}
```

---

## 5. Machine Learning API

### Train Model
```http
POST /graph/ml/api/train-model/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "model_type": "node_classification",
    "target_labels": ["Person", "Company", "Project"],
    "features": ["degree", "clustering_coefficient", "betweenness"],
    "algorithm": "random_forest",
    "training_params": {
        "test_size": 0.2,
        "random_state": 42
    }
}
```

**Response:**
```json
{
    "success": true,
    "model_id": "model_xyz789",
    "training_results": {
        "accuracy": 0.92,
        "precision": 0.89,
        "recall": 0.91,
        "f1_score": 0.90
    },
    "feature_importance": {
        "degree": 0.45,
        "clustering_coefficient": 0.32,
        "betweenness": 0.23
    }
}
```

### Make Predictions
```http
POST /graph/ml/api/predict/<model_id>/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "node_ids": [1, 2, 3, 4, 5],
    "include_confidence": true
}
```

### Detect Anomalies
```http
POST /graph/ml/api/detect-anomalies/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "algorithm": "isolation_forest",
    "contamination": 0.1,
    "features": ["degree", "clustering_coefficient"]
}
```

---

## 6. AI Analytics Assistant API

### Natural Language Query
```http
POST /graph/ai-assistant/api/natural-language-query/
Content-Type: application/json

{
    "query": "Find the most connected person in the engineering department",
    "graph_name": "company_graph",
    "context": "social network analysis"
}
```

**Response:**
```json
{
    "success": true,
    "suggestion": {
        "cypher_query": "MATCH (p:Person {department: 'Engineering'})-[r]-(n) RETURN p.name, count(r) as connections ORDER BY connections DESC LIMIT 1",
        "explanation": "This query finds persons in Engineering department and counts their connections",
        "confidence_score": 0.95,
        "complexity": "simple",
        "performance_notes": ["Consider adding index on department property"]
    }
}
```

### Get Automated Insights
```http
GET /graph/ai-assistant/api/insights/<graph_name>/?force_refresh=true
```

**Response:**
```json
{
    "success": true,
    "insights": [
        {
            "insight_id": "insight_123",
            "title": "High Clustering in Engineering Team",
            "description": "Engineering department shows unusually high clustering coefficient",
            "priority": "high",
            "confidence_score": 0.87,
            "analysis_type": "structure_analysis",
            "recommended_actions": [
                "Investigate team formation patterns",
                "Consider cross-departmental collaboration initiatives"
            ],
            "data_evidence": {
                "clustering_coefficient": 0.85,
                "department_avg": 0.45
            }
        }
    ]
}
```

### Analyze Graph
```http
POST /graph/ai-assistant/api/analyze-graph/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "analysis_types": ["structure_analysis", "centrality_analysis", "anomaly_detection"]
}
```

---

## 7. Performance Optimization API

### Analyze Query Performance
```http
POST /graph/performance/api/analyze-query/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "cypher_query": "MATCH (n:Person)-[:WORKS_FOR]->(c:Company) RETURN n.name, c.name",
    "include_execution_plan": true
}
```

**Response:**
```json
{
    "success": true,
    "performance_metrics": {
        "execution_time": 0.125,
        "rows_examined": 1500,
        "index_usage": ["person_name_idx"],
        "complexity_score": 6.8
    },
    "execution_plan": "NodeByLabelScan -> Expand -> Project",
    "optimization_suggestions": [
        "Add index on Company.name",
        "Consider using WITH clause for better memory usage"
    ]
}
```

### Optimize Query
```http
POST /graph/performance/api/optimize-query/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "cypher_query": "MATCH (n:Person)-[:WORKS_FOR]->(c:Company) RETURN n.name, c.name",
    "optimization_level": "aggressive"
}
```

### Get System Metrics
```http
GET /graph/performance/api/system-metrics/
```

---

## 8. Import/Export Pipeline API

### Import Data
```http
POST /graph/import-export/api/import/
Content-Type: application/json

{
    "source_type": "json",
    "file_path": "/path/to/data.json",
    "target_graph": "imported_graph",
    "merge_strategy": "append",
    "transformation_rules": [
        {
            "type": "property_mapping",
            "from": "full_name",
            "to": "name"
        }
    ]
}
```

### Export Data
```http
POST /graph/import-export/api/export/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "export_format": "graphml",
    "output_path": "/path/to/export.graphml",
    "filters": {
        "node_labels": ["Person"],
        "edge_types": ["KNOWS", "WORKS_FOR"]
    },
    "include_computed": true
}
```

### Validate Data
```http
POST /graph/import-export/api/validate/
Content-Type: application/json

{
    "source_type": "csv",
    "file_path": "/path/to/nodes.csv",
    "schema": {
        "required_columns": ["id", "name", "type"],
        "data_types": {
            "id": "integer",
            "name": "string"
        }
    }
}
```

---

## 9. Collaboration System API

### Create Collaboration Session
```http
POST /graph/collaboration/api/create-session/
Content-Type: application/json

{
    "graph_name": "team_project",
    "session_config": {
        "max_users": 5,
        "permissions": ["edit", "view"],
        "auto_save": true,
        "conflict_resolution": "last_write_wins"
    }
}
```

### Join Session
```http
POST /graph/collaboration/api/join-session/<session_id>/
Content-Type: application/json

{
    "user_info": {
        "role": "analyst",
        "name": "John Smith",
        "permissions": ["edit"]
    }
}
```

### Broadcast Operation
```http
POST /graph/collaboration/api/broadcast-operation/<session_id>/
Content-Type: application/json

{
    "operation": {
        "type": "node_created",
        "data": {
            "name": "New Node",
            "type": "Person",
            "properties": {"department": "Marketing"}
        },
        "user_id": "user123",
        "timestamp": "2024-01-01T12:00:00Z"
    }
}
```

---

## 10. Advanced Visualization API

### Generate Layout
```http
POST /graph/visualization/api/generate-layout/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "layout_algorithm": "force_directed",
    "layout_params": {
        "iterations": 100,
        "spring_strength": 0.8,
        "repulsion_strength": 1.2
    },
    "filters": {
        "max_nodes": 500,
        "node_labels": ["Person", "Company"]
    }
}
```

**Response:**
```json
{
    "success": true,
    "layout": {
        "nodes": [
            {
                "id": 1,
                "x": 150.5,
                "y": 200.3,
                "name": "Alice",
                "type": "Person"
            }
        ],
        "edges": [
            {
                "from": 1,
                "to": 2,
                "type": "KNOWS"
            }
        ]
    },
    "layout_metadata": {
        "algorithm": "force_directed",
        "execution_time": 0.85,
        "convergence_achieved": true
    }
}
```

### Generate Interactive Config
```http
POST /graph/visualization/api/interactive-config/
Content-Type: application/json

{
    "graph_data": {
        "nodes": [...],
        "edges": [...]
    },
    "interaction_types": ["zoom", "pan", "select", "hover"],
    "styling": {
        "node_size_property": "degree",
        "edge_width_property": "weight",
        "color_scheme": "category10"
    }
}
```

---

## 11. Enterprise Integration API

### Store Credential
```http
POST /enterprise/api/credentials/
Content-Type: application/json

{
    "name": "CompanyLDAP",
    "integration_type": "LDAP_DIRECTORY",
    "auth_method": "LDAP_BIND",
    "credential_data": {
        "bind_dn": "CN=service,DC=company,DC=com",
        "bind_password": "secure_password"
    },
    "expires_at": "2024-12-31T23:59:59Z"
}
```

### Configure SSO Provider
```http
POST /enterprise/api/sso-provider/
Content-Type: application/json

{
    "provider_type": "saml",
    "provider_name": "CorporateSSO",
    "configuration": {
        "entity_id": "https://company.com/saml/entity",
        "sso_url": "https://company.com/saml/sso",
        "certificate": "-----BEGIN CERTIFICATE-----\nMIIC...",
        "attribute_mapping": {
            "email": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "first_name": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname"
        }
    }
}
```

### Generate API Key
```http
POST /enterprise/api/api-keys/
Content-Type: application/json

{
    "name": "ExternalIntegration",
    "permissions": ["read", "write"],
    "expires_at": "2024-06-30T23:59:59Z"
}
```

**Response:**
```json
{
    "success": true,
    "api_key": "ak_1234567890abcdef",
    "api_secret": "as_0987654321fedcba",
    "message": "API key generated successfully",
    "warning": "Store the API secret securely - it will not be shown again"
}
```

### Get Audit Logs
```http
GET /enterprise/api/audit-logs/?user_id=user123&action=graph_query&start_time=2024-01-01T00:00:00Z&limit=50
```

---

## Error Responses

All endpoints return consistent error responses:

```json
{
    "success": false,
    "error": "Error description",
    "error_code": "GRAPH_NOT_FOUND",
    "details": {
        "graph_name": "nonexistent_graph",
        "suggested_action": "Create the graph first using POST /graph/api/create-graph/"
    }
}
```

### Common Error Codes
- `GRAPH_NOT_FOUND`: Specified graph does not exist
- `INVALID_CYPHER`: Cypher query syntax error
- `PERMISSION_DENIED`: Insufficient permissions
- `DATABASE_ERROR`: Database connection or query error
- `VALIDATION_ERROR`: Request validation failed
- `RATE_LIMITED`: Too many requests

---

## Rate Limiting

All API endpoints are rate limited:
- **Standard endpoints**: 100 requests per minute
- **Analysis endpoints**: 20 requests per minute
- **Bulk operations**: 5 requests per minute

Rate limit headers are included in responses:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1640995200
```

---

## WebSocket API

### Real-time Graph Streaming
```javascript
const ws = new WebSocket('ws://localhost:8080/graph/streaming/ws/session_123/');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('Received event:', data.event_type, data.data);
};

// Send events
ws.send(JSON.stringify({
    type: 'subscribe',
    event_types: ['node_created', 'edge_updated']
}));
```

### Collaboration Events
```javascript
const collabWs = new WebSocket('ws://localhost:8080/graph/collaboration/ws/session_456/');

collabWs.onmessage = function(event) {
    const operation = JSON.parse(event.data);
    // Handle collaborative operation
    handleOperation(operation);
};
```

---

## SDK Examples

### Python SDK
```python
from graph_analytics_sdk import GraphAnalyticsClient

client = GraphAnalyticsClient(
    base_url='http://localhost:8080',
    api_key='your_api_key',
    api_secret='your_api_secret'
)

# Create and analyze graph
graph = client.create_graph('my_graph')
nodes = graph.create_nodes([
    {'name': 'Alice', 'type': 'Person'},
    {'name': 'Bob', 'type': 'Person'}
])

# Natural language query
suggestion = client.ai_assistant.query(
    "Find all people connected to Alice",
    graph_name='my_graph'
)

# Execute suggested query
results = graph.execute_cypher(suggestion.cypher_query)
print(f"Found {len(results)} results")
```

### JavaScript SDK
```javascript
import { GraphAnalyticsClient } from 'graph-analytics-sdk';

const client = new GraphAnalyticsClient({
    baseUrl: 'http://localhost:8080',
    apiKey: 'your_api_key',
    apiSecret: 'your_api_secret'
});

// Real-time collaboration
const session = await client.collaboration.createSession('my_graph', {
    maxUsers: 5,
    permissions: ['edit', 'view']
});

session.on('operation', (operation) => {
    console.log('Collaborative operation:', operation);
});

await session.join({ role: 'analyst', name: 'John' });
```

---

## Advanced Features

### Bulk Operations
```http
POST /graph/query-builder/api/batch-execute/
Content-Type: application/json

{
    "graph_name": "my_graph",
    "operations": [
        {
            "type": "cypher",
            "query": "CREATE (n:Person {name: $name})",
            "parameters": {"name": "Alice"}
        },
        {
            "type": "cypher", 
            "query": "CREATE (n:Person {name: $name})",
            "parameters": {"name": "Bob"}
        }
    ],
    "transaction_mode": "atomic"
}
```

### Query Templates
```http
GET /graph/query-builder/api/templates/?category=social_network
```

**Response:**
```json
{
    "success": true,
    "templates": [
        {
            "name": "Find Influencers",
            "description": "Find nodes with high centrality scores",
            "cypher": "MATCH (n) RETURN n ORDER BY n.degree DESC LIMIT $limit",
            "parameters": {"limit": 10},
            "category": "social_network"
        }
    ]
}
```

This comprehensive API documentation covers all major features of the enterprise-grade graph analytics platform. For additional examples and tutorials, see the `/examples/` directory in the repository.