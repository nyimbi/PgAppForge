"""
Monitoring Setup Engine

Automated monitoring and observability setup for PgForge applications.
Supports Prometheus, Grafana, ELK Stack, Jaeger, and cloud-native monitoring.
"""

import os
import json
import yaml
import asyncio
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
import aiohttp
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MonitoringProvider(Enum):
    """Supported monitoring providers"""
    PROMETHEUS_GRAFANA = "prometheus_grafana"
    ELK_STACK = "elk_stack"
    DATADOG = "datadog"
    NEW_RELIC = "new_relic"
    AWS_CLOUDWATCH = "aws_cloudwatch"
    AZURE_MONITOR = "azure_monitor"
    GOOGLE_CLOUD_MONITORING = "google_cloud_monitoring"
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"

class MetricType(Enum):
    """Types of metrics to collect"""
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    BUSINESS = "business"
    SECURITY = "security"
    PERFORMANCE = "performance"

class AlertSeverity(Enum):
    """Alert severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

@dataclass
class MetricConfig:
    """Metric configuration"""
    name: str
    type: MetricType
    query: str
    description: str
    labels: Dict[str, str] = field(default_factory=dict)
    interval: int = 60  # seconds
    enabled: bool = True

@dataclass
class AlertRule:
    """Alert rule configuration"""
    name: str
    severity: AlertSeverity
    condition: str
    threshold: Union[int, float]
    duration: str = "5m"
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    notification_channels: List[str] = field(default_factory=list)

@dataclass
class DashboardConfig:
    """Dashboard configuration"""
    name: str
    description: str
    panels: List[Dict[str, Any]] = field(default_factory=list)
    variables: List[Dict[str, Any]] = field(default_factory=list)
    refresh_interval: str = "30s"
    time_range: str = "1h"
    tags: List[str] = field(default_factory=list)

@dataclass
class MonitoringConfig:
    """Monitoring setup configuration"""
    app_name: str
    environment: str
    providers: List[MonitoringProvider]
    metrics: List[MetricConfig] = field(default_factory=list)
    alert_rules: List[AlertRule] = field(default_factory=list)
    dashboards: List[DashboardConfig] = field(default_factory=list)
    log_level: str = "INFO"
    retention_days: int = 30
    enable_tracing: bool = True
    enable_profiling: bool = False
    notification_channels: Dict[str, Dict[str, str]] = field(default_factory=dict)
    custom_labels: Dict[str, str] = field(default_factory=dict)
    sampling_rate: float = 0.1  # For tracing

class MonitoringSetupEngine:
    """
    Monitoring Setup Engine for comprehensive observability.
    
    Features:
    - Multi-provider monitoring setup (Prometheus, ELK, Datadog, etc.)
    - Automated metric collection and alerting
    - Custom dashboard generation
    - Distributed tracing setup
    - Log aggregation and analysis
    - Performance monitoring and profiling
    - Business metrics tracking
    - Security event monitoring
    """
    
    def __init__(self, config: MonitoringConfig):
        self.config = config
        self.templates_path = Path(__file__).parent.parent / "templates" / "monitoring"
        self._setup_default_metrics()
        self._setup_default_alerts()
        self._setup_default_dashboards()
    
    async def setup_monitoring(self, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Setup comprehensive monitoring for the application.
        
        Args:
            output_dir: Directory to save monitoring configurations
            
        Returns:
            Dictionary with setup results and configurations
        """
        logger.info(f"Setting up monitoring for {self.config.app_name}")
        
        results = {
            "app_name": self.config.app_name,
            "environment": self.config.environment,
            "providers": [p.value for p in self.config.providers],
            "configurations": {},
            "setup_status": {}
        }
        
        # Setup each monitoring provider
        for provider in self.config.providers:
            try:
                logger.info(f"Setting up {provider.value}")
                
                if provider == MonitoringProvider.PROMETHEUS_GRAFANA:
                    config = await self._setup_prometheus_grafana()
                elif provider == MonitoringProvider.ELK_STACK:
                    config = await self._setup_elk_stack()
                elif provider == MonitoringProvider.DATADOG:
                    config = await self._setup_datadog()
                elif provider == MonitoringProvider.JAEGER:
                    config = await self._setup_jaeger()
                elif provider == MonitoringProvider.AWS_CLOUDWATCH:
                    config = await self._setup_aws_cloudwatch()
                else:
                    logger.warning(f"Provider {provider.value} not yet implemented")
                    continue
                
                results["configurations"][provider.value] = config
                results["setup_status"][provider.value] = "success"
                
            except Exception as e:
                logger.error(f"Failed to setup {provider.value}: {e}")
                results["setup_status"][provider.value] = f"failed: {str(e)}"
        
        # Generate application instrumentation
        results["instrumentation"] = self._generate_application_instrumentation()
        
        # Save configurations if output directory provided
        if output_dir:
            await self._save_monitoring_configs(results, output_dir)
        
        return results
    
    async def _setup_prometheus_grafana(self) -> Dict[str, Any]:
        """Setup Prometheus and Grafana monitoring"""
        config = {
            "prometheus": self._generate_prometheus_config(),
            "grafana": self._generate_grafana_config(),
            "alertmanager": self._generate_alertmanager_config(),
            "kubernetes_manifests": self._generate_prometheus_k8s_manifests()
        }
        
        return config
    
    def _generate_prometheus_config(self) -> Dict[str, Any]:
        """Generate Prometheus configuration"""
        config = {
            "global": {
                "scrape_interval": "15s",
                "evaluation_interval": "15s"
            },
            "rule_files": ["alert_rules.yml"],
            "alerting": {
                "alertmanagers": [{
                    "static_configs": [{
                        "targets": ["alertmanager:9093"]
                    }]
                }]
            },
            "scrape_configs": [
                {
                    "job_name": "prometheus",
                    "static_configs": [{
                        "targets": ["localhost:9090"]
                    }]
                },
                {
                    "job_name": self.config.app_name,
                    "static_configs": [{
                        "targets": [f"{self.config.app_name}:8080"]
                    }],
                    "metrics_path": "/metrics",
                    "scrape_interval": "30s",
                    "scrape_timeout": "10s"
                }
            ]
        }
        
        # Add Kubernetes service discovery if running in K8s
        if any("kubernetes" in str(provider) for provider in self.config.providers):
            config["scrape_configs"].extend([
                {
                    "job_name": "kubernetes-apiservers",
                    "kubernetes_sd_configs": [{
                        "role": "endpoints"
                    }],
                    "scheme": "https",
                    "tls_config": {
                        "ca_file": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
                    },
                    "bearer_token_file": "/var/run/secrets/kubernetes.io/serviceaccount/token",
                    "relabel_configs": [
                        {
                            "source_labels": ["__meta_kubernetes_namespace", "__meta_kubernetes_service_name", "__meta_kubernetes_endpoint_port_name"],
                            "action": "keep",
                            "regex": "default;kubernetes;https"
                        }
                    ]
                },
                {
                    "job_name": "kubernetes-nodes",
                    "kubernetes_sd_configs": [{
                        "role": "node"
                    }],
                    "scheme": "https",
                    "tls_config": {
                        "ca_file": "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
                    },
                    "bearer_token_file": "/var/run/secrets/kubernetes.io/serviceaccount/token",
                    "relabel_configs": [
                        {
                            "action": "labelmap",
                            "regex": "__meta_kubernetes_node_label_(.+)"
                        }
                    ]
                },
                {
                    "job_name": "kubernetes-pods",
                    "kubernetes_sd_configs": [{
                        "role": "pod"
                    }],
                    "relabel_configs": [
                        {
                            "source_labels": ["__meta_kubernetes_pod_annotation_prometheus_io_scrape"],
                            "action": "keep",
                            "regex": True
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_annotation_prometheus_io_path"],
                            "action": "replace",
                            "target_label": "__metrics_path__",
                            "regex": "(.+)"
                        }
                    ]
                }
            ])
        
        return config
    
    def _generate_grafana_config(self) -> Dict[str, Any]:
        """Generate Grafana configuration"""
        datasources = {
            "apiVersion": 1,
            "datasources": [
                {
                    "name": "Prometheus",
                    "type": "prometheus",
                    "access": "proxy",
                    "url": "http://prometheus:9090",
                    "isDefault": True
                }
            ]
        }
        
        # Add additional datasources based on providers
        if MonitoringProvider.ELK_STACK in self.config.providers:
            datasources["datasources"].append({
                "name": "Elasticsearch",
                "type": "elasticsearch",
                "access": "proxy",
                "url": "http://elasticsearch:9200",
                "database": f"{self.config.app_name}-logs-*"
            })
        
        if self.config.enable_tracing:
            if MonitoringProvider.JAEGER in self.config.providers:
                datasources["datasources"].append({
                    "name": "Jaeger",
                    "type": "jaeger",
                    "access": "proxy",
                    "url": "http://jaeger:16686"
                })
        
        # Generate dashboard configurations
        dashboards = []
        for dashboard_config in self.config.dashboards:
            dashboard = self._generate_grafana_dashboard(dashboard_config)
            dashboards.append(dashboard)
        
        return {
            "datasources": datasources,
            "dashboards": dashboards,
            "provisioning": {
                "dashboards": [{
                    "name": "default",
                    "type": "file",
                    "disableDeletion": False,
                    "editable": True,
                    "options": {
                        "path": "/etc/grafana/provisioning/dashboards"
                    }
                }]
            }
        }
    
    def _generate_alertmanager_config(self) -> Dict[str, Any]:
        """Generate Alertmanager configuration"""
        config = {
            "global": {
                "smtp_smarthost": "localhost:587",
                "smtp_from": f"alerts@{self.config.app_name}.com"
            },
            "route": {
                "group_by": ["alertname"],
                "group_wait": "10s",
                "group_interval": "10s",
                "repeat_interval": "1h",
                "receiver": "web.hook"
            },
            "receivers": []
        }
        
        # Add notification channels
        for channel_name, channel_config in self.config.notification_channels.items():
            if channel_config.get("type") == "slack":
                config["receivers"].append({
                    "name": channel_name,
                    "slack_configs": [{
                        "api_url": channel_config["webhook_url"],
                        "channel": channel_config["channel"],
                        "title": f"Alert - {self.config.app_name}",
                        "text": "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"
                    }]
                })
            elif channel_config.get("type") == "email":
                config["receivers"].append({
                    "name": channel_name,
                    "email_configs": [{
                        "to": channel_config["to"],
                        "subject": f"Alert - {self.config.app_name}",
                        "body": "{{ range .Alerts }}{{ .Annotations.description }}{{ end }}"
                    }]
                })
            elif channel_config.get("type") == "webhook":
                config["receivers"].append({
                    "name": channel_name,
                    "webhook_configs": [{
                        "url": channel_config["url"],
                        "send_resolved": True
                    }]
                })
        
        # Default webhook receiver
        config["receivers"].append({
            "name": "web.hook",
            "webhook_configs": [{
                "url": "http://localhost:5001/webhook"
            }]
        })
        
        return config
    
    def _generate_prometheus_k8s_manifests(self) -> Dict[str, Any]:
        """Generate Kubernetes manifests for Prometheus stack"""
        manifests = {}
        
        # Prometheus deployment
        manifests["prometheus"] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "prometheus",
                "namespace": "monitoring"
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": "prometheus"}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": "prometheus"}
                    },
                    "spec": {
                        "containers": [{
                            "name": "prometheus",
                            "image": "prom/prometheus:latest",
                            "ports": [{"containerPort": 9090}],
                            "volumeMounts": [{
                                "name": "config",
                                "mountPath": "/etc/prometheus"
                            }]
                        }],
                        "volumes": [{
                            "name": "config",
                            "configMap": {"name": "prometheus-config"}
                        }]
                    }
                }
            }
        }
        
        # Grafana deployment
        manifests["grafana"] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "grafana",
                "namespace": "monitoring"
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": "grafana"}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": "grafana"}
                    },
                    "spec": {
                        "containers": [{
                            "name": "grafana",
                            "image": "grafana/grafana:latest",
                            "ports": [{"containerPort": 3000}],
                            "env": [
                                {"name": "GF_SECURITY_ADMIN_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "grafana-admin", "key": "password"}}}
                            ]
                        }]
                    }
                }
            }
        }
        
        # Services
        manifests["prometheus_service"] = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "prometheus",
                "namespace": "monitoring"
            },
            "spec": {
                "selector": {"app": "prometheus"},
                "ports": [{"port": 9090, "targetPort": 9090}]
            }
        }
        
        manifests["grafana_service"] = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "grafana",
                "namespace": "monitoring"
            },
            "spec": {
                "selector": {"app": "grafana"},
                "ports": [{"port": 3000, "targetPort": 3000}],
                "type": "LoadBalancer"
            }
        }
        
        return manifests
    
    async def _setup_elk_stack(self) -> Dict[str, Any]:
        """Setup ELK Stack (Elasticsearch, Logstash, Kibana)"""
        config = {
            "elasticsearch": self._generate_elasticsearch_config(),
            "logstash": self._generate_logstash_config(),
            "kibana": self._generate_kibana_config(),
            "filebeat": self._generate_filebeat_config(),
            "kubernetes_manifests": self._generate_elk_k8s_manifests()
        }
        
        return config
    
    def _generate_elasticsearch_config(self) -> Dict[str, Any]:
        """Generate Elasticsearch configuration"""
        return {
            "cluster.name": f"{self.config.app_name}-cluster",
            "node.name": "elasticsearch-node",
            "network.host": "0.0.0.0",
            "discovery.type": "single-node",
            "xpack.security.enabled": False,
            "xpack.monitoring.collection.enabled": True,
            "indices.lifecycle.rollover.only_if_has_documents": False
        }
    
    def _generate_logstash_config(self) -> Dict[str, Any]:
        """Generate Logstash configuration"""
        return {
            "input": {
                "beats": {
                    "port": 5044
                }
            },
            "filter": [
                {
                    "if": "[fields][app] == \"{}\"".format(self.config.app_name),
                    "mutate": {
                        "add_field": {
                            "environment": self.config.environment
                        }
                    }
                },
                {
                    "grok": {
                        "match": {
                            "message": "%{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}"
                        }
                    }
                },
                {
                    "date": {
                        "match": ["timestamp", "ISO8601"]
                    }
                }
            ],
            "output": {
                "elasticsearch": {
                    "hosts": ["elasticsearch:9200"],
                    "index": f"{self.config.app_name}-logs-%{{+YYYY.MM.dd}}"
                }
            }
        }
    
    def _generate_kibana_config(self) -> Dict[str, Any]:
        """Generate Kibana configuration"""
        return {
            "server.name": "kibana",
            "server.host": "0.0.0.0",
            "elasticsearch.hosts": ["http://elasticsearch:9200"],
            "monitoring.ui.container.elasticsearch.enabled": True,
            "xpack.security.enabled": False
        }
    
    def _generate_filebeat_config(self) -> Dict[str, Any]:
        """Generate Filebeat configuration"""
        return {
            "filebeat.inputs": [{
                "type": "log",
                "enabled": True,
                "paths": [f"/var/log/{self.config.app_name}/*.log"],
                "fields": {
                    "app": self.config.app_name,
                    "environment": self.config.environment
                },
                "fields_under_root": True,
                "multiline.pattern": "^\\d{4}-\\d{2}-\\d{2}",
                "multiline.negate": True,
                "multiline.match": "after"
            }],
            "output.logstash": {
                "hosts": ["logstash:5044"]
            },
            "processors": [
                {
                    "add_host_metadata": {
                        "when.not.contains.tags": "forwarded"
                    }
                },
                {
                    "add_docker_metadata": {}
                },
                {
                    "add_kubernetes_metadata": {}
                }
            ]
        }
    
    def _generate_elk_k8s_manifests(self) -> Dict[str, Any]:
        """Generate Kubernetes manifests for ELK stack"""
        manifests = {}
        
        # Elasticsearch StatefulSet
        manifests["elasticsearch"] = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": "elasticsearch",
                "namespace": "logging"
            },
            "spec": {
                "serviceName": "elasticsearch",
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": "elasticsearch"}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": "elasticsearch"}
                    },
                    "spec": {
                        "containers": [{
                            "name": "elasticsearch",
                            "image": "docker.elastic.co/elasticsearch/elasticsearch:8.8.0",
                            "ports": [
                                {"containerPort": 9200, "name": "rest"},
                                {"containerPort": 9300, "name": "inter-node"}
                            ],
                            "env": [
                                {"name": "cluster.name", "value": f"{self.config.app_name}-cluster"},
                                {"name": "node.name", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
                                {"name": "discovery.type", "value": "single-node"},
                                {"name": "ES_JAVA_OPTS", "value": "-Xms512m -Xmx512m"},
                                {"name": "xpack.security.enabled", "value": "false"}
                            ]
                        }]
                    }
                }
            }
        }
        
        # Kibana deployment
        manifests["kibana"] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "kibana",
                "namespace": "logging"
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": "kibana"}
                },
                "template": {
                    "metadata": {
                        "labels": {"app": "kibana"}
                    },
                    "spec": {
                        "containers": [{
                            "name": "kibana",
                            "image": "docker.elastic.co/kibana/kibana:8.8.0",
                            "ports": [{"containerPort": 5601}],
                            "env": [
                                {"name": "ELASTICSEARCH_HOSTS", "value": "http://elasticsearch:9200"}
                            ]
                        }]
                    }
                }
            }
        }
        
        return manifests
    
    async def _setup_datadog(self) -> Dict[str, Any]:
        """Setup Datadog monitoring"""
        config = {
            "agent_config": {
                "api_key": "${DD_API_KEY}",
                "site": "datadoghq.com",
                "logs_enabled": True,
                "apm_enabled": True,
                "process_agent_enabled": True,
                "tags": [
                    f"env:{self.config.environment}",
                    f"app:{self.config.app_name}",
                    *[f"{k}:{v}" for k, v in self.config.custom_labels.items()]
                ]
            },
            "integrations": {
                "flask": {
                    "init_config": {},
                    "instances": [{
                        "url": "http://localhost:8080/health",
                        "tags": [f"app:{self.config.app_name}"]
                    }]
                },
                "postgres": {
                    "init_config": {},
                    "instances": [{
                        "host": "localhost",
                        "port": 5432,
                        "dbname": f"{self.config.app_name}_db",
                        "tags": [f"app:{self.config.app_name}"]
                    }]
                }
            },
            "dashboards": self._generate_datadog_dashboards(),
            "monitors": self._generate_datadog_monitors()
        }
        
        return config
    
    async def _setup_jaeger(self) -> Dict[str, Any]:
        """Setup Jaeger distributed tracing"""
        config = {
            "jaeger_config": {
                "service_name": self.config.app_name,
                "logging": True,
                "sampler": {
                    "type": "probabilistic",
                    "param": self.config.sampling_rate
                },
                "local_agent": {
                    "reporting_host": "jaeger-agent",
                    "reporting_port": 6831
                }
            },
            "kubernetes_manifests": self._generate_jaeger_k8s_manifests(),
            "instrumentation": self._generate_jaeger_instrumentation()
        }
        
        return config
    
    async def _setup_aws_cloudwatch(self) -> Dict[str, Any]:
        """Setup AWS CloudWatch monitoring"""
        config = {
            "cloudwatch_config": {
                "region": "us-east-1",
                "namespace": f"{self.config.app_name}/Application",
                "dimensions": {
                    "Environment": self.config.environment,
                    "Application": self.config.app_name
                }
            },
            "log_groups": [
                {
                    "name": f"/aws/application/{self.config.app_name}",
                    "retention_days": self.config.retention_days
                }
            ],
            "dashboards": self._generate_cloudwatch_dashboards(),
            "alarms": self._generate_cloudwatch_alarms()
        }
        
        return config
    
    def _setup_default_metrics(self) -> None:
        """Setup default metrics for PgForge applications"""
        default_metrics = [
            MetricConfig(
                name="http_requests_total",
                type=MetricType.APPLICATION,
                query="sum(rate(http_requests_total[5m])) by (method, endpoint)",
                description="Total HTTP requests per second"
            ),
            MetricConfig(
                name="http_request_duration_seconds",
                type=MetricType.PERFORMANCE,
                query="histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
                description="95th percentile HTTP request duration"
            ),
            MetricConfig(
                name="http_errors_total",
                type=MetricType.APPLICATION,
                query="sum(rate(http_requests_total{status=~\"4..|5..\"}[5m]))",
                description="HTTP error rate"
            ),
            MetricConfig(
                name="database_connections_active",
                type=MetricType.INFRASTRUCTURE,
                query="sqlalchemy_pool_size - sqlalchemy_pool_checked_out",
                description="Active database connections"
            ),
            MetricConfig(
                name="memory_usage_bytes",
                type=MetricType.INFRASTRUCTURE,
                query="process_resident_memory_bytes",
                description="Process memory usage in bytes"
            ),
            MetricConfig(
                name="cpu_usage_percent",
                type=MetricType.INFRASTRUCTURE,
                query="rate(process_cpu_seconds_total[5m]) * 100",
                description="CPU usage percentage"
            ),
            MetricConfig(
                name="login_attempts_total",
                type=MetricType.SECURITY,
                query="sum(rate(fab_login_attempts_total[5m])) by (status)",
                description="Login attempts per second by status"
            ),
            MetricConfig(
                name="active_users_total",
                type=MetricType.BUSINESS,
                query="fab_active_users",
                description="Number of active users"
            )
        ]
        
        self.config.metrics.extend(default_metrics)
    
    def _setup_default_alerts(self) -> None:
        """Setup default alert rules"""
        default_alerts = [
            AlertRule(
                name="HighErrorRate",
                severity=AlertSeverity.CRITICAL,
                condition="rate(http_requests_total{status=~\"5..\"}[5m]) > 0.1",
                threshold=0.1,
                duration="5m",
                description="High HTTP 5xx error rate",
                notification_channels=["critical-alerts"]
            ),
            AlertRule(
                name="HighLatency",
                severity=AlertSeverity.HIGH,
                condition="histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le)) > 2",
                threshold=2.0,
                duration="10m",
                description="High request latency (95th percentile > 2s)",
                notification_channels=["performance-alerts"]
            ),
            AlertRule(
                name="DatabaseConnectionPoolExhausted",
                severity=AlertSeverity.CRITICAL,
                condition="sqlalchemy_pool_checked_out / sqlalchemy_pool_size > 0.9",
                threshold=0.9,
                duration="5m",
                description="Database connection pool nearly exhausted",
                notification_channels=["critical-alerts"]
            ),
            AlertRule(
                name="HighMemoryUsage",
                severity=AlertSeverity.HIGH,
                condition="process_resident_memory_bytes > 500000000",  # 500MB
                threshold=500000000,
                duration="15m",
                description="High memory usage",
                notification_channels=["resource-alerts"]
            ),
            AlertRule(
                name="ApplicationDown",
                severity=AlertSeverity.CRITICAL,
                condition="up == 0",
                threshold=0,
                duration="1m",
                description="Application is down",
                notification_channels=["critical-alerts"]
            ),
            AlertRule(
                name="HighFailedLoginRate",
                severity=AlertSeverity.MEDIUM,
                condition="rate(fab_login_attempts_total{status=\"failed\"}[5m]) > 5",
                threshold=5,
                duration="5m",
                description="High failed login attempt rate (potential brute force)",
                notification_channels=["security-alerts"]
            )
        ]
        
        self.config.alert_rules.extend(default_alerts)
    
    def _setup_default_dashboards(self) -> None:
        """Setup default dashboards"""
        # Application Overview Dashboard
        app_dashboard = DashboardConfig(
            name=f"{self.config.app_name} - Application Overview",
            description="Overall application health and performance metrics",
            panels=[
                {
                    "title": "Request Rate",
                    "type": "graph",
                    "targets": [{
                        "expr": "sum(rate(http_requests_total[5m])) by (method)",
                        "legendFormat": "{{method}}"
                    }]
                },
                {
                    "title": "Response Time",
                    "type": "graph",
                    "targets": [{
                        "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
                        "legendFormat": "95th percentile"
                    }]
                },
                {
                    "title": "Error Rate",
                    "type": "graph",
                    "targets": [{
                        "expr": "sum(rate(http_requests_total{status=~\"4..|5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
                        "legendFormat": "Error Rate"
                    }]
                },
                {
                    "title": "Active Users",
                    "type": "singlestat",
                    "targets": [{
                        "expr": "fab_active_users",
                        "legendFormat": "Active Users"
                    }]
                }
            ],
            tags=["flask-appbuilder", "application"]
        )
        
        # Infrastructure Dashboard
        infra_dashboard = DashboardConfig(
            name=f"{self.config.app_name} - Infrastructure",
            description="Infrastructure and resource utilization metrics",
            panels=[
                {
                    "title": "CPU Usage",
                    "type": "graph",
                    "targets": [{
                        "expr": "rate(process_cpu_seconds_total[5m]) * 100",
                        "legendFormat": "CPU %"
                    }]
                },
                {
                    "title": "Memory Usage",
                    "type": "graph",
                    "targets": [{
                        "expr": "process_resident_memory_bytes / 1024 / 1024",
                        "legendFormat": "Memory (MB)"
                    }]
                },
                {
                    "title": "Database Connections",
                    "type": "graph",
                    "targets": [{
                        "expr": "sqlalchemy_pool_checked_out",
                        "legendFormat": "Active Connections"
                    }]
                }
            ],
            tags=["infrastructure", "resources"]
        )
        
        self.config.dashboards.extend([app_dashboard, infra_dashboard])
    
    def _generate_application_instrumentation(self) -> Dict[str, Any]:
        """Generate application instrumentation code"""
        instrumentation = {
            "prometheus": {
                "python_code": self._generate_prometheus_instrumentation(),
                "requirements": ["prometheus-client", "flask-prometheus-metrics"]
            },
            "logging": {
                "python_code": self._generate_logging_instrumentation(),
                "requirements": ["structlog", "python-json-logger"]
            }
        }
        
        if self.config.enable_tracing:
            instrumentation["tracing"] = {
                "python_code": self._generate_tracing_instrumentation(),
                "requirements": ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-instrumentation-flask"]
            }
        
        return instrumentation
    
    def _generate_prometheus_instrumentation(self) -> str:
        """Generate Prometheus instrumentation code"""
        return f'''
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from flask import request, g
import time

# Metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_USERS = Gauge(
    'fab_active_users',
    'Number of active users'
)

LOGIN_ATTEMPTS = Counter(
    'fab_login_attempts_total',
    'Total login attempts',
    ['status']
)

def setup_metrics(app):
    """Setup Prometheus metrics for PgForge"""
    
    @app.before_request
    def before_request():
        g.start_time = time.time()
    
    @app.after_request
    def after_request(response):
        # Record request metrics
        request_duration = time.time() - g.start_time
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.endpoint or 'unknown'
        ).observe(request_duration)
        
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.endpoint or 'unknown',
            status=response.status_code
        ).inc()
        
        return response
    
    @app.route('/metrics')
    def metrics():
        """Prometheus metrics endpoint"""
        return generate_latest()
    
    return app

def track_login_attempt(success=True):
    """Track login attempts"""
    status = 'success' if success else 'failed'
    LOGIN_ATTEMPTS.labels(status=status).inc()

def update_active_users(count):
    """Update active users count"""
    ACTIVE_USERS.set(count)
'''
    
    def _generate_logging_instrumentation(self) -> str:
        """Generate structured logging instrumentation"""
        return f'''
import structlog
import logging
from pythonjsonlogger import jsonlogger

def setup_logging(app):
    """Setup structured logging for PgForge"""
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    logHandler.setFormatter(formatter)
    
    logger = logging.getLogger()
    logger.addHandler(logHandler)
    logger.setLevel(getattr(logging, '{self.config.log_level}'))
    
    # Add request logging
    @app.before_request
    def log_request():
        structlog.get_logger().info(
            "request_started",
            method=request.method,
            path=request.path,
            remote_addr=request.remote_addr,
            user_agent=str(request.user_agent)
        )
    
    @app.after_request
    def log_response(response):
        structlog.get_logger().info(
            "request_completed",
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            response_size=response.content_length
        )
        return response
    
    return app
'''
    
    def _generate_tracing_instrumentation(self) -> str:
        """Generate distributed tracing instrumentation"""
        return f'''
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

def setup_tracing(app):
    """Setup distributed tracing for PgForge"""
    
    # Configure tracer
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)
    
    # Configure Jaeger exporter
    jaeger_exporter = JaegerExporter(
        agent_host_name="jaeger-agent",
        agent_port=6831,
    )
    
    span_processor = BatchSpanProcessor(jaeger_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)
    
    # Auto-instrument Flask
    FlaskInstrumentor().instrument_app(app)
    
    # Auto-instrument SQLAlchemy
    SQLAlchemyInstrumentor().instrument()
    
    # Auto-instrument requests
    RequestsInstrumentor().instrument()
    
    return app

def trace_function(name):
    """Decorator to trace functions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span(name):
                return func(*args, **kwargs)
        return wrapper
    return decorator
'''
    
    def _generate_grafana_dashboard(self, dashboard_config: DashboardConfig) -> Dict[str, Any]:
        """Generate Grafana dashboard JSON"""
        dashboard = {
            "dashboard": {
                "id": None,
                "title": dashboard_config.name,
                "description": dashboard_config.description,
                "tags": dashboard_config.tags,
                "timezone": "browser",
                "panels": [],
                "time": {
                    "from": f"now-{dashboard_config.time_range}",
                    "to": "now"
                },
                "timepicker": {},
                "templating": {
                    "list": dashboard_config.variables
                },
                "refresh": dashboard_config.refresh_interval
            }
        }
        
        # Convert panels to Grafana format
        for i, panel in enumerate(dashboard_config.panels):
            grafana_panel = {
                "id": i + 1,
                "title": panel["title"],
                "type": panel["type"],
                "gridPos": {"h": 8, "w": 12, "x": (i % 2) * 12, "y": (i // 2) * 8},
                "targets": panel["targets"]
            }
            dashboard["dashboard"]["panels"].append(grafana_panel)
        
        return dashboard
    
    def _generate_datadog_dashboards(self) -> List[Dict[str, Any]]:
        """Generate Datadog dashboard configurations"""
        return [
            {
                "title": f"{self.config.app_name} - Application Dashboard",
                "description": "Application performance and health metrics",
                "widgets": [
                    {
                        "definition": {
                            "type": "timeseries",
                            "requests": [{
                                "q": f"avg:flask.request.duration{{app:{self.config.app_name}}}",
                                "display_type": "line"
                            }],
                            "title": "Average Request Duration"
                        }
                    },
                    {
                        "definition": {
                            "type": "query_value",
                            "requests": [{
                                "q": f"sum:flask.request.count{{app:{self.config.app_name}}}",
                                "aggregator": "avg"
                            }],
                            "title": "Request Count"
                        }
                    }
                ]
            }
        ]
    
    def _generate_datadog_monitors(self) -> List[Dict[str, Any]]:
        """Generate Datadog monitor configurations"""
        return [
            {
                "name": f"{self.config.app_name} - High Error Rate",
                "type": "metric alert",
                "query": f"avg(last_5m):sum:flask.request.count{{status:5xx,app:{self.config.app_name}}} > 10",
                "message": "High error rate detected in Flask application",
                "options": {
                    "thresholds": {"critical": 10, "warning": 5}
                }
            }
        ]
    
    def _generate_jaeger_k8s_manifests(self) -> Dict[str, Any]:
        """Generate Kubernetes manifests for Jaeger"""
        return {
            "jaeger": {
                "apiVersion": "jaegertracing.io/v1",
                "kind": "Jaeger",
                "metadata": {
                    "name": "simple-prod",
                    "namespace": "tracing"
                },
                "spec": {
                    "strategy": "production",
                    "storage": {
                        "type": "elasticsearch",
                        "elasticsearch": {
                            "nodeCount": 1,
                            "redundancyPolicy": "ZeroRedundancy"
                        }
                    }
                }
            }
        }
    
    def _generate_jaeger_instrumentation(self) -> str:
        """Generate Jaeger-specific instrumentation"""
        return '''
# Jaeger configuration for PgForge
JAEGER_CONFIG = {
    'sampler': {
        'type': 'probabilistic',
        'param': 0.1,
    },
    'local_agent': {
        'reporting_host': 'jaeger-agent',
        'reporting_port': 6831,
    },
    'logging': True,
}
'''
    
    def _generate_cloudwatch_dashboards(self) -> List[Dict[str, Any]]:
        """Generate CloudWatch dashboard configurations"""
        return [
            {
                "widgets": [
                    {
                        "type": "metric",
                        "properties": {
                            "metrics": [
                                [f"{self.config.app_name}/Application", "RequestCount"],
                                [f"{self.config.app_name}/Application", "ErrorCount"]
                            ],
                            "period": 300,
                            "stat": "Sum",
                            "region": "us-east-1",
                            "title": "Request and Error Count"
                        }
                    }
                ]
            }
        ]
    
    def _generate_cloudwatch_alarms(self) -> List[Dict[str, Any]]:
        """Generate CloudWatch alarm configurations"""
        return [
            {
                "AlarmName": f"{self.config.app_name}-HighErrorRate",
                "ComparisonOperator": "GreaterThanThreshold",
                "EvaluationPeriods": 2,
                "MetricName": "ErrorCount",
                "Namespace": f"{self.config.app_name}/Application",
                "Period": 300,
                "Statistic": "Sum",
                "Threshold": 10.0,
                "ActionsEnabled": True,
                "AlarmDescription": "High error rate detected"
            }
        ]
    
    async def _save_monitoring_configs(self, results: Dict[str, Any], output_dir: str) -> None:
        """Save monitoring configurations to files"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for provider, config in results["configurations"].items():
            provider_dir = output_path / provider
            provider_dir.mkdir(parents=True, exist_ok=True)
            
            for config_name, config_content in config.items():
                if isinstance(config_content, dict):
                    file_path = provider_dir / f"{config_name}.yml"
                    with open(file_path, 'w') as f:
                        yaml.dump(config_content, f, default_flow_style=False)
                elif isinstance(config_content, str):
                    file_path = provider_dir / f"{config_name}.txt"
                    with open(file_path, 'w') as f:
                        f.write(config_content)
        
        # Save instrumentation code
        if "instrumentation" in results:
            instrumentation_dir = output_path / "instrumentation"
            instrumentation_dir.mkdir(parents=True, exist_ok=True)
            
            for instr_type, instr_config in results["instrumentation"].items():
                if "python_code" in instr_config:
                    file_path = instrumentation_dir / f"{instr_type}_instrumentation.py"
                    with open(file_path, 'w') as f:
                        f.write(instr_config["python_code"])
        
        logger.info(f"Monitoring configurations saved to {output_dir}")
    
    async def validate_monitoring_setup(self) -> Dict[str, Any]:
        """Validate monitoring setup and connectivity"""
        validation_results = {
            "overall_status": "unknown",
            "provider_status": {},
            "connectivity_tests": {},
            "recommendations": []
        }
        
        for provider in self.config.providers:
            try:
                if provider == MonitoringProvider.PROMETHEUS_GRAFANA:
                    status = await self._validate_prometheus_connectivity()
                elif provider == MonitoringProvider.ELK_STACK:
                    status = await self._validate_elasticsearch_connectivity()
                elif provider == MonitoringProvider.DATADOG:
                    status = await self._validate_datadog_connectivity()
                else:
                    status = {"status": "not_implemented", "message": "Validation not implemented"}
                
                validation_results["provider_status"][provider.value] = status
                
            except Exception as e:
                validation_results["provider_status"][provider.value] = {
                    "status": "error",
                    "message": str(e)
                }
        
        # Determine overall status
        statuses = [result.get("status") for result in validation_results["provider_status"].values()]
        if all(status == "healthy" for status in statuses):
            validation_results["overall_status"] = "healthy"
        elif any(status == "error" for status in statuses):
            validation_results["overall_status"] = "error"
        else:
            validation_results["overall_status"] = "partial"
        
        return validation_results
    
    async def _validate_prometheus_connectivity(self) -> Dict[str, Any]:
        """Validate Prometheus connectivity"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://prometheus:9090/-/healthy", timeout=10) as response:
                    if response.status == 200:
                        return {"status": "healthy", "message": "Prometheus is accessible"}
                    else:
                        return {"status": "unhealthy", "message": f"Prometheus returned status {response.status}"}
        except Exception as e:
            return {"status": "error", "message": f"Cannot connect to Prometheus: {str(e)}"}
    
    async def _validate_elasticsearch_connectivity(self) -> Dict[str, Any]:
        """Validate Elasticsearch connectivity"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://elasticsearch:9200/_cluster/health", timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "status": "healthy" if data.get("status") in ["green", "yellow"] else "unhealthy",
                            "message": f"Elasticsearch cluster status: {data.get('status')}"
                        }
                    else:
                        return {"status": "unhealthy", "message": f"Elasticsearch returned status {response.status}"}
        except Exception as e:
            return {"status": "error", "message": f"Cannot connect to Elasticsearch: {str(e)}"}
    
    async def _validate_datadog_connectivity(self) -> Dict[str, Any]:
        """Validate Datadog connectivity"""
        # This would require actual Datadog API calls with proper credentials
        return {"status": "not_implemented", "message": "Datadog validation requires API credentials"}
    
    def generate_monitoring_documentation(self) -> str:
        """Generate comprehensive monitoring documentation"""
        doc = f"""
# Monitoring Setup Documentation - {self.config.app_name}

## Overview
This document describes the monitoring and observability setup for **{self.config.app_name}** in the **{self.config.environment}** environment.

## Monitoring Providers
"""
        
        for provider in self.config.providers:
            doc += f"- {provider.value}\n"
        
        doc += f"""

## Metrics Collection

### Application Metrics
"""
        
        app_metrics = [m for m in self.config.metrics if m.type == MetricType.APPLICATION]
        for metric in app_metrics:
            doc += f"- **{metric.name}**: {metric.description}\n"
        
        doc += f"""

### Infrastructure Metrics
"""
        
        infra_metrics = [m for m in self.config.metrics if m.type == MetricType.INFRASTRUCTURE]
        for metric in infra_metrics:
            doc += f"- **{metric.name}**: {metric.description}\n"
        
        doc += f"""

## Alert Rules

### Critical Alerts
"""
        
        critical_alerts = [a for a in self.config.alert_rules if a.severity == AlertSeverity.CRITICAL]
        for alert in critical_alerts:
            doc += f"- **{alert.name}**: {alert.description} (Threshold: {alert.threshold})\n"
        
        doc += f"""

### High Priority Alerts
"""
        
        high_alerts = [a for a in self.config.alert_rules if a.severity == AlertSeverity.HIGH]
        for alert in high_alerts:
            doc += f"- **{alert.name}**: {alert.description} (Threshold: {alert.threshold})\n"
        
        doc += f"""

## Dashboards
"""
        
        for dashboard in self.config.dashboards:
            doc += f"- **{dashboard.name}**: {dashboard.description}\n"
        
        doc += f"""

## Configuration

### Log Level
- **Level**: {self.config.log_level}
- **Retention**: {self.config.retention_days} days

### Tracing
- **Enabled**: {self.config.enable_tracing}
- **Sampling Rate**: {self.config.sampling_rate * 100}%

### Profiling
- **Enabled**: {self.config.enable_profiling}

## Notification Channels
"""
        
        for channel_name, channel_config in self.config.notification_channels.items():
            doc += f"- **{channel_name}**: {channel_config.get('type', 'unknown')}\n"
        
        doc += f"""

## Access Information

### Prometheus
- **URL**: http://prometheus:9090
- **Metrics Endpoint**: /metrics

### Grafana
- **URL**: http://grafana:3000
- **Default Credentials**: admin/admin

### Jaeger (if enabled)
- **URL**: http://jaeger:16686

### Kibana (if ELK enabled)
- **URL**: http://kibana:5601

## Troubleshooting

### Common Issues
1. **Metrics not appearing**: Check if application metrics endpoint is accessible
2. **Alerts not firing**: Verify Alertmanager configuration and notification channels
3. **Dashboard empty**: Ensure Prometheus is scraping the correct targets
4. **High resource usage**: Consider adjusting scrape intervals and retention periods

### Health Checks
- Application health: `curl http://localhost:8080/health`
- Prometheus targets: `curl http://prometheus:9090/api/v1/targets`
- Grafana health: `curl http://grafana:3000/api/health`

## Maintenance
- Regular backup of Grafana dashboards and Prometheus data
- Monitor disk usage for log and metric storage
- Update retention policies based on compliance requirements
- Review and update alert thresholds based on application behavior
"""
        
        return doc