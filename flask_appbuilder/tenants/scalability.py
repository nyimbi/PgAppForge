"""
Multi-Tenant Scalability and Distribution Module.

This module provides horizontal scaling, load distribution, and infrastructure
management for large-scale multi-tenant SaaS applications.
"""

import logging
import threading
import hashlib
import random
import time
from functools import wraps
from typing import Dict, Optional, Any, List, Callable, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict
import json

from flask import current_app, g, request
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
import redis
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

log = logging.getLogger(__name__)


class DistributionStrategy(Enum):
    """Strategies for distributing tenants across infrastructure."""
    ROUND_ROBIN = "round_robin"
    HASH_BASED = "hash_based"
    LOAD_BASED = "load_based"
    GEOGRAPHIC = "geographic"
    CUSTOM = "custom"


class ScalingTrigger(Enum):
    """Triggers for automatic scaling decisions."""
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    TENANT_COUNT = "tenant_count"
    REQUEST_RATE = "request_rate"
    RESPONSE_TIME = "response_time"
    ERROR_RATE = "error_rate"


@dataclass
class ApplicationInstance:
    """Represents an application instance in the cluster."""
    instance_id: str
    host: str
    port: int
    region: str
    availability_zone: str
    status: str  # active, maintenance, draining, inactive
    tenant_count: int
    cpu_usage: float
    memory_usage: float
    last_heartbeat: datetime
    max_tenants: int
    assigned_tenants: List[int]


@dataclass
class ScalingMetric:
    """Scaling decision metric."""
    metric_type: ScalingTrigger
    current_value: float
    threshold_value: float
    scale_up_threshold: float
    scale_down_threshold: float
    is_critical: bool


class TenantDistributionManager:
    """Manages distribution of tenants across application instances."""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self._instances = {}  # instance_id -> ApplicationInstance
        self._tenant_assignments = {}  # tenant_id -> instance_id
        self._distribution_strategy = DistributionStrategy.HASH_BASED
        self._lock = threading.RLock()
        
        # Load balancing weights
        self._instance_weights = defaultdict(lambda: 1.0)
        
        # Health checking
        self._health_check_interval = 30  # seconds
        self._start_health_monitoring()
    
    def register_instance(self, instance: ApplicationInstance):
        """Register a new application instance."""
        with self._lock:
            self._instances[instance.instance_id] = instance
            log.info(f"Registered application instance: {instance.instance_id} "
                    f"at {instance.host}:{instance.port}")
            
            # Store in Redis for cluster coordination
            if self.redis_client:
                try:
                    instance_data = {
                        'instance_id': instance.instance_id,
                        'host': instance.host,
                        'port': instance.port,
                        'region': instance.region,
                        'availability_zone': instance.availability_zone,
                        'status': instance.status,
                        'max_tenants': instance.max_tenants,
                        'registered_at': datetime.now(tz=timezone.utc).isoformat()
                    }
                    self.redis_client.hset(
                        'cluster_instances', 
                        instance.instance_id, 
                        json.dumps(instance_data)
                    )
                    self.redis_client.expire('cluster_instances', 300)  # 5 minute TTL
                except Exception as e:
                    log.debug(f"Redis instance registration error: {e}")
    
    def assign_tenant_to_instance(self, tenant_id: int, 
                                 preferred_region: str = None) -> Optional[str]:
        """Assign a tenant to an optimal application instance."""
        with self._lock:
            if not self._instances:
                log.error("No application instances available for tenant assignment")
                return None
            
            # Check if tenant is already assigned
            if tenant_id in self._tenant_assignments:
                assigned_instance = self._tenant_assignments[tenant_id]
                if (assigned_instance in self._instances and 
                    self._instances[assigned_instance].status == 'active'):
                    return assigned_instance
                else:
                    # Reassign if previous instance is unavailable
                    del self._tenant_assignments[tenant_id]
            
            # Find best instance based on strategy
            target_instance = self._select_instance_for_tenant(tenant_id, preferred_region)
            
            if target_instance:
                self._tenant_assignments[tenant_id] = target_instance.instance_id
                target_instance.assigned_tenants.append(tenant_id)
                target_instance.tenant_count += 1
                
                log.info(f"Assigned tenant {tenant_id} to instance {target_instance.instance_id}")
                
                # Store assignment in Redis
                if self.redis_client:
                    try:
                        assignment_data = {
                            'tenant_id': tenant_id,
                            'instance_id': target_instance.instance_id,
                            'assigned_at': datetime.now(tz=timezone.utc).isoformat(),
                            'region': target_instance.region
                        }
                        self.redis_client.hset(
                            'tenant_assignments',
                            str(tenant_id),
                            json.dumps(assignment_data)
                        )
                    except Exception as e:
                        log.debug(f"Redis assignment storage error: {e}")
                
                return target_instance.instance_id
            
            return None
    
    def get_tenant_instance(self, tenant_id: int) -> Optional[ApplicationInstance]:
        """Get the application instance assigned to a tenant."""
        with self._lock:
            instance_id = self._tenant_assignments.get(tenant_id)
            if instance_id and instance_id in self._instances:
                return self._instances[instance_id]
            return None
    
    def rebalance_tenants(self):
        """Rebalance tenant assignments across instances."""
        log.info("Starting tenant rebalancing...")
        
        with self._lock:
            if len(self._instances) < 2:
                log.info("Not enough instances for rebalancing")
                return
            
            # Calculate current load distribution
            instance_loads = {}
            for instance_id, instance in self._instances.items():
                if instance.status == 'active':
                    load_score = self._calculate_instance_load(instance)
                    instance_loads[instance_id] = load_score
            
            if not instance_loads:
                log.warning("No active instances available for rebalancing")
                return
            
            # Find overloaded and underloaded instances
            avg_load = sum(instance_loads.values()) / len(instance_loads)
            overloaded = {k: v for k, v in instance_loads.items() if v > avg_load * 1.2}
            underloaded = {k: v for k, v in instance_loads.items() if v < avg_load * 0.8}
            
            # Move tenants from overloaded to underloaded instances
            tenants_moved = 0
            for overloaded_id in overloaded:
                overloaded_instance = self._instances[overloaded_id]
                tenants_to_move = overloaded_instance.assigned_tenants[:5]  # Move up to 5 tenants
                
                for tenant_id in tenants_to_move:
                    # Find best underloaded instance
                    best_instance = min(underloaded.keys(), 
                                      key=lambda x: instance_loads[x],
                                      default=None)
                    
                    if best_instance and best_instance != overloaded_id:
                        # Perform the move
                        self._move_tenant(tenant_id, overloaded_id, best_instance)
                        tenants_moved += 1
                        
                        # Update load scores
                        instance_loads[overloaded_id] -= 0.1
                        instance_loads[best_instance] += 0.1
            
            log.info(f"Rebalancing completed: moved {tenants_moved} tenants")
    
    def remove_instance(self, instance_id: str, drain_tenants: bool = True):
        """Remove an instance from the cluster."""
        with self._lock:
            if instance_id not in self._instances:
                log.warning(f"Instance {instance_id} not found for removal")
                return
            
            instance = self._instances[instance_id]
            
            if drain_tenants and instance.assigned_tenants:
                log.info(f"Draining {len(instance.assigned_tenants)} tenants from {instance_id}")
                
                # Reassign tenants to other instances
                for tenant_id in instance.assigned_tenants.copy():
                    self._reassign_tenant_from_instance(tenant_id, instance_id)
            
            # Remove instance
            del self._instances[instance_id]
            
            # Remove from Redis
            if self.redis_client:
                try:
                    self.redis_client.hdel('cluster_instances', instance_id)
                except Exception as e:
                    log.debug(f"Redis instance removal error: {e}")
            
            log.info(f"Removed instance {instance_id} from cluster")
    
    def _select_instance_for_tenant(self, tenant_id: int, 
                                   preferred_region: str = None) -> Optional[ApplicationInstance]:
        """Select the best instance for a tenant based on distribution strategy."""
        active_instances = [i for i in self._instances.values() if i.status == 'active']
        
        if not active_instances:
            return None
        
        if self._distribution_strategy == DistributionStrategy.HASH_BASED:
            # Consistent hashing based on tenant ID
            tenant_hash = int(hashlib.md5(str(tenant_id).encode()).hexdigest(), 16)
            selected_index = tenant_hash % len(active_instances)
            return active_instances[selected_index]
        
        elif self._distribution_strategy == DistributionStrategy.LOAD_BASED:
            # Select instance with lowest load
            return min(active_instances, key=self._calculate_instance_load)
        
        elif self._distribution_strategy == DistributionStrategy.GEOGRAPHIC:
            # Prefer instances in the same region
            if preferred_region:
                region_instances = [i for i in active_instances if i.region == preferred_region]
                if region_instances:
                    return min(region_instances, key=self._calculate_instance_load)
            
            # Fall back to load-based selection
            return min(active_instances, key=self._calculate_instance_load)
        
        elif self._distribution_strategy == DistributionStrategy.ROUND_ROBIN:
            # Simple round-robin selection
            if not hasattr(self, '_round_robin_index'):
                self._round_robin_index = 0
            
            selected_instance = active_instances[self._round_robin_index % len(active_instances)]
            self._round_robin_index += 1
            return selected_instance
        
        else:
            # Default to load-based
            return min(active_instances, key=self._calculate_instance_load)
    
    def _calculate_instance_load(self, instance: ApplicationInstance) -> float:
        """Calculate a load score for an instance."""
        # Combine multiple factors into a load score
        tenant_load = instance.tenant_count / max(instance.max_tenants, 1)
        cpu_load = instance.cpu_usage / 100.0
        memory_load = instance.memory_usage / 100.0
        
        # Weight the factors
        load_score = (tenant_load * 0.4 + cpu_load * 0.3 + memory_load * 0.3)
        
        return load_score
    
    def _move_tenant(self, tenant_id: int, from_instance_id: str, to_instance_id: str):
        """Move a tenant from one instance to another."""
        if (from_instance_id not in self._instances or 
            to_instance_id not in self._instances):
            return
        
        from_instance = self._instances[from_instance_id]
        to_instance = self._instances[to_instance_id]
        
        # Update assignments
        if tenant_id in from_instance.assigned_tenants:
            from_instance.assigned_tenants.remove(tenant_id)
            from_instance.tenant_count -= 1
        
        to_instance.assigned_tenants.append(tenant_id)
        to_instance.tenant_count += 1
        
        self._tenant_assignments[tenant_id] = to_instance_id
        
        log.info(f"Moved tenant {tenant_id} from {from_instance_id} to {to_instance_id}")
    
    def _reassign_tenant_from_instance(self, tenant_id: int, instance_id: str):
        """Reassign a tenant from a specific instance to another."""
        if tenant_id in self._tenant_assignments:
            del self._tenant_assignments[tenant_id]
        
        # Find new instance
        new_instance_id = self.assign_tenant_to_instance(tenant_id)
        if new_instance_id:
            log.info(f"Reassigned tenant {tenant_id} from {instance_id} to {new_instance_id}")
        else:
            log.error(f"Failed to reassign tenant {tenant_id} from {instance_id}")
    
    def _start_health_monitoring(self):
        """Start health monitoring thread."""
        def health_check_loop():
            while True:
                try:
                    self._perform_health_checks()
                    time.sleep(self._health_check_interval)
                except Exception as e:
                    log.error(f"Health check error: {e}")
                    time.sleep(60)  # Wait longer on error
        
        health_thread = threading.Thread(target=health_check_loop, daemon=True)
        health_thread.start()
        log.info("Started instance health monitoring")
    
    def _perform_health_checks(self):
        """Perform health checks on all instances."""
        current_time = datetime.now(tz=timezone.utc)
        unhealthy_instances = []
        
        with self._lock:
            for instance_id, instance in self._instances.items():
                # Check if instance has sent heartbeat recently
                time_since_heartbeat = current_time - instance.last_heartbeat
                
                if time_since_heartbeat.total_seconds() > 120:  # 2 minutes
                    log.warning(f"Instance {instance_id} appears unhealthy "
                               f"(no heartbeat for {time_since_heartbeat.total_seconds()}s)")
                    unhealthy_instances.append(instance_id)
        
        # Mark unhealthy instances as inactive
        for instance_id in unhealthy_instances:
            if self._instances[instance_id].status == 'active':
                self._instances[instance_id].status = 'inactive'
                log.warning(f"Marked instance {instance_id} as inactive due to health check failure")


class DatabaseScalingManager:
    """Manages database scaling and read replica distribution."""
    
    def __init__(self):
        self._read_replicas = {}  # replica_id -> connection_info
        self._write_master = None
        self._replica_weights = defaultdict(lambda: 1.0)
        self._connection_pools = {}
        self._lock = threading.RLock()
    
    def add_read_replica(self, replica_id: str, connection_string: str, 
                        region: str = None, weight: float = 1.0):
        """Add a read replica to the pool."""
        try:
            # Test connection
            engine = create_engine(
                connection_string,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True
            )
            
            # Test connectivity
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            with self._lock:
                self._read_replicas[replica_id] = {
                    'connection_string': connection_string,
                    'engine': engine,
                    'region': region,
                    'weight': weight,
                    'status': 'active',
                    'last_check': datetime.now(tz=timezone.utc)
                }
                
                self._replica_weights[replica_id] = weight
            
            log.info(f"Added read replica {replica_id} in region {region}")
            
        except Exception as e:
            log.error(f"Failed to add read replica {replica_id}: {e}")
    
    def get_read_connection(self, preferred_region: str = None):
        """Get a read connection, preferring specified region."""
        with self._lock:
            active_replicas = {
                k: v for k, v in self._read_replicas.items() 
                if v['status'] == 'active'
            }
            
            if not active_replicas:
                log.warning("No active read replicas available")
                return None
            
            # Prefer same region if specified
            if preferred_region:
                region_replicas = {
                    k: v for k, v in active_replicas.items()
                    if v['region'] == preferred_region
                }
                if region_replicas:
                    active_replicas = region_replicas
            
            # Weighted random selection
            replica_ids = list(active_replicas.keys())
            weights = [self._replica_weights[rid] for rid in replica_ids]
            
            if not replica_ids:
                return None
            
            # Simple weighted selection
            total_weight = sum(weights)
            if total_weight <= 0:
                selected_replica = random.choice(replica_ids)
            else:
                r = random.uniform(0, total_weight)
                cumulative_weight = 0
                selected_replica = replica_ids[0]
                
                for i, weight in enumerate(weights):
                    cumulative_weight += weight
                    if r <= cumulative_weight:
                        selected_replica = replica_ids[i]
                        break
            
            return active_replicas[selected_replica]['engine']
    
    def set_write_master(self, connection_string: str):
        """Set the master database for write operations."""
        try:
            engine = create_engine(
                connection_string,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True
            )
            
            # Test connectivity
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self._write_master = engine
            log.info("Set write master database connection")
            
        except Exception as e:
            log.error(f"Failed to set write master: {e}")
    
    def get_write_connection(self):
        """Get a write connection to the master database."""
        return self._write_master
    
    def check_replica_health(self):
        """Check health of all read replicas."""
        current_time = datetime.now(tz=timezone.utc)
        
        with self._lock:
            for replica_id, replica_info in self._read_replicas.items():
                try:
                    # Test connection
                    with replica_info['engine'].connect() as conn:
                        conn.execute(text("SELECT 1"))
                    
                    # Update status
                    replica_info['status'] = 'active'
                    replica_info['last_check'] = current_time
                    
                except Exception as e:
                    log.warning(f"Read replica {replica_id} health check failed: {e}")
                    replica_info['status'] = 'inactive'


class CDNAssetManager:
    """Manages tenant assets distribution via CDN."""
    
    def __init__(self, s3_bucket: str = None, cloudfront_domain: str = None):
        self.s3_bucket = s3_bucket
        self.cloudfront_domain = cloudfront_domain
        self._s3_client = None
        self._cloudfront_client = None
        
        # Initialize AWS clients if credentials are available
        try:
            if s3_bucket:
                self._s3_client = boto3.client('s3')
                self._cloudfront_client = boto3.client('cloudfront')
                log.info(f"Initialized CDN asset manager with bucket: {s3_bucket}")
        except (NoCredentialsError, Exception) as e:
            log.warning(f"AWS credentials not available for CDN: {e}")
    
    def upload_tenant_asset(self, tenant_id: int, asset_path: str, 
                           content: bytes, content_type: str = None) -> Optional[str]:
        """Upload a tenant asset to CDN storage."""
        if not self._s3_client or not self.s3_bucket:
            log.warning("S3 client not configured for asset upload")
            return None
        
        try:
            # Generate S3 key
            s3_key = f"tenant-assets/{tenant_id}/{asset_path}"
            
            # Upload to S3
            upload_params = {
                'Bucket': self.s3_bucket,
                'Key': s3_key,
                'Body': content,
                'ACL': 'public-read'
            }
            
            if content_type:
                upload_params['ContentType'] = content_type
            
            self._s3_client.put_object(**upload_params)
            
            # Return CDN URL
            if self.cloudfront_domain:
                asset_url = f"https://{self.cloudfront_domain}/{s3_key}"
            else:
                asset_url = f"https://{self.s3_bucket}.s3.amazonaws.com/{s3_key}"
            
            log.info(f"Uploaded tenant {tenant_id} asset: {asset_path}")
            return asset_url
            
        except ClientError as e:
            log.error(f"Failed to upload tenant asset: {e}")
            return None
    
    def invalidate_tenant_cache(self, tenant_id: int, asset_paths: List[str] = None):
        """Invalidate CDN cache for tenant assets."""
        if not self._cloudfront_client or not self.cloudfront_domain:
            return
        
        try:
            # Build invalidation paths
            if asset_paths:
                paths = [f"/tenant-assets/{tenant_id}/{path}" for path in asset_paths]
            else:
                paths = [f"/tenant-assets/{tenant_id}/*"]
            
            # Create CloudFront invalidation
            response = self._cloudfront_client.create_invalidation(
                DistributionId=self._get_distribution_id(),
                InvalidationBatch={
                    'Paths': {
                        'Quantity': len(paths),
                        'Items': paths
                    },
                    'CallerReference': f"tenant-{tenant_id}-{int(time.time())}"
                }
            )
            
            log.info(f"Created CDN invalidation for tenant {tenant_id}: {response['Invalidation']['Id']}")
            
        except Exception as e:
            log.error(f"Failed to invalidate CDN cache for tenant {tenant_id}: {e}")
    
    def _get_distribution_id(self) -> str:
        """Get CloudFront distribution ID for the domain."""
        # This would be configured or looked up
        # For now, we'll assume it's stored in app config
        if current_app:
            return current_app.config.get('CLOUDFRONT_DISTRIBUTION_ID', '')
        return ''


class AutoScalingManager:
    """Manages automatic scaling decisions and actions."""
    
    def __init__(self, distribution_manager: TenantDistributionManager):
        self.distribution_manager = distribution_manager
        self._scaling_metrics = {}
        self._scaling_rules = []
        self._lock = threading.RLock()
        
        # Start monitoring thread
        self._monitoring_active = True
        self._start_scaling_monitor()
    
    def add_scaling_rule(self, trigger: ScalingTrigger, scale_up_threshold: float,
                        scale_down_threshold: float, cooldown_seconds: int = 300):
        """Add an auto-scaling rule."""
        rule = {
            'trigger': trigger,
            'scale_up_threshold': scale_up_threshold,
            'scale_down_threshold': scale_down_threshold,
            'cooldown_seconds': cooldown_seconds,
            'last_action': None
        }
        
        with self._lock:
            self._scaling_rules.append(rule)
        
        log.info(f"Added auto-scaling rule for {trigger.value}: "
                f"up>{scale_up_threshold}, down<{scale_down_threshold}")
    
    def _start_scaling_monitor(self):
        """Start the auto-scaling monitoring thread."""
        def scaling_loop():
            while self._monitoring_active:
                try:
                    self._check_scaling_conditions()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    log.error(f"Auto-scaling check error: {e}")
                    time.sleep(120)  # Wait longer on error
        
        scaling_thread = threading.Thread(target=scaling_loop, daemon=True)
        scaling_thread.start()
        log.info("Started auto-scaling monitor")
    
    def _check_scaling_conditions(self):
        """Check if scaling actions should be triggered."""
        current_time = datetime.now(tz=timezone.utc)
        
        # Collect current metrics
        metrics = self._collect_scaling_metrics()
        
        with self._lock:
            for rule in self._scaling_rules:
                # Check cooldown period
                if (rule['last_action'] and 
                    (current_time - rule['last_action']).total_seconds() < rule['cooldown_seconds']):
                    continue
                
                metric_value = metrics.get(rule['trigger'], 0)
                
                if metric_value > rule['scale_up_threshold']:
                    self._trigger_scale_up(rule['trigger'], metric_value)
                    rule['last_action'] = current_time
                elif metric_value < rule['scale_down_threshold']:
                    self._trigger_scale_down(rule['trigger'], metric_value)
                    rule['last_action'] = current_time
    
    def _collect_scaling_metrics(self) -> Dict[ScalingTrigger, float]:
        """Collect current scaling metrics."""
        metrics = {}
        
        # Get instance metrics
        instances = list(self.distribution_manager._instances.values())
        if instances:
            # Average CPU usage across instances
            avg_cpu = sum(i.cpu_usage for i in instances) / len(instances)
            metrics[ScalingTrigger.CPU_USAGE] = avg_cpu
            
            # Average memory usage
            avg_memory = sum(i.memory_usage for i in instances) / len(instances)
            metrics[ScalingTrigger.MEMORY_USAGE] = avg_memory
            
            # Total tenant count
            total_tenants = sum(i.tenant_count for i in instances)
            metrics[ScalingTrigger.TENANT_COUNT] = total_tenants
        
        return metrics
    
    def _trigger_scale_up(self, trigger: ScalingTrigger, metric_value: float):
        """Trigger scale-up actions."""
        log.info(f"Triggering scale-up due to {trigger.value}: {metric_value}")
        
        # This would integrate with container orchestration or cloud auto-scaling
        # For now, we just log the action
        # In production, this would:
        # 1. Launch new application instances
        # 2. Register them with the distribution manager
        # 3. Trigger tenant rebalancing
        
        if current_app and hasattr(current_app, 'extensions'):
            scaling_event = {
                'action': 'scale_up',
                'trigger': trigger.value,
                'metric_value': metric_value,
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'instance_count': len(self.distribution_manager._instances)
            }
            
            # Store scaling event for monitoring
            extensions = current_app.extensions
            if 'scaling_events' not in extensions:
                extensions['scaling_events'] = []
            
            extensions['scaling_events'].append(scaling_event)
            
            # Keep only recent events
            if len(extensions['scaling_events']) > 1000:
                extensions['scaling_events'] = extensions['scaling_events'][-500:]
    
    def _trigger_scale_down(self, trigger: ScalingTrigger, metric_value: float):
        """Trigger scale-down actions."""
        log.info(f"Triggering scale-down due to {trigger.value}: {metric_value}")
        
        # Scale down only if we have more than minimum instances
        if len(self.distribution_manager._instances) <= 1:
            log.info("Cannot scale down: minimum instance count reached")
            return
        
        # Find least loaded instance for removal
        instances = [i for i in self.distribution_manager._instances.values() if i.status == 'active']
        if instances:
            least_loaded = min(instances, key=self.distribution_manager._calculate_instance_load)
            
            # Drain and remove instance
            log.info(f"Scaling down by removing instance: {least_loaded.instance_id}")
            self.distribution_manager.remove_instance(least_loaded.instance_id, drain_tenants=True)


# Global instances
_distribution_manager = None
_db_scaling_manager = None
_cdn_manager = None
_autoscaling_manager = None
_scalability_lock = threading.Lock()


def get_distribution_manager() -> TenantDistributionManager:
    """Get global tenant distribution manager."""
    global _distribution_manager
    if _distribution_manager is None:
        with _scalability_lock:
            if _distribution_manager is None:
                redis_client = None
                if current_app and current_app.config.get('REDIS_URL'):
                    try:
                        redis_client = redis.from_url(current_app.config['REDIS_URL'])
                    except Exception as e:
                        log.warning(f"Failed to connect to Redis for distribution: {e}")
                
                _distribution_manager = TenantDistributionManager(redis_client)
    return _distribution_manager


def get_db_scaling_manager() -> DatabaseScalingManager:
    """Get global database scaling manager."""
    global _db_scaling_manager
    if _db_scaling_manager is None:
        with _scalability_lock:
            if _db_scaling_manager is None:
                _db_scaling_manager = DatabaseScalingManager()
    return _db_scaling_manager


def get_cdn_manager() -> CDNAssetManager:
    """Get global CDN asset manager."""
    global _cdn_manager
    if _cdn_manager is None:
        with _scalability_lock:
            if _cdn_manager is None:
                s3_bucket = None
                cloudfront_domain = None
                
                if current_app:
                    s3_bucket = current_app.config.get('S3_BUCKET_NAME')
                    cloudfront_domain = current_app.config.get('CLOUDFRONT_DOMAIN')
                
                _cdn_manager = CDNAssetManager(s3_bucket, cloudfront_domain)
    return _cdn_manager


def get_autoscaling_manager() -> AutoScalingManager:
    """Get global auto-scaling manager."""
    global _autoscaling_manager
    if _autoscaling_manager is None:
        with _scalability_lock:
            if _autoscaling_manager is None:
                distribution_manager = get_distribution_manager()
                _autoscaling_manager = AutoScalingManager(distribution_manager)
    return _autoscaling_manager


def initialize_scalability_systems(app):
    """Initialize all scalability and distribution systems."""
    log.info("Initializing multi-tenant scalability systems...")
    
    # Initialize global managers
    distribution_manager = get_distribution_manager()
    db_scaling_manager = get_db_scaling_manager()
    cdn_manager = get_cdn_manager()
    autoscaling_manager = get_autoscaling_manager()
    
    # Configure based on app settings
    if app.config.get('ENABLE_AUTO_SCALING', False):
        # Add default scaling rules
        autoscaling_manager.add_scaling_rule(ScalingTrigger.CPU_USAGE, 80.0, 30.0)
        autoscaling_manager.add_scaling_rule(ScalingTrigger.MEMORY_USAGE, 85.0, 40.0)
        autoscaling_manager.add_scaling_rule(ScalingTrigger.TENANT_COUNT, 100, 20)
    
    # Set up database read replicas if configured
    read_replicas = app.config.get('DATABASE_READ_REPLICAS', [])
    for replica_config in read_replicas:
        db_scaling_manager.add_read_replica(
            replica_config['id'],
            replica_config['connection_string'],
            replica_config.get('region'),
            replica_config.get('weight', 1.0)
        )
    
    # Store in app extensions
    app.extensions['tenant_distribution_manager'] = distribution_manager
    app.extensions['db_scaling_manager'] = db_scaling_manager
    app.extensions['cdn_manager'] = cdn_manager
    app.extensions['autoscaling_manager'] = autoscaling_manager
    
    log.info("Multi-tenant scalability systems initialized successfully")