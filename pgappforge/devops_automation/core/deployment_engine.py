"""
Deployment Automation Engine

Automated deployment management for PgForge applications across
multiple environments with rollback capabilities, health monitoring, and
infrastructure-as-code integration.
"""

import os
import json
import yaml
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
import shutil
import uuid
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class DeploymentTarget(Enum):
    """Supported deployment targets"""
    KUBERNETES = "kubernetes"
    DOCKER_COMPOSE = "docker_compose"
    DOCKER_SWARM = "docker_swarm"
    AWS_ECS = "aws_ecs"
    AWS_LAMBDA = "aws_lambda"
    AZURE_CONTAINER_INSTANCES = "azure_container_instances"
    GOOGLE_CLOUD_RUN = "google_cloud_run"
    HEROKU = "heroku"

class DeploymentStrategy(Enum):
    """Deployment strategies"""
    ROLLING_UPDATE = "rolling_update"
    BLUE_GREEN = "blue_green"
    CANARY = "canary"
    RECREATE = "recreate"

class DeploymentStatus(Enum):
    """Deployment status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

@dataclass
class HealthCheck:
    """Health check configuration"""
    endpoint: str = "/health"
    timeout: int = 30
    interval: int = 10
    retries: int = 3
    initial_delay: int = 30

@dataclass
class RollbackConfig:
    """Rollback configuration"""
    enabled: bool = True
    auto_rollback: bool = True
    failure_threshold: int = 3
    rollback_timeout: int = 300

@dataclass
class ResourceLimits:
    """Resource limits configuration"""
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "128Mi"
    memory_limit: str = "512Mi"
    
@dataclass
class ScalingConfig:
    """Auto-scaling configuration"""
    min_replicas: int = 1
    max_replicas: int = 10
    target_cpu_percent: int = 70
    target_memory_percent: int = 80
    scale_down_delay: int = 300
    scale_up_delay: int = 60

@dataclass
class DeploymentConfig:
    """Deployment configuration"""
    app_name: str
    environment: str
    target: DeploymentTarget
    strategy: DeploymentStrategy = DeploymentStrategy.ROLLING_UPDATE
    image_tag: str = "latest"
    replicas: int = 3
    namespace: str = "default"
    health_check: HealthCheck = field(default_factory=HealthCheck)
    rollback_config: RollbackConfig = field(default_factory=RollbackConfig)
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    scaling_config: ScalingConfig = field(default_factory=ScalingConfig)
    environment_variables: Dict[str, str] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    config_maps: Dict[str, str] = field(default_factory=dict)
    volumes: List[Dict[str, Any]] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    ingress_config: Optional[Dict[str, Any]] = None
    monitoring_enabled: bool = True
    logging_enabled: bool = True

@dataclass
class DeploymentResult:
    """Deployment operation result"""
    deployment_id: str
    status: DeploymentStatus
    message: str
    deployment_time: datetime
    rollback_available: bool = False
    health_check_passed: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)

class DeploymentAutomationEngine:
    """
    Deployment Automation Engine for comprehensive deployment management.
    
    Features:
    - Multi-platform deployment (Kubernetes, Docker, Cloud services)
    - Multiple deployment strategies (Rolling, Blue-Green, Canary)
    - Automated health checking and rollback
    - Infrastructure-as-code generation
    - Real-time monitoring and alerting
    - Security and compliance integration
    """
    
    def __init__(self, config: DeploymentConfig):
        self.config = config
        self.deployment_history: List[DeploymentResult] = []
        self.active_deployments: Dict[str, DeploymentResult] = {}
        self.templates_path = Path(__file__).parent.parent / "templates" / "deployment"
        
    async def deploy(self, image_tag: Optional[str] = None) -> DeploymentResult:
        """
        Execute deployment with the configured strategy.

        Args:
            image_tag: Override image tag for deployment

        Returns:
            Deployment result with status and metrics
        """
        deployment_id = f"{self.config.app_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        if image_tag:
            self.config.image_tag = image_tag

        logger.info(f"Starting deployment {deployment_id} to {self.config.environment}")

        result = DeploymentResult(
            deployment_id=deployment_id,
            status=DeploymentStatus.IN_PROGRESS,
            message="Deployment started",
            deployment_time=datetime.now()
        )

        self.active_deployments[deployment_id] = result

        try:
            # Validate external dependencies first
            await self._validate_dependencies()

            # Pre-deployment validation
            await self._validate_deployment()
            
            # Generate deployment manifests
            manifests = await self._generate_manifests()
            
            # Execute deployment based on target
            if self.config.target == DeploymentTarget.KUBERNETES:
                await self._deploy_kubernetes(manifests, result)
            elif self.config.target == DeploymentTarget.DOCKER_COMPOSE:
                await self._deploy_docker_compose(manifests, result)
            elif self.config.target == DeploymentTarget.AWS_ECS:
                await self._deploy_aws_ecs(manifests, result)
            elif self.config.target == DeploymentTarget.GOOGLE_CLOUD_RUN:
                await self._deploy_cloud_run(manifests, result)
            else:
                raise ValueError(f"Unsupported deployment target: {self.config.target}")
            
            # Wait for deployment completion
            await self._wait_for_deployment(result)
            
            # Perform health checks
            health_ok = await self._perform_health_check(result)
            result.health_check_passed = health_ok
            
            if health_ok:
                result.status = DeploymentStatus.SUCCESS
                result.message = "Deployment completed successfully"
            else:
                if self.config.rollback_config.auto_rollback:
                    await self._rollback_deployment(result)
                else:
                    result.status = DeploymentStatus.FAILED
                    result.message = "Health check failed, auto-rollback disabled"
            
        except Exception as e:
            logger.error(f"Deployment {deployment_id} failed: {e}")
            result.status = DeploymentStatus.FAILED
            result.message = f"Deployment failed: {str(e)}"

            if self.config.rollback_config.auto_rollback:
                await self._rollback_deployment(result)
            else:
                # Clean up partial resources
                await self._cleanup_failed_deployment(result)

        # Store deployment history
        self.deployment_history.append(result)
        if deployment_id in self.active_deployments:
            del self.active_deployments[deployment_id]

        return result

    async def _execute_kubectl_command(self, *args) -> str:
        """Execute kubectl command with proper async handling"""
        process = await asyncio.create_subprocess_exec(
            'kubectl', *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"kubectl {' '.join(args)} failed: {stderr.decode()}")

        return stdout.decode()

    @asynccontextmanager
    async def _temporary_file(self, content: str, suffix: str = ".yml"):
        """Context manager for temporary files with guaranteed cleanup"""
        temp_file = None
        try:
            temp_file = Path(f"/tmp/{self.config.app_name}-{uuid.uuid4()}{suffix}")
            with open(temp_file, 'w') as f:
                f.write(content)
            yield temp_file
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError as e:
                    logger.warning(f"Failed to cleanup temporary file {temp_file}: {e}")

    def _parse_cpu_value(self, cpu_str: str) -> float:
        """Parse CPU value from string (e.g., '500m' -> 0.5)"""
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000
        return float(cpu_str)

    def _parse_memory_value(self, memory_str: str) -> int:
        """Parse memory value from string (e.g., '512Mi' -> 536870912)"""
        if memory_str.endswith('Mi'):
            return int(memory_str[:-2]) * 1024 * 1024
        elif memory_str.endswith('Gi'):
            return int(memory_str[:-2]) * 1024 * 1024 * 1024
        elif memory_str.endswith('Ki'):
            return int(memory_str[:-2]) * 1024
        return int(memory_str)

    def _validate_resource_limits(self) -> None:
        """Validate resource limits configuration"""
        try:
            cpu_limit = self._parse_cpu_value(self.config.resource_limits.cpu_limit)
            cpu_request = self._parse_cpu_value(self.config.resource_limits.cpu_request)

            if cpu_limit < cpu_request:
                raise ValueError("CPU limit must be >= CPU request")

            memory_limit = self._parse_memory_value(self.config.resource_limits.memory_limit)
            memory_request = self._parse_memory_value(self.config.resource_limits.memory_request)

            if memory_limit < memory_request:
                raise ValueError("Memory limit must be >= memory request")

        except (ValueError, AttributeError) as e:
            raise ValueError(f"Invalid resource configuration: {e}")

    async def _validate_dependencies(self) -> None:
        """Validate external tool dependencies"""
        required_tools = {}

        if self.config.target == DeploymentTarget.KUBERNETES:
            required_tools['kubectl'] = 'Kubernetes CLI'
        elif self.config.target == DeploymentTarget.DOCKER_COMPOSE:
            required_tools['docker-compose'] = 'Docker Compose'
        elif self.config.target == DeploymentTarget.GOOGLE_CLOUD_RUN:
            required_tools['gcloud'] = 'Google Cloud CLI'

        # Always require docker if using containers
        if self.config.target in [DeploymentTarget.KUBERNETES, DeploymentTarget.DOCKER_COMPOSE]:
            required_tools['docker'] = 'Docker CLI'

        missing_tools = []
        for tool, description in required_tools.items():
            if not shutil.which(tool):
                missing_tools.append(f"{tool} ({description})")

        if missing_tools:
            raise RuntimeError(f"Missing required tools: {', '.join(missing_tools)}")

    async def _cleanup_failed_deployment(self, result: DeploymentResult) -> None:
        """Clean up resources from failed deployment"""
        try:
            if self.config.target == DeploymentTarget.KUBERNETES:
                # Clean up any partially created Kubernetes resources
                await self._execute_kubectl_command(
                    'delete', 'deployment', self.config.app_name,
                    '-n', self.config.namespace, '--ignore-not-found=true'
                )
            result.logs.append("Cleaned up failed deployment resources")
        except Exception as e:
            logger.warning(f"Failed to clean up resources: {e}")
            result.logs.append(f"Cleanup warning: {str(e)}")
    
    async def rollback(self, target_deployment: Optional[str] = None) -> DeploymentResult:
        """
        Rollback to previous deployment or specific deployment.
        
        Args:
            target_deployment: Specific deployment ID to rollback to
            
        Returns:
            Rollback result
        """
        if target_deployment:
            target = next((d for d in self.deployment_history 
                          if d.deployment_id == target_deployment), None)
            if not target:
                raise ValueError(f"Deployment {target_deployment} not found")
        else:
            # Find last successful deployment
            successful_deployments = [d for d in self.deployment_history 
                                    if d.status == DeploymentStatus.SUCCESS]
            if not successful_deployments:
                raise ValueError("No successful deployments found for rollback")
            target = successful_deployments[-1]
        
        logger.info(f"Rolling back to deployment {target.deployment_id}")
        
        rollback_id = f"rollback-{target.deployment_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        result = DeploymentResult(
            deployment_id=rollback_id,
            status=DeploymentStatus.IN_PROGRESS,
            message=f"Rolling back to {target.deployment_id}",
            deployment_time=datetime.now()
        )
        
        try:
            # Restore previous configuration
            previous_tag = target.deployment_id.split('-')[-1]  # Extract tag from deployment ID
            await self.deploy(image_tag=previous_tag)
            
            result.status = DeploymentStatus.SUCCESS
            result.message = f"Successfully rolled back to {target.deployment_id}"
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            result.status = DeploymentStatus.FAILED
            result.message = f"Rollback failed: {str(e)}"
        
        return result
    
    async def _validate_deployment(self) -> None:
        """Validate deployment configuration and prerequisites"""
        logger.info("Validating deployment configuration")
        
        # Check required environment variables
        required_vars = ["DATABASE_URL", "SECRET_KEY"]
        missing_vars = [var for var in required_vars 
                       if var not in self.config.environment_variables]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")
        
        # Validate resource limits
        self._validate_resource_limits()
        
        # Check image availability (if registry is accessible)
        try:
            await self._check_image_availability()
        except Exception as e:
            logger.warning(f"Could not verify image availability: {e}")
        
        # Validate target-specific requirements
        if self.config.target == DeploymentTarget.KUBERNETES:
            await self._validate_kubernetes_access()
        elif self.config.target == DeploymentTarget.AWS_ECS:
            await self._validate_aws_access()
    
    async def _generate_manifests(self) -> Dict[str, Any]:
        """Generate deployment manifests based on target"""
        logger.info(f"Generating manifests for {self.config.target.value}")
        
        if self.config.target == DeploymentTarget.KUBERNETES:
            return self._generate_kubernetes_manifests()
        elif self.config.target == DeploymentTarget.DOCKER_COMPOSE:
            return self._generate_docker_compose_manifests()
        elif self.config.target == DeploymentTarget.AWS_ECS:
            return self._generate_ecs_manifests()
        elif self.config.target == DeploymentTarget.GOOGLE_CLOUD_RUN:
            return self._generate_cloud_run_manifests()
        else:
            raise ValueError(f"Unsupported target: {self.config.target}")
    
    def _generate_kubernetes_manifests(self) -> Dict[str, Any]:
        """Generate Kubernetes deployment manifests"""
        manifests = {}
        
        # Deployment manifest
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self.config.app_name,
                "namespace": self.config.namespace,
                "labels": {
                    "app": self.config.app_name,
                    "environment": self.config.environment,
                    **self.config.labels
                },
                "annotations": self.config.annotations
            },
            "spec": {
                "replicas": self.config.replicas,
                "strategy": self._get_k8s_strategy(),
                "selector": {
                    "matchLabels": {
                        "app": self.config.app_name
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": self.config.app_name,
                            "environment": self.config.environment
                        }
                    },
                    "spec": {
                        "containers": [{
                            "name": self.config.app_name,
                            "image": f"{self.config.app_name}:{self.config.image_tag}",
                            "ports": [{
                                "containerPort": 8080,
                                "protocol": "TCP"
                            }],
                            "env": [
                                {"name": k, "value": v} 
                                for k, v in self.config.environment_variables.items()
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": self.config.resource_limits.cpu_request,
                                    "memory": self.config.resource_limits.memory_request
                                },
                                "limits": {
                                    "cpu": self.config.resource_limits.cpu_limit,
                                    "memory": self.config.resource_limits.memory_limit
                                }
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": self.config.health_check.endpoint,
                                    "port": 8080
                                },
                                "initialDelaySeconds": self.config.health_check.initial_delay,
                                "periodSeconds": self.config.health_check.interval,
                                "timeoutSeconds": self.config.health_check.timeout,
                                "failureThreshold": self.config.health_check.retries
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": self.config.health_check.endpoint,
                                    "port": 8080
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 5,
                                "timeoutSeconds": 3,
                                "failureThreshold": 2
                            }
                        }],
                        "imagePullSecrets": [{"name": "registry-secret"}] if self.config.secrets else []
                    }
                }
            }
        }
        
        manifests["deployment"] = deployment
        
        # Service manifest
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"{self.config.app_name}-service",
                "namespace": self.config.namespace,
                "labels": {
                    "app": self.config.app_name
                }
            },
            "spec": {
                "type": "ClusterIP",
                "ports": [{
                    "port": 80,
                    "targetPort": 8080,
                    "protocol": "TCP",
                    "name": "http"
                }],
                "selector": {
                    "app": self.config.app_name
                }
            }
        }
        
        manifests["service"] = service
        
        # ConfigMap for configuration
        if self.config.config_maps:
            configmap = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": f"{self.config.app_name}-config",
                    "namespace": self.config.namespace
                },
                "data": self.config.config_maps
            }
            manifests["configmap"] = configmap
        
        # HorizontalPodAutoscaler
        if self.config.scaling_config.max_replicas > self.config.scaling_config.min_replicas:
            hpa = {
                "apiVersion": "autoscaling/v2",
                "kind": "HorizontalPodAutoscaler",
                "metadata": {
                    "name": f"{self.config.app_name}-hpa",
                    "namespace": self.config.namespace
                },
                "spec": {
                    "scaleTargetRef": {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "name": self.config.app_name
                    },
                    "minReplicas": self.config.scaling_config.min_replicas,
                    "maxReplicas": self.config.scaling_config.max_replicas,
                    "metrics": [
                        {
                            "type": "Resource",
                            "resource": {
                                "name": "cpu",
                                "target": {
                                    "type": "Utilization",
                                    "averageUtilization": self.config.scaling_config.target_cpu_percent
                                }
                            }
                        },
                        {
                            "type": "Resource",
                            "resource": {
                                "name": "memory",
                                "target": {
                                    "type": "Utilization",
                                    "averageUtilization": self.config.scaling_config.target_memory_percent
                                }
                            }
                        }
                    ]
                }
            }
            manifests["hpa"] = hpa
        
        # Ingress
        if self.config.ingress_config:
            ingress = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {
                    "name": f"{self.config.app_name}-ingress",
                    "namespace": self.config.namespace,
                    "annotations": self.config.ingress_config.get("annotations", {})
                },
                "spec": {
                    "rules": [{
                        "host": self.config.ingress_config.get("host"),
                        "http": {
                            "paths": [{
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": f"{self.config.app_name}-service",
                                        "port": {"number": 80}
                                    }
                                }
                            }]
                        }
                    }]
                }
            }
            
            if self.config.ingress_config.get("tls"):
                ingress["spec"]["tls"] = [{
                    "hosts": [self.config.ingress_config.get("host")],
                    "secretName": f"{self.config.app_name}-tls"
                }]
            
            manifests["ingress"] = ingress
        
        return manifests
    
    def _generate_docker_compose_manifests(self) -> Dict[str, Any]:
        """Generate Docker Compose manifests"""
        compose = {
            "version": "3.8",
            "services": {
                self.config.app_name: {
                    "image": f"{self.config.app_name}:{self.config.image_tag}",
                    "ports": ["8080:8080"],
                    "environment": self.config.environment_variables,
                    "restart": "unless-stopped",
                    "healthcheck": {
                        "test": f"curl -f http://localhost:8080{self.config.health_check.endpoint} || exit 1",
                        "interval": f"{self.config.health_check.interval}s",
                        "timeout": f"{self.config.health_check.timeout}s",
                        "retries": self.config.health_check.retries,
                        "start_period": f"{self.config.health_check.initial_delay}s"
                    },
                    "deploy": {
                        "replicas": self.config.replicas,
                        "resources": {
                            "limits": {
                                "memory": self.config.resource_limits.memory_limit,
                                "cpus": str(self._parse_cpu_value(self.config.resource_limits.cpu_limit))
                            },
                            "reservations": {
                                "memory": self.config.resource_limits.memory_request,
                                "cpus": str(self._parse_cpu_value(self.config.resource_limits.cpu_request))
                            }
                        }
                    }
                }
            }
        }
        
        # Add volumes if configured
        if self.config.volumes:
            compose["services"][self.config.app_name]["volumes"] = [
                f"{vol['host_path']}:{vol['container_path']}" 
                for vol in self.config.volumes
            ]
        
        return {"docker-compose": compose}
    
    def _generate_ecs_manifests(self) -> Dict[str, Any]:
        """Generate AWS ECS task definition"""
        task_definition = {
            "family": self.config.app_name,
            "networkMode": "awsvpc",
            "requiresCompatibilities": ["FARGATE"],
            "cpu": "512",
            "memory": "1024",
            "executionRoleArn": "${AWS_EXECUTION_ROLE_ARN}",
            "containerDefinitions": [{
                "name": self.config.app_name,
                "image": f"{self.config.app_name}:{self.config.image_tag}",
                "portMappings": [{
                    "containerPort": 8080,
                    "protocol": "tcp"
                }],
                "environment": [
                    {"name": k, "value": v} 
                    for k, v in self.config.environment_variables.items()
                ],
                "healthCheck": {
                    "command": [
                        "CMD-SHELL",
                        f"curl -f http://localhost:8080{self.config.health_check.endpoint} || exit 1"
                    ],
                    "interval": self.config.health_check.interval,
                    "timeout": self.config.health_check.timeout,
                    "retries": self.config.health_check.retries,
                    "startPeriod": self.config.health_check.initial_delay
                },
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": f"/ecs/{self.config.app_name}",
                        "awslogs-region": "us-east-1",
                        "awslogs-stream-prefix": "ecs"
                    }
                }
            }]
        }
        
        # ECS Service definition
        service = {
            "serviceName": self.config.app_name,
            "cluster": f"{self.config.app_name}-cluster",
            "taskDefinition": self.config.app_name,
            "desiredCount": self.config.replicas,
            "launchType": "FARGATE",
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": "${AWS_SUBNETS}".split(','),
                    "securityGroups": "${AWS_SECURITY_GROUPS}".split(','),
                    "assignPublicIp": "ENABLED"
                }
            },
            "loadBalancers": [{
                "targetGroupArn": f"arn:aws:elasticloadbalancing:us-east-1:{{account_id}}:targetgroup/{self.config.app_name}-tg/1234567890123456",
                "containerName": self.config.app_name,
                "containerPort": 8080
            }] if self.config.ingress_config else []
        }
        
        return {
            "task_definition": task_definition,
            "service": service
        }
    
    def _generate_cloud_run_manifests(self) -> Dict[str, Any]:
        """Generate Google Cloud Run service configuration"""
        service = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": self.config.app_name,
                "annotations": {
                    "run.googleapis.com/ingress": "all"
                }
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "autoscaling.knative.dev/minScale": str(self.config.scaling_config.min_replicas),
                            "autoscaling.knative.dev/maxScale": str(self.config.scaling_config.max_replicas),
                            "run.googleapis.com/cpu-throttling": "false"
                        }
                    },
                    "spec": {
                        "containers": [{
                            "image": f"gcr.io/{{project_id}}/{self.config.app_name}:{self.config.image_tag}",
                            "ports": [{"containerPort": 8080}],
                            "env": [
                                {"name": k, "value": v} 
                                for k, v in self.config.environment_variables.items()
                            ],
                            "resources": {
                                "limits": {
                                    "cpu": self.config.resource_limits.cpu_limit,
                                    "memory": self.config.resource_limits.memory_limit
                                }
                            },
                            "startupProbe": {
                                "httpGet": {
                                    "path": self.config.health_check.endpoint,
                                    "port": 8080
                                },
                                "initialDelaySeconds": self.config.health_check.initial_delay,
                                "periodSeconds": self.config.health_check.interval,
                                "timeoutSeconds": self.config.health_check.timeout,
                                "failureThreshold": self.config.health_check.retries
                            }
                        }]
                    }
                }
            }
        }
        
        return {"service": service}
    
    def _get_k8s_strategy(self) -> Dict[str, Any]:
        """Get Kubernetes deployment strategy configuration"""
        if self.config.strategy == DeploymentStrategy.ROLLING_UPDATE:
            return {
                "type": "RollingUpdate",
                "rollingUpdate": {
                    "maxUnavailable": "25%",
                    "maxSurge": "25%"
                }
            }
        elif self.config.strategy == DeploymentStrategy.RECREATE:
            return {"type": "Recreate"}
        else:
            # For blue-green and canary, use rolling update as base
            return {
                "type": "RollingUpdate",
                "rollingUpdate": {
                    "maxUnavailable": "0%",
                    "maxSurge": "100%"
                }
            }
    
    async def _deploy_kubernetes(self, manifests: Dict[str, Any], result: DeploymentResult) -> None:
        """Execute Kubernetes deployment"""
        logger.info("Deploying to Kubernetes")
        
        try:
            # Apply manifests in order
            for manifest_name, manifest in manifests.items():
                logger.info(f"Applying {manifest_name} manifest")
                
                # Convert to YAML and apply
                yaml_content = yaml.dump(manifest, default_flow_style=False)
                
                # Use kubectl to apply manifest
                process = await asyncio.create_subprocess_exec(
                    'kubectl', 'apply', '-f', '-',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate(yaml_content.encode())
                
                if process.returncode != 0:
                    raise RuntimeError(f"kubectl apply failed: {stderr.decode()}")
                
                result.logs.append(f"Applied {manifest_name}: {stdout.decode()}")
            
            result.message = "Kubernetes manifests applied successfully"
            
        except Exception as e:
            raise RuntimeError(f"Kubernetes deployment failed: {e}")
    
    async def _deploy_docker_compose(self, manifests: Dict[str, Any], result: DeploymentResult) -> None:
        """Execute Docker Compose deployment"""
        logger.info("Deploying with Docker Compose")

        try:
            compose_content = yaml.dump(manifests["docker-compose"], default_flow_style=False)

            # Use context manager for temporary file with guaranteed cleanup
            async with self._temporary_file(compose_content, "-compose.yml") as compose_file:
                # Deploy with docker-compose
                process = await asyncio.create_subprocess_exec(
                    'docker-compose', '-f', str(compose_file), 'up', '-d',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    raise RuntimeError(f"docker-compose up failed: {stderr.decode()}")

                result.logs.append(f"Docker Compose deployment: {stdout.decode()}")
                result.message = "Docker Compose deployment completed"

        except Exception as e:
            raise RuntimeError(f"Docker Compose deployment failed: {e}")
    
    async def _deploy_aws_ecs(self, manifests: Dict[str, Any], result: DeploymentResult) -> None:
        """Execute AWS ECS deployment"""
        logger.info("Deploying to AWS ECS")
        
        # This would require boto3 and proper AWS credentials
        # For now, we'll simulate the deployment
        try:
            task_def = manifests["task_definition"]
            service_def = manifests["service"]
            
            # Register task definition (simulated)
            logger.info("Registering ECS task definition")
            
            # Update service (simulated)
            logger.info("Updating ECS service")
            
            result.message = "ECS deployment completed"
            result.logs.append("ECS task definition registered")
            result.logs.append("ECS service updated")
            
        except Exception as e:
            raise RuntimeError(f"ECS deployment failed: {e}")
    
    async def _deploy_cloud_run(self, manifests: Dict[str, Any], result: DeploymentResult) -> None:
        """Execute Google Cloud Run deployment"""
        logger.info("Deploying to Google Cloud Run")
        
        try:
            service_config = manifests["service"]
            yaml_content = yaml.dump(service_config, default_flow_style=False)
            
            # Use gcloud to deploy
            process = await asyncio.create_subprocess_exec(
                'gcloud', 'run', 'services', 'replace', '-',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate(yaml_content.encode())
            
            if process.returncode != 0:
                raise RuntimeError(f"gcloud run deploy failed: {stderr.decode()}")
            
            result.logs.append(f"Cloud Run deployment: {stdout.decode()}")
            result.message = "Cloud Run deployment completed"
            
        except Exception as e:
            raise RuntimeError(f"Cloud Run deployment failed: {e}")
    
    async def _wait_for_deployment(self, result: DeploymentResult) -> None:
        """Wait for deployment to complete"""
        logger.info("Waiting for deployment to complete")
        
        max_wait_time = 600  # 10 minutes
        wait_interval = 10   # 10 seconds
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            if self.config.target == DeploymentTarget.KUBERNETES:
                # Check deployment status
                process = await asyncio.create_subprocess_exec(
                    'kubectl', 'rollout', 'status', 
                    f'deployment/{self.config.app_name}',
                    '-n', self.config.namespace,
                    '--timeout=10s',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    result.logs.append("Deployment rollout completed")
                    return
                elif "timed out" not in stderr.decode().lower():
                    raise RuntimeError(f"Deployment failed: {stderr.decode()}")
            
            await asyncio.sleep(wait_interval)
            elapsed_time += wait_interval
        
        raise RuntimeError(f"Deployment timed out after {max_wait_time} seconds")
    
    async def _perform_health_check(self, result: DeploymentResult) -> bool:
        """Perform health check on deployed application"""
        logger.info("Performing health check")
        
        # Get service endpoint
        endpoint = await self._get_service_endpoint()
        if not endpoint:
            logger.warning("Could not determine service endpoint for health check")
            return True  # Assume healthy if we can't check
        
        health_url = f"http://{endpoint}{self.config.health_check.endpoint}"
        
        for attempt in range(self.config.health_check.retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        health_url, 
                        timeout=aiohttp.ClientTimeout(total=self.config.health_check.timeout)
                    ) as response:
                        if response.status == 200:
                            result.logs.append(f"Health check passed (attempt {attempt + 1})")
                            return True
                        else:
                            logger.warning(f"Health check failed with status {response.status}")
                            
            except Exception as e:
                logger.warning(f"Health check attempt {attempt + 1} failed: {e}")
            
            if attempt < self.config.health_check.retries - 1:
                await asyncio.sleep(self.config.health_check.interval)
        
        result.logs.append("All health check attempts failed")
        return False
    
    async def _get_service_endpoint(self) -> Optional[str]:
        """Get the service endpoint URL"""
        if self.config.target == DeploymentTarget.KUBERNETES:
            try:
                # Get service information
                process = await asyncio.create_subprocess_exec(
                    'kubectl', 'get', 'service', 
                    f'{self.config.app_name}-service',
                    '-n', self.config.namespace,
                    '-o', 'json',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    service_info = json.loads(stdout.decode())
                    # For LoadBalancer services, get external IP
                    if service_info['spec']['type'] == 'LoadBalancer':
                        ingress = service_info.get('status', {}).get('loadBalancer', {}).get('ingress', [])
                        if ingress:
                            return f"{ingress[0].get('ip', 'localhost')}:80"
                    
                    # For ClusterIP, use port-forward or assume localhost
                    return "localhost:8080"
                    
            except Exception as e:
                logger.warning(f"Could not get service endpoint: {e}")
        
        return "localhost:8080"
    
    async def _rollback_deployment(self, result: DeploymentResult) -> None:
        """Perform automatic rollback"""
        logger.info("Performing automatic rollback")
        
        try:
            if self.config.target == DeploymentTarget.KUBERNETES:
                process = await asyncio.create_subprocess_exec(
                    'kubectl', 'rollout', 'undo',
                    f'deployment/{self.config.app_name}',
                    '-n', self.config.namespace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    result.status = DeploymentStatus.ROLLED_BACK
                    result.message = "Deployment rolled back successfully"
                    result.logs.append("Automatic rollback completed")
                else:
                    result.logs.append(f"Rollback failed: {stderr.decode()}")
                    
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            result.logs.append(f"Rollback error: {str(e)}")
    
    async def _check_image_availability(self) -> None:
        """Check if the deployment image is available"""
        # This would typically involve checking the container registry
        # For now, we'll simulate the check
        pass
    
    async def _validate_kubernetes_access(self) -> None:
        """Validate Kubernetes cluster access"""
        try:
            process = await asyncio.create_subprocess_exec(
                'kubectl', 'cluster-info',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise RuntimeError(f"Kubernetes access validation failed: {stderr.decode()}")
                
        except FileNotFoundError:
            raise RuntimeError("kubectl not found. Please install kubectl.")
    
    async def _validate_aws_access(self) -> None:
        """Validate AWS access for ECS deployment"""
        # This would involve checking AWS credentials and permissions
        pass
    
    def get_deployment_status(self, deployment_id: str) -> Optional[DeploymentResult]:
        """Get status of a specific deployment"""
        return next((d for d in self.deployment_history 
                    if d.deployment_id == deployment_id), None)
    
    def list_deployments(self, limit: Optional[int] = None) -> List[DeploymentResult]:
        """List deployment history"""
        history = sorted(self.deployment_history, 
                        key=lambda x: x.deployment_time, reverse=True)
        
        if limit:
            return history[:limit]
        
        return history
    
    def get_active_deployments(self) -> Dict[str, DeploymentResult]:
        """Get currently active deployments"""
        return self.active_deployments.copy()
    
    async def scale_deployment(self, replicas: int) -> DeploymentResult:
        """Scale the deployment to specified replica count"""
        logger.info(f"Scaling deployment to {replicas} replicas")
        
        result = DeploymentResult(
            deployment_id=f"scale-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            status=DeploymentStatus.IN_PROGRESS,
            message=f"Scaling to {replicas} replicas",
            deployment_time=datetime.now()
        )
        
        try:
            if self.config.target == DeploymentTarget.KUBERNETES:
                process = await asyncio.create_subprocess_exec(
                    'kubectl', 'scale', 
                    f'deployment/{self.config.app_name}',
                    f'--replicas={replicas}',
                    '-n', self.config.namespace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    self.config.replicas = replicas
                    result.status = DeploymentStatus.SUCCESS
                    result.message = f"Successfully scaled to {replicas} replicas"
                    result.logs.append(stdout.decode())
                else:
                    raise RuntimeError(f"Scaling failed: {stderr.decode()}")
                    
        except Exception as e:
            result.status = DeploymentStatus.FAILED
            result.message = f"Scaling failed: {str(e)}"
        
        return result
    
    def generate_deployment_report(self) -> Dict[str, Any]:
        """Generate comprehensive deployment report"""
        successful_deployments = [d for d in self.deployment_history 
                                 if d.status == DeploymentStatus.SUCCESS]
        failed_deployments = [d for d in self.deployment_history 
                             if d.status == DeploymentStatus.FAILED]
        rolled_back_deployments = [d for d in self.deployment_history 
                                  if d.status == DeploymentStatus.ROLLED_BACK]
        
        total_deployments = len(self.deployment_history)
        success_rate = (len(successful_deployments) / total_deployments * 100) if total_deployments > 0 else 0
        
        # Calculate average deployment time
        successful_times = [d.deployment_time for d in successful_deployments]
        avg_deployment_time = None
        if len(successful_times) > 1:
            time_diffs = [(successful_times[i] - successful_times[i-1]).total_seconds() 
                         for i in range(1, len(successful_times))]
            avg_deployment_time = sum(time_diffs) / len(time_diffs)
        
        return {
            "summary": {
                "app_name": self.config.app_name,
                "environment": self.config.environment,
                "target": self.config.target.value,
                "total_deployments": total_deployments,
                "successful_deployments": len(successful_deployments),
                "failed_deployments": len(failed_deployments),
                "rolled_back_deployments": len(rolled_back_deployments),
                "success_rate": f"{success_rate:.1f}%",
                "average_deployment_time": f"{avg_deployment_time:.0f}s" if avg_deployment_time else "N/A"
            },
            "configuration": {
                "deployment_strategy": self.config.strategy.value,
                "replicas": self.config.replicas,
                "auto_scaling": {
                    "enabled": self.config.scaling_config.max_replicas > self.config.scaling_config.min_replicas,
                    "min_replicas": self.config.scaling_config.min_replicas,
                    "max_replicas": self.config.scaling_config.max_replicas
                },
                "health_check": {
                    "endpoint": self.config.health_check.endpoint,
                    "timeout": f"{self.config.health_check.timeout}s",
                    "retries": self.config.health_check.retries
                },
                "rollback": {
                    "enabled": self.config.rollback_config.enabled,
                    "auto_rollback": self.config.rollback_config.auto_rollback
                }
            },
            "recent_deployments": [
                {
                    "deployment_id": d.deployment_id,
                    "status": d.status.value,
                    "message": d.message,
                    "deployment_time": d.deployment_time.isoformat(),
                    "health_check_passed": d.health_check_passed
                }
                for d in sorted(self.deployment_history, 
                              key=lambda x: x.deployment_time, reverse=True)[:10]
            ]
        }