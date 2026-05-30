"""
Process Analytics and Monitoring Dashboard.

Provides comprehensive business intelligence, real-time monitoring,
performance analytics, and bottleneck detection for business processes.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, Counter
import threading

try:
    import pandas as pd
    import numpy as np
    from scipy import stats
    ANALYTICS_AVAILABLE = True
except ImportError:
    pd = None
    np = None
    stats = None
    ANALYTICS_AVAILABLE = False

from flask import current_app
from flask_appbuilder import db
from sqlalchemy import func, and_, or_, desc, asc, text

from ..models.process_models import (
    ProcessInstance, ProcessStep, ProcessDefinition, ProcessMetric,
    ApprovalRequest, SmartTrigger, ProcessInstanceStatus, ProcessStepStatus
)
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)


class ProcessAnalytics:
    """Core analytics engine for process performance and insights."""
    
    def __init__(self):
        self._cache = {}
        self._cache_timeout = 300  # 5 minutes
        self._lock = threading.RLock()
    
    def get_dashboard_metrics(self, time_range: int = 30) -> Dict[str, Any]:
        """Get comprehensive dashboard metrics."""
        cache_key = f"dashboard_metrics_{time_range}_{TenantContext.get_current_tenant_id()}"
        
        with self._lock:
            # Check cache
            if cache_key in self._cache:
                cached_data, timestamp = self._cache[cache_key]
                if (datetime.now(tz=timezone.utc) - timestamp).seconds < self._cache_timeout:
                    return cached_data
            
            try:
                tenant_id = TenantContext.get_current_tenant_id()
                cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=time_range)
                
                # Get base metrics
                metrics = {
                    'overview': self._get_overview_metrics(tenant_id, cutoff_date),
                    'process_performance': self._get_process_performance(tenant_id, cutoff_date),
                    'bottlenecks': self._get_bottleneck_analysis(tenant_id, cutoff_date),
                    'trends': self._get_trend_analysis(tenant_id, cutoff_date),
                    'approvals': self._get_approval_analytics(tenant_id, cutoff_date),
                    'triggers': self._get_trigger_analytics(tenant_id, cutoff_date),
                    'real_time': self._get_real_time_metrics(tenant_id)
                }
                
                # Cache the results
                self._cache[cache_key] = (metrics, datetime.now(tz=timezone.utc))
                return metrics
                
            except Exception as e:
                log.error(f"Error getting dashboard metrics: {str(e)}")
                return {'error': str(e)}
    
    def _get_overview_metrics(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Get overview metrics for the dashboard."""
        try:
            # Total instances
            total_instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).count()
            
            # Status distribution
            status_query = db.session.query(
                ProcessInstance.status,
                func.count(ProcessInstance.id).label('count')
            ).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).group_by(ProcessInstance.status).all()
            
            status_distribution = {status: count for status, count in status_query}
            
            # Success rate
            completed = status_distribution.get(ProcessInstanceStatus.COMPLETED.value, 0)
            failed = status_distribution.get(ProcessInstanceStatus.FAILED.value, 0)
            total_finished = completed + failed
            success_rate = (completed / total_finished * 100) if total_finished > 0 else 0
            
            # Average duration for completed processes
            avg_duration = db.session.query(
                func.avg(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                )
            ).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value,
                ProcessInstance.started_at >= cutoff_date,
                ProcessInstance.completed_at.isnot(None)
            ).scalar()
            
            # Active processes
            active_processes = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == ProcessInstanceStatus.RUNNING.value
            ).count()
            
            return {
                'total_instances': total_instances,
                'active_processes': active_processes,
                'success_rate': round(success_rate, 2),
                'average_duration': round(avg_duration or 0, 2),
                'status_distribution': status_distribution,
                'completed_today': self._get_completed_today(tenant_id),
                'failed_today': self._get_failed_today(tenant_id)
            }
            
        except Exception as e:
            log.error(f"Error getting overview metrics: {str(e)}")
            return {}
    
    def _get_process_performance(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Get detailed process performance metrics."""
        try:
            # Performance by process definition
            performance_query = db.session.query(
                ProcessDefinition.name,
                ProcessDefinition.id,
                func.count(ProcessInstance.id).label('total_instances'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value, 1)], else_=0)).label('completed'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.FAILED.value, 1)], else_=0)).label('failed'),
                func.avg(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                ).label('avg_duration'),
                func.min(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                ).label('min_duration'),
                func.max(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                ).label('max_duration')
            ).join(ProcessDefinition).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).group_by(ProcessDefinition.id, ProcessDefinition.name).all()
            
            performance_data = []
            for row in performance_query:
                total = row.total_instances or 0
                completed = row.completed or 0
                failed = row.failed or 0
                
                performance_data.append({
                    'process_name': row.name,
                    'process_id': row.id,
                    'total_instances': total,
                    'completed': completed,
                    'failed': failed,
                    'running': total - completed - failed,
                    'success_rate': (completed / total * 100) if total > 0 else 0,
                    'avg_duration': round(row.avg_duration or 0, 2),
                    'min_duration': round(row.min_duration or 0, 2),
                    'max_duration': round(row.max_duration or 0, 2)
                })
            
            # Sort by total instances descending
            performance_data.sort(key=lambda x: x['total_instances'], reverse=True)
            
            return {
                'process_performance': performance_data,
                'top_performers': self._get_top_performers(performance_data),
                'underperformers': self._get_underperformers(performance_data)
            }
            
        except Exception as e:
            log.error(f"Error getting process performance: {str(e)}")
            return {}
    
    def _get_bottleneck_analysis(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Analyze process bottlenecks and identify problem areas."""
        try:
            # Step-level bottleneck analysis
            step_performance = db.session.query(
                ProcessStep.node_id,
                ProcessStep.node_type,
                func.count(ProcessStep.id).label('total_steps'),
                func.avg(
                    func.extract('epoch', ProcessStep.completed_at - ProcessStep.started_at)
                ).label('avg_duration'),
                func.sum(func.case([(ProcessStep.status == ProcessStepStatus.FAILED.value, 1)], else_=0)).label('failures'),
                func.avg(ProcessStep.retry_count).label('avg_retries')
            ).join(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date,
                ProcessStep.started_at.isnot(None),
                ProcessStep.completed_at.isnot(None)
            ).group_by(ProcessStep.node_id, ProcessStep.node_type).all()
            
            bottlenecks = []
            for row in step_performance:
                total_steps = row.total_steps or 0
                failures = row.failures or 0
                avg_duration = row.avg_duration or 0
                avg_retries = row.avg_retries or 0
                
                # Calculate bottleneck score
                failure_rate = (failures / total_steps) if total_steps > 0 else 0
                bottleneck_score = (avg_duration / 3600) + (failure_rate * 10) + avg_retries
                
                bottlenecks.append({
                    'node_id': row.node_id,
                    'node_type': row.node_type,
                    'total_executions': total_steps,
                    'avg_duration': round(avg_duration, 2),
                    'failure_rate': round(failure_rate * 100, 2),
                    'avg_retries': round(avg_retries, 2),
                    'bottleneck_score': round(bottleneck_score, 2)
                })
            
            # Sort by bottleneck score descending
            bottlenecks.sort(key=lambda x: x['bottleneck_score'], reverse=True)
            
            # Identify stuck processes
            stuck_processes = self._get_stuck_processes(tenant_id)
            
            return {
                'bottlenecks': bottlenecks[:10],  # Top 10 bottlenecks
                'stuck_processes': stuck_processes,
                'bottleneck_summary': self._summarize_bottlenecks(bottlenecks)
            }
            
        except Exception as e:
            log.error(f"Error getting bottleneck analysis: {str(e)}")
            return {}
    
    def _get_trend_analysis(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Analyze trends in process execution over time."""
        try:
            if not ANALYTICS_AVAILABLE:
                return self._get_basic_trend_analysis(tenant_id, cutoff_date)
            
            # Daily trend analysis
            daily_stats = db.session.query(
                func.date(ProcessInstance.started_at).label('date'),
                func.count(ProcessInstance.id).label('total'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value, 1)], else_=0)).label('completed'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.FAILED.value, 1)], else_=0)).label('failed'),
                func.avg(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                ).label('avg_duration')
            ).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).group_by(func.date(ProcessInstance.started_at)).order_by(func.date(ProcessInstance.started_at)).all()
            
            # Convert to pandas for trend analysis
            if daily_stats:
                df = pd.DataFrame([
                    {
                        'date': row.date,
                        'total': row.total or 0,
                        'completed': row.completed or 0,
                        'failed': row.failed or 0,
                        'success_rate': (row.completed / row.total * 100) if row.total > 0 else 0,
                        'avg_duration': row.avg_duration or 0
                    }
                    for row in daily_stats
                ])
                
                trends = {
                    'daily_stats': df.to_dict('records'),
                    'trends': self._calculate_trends(df)
                }
            else:
                trends = {'daily_stats': [], 'trends': {}}
            
            # Hourly pattern analysis
            hourly_pattern = self._get_hourly_patterns(tenant_id, cutoff_date)
            trends['hourly_patterns'] = hourly_pattern
            
            return trends
            
        except Exception as e:
            log.error(f"Error getting trend analysis: {str(e)}")
            return {}
    
    def _get_basic_trend_analysis(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Basic trend analysis without pandas."""
        try:
            daily_stats = db.session.query(
                func.date(ProcessInstance.started_at).label('date'),
                func.count(ProcessInstance.id).label('total'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value, 1)], else_=0)).label('completed'),
                func.sum(func.case([(ProcessInstance.status == ProcessInstanceStatus.FAILED.value, 1)], else_=0)).label('failed')
            ).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).group_by(func.date(ProcessInstance.started_at)).order_by(func.date(ProcessInstance.started_at)).all()
            
            daily_data = []
            for row in daily_stats:
                total = row.total or 0
                completed = row.completed or 0
                failed = row.failed or 0
                
                daily_data.append({
                    'date': row.date.isoformat() if row.date else None,
                    'total': total,
                    'completed': completed,
                    'failed': failed,
                    'success_rate': (completed / total * 100) if total > 0 else 0
                })
            
            # Simple trend calculation
            trends = {}
            if len(daily_data) >= 2:
                latest = daily_data[-1]
                previous = daily_data[-2]
                
                trends['total_change'] = latest['total'] - previous['total']
                trends['success_rate_change'] = latest['success_rate'] - previous['success_rate']
            
            return {
                'daily_stats': daily_data,
                'trends': trends,
                'hourly_patterns': []
            }
            
        except Exception as e:
            log.error(f"Error getting basic trend analysis: {str(e)}")
            return {}
    
    def _calculate_trends(self, df: 'pd.DataFrame') -> Dict[str, Any]:
        """Calculate trend indicators using pandas."""
        if len(df) < 2:
            return {}
        
        try:
            trends = {}
            
            # Total instances trend
            if 'total' in df.columns:
                total_trend = np.polyfit(range(len(df)), df['total'].values, 1)[0]
                trends['total_trend'] = float(total_trend)
                trends['total_direction'] = 'increasing' if total_trend > 0 else 'decreasing' if total_trend < 0 else 'stable'
            
            # Success rate trend
            if 'success_rate' in df.columns:
                success_trend = np.polyfit(range(len(df)), df['success_rate'].values, 1)[0]
                trends['success_rate_trend'] = float(success_trend)
                trends['success_rate_direction'] = 'improving' if success_trend > 0 else 'declining' if success_trend < 0 else 'stable'
            
            # Duration trend
            if 'avg_duration' in df.columns:
                duration_trend = np.polyfit(range(len(df)), df['avg_duration'].values, 1)[0]
                trends['duration_trend'] = float(duration_trend)
                trends['duration_direction'] = 'increasing' if duration_trend > 0 else 'decreasing' if duration_trend < 0 else 'stable'
            
            # Volatility analysis
            if 'total' in df.columns and len(df) >= 7:
                volatility = df['total'].rolling(window=7).std().iloc[-1]
                trends['volatility'] = float(volatility) if pd.notna(volatility) else 0
            
            return trends
            
        except Exception as e:
            log.error(f"Error calculating trends: {str(e)}")
            return {}
    
    def _get_hourly_patterns(self, tenant_id: int, cutoff_date: datetime) -> List[Dict[str, Any]]:
        """Analyze hourly execution patterns."""
        try:
            hourly_stats = db.session.query(
                func.extract('hour', ProcessInstance.started_at).label('hour'),
                func.count(ProcessInstance.id).label('count'),
                func.avg(
                    func.extract('epoch', ProcessInstance.completed_at - ProcessInstance.started_at)
                ).label('avg_duration')
            ).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).group_by(func.extract('hour', ProcessInstance.started_at)).order_by('hour').all()
            
            hourly_data = []
            for row in hourly_stats:
                hourly_data.append({
                    'hour': int(row.hour) if row.hour else 0,
                    'count': row.count or 0,
                    'avg_duration': round(row.avg_duration or 0, 2)
                })
            
            return hourly_data
            
        except Exception as e:
            log.error(f"Error getting hourly patterns: {str(e)}")
            return []
    
    def _get_approval_analytics(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Get approval-specific analytics."""
        try:
            # Approval request statistics
            approval_stats = db.session.query(
                func.count(ApprovalRequest.id).label('total_requests'),
                func.sum(func.case([(ApprovalRequest.status == 'approved', 1)], else_=0)).label('approved'),
                func.sum(func.case([(ApprovalRequest.status == 'rejected', 1)], else_=0)).label('rejected'),
                func.sum(func.case([(ApprovalRequest.status == 'pending', 1)], else_=0)).label('pending'),
                func.avg(
                    func.extract('epoch', ApprovalRequest.responded_at - ApprovalRequest.requested_at)
                ).label('avg_response_time')
            ).filter(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.requested_at >= cutoff_date
            ).first()
            
            total = approval_stats.total_requests or 0
            approved = approval_stats.approved or 0
            rejected = approval_stats.rejected or 0
            pending = approval_stats.pending or 0
            
            # Approval rate by approver
            approver_stats = db.session.query(
                ApprovalRequest.approver_id,
                func.count(ApprovalRequest.id).label('total'),
                func.sum(func.case([(ApprovalRequest.status == 'approved', 1)], else_=0)).label('approved'),
                func.avg(
                    func.extract('epoch', ApprovalRequest.responded_at - ApprovalRequest.requested_at)
                ).label('avg_response_time')
            ).filter(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.requested_at >= cutoff_date,
                ApprovalRequest.responded_at.isnot(None)
            ).group_by(ApprovalRequest.approver_id).all()
            
            approver_data = []
            for row in approver_stats:
                approver_total = row.total or 0
                approver_approved = row.approved or 0
                
                approver_data.append({
                    'approver_id': row.approver_id,
                    'total_requests': approver_total,
                    'approved': approver_approved,
                    'approval_rate': (approver_approved / approver_total * 100) if approver_total > 0 else 0,
                    'avg_response_time': round(row.avg_response_time or 0, 2)
                })
            
            return {
                'total_requests': total,
                'approved': approved,
                'rejected': rejected,
                'pending': pending,
                'approval_rate': (approved / total * 100) if total > 0 else 0,
                'avg_response_time': round(approval_stats.avg_response_time or 0, 2),
                'approver_performance': approver_data
            }
            
        except Exception as e:
            log.error(f"Error getting approval analytics: {str(e)}")
            return {}
    
    def _get_trigger_analytics(self, tenant_id: int, cutoff_date: datetime) -> Dict[str, Any]:
        """Get smart trigger analytics."""
        try:
            # Trigger activation statistics
            trigger_stats = db.session.query(
                SmartTrigger.trigger_type,
                func.count(SmartTrigger.id).label('total_triggers'),
                func.sum(SmartTrigger.trigger_count).label('total_activations'),
                func.avg(SmartTrigger.trigger_count).label('avg_activations')
            ).filter(
                SmartTrigger.tenant_id == tenant_id,
                SmartTrigger.created_at >= cutoff_date
            ).group_by(SmartTrigger.trigger_type).all()
            
            trigger_data = []
            for row in trigger_stats:
                trigger_data.append({
                    'trigger_type': row.trigger_type,
                    'total_triggers': row.total_triggers or 0,
                    'total_activations': row.total_activations or 0,
                    'avg_activations': round(row.avg_activations or 0, 2)
                })
            
            # Most active triggers
            active_triggers = db.session.query(
                SmartTrigger.name,
                SmartTrigger.trigger_type,
                SmartTrigger.trigger_count
            ).filter(
                SmartTrigger.tenant_id == tenant_id,
                SmartTrigger.is_active == True
            ).order_by(desc(SmartTrigger.trigger_count)).limit(10).all()
            
            return {
                'trigger_types': trigger_data,
                'most_active_triggers': [
                    {
                        'name': trigger.name,
                        'type': trigger.trigger_type,
                        'activations': trigger.trigger_count or 0
                    }
                    for trigger in active_triggers
                ]
            }
            
        except Exception as e:
            log.error(f"Error getting trigger analytics: {str(e)}")
            return {}
    
    def _get_real_time_metrics(self, tenant_id: int) -> Dict[str, Any]:
        """Get real-time system metrics."""
        try:
            now = datetime.now(tz=timezone.utc)
            
            # Currently running processes
            running_processes = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == ProcessInstanceStatus.RUNNING.value
            ).count()
            
            # Processes started in last hour
            last_hour = now - timedelta(hours=1)
            recent_starts = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= last_hour
            ).count()
            
            # Pending approvals
            pending_approvals = db.session.query(ApprovalRequest).filter(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == 'pending'
            ).count()
            
            # Overdue approvals
            overdue_approvals = db.session.query(ApprovalRequest).filter(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == 'pending',
                ApprovalRequest.expires_at < now
            ).count()
            
            # System health indicators
            avg_step_duration = db.session.query(
                func.avg(
                    func.extract('epoch', ProcessStep.completed_at - ProcessStep.started_at)
                )
            ).filter(
                ProcessStep.completed_at >= last_hour,
                ProcessStep.started_at.isnot(None),
                ProcessStep.completed_at.isnot(None)
            ).scalar()
            
            return {
                'running_processes': running_processes,
                'recent_starts': recent_starts,
                'pending_approvals': pending_approvals,
                'overdue_approvals': overdue_approvals,
                'avg_step_duration': round(avg_step_duration or 0, 2),
                'timestamp': now.isoformat()
            }
            
        except Exception as e:
            log.error(f"Error getting real-time metrics: {str(e)}")
            return {}
    
    def _get_completed_today(self, tenant_id: int) -> int:
        """Get count of processes completed today."""
        today = datetime.now(tz=timezone.utc).date()
        return db.session.query(ProcessInstance).filter(
            ProcessInstance.tenant_id == tenant_id,
            func.date(ProcessInstance.completed_at) == today,
            ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value
        ).count()
    
    def _get_failed_today(self, tenant_id: int) -> int:
        """Get count of processes failed today."""
        today = datetime.now(tz=timezone.utc).date()
        return db.session.query(ProcessInstance).filter(
            ProcessInstance.tenant_id == tenant_id,
            func.date(ProcessInstance.completed_at) == today,
            ProcessInstance.status == ProcessInstanceStatus.FAILED.value
        ).count()
    
    def _get_top_performers(self, performance_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify top performing processes."""
        sorted_by_success = sorted(
            performance_data,
            key=lambda x: (x['success_rate'], x['total_instances']),
            reverse=True
        )
        return sorted_by_success[:5]
    
    def _get_underperformers(self, performance_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify underperforming processes."""
        # Filter out processes with very few instances
        significant_processes = [p for p in performance_data if p['total_instances'] >= 5]
        
        sorted_by_failure = sorted(
            significant_processes,
            key=lambda x: (x['success_rate'], -x['total_instances'])
        )
        return sorted_by_failure[:5]
    
    def _get_stuck_processes(self, tenant_id: int) -> List[Dict[str, Any]]:
        """Identify processes that appear to be stuck."""
        try:
            # Processes running longer than expected
            threshold_hours = current_app.config.get('STUCK_PROCESS_THRESHOLD_HOURS', 24)
            cutoff_time = datetime.now(tz=timezone.utc) - timedelta(hours=threshold_hours)
            
            stuck_instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == ProcessInstanceStatus.RUNNING.value,
                ProcessInstance.started_at < cutoff_time
            ).all()
            
            stuck_data = []
            for instance in stuck_instances:
                duration = (datetime.now(tz=timezone.utc) - instance.started_at).total_seconds()
                
                stuck_data.append({
                    'instance_id': instance.id,
                    'process_name': instance.definition.name,
                    'started_at': instance.started_at.isoformat(),
                    'duration_hours': round(duration / 3600, 2),
                    'current_step': instance.current_step,
                    'progress_percentage': instance.progress_percentage or 0
                })
            
            return stuck_data
            
        except Exception as e:
            log.error(f"Error getting stuck processes: {str(e)}")
            return []
    
    def _summarize_bottlenecks(self, bottlenecks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize bottleneck analysis."""
        if not bottlenecks:
            return {}
        
        try:
            # Most problematic node types
            node_types = defaultdict(list)
            for bottleneck in bottlenecks:
                node_types[bottleneck['node_type']].append(bottleneck['bottleneck_score'])
            
            type_averages = {
                node_type: sum(scores) / len(scores)
                for node_type, scores in node_types.items()
            }
            
            most_problematic = max(type_averages.items(), key=lambda x: x[1])
            
            # Overall bottleneck severity
            avg_bottleneck_score = sum(b['bottleneck_score'] for b in bottlenecks[:5]) / min(5, len(bottlenecks))
            
            severity = 'low'
            if avg_bottleneck_score > 5:
                severity = 'high'
            elif avg_bottleneck_score > 2:
                severity = 'medium'
            
            return {
                'most_problematic_node_type': most_problematic[0],
                'avg_bottleneck_score': round(avg_bottleneck_score, 2),
                'severity': severity,
                'total_bottlenecks': len(bottlenecks)
            }
            
        except Exception as e:
            log.error(f"Error summarizing bottlenecks: {str(e)}")
            return {}
    
    def get_process_details(self, process_id: int, time_range: int = 30) -> Dict[str, Any]:
        """Get detailed analytics for a specific process definition."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=time_range)
            
            # Get process definition
            definition = db.session.query(ProcessDefinition).filter_by(
                id=process_id, tenant_id=tenant_id
            ).first()
            
            if not definition:
                return {'error': 'Process definition not found'}
            
            # Get instances for this process
            instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.definition_id == process_id,
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).all()
            
            if not instances:
                return {
                    'process_name': definition.name,
                    'total_instances': 0,
                    'message': 'No instances found in the specified time range'
                }
            
            # Analyze instances
            analysis = {
                'process_name': definition.name,
                'process_id': process_id,
                'total_instances': len(instances),
                'status_breakdown': self._analyze_instance_statuses(instances),
                'duration_analysis': self._analyze_durations(instances),
                'step_analysis': self._analyze_process_steps(instances),
                'failure_analysis': self._analyze_failures(instances),
                'trend_analysis': self._analyze_process_trends(instances),
                'recommendations': self._generate_recommendations(instances)
            }
            
            return analysis
            
        except Exception as e:
            log.error(f"Error getting process details: {str(e)}")
            return {'error': str(e)}
    
    def _analyze_instance_statuses(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Analyze status distribution of instances."""
        status_counts = Counter(instance.status for instance in instances)
        total = len(instances)
        
        return {
            'counts': dict(status_counts),
            'percentages': {
                status: round(count / total * 100, 2)
                for status, count in status_counts.items()
            }
        }
    
    def _analyze_durations(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Analyze duration patterns of completed instances."""
        completed_instances = [
            i for i in instances
            if i.status == ProcessInstanceStatus.COMPLETED.value and i.completed_at and i.started_at
        ]
        
        if not completed_instances:
            return {'message': 'No completed instances for duration analysis'}
        
        durations = [
            (i.completed_at - i.started_at).total_seconds()
            for i in completed_instances
        ]
        
        return {
            'count': len(durations),
            'avg_duration': round(sum(durations) / len(durations), 2),
            'min_duration': round(min(durations), 2),
            'max_duration': round(max(durations), 2),
            'median_duration': round(sorted(durations)[len(durations) // 2], 2) if durations else 0
        }
    
    def _analyze_process_steps(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Analyze step-level performance."""
        # Get all steps for these instances
        instance_ids = [i.id for i in instances]
        steps = db.session.query(ProcessStep).filter(
            ProcessStep.instance_id.in_(instance_ids)
        ).all()
        
        if not steps:
            return {'message': 'No steps found for analysis'}
        
        # Group by node_id and analyze
        step_groups = defaultdict(list)
        for step in steps:
            step_groups[step.node_id].append(step)
        
        step_analysis = []
        for node_id, node_steps in step_groups.items():
            completed_steps = [
                s for s in node_steps
                if s.completed_at and s.started_at
            ]
            
            if completed_steps:
                durations = [
                    (s.completed_at - s.started_at).total_seconds()
                    for s in completed_steps
                ]
                
                failures = [s for s in node_steps if s.status == ProcessStepStatus.FAILED.value]
                
                step_analysis.append({
                    'node_id': node_id,
                    'node_type': completed_steps[0].node_type,
                    'total_executions': len(node_steps),
                    'completed': len(completed_steps),
                    'failed': len(failures),
                    'avg_duration': round(sum(durations) / len(durations), 2),
                    'failure_rate': round(len(failures) / len(node_steps) * 100, 2)
                })
        
        # Sort by failure rate descending
        step_analysis.sort(key=lambda x: x['failure_rate'], reverse=True)
        
        return {
            'step_performance': step_analysis,
            'total_steps_analyzed': len(steps)
        }
    
    def _analyze_failures(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Analyze failure patterns."""
        failed_instances = [
            i for i in instances
            if i.status == ProcessInstanceStatus.FAILED.value
        ]
        
        if not failed_instances:
            return {'message': 'No failed instances to analyze'}
        
        # Common failure reasons
        error_messages = [i.error_message for i in failed_instances if i.error_message]
        error_counts = Counter(error_messages)
        
        return {
            'total_failures': len(failed_instances),
            'common_errors': dict(error_counts.most_common(10)),
            'failure_rate': round(len(failed_instances) / len(instances) * 100, 2)
        }
    
    def _analyze_process_trends(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Analyze trends in process execution."""
        if not ANALYTICS_AVAILABLE or len(instances) < 5:
            return {'message': 'Insufficient data for trend analysis'}
        
        try:
            # Group by day
            daily_data = defaultdict(lambda: {'total': 0, 'completed': 0, 'failed': 0})
            
            for instance in instances:
                day = instance.started_at.date()
                daily_data[day]['total'] += 1
                
                if instance.status == ProcessInstanceStatus.COMPLETED.value:
                    daily_data[day]['completed'] += 1
                elif instance.status == ProcessInstanceStatus.FAILED.value:
                    daily_data[day]['failed'] += 1
            
            # Convert to DataFrame
            df_data = []
            for day, counts in sorted(daily_data.items()):
                success_rate = (counts['completed'] / counts['total'] * 100) if counts['total'] > 0 else 0
                df_data.append({
                    'date': day,
                    'total': counts['total'],
                    'success_rate': success_rate
                })
            
            if len(df_data) >= 2:
                df = pd.DataFrame(df_data)
                
                # Calculate trends
                total_trend = np.polyfit(range(len(df)), df['total'].values, 1)[0]
                success_trend = np.polyfit(range(len(df)), df['success_rate'].values, 1)[0]
                
                return {
                    'daily_data': df_data,
                    'total_trend': float(total_trend),
                    'success_rate_trend': float(success_trend),
                    'trend_direction': 'improving' if success_trend > 0 else 'declining' if success_trend < 0 else 'stable'
                }
            
            return {'message': 'Insufficient data points for trend analysis'}
            
        except Exception as e:
            log.error(f"Error analyzing process trends: {str(e)}")
            return {'error': str(e)}
    
    def _generate_recommendations(self, instances: List[ProcessInstance]) -> List[str]:
        """Generate optimization recommendations based on analysis."""
        recommendations = []
        
        try:
            # Calculate key metrics
            total = len(instances)
            completed = len([i for i in instances if i.status == ProcessInstanceStatus.COMPLETED.value])
            failed = len([i for i in instances if i.status == ProcessInstanceStatus.FAILED.value])
            success_rate = (completed / total * 100) if total > 0 else 0
            
            # Success rate recommendations
            if success_rate < 80:
                recommendations.append("Process success rate is below 80%. Consider reviewing failure patterns and adding error handling.")
            elif success_rate < 90:
                recommendations.append("Process success rate could be improved. Review common failure points.")
            
            # Duration recommendations
            completed_instances = [
                i for i in instances
                if i.status == ProcessInstanceStatus.COMPLETED.value and i.completed_at and i.started_at
            ]
            
            if completed_instances:
                durations = [(i.completed_at - i.started_at).total_seconds() for i in completed_instances]
                avg_duration = sum(durations) / len(durations)
                
                if avg_duration > 3600:  # More than 1 hour
                    recommendations.append("Average process duration is high. Consider optimizing slow steps or adding parallel processing.")
                
                # Check for high variance in durations
                if len(durations) > 1:
                    variance = sum((d - avg_duration) ** 2 for d in durations) / len(durations)
                    std_dev = variance ** 0.5
                    
                    if std_dev > avg_duration * 0.5:  # High variance
                        recommendations.append("Process execution time varies significantly. Consider identifying and addressing inconsistent steps.")
            
            # Volume recommendations
            if total > 1000:
                recommendations.append("High process volume detected. Consider implementing auto-scaling or load balancing.")
            
            if not recommendations:
                recommendations.append("Process is performing well. Continue monitoring for any changes in patterns.")
            
            return recommendations
            
        except Exception as e:
            log.error(f"Error generating recommendations: {str(e)}")
            return ["Unable to generate recommendations due to analysis error."]
    
    def clear_cache(self):
        """Clear analytics cache."""
        with self._lock:
            self._cache.clear()
            log.info("Analytics cache cleared")