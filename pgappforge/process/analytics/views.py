"""
Process Analytics Dashboard Views.

Provides comprehensive web interface for process analytics, monitoring,
and business intelligence with real-time metrics and insights.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, g, render_template_string
from pgappforge import BaseView, expose, has_access
from pgappforge.api import BaseApi
from pgappforge.security.decorators import has_access_api

from pgappforge import db
from ..models.process_models import ProcessDefinition, ProcessInstance
from .dashboard import ProcessAnalytics
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)


class AnalyticsDashboardView(BaseView):
    """Main analytics dashboard view."""
    
    route_base = '/analytics'
    
    @expose('/')
    @has_access
    def index(self):
        """Main analytics dashboard."""
        try:
            # Get time range from query parameters
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            # Get available process definitions for filtering
            tenant_id = TenantContext.get_current_tenant_id()
            definitions = db.session.query(ProcessDefinition).filter_by(
                tenant_id=tenant_id,
                status='active'
            ).all()
            
            return self.render_template(
                'analytics/dashboard.html',
                dashboard_data=dashboard_data,
                definitions=definitions,
                time_range=time_range,
                refresh_interval=30  # 30 seconds
            )
            
        except Exception as e:
            log.error(f"Error loading analytics dashboard: {str(e)}")
            flash(f'Error loading dashboard: {str(e)}', 'error')
            return redirect(url_for('HomeView.index'))
    
    @expose('/process/<int:process_id>')
    @has_access
    def process_details(self, process_id):
        """Detailed analytics for a specific process."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            process_data = analytics.get_process_details(process_id, time_range)
            
            if 'error' in process_data:
                flash(process_data['error'], 'error')
                return redirect(url_for('AnalyticsDashboardView.index'))
            
            return self.render_template(
                'analytics/process_details.html',
                process_data=process_data,
                time_range=time_range
            )
            
        except Exception as e:
            log.error(f"Error loading process details: {str(e)}")
            flash(f'Error loading process details: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/performance/')
    @has_access
    def performance(self):
        """Process performance analysis."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            performance_data = dashboard_data.get('process_performance', {})
            
            return self.render_template(
                'analytics/performance.html',
                performance_data=performance_data,
                time_range=time_range
            )
            
        except Exception as e:
            log.error(f"Error loading performance analytics: {str(e)}")
            flash(f'Error loading performance analytics: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/bottlenecks/')
    @has_access
    def bottlenecks(self):
        """Bottleneck analysis and optimization recommendations."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            bottleneck_data = dashboard_data.get('bottlenecks', {})
            
            return self.render_template(
                'analytics/bottlenecks.html',
                bottleneck_data=bottleneck_data,
                time_range=time_range
            )
            
        except Exception as e:
            log.error(f"Error loading bottleneck analysis: {str(e)}")
            flash(f'Error loading bottleneck analysis: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/trends/')
    @has_access
    def trends(self):
        """Trend analysis and forecasting."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            trend_data = dashboard_data.get('trends', {})
            
            return self.render_template(
                'analytics/trends.html',
                trend_data=trend_data,
                time_range=time_range
            )
            
        except Exception as e:
            log.error(f"Error loading trend analysis: {str(e)}")
            flash(f'Error loading trend analysis: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/real-time/')
    @has_access
    def real_time(self):
        """Real-time monitoring dashboard."""
        try:
            analytics = ProcessAnalytics()
            tenant_id = TenantContext.get_current_tenant_id()
            
            real_time_data = analytics._get_real_time_metrics(tenant_id)
            
            return self.render_template(
                'analytics/real_time.html',
                real_time_data=real_time_data,
                refresh_interval=5  # 5 seconds for real-time
            )
            
        except Exception as e:
            log.error(f"Error loading real-time dashboard: {str(e)}")
            flash(f'Error loading real-time dashboard: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/reports/')
    @has_access
    def reports(self):
        """Analytics reports and export."""
        try:
            return self.render_template(
                'analytics/reports.html',
                available_reports=[
                    {
                        'id': 'process_summary',
                        'name': 'Process Summary Report',
                        'description': 'Comprehensive summary of process performance'
                    },
                    {
                        'id': 'bottleneck_analysis',
                        'name': 'Bottleneck Analysis Report',
                        'description': 'Detailed bottleneck identification and recommendations'
                    },
                    {
                        'id': 'approval_performance',
                        'name': 'Approval Performance Report',
                        'description': 'Analysis of approval workflows and response times'
                    },
                    {
                        'id': 'trigger_effectiveness',
                        'name': 'Trigger Effectiveness Report',
                        'description': 'Smart trigger performance and automation metrics'
                    }
                ]
            )
            
        except Exception as e:
            log.error(f"Error loading reports page: {str(e)}")
            flash(f'Error loading reports: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.index'))
    
    @expose('/export/<report_type>')
    @has_access
    def export_report(self, report_type):
        """Export analytics report."""
        try:
            time_range = int(request.args.get('time_range', 30))
            format_type = request.args.get('format', 'json')
            
            analytics = ProcessAnalytics()
            
            if report_type == 'process_summary':
                data = analytics.get_dashboard_metrics(time_range)
            elif report_type == 'bottleneck_analysis':
                dashboard_data = analytics.get_dashboard_metrics(time_range)
                data = dashboard_data.get('bottlenecks', {})
            elif report_type == 'approval_performance':
                dashboard_data = analytics.get_dashboard_metrics(time_range)
                data = dashboard_data.get('approvals', {})
            elif report_type == 'trigger_effectiveness':
                dashboard_data = analytics.get_dashboard_metrics(time_range)
                data = dashboard_data.get('triggers', {})
            else:
                flash('Unknown report type', 'error')
                return redirect(url_for('AnalyticsDashboardView.reports'))
            
            if format_type == 'json':
                return jsonify({
                    'report_type': report_type,
                    'generated_at': datetime.now(tz=timezone.utc).isoformat(),
                    'time_range_days': time_range,
                    'data': data
                })
            else:
                # For other formats, would implement CSV, PDF, etc.
                flash('Export format not implemented yet', 'warning')
                return redirect(url_for('AnalyticsDashboardView.reports'))
                
        except Exception as e:
            log.error(f"Error exporting report: {str(e)}")
            flash(f'Error exporting report: {str(e)}', 'error')
            return redirect(url_for('AnalyticsDashboardView.reports'))


class AnalyticsApi(BaseApi):
    """REST API for analytics data."""
    
    resource_name = 'analytics'
    
    @expose('/dashboard', methods=['GET'])
    @has_access_api
    def get_dashboard_metrics(self):
        """Get dashboard metrics via API."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            return self.response(200, result={
                'dashboard_data': dashboard_data,
                'time_range_days': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting dashboard metrics: {str(e)}")
            return self.response_400(f'Error getting dashboard metrics: {str(e)}')
    
    @expose('/process/<int:process_id>', methods=['GET'])
    @has_access_api
    def get_process_analytics(self, process_id):
        """Get detailed analytics for a specific process."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            process_data = analytics.get_process_details(process_id, time_range)
            
            if 'error' in process_data:
                return self.response_404(process_data['error'])
            
            return self.response(200, result={
                'process_data': process_data,
                'time_range_days': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting process analytics: {str(e)}")
            return self.response_400(f'Error getting process analytics: {str(e)}')
    
    @expose('/real-time', methods=['GET'])
    @has_access_api
    def get_real_time_metrics(self):
        """Get real-time system metrics."""
        try:
            analytics = ProcessAnalytics()
            tenant_id = TenantContext.get_current_tenant_id()
            
            real_time_data = analytics._get_real_time_metrics(tenant_id)
            
            return self.response(200, result=real_time_data)
            
        except Exception as e:
            log.error(f"Error getting real-time metrics: {str(e)}")
            return self.response_400(f'Error getting real-time metrics: {str(e)}')
    
    @expose('/performance', methods=['GET'])
    @has_access_api
    def get_performance_metrics(self):
        """Get process performance metrics."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            performance_data = dashboard_data.get('process_performance', {})
            
            return self.response(200, result={
                'performance_data': performance_data,
                'time_range_days': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting performance metrics: {str(e)}")
            return self.response_400(f'Error getting performance metrics: {str(e)}')
    
    @expose('/bottlenecks', methods=['GET'])
    @has_access_api
    def get_bottleneck_analysis(self):
        """Get bottleneck analysis."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            bottleneck_data = dashboard_data.get('bottlenecks', {})
            
            return self.response(200, result={
                'bottleneck_data': bottleneck_data,
                'time_range_days': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting bottleneck analysis: {str(e)}")
            return self.response_400(f'Error getting bottleneck analysis: {str(e)}')
    
    @expose('/trends', methods=['GET'])
    @has_access_api
    def get_trend_analysis(self):
        """Get trend analysis data."""
        try:
            time_range = int(request.args.get('time_range', 30))
            
            analytics = ProcessAnalytics()
            dashboard_data = analytics.get_dashboard_metrics(time_range)
            
            trend_data = dashboard_data.get('trends', {})
            
            return self.response(200, result={
                'trend_data': trend_data,
                'time_range_days': time_range,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting trend analysis: {str(e)}")
            return self.response_400(f'Error getting trend analysis: {str(e)}')
    
    @expose('/alerts', methods=['GET'])
    @has_access_api
    def get_alerts(self):
        """Get system alerts and recommendations."""
        try:
            analytics = ProcessAnalytics()
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get various metrics to generate alerts
            dashboard_data = analytics.get_dashboard_metrics(30)  # Last 30 days
            
            alerts = []
            
            # Check success rate alerts
            overview = dashboard_data.get('overview', {})
            success_rate = overview.get('success_rate', 0)
            
            if success_rate < 80:
                alerts.append({
                    'type': 'error',
                    'title': 'Low Success Rate',
                    'message': f'Process success rate is {success_rate}%, below the recommended 80% threshold.',
                    'recommendation': 'Review failed processes and implement error handling improvements.',
                    'priority': 'high'
                })
            elif success_rate < 90:
                alerts.append({
                    'type': 'warning',
                    'title': 'Moderate Success Rate',
                    'message': f'Process success rate is {success_rate}%, which could be improved.',
                    'recommendation': 'Investigate common failure patterns and optimize process flows.',
                    'priority': 'medium'
                })
            
            # Check for stuck processes
            real_time = dashboard_data.get('real_time', {})
            overdue_approvals = real_time.get('overdue_approvals', 0)
            
            if overdue_approvals > 0:
                alerts.append({
                    'type': 'warning',
                    'title': 'Overdue Approvals',
                    'message': f'{overdue_approvals} approval requests are overdue.',
                    'recommendation': 'Review approval workflows and consider escalation or delegation.',
                    'priority': 'medium'
                })
            
            # Check bottleneck severity
            bottlenecks = dashboard_data.get('bottlenecks', {})
            bottleneck_summary = bottlenecks.get('bottleneck_summary', {})
            severity = bottleneck_summary.get('severity', 'low')
            
            if severity == 'high':
                alerts.append({
                    'type': 'error',
                    'title': 'High Bottleneck Severity',
                    'message': 'Multiple high-impact bottlenecks detected in process flows.',
                    'recommendation': 'Prioritize optimization of bottleneck nodes and consider parallel processing.',
                    'priority': 'high'
                })
            elif severity == 'medium':
                alerts.append({
                    'type': 'warning',
                    'title': 'Moderate Bottlenecks',
                    'message': 'Some bottlenecks detected that may impact performance.',
                    'recommendation': 'Review and optimize identified bottleneck points.',
                    'priority': 'medium'
                })
            
            # Performance trending alerts
            trends = dashboard_data.get('trends', {})
            trend_info = trends.get('trends', {})
            
            if trend_info.get('success_rate_direction') == 'declining':
                alerts.append({
                    'type': 'warning',
                    'title': 'Declining Success Rate Trend',
                    'message': 'Process success rate is trending downward.',
                    'recommendation': 'Investigate recent changes and implement corrective measures.',
                    'priority': 'medium'
                })
            
            if trend_info.get('duration_direction') == 'increasing':
                alerts.append({
                    'type': 'info',
                    'title': 'Increasing Duration Trend',
                    'message': 'Process execution times are trending upward.',
                    'recommendation': 'Monitor for performance degradation and optimize slow components.',
                    'priority': 'low'
                })
            
            # If no alerts, add positive message
            if not alerts:
                alerts.append({
                    'type': 'success',
                    'title': 'System Healthy',
                    'message': 'All process metrics are within normal ranges.',
                    'recommendation': 'Continue monitoring for any changes in performance patterns.',
                    'priority': 'info'
                })
            
            # Sort alerts by priority
            priority_order = {'high': 0, 'medium': 1, 'low': 2, 'info': 3}
            alerts.sort(key=lambda x: priority_order.get(x['priority'], 3))
            
            return self.response(200, result={
                'alerts': alerts,
                'alert_count': len([a for a in alerts if a['type'] in ['error', 'warning']]),
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting alerts: {str(e)}")
            return self.response_400(f'Error getting alerts: {str(e)}')
    
    @expose('/cache/clear', methods=['POST'])
    @has_access_api
    def clear_cache(self):
        """Clear analytics cache."""
        try:
            analytics = ProcessAnalytics()
            analytics.clear_cache()
            
            return self.response(200, message='Analytics cache cleared successfully')
            
        except Exception as e:
            log.error(f"Error clearing cache: {str(e)}")
            return self.response_400(f'Error clearing cache: {str(e)}')
    
    @expose('/health', methods=['GET'])
    @has_access_api
    def health_check(self):
        """Analytics system health check."""
        try:
            analytics = ProcessAnalytics()
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Perform basic health checks
            health_status = {
                'status': 'healthy',
                'database_connection': True,
                'analytics_engine': True,
                'cache_status': 'operational',
                'last_updated': datetime.now(tz=timezone.utc).isoformat()
            }
            
            try:
                # Test database query
                db.session.query(ProcessInstance).filter_by(tenant_id=tenant_id).limit(1).all()
            except Exception as e:
                health_status['database_connection'] = False
                health_status['status'] = 'degraded'
                health_status['database_error'] = str(e)
            
            try:
                # Test analytics engine
                real_time_data = analytics._get_real_time_metrics(tenant_id)
                if not isinstance(real_time_data, dict):
                    health_status['analytics_engine'] = False
                    health_status['status'] = 'degraded'
            except Exception as e:
                health_status['analytics_engine'] = False
                health_status['status'] = 'degraded'
                health_status['analytics_error'] = str(e)
            
            return self.response(200, result=health_status)
            
        except Exception as e:
            log.error(f"Error performing health check: {str(e)}")
            return self.response_500(f'Health check failed: {str(e)}')


class MonitoringView(BaseView):
    """Real-time monitoring and alerting view."""
    
    route_base = '/monitoring'
    
    @expose('/')
    @has_access
    def index(self):
        """Real-time monitoring dashboard."""
        try:
            return self.render_template(
                'monitoring/dashboard.html',
                refresh_interval=5  # 5 seconds refresh
            )
            
        except Exception as e:
            log.error(f"Error loading monitoring dashboard: {str(e)}")
            flash(f'Error loading monitoring dashboard: {str(e)}', 'error')
            return redirect(url_for('HomeView.index'))
    
    @expose('/alerts/')
    @has_access
    def alerts(self):
        """System alerts and notifications."""
        try:
            return self.render_template(
                'monitoring/alerts.html'
            )
            
        except Exception as e:
            log.error(f"Error loading alerts page: {str(e)}")
            flash(f'Error loading alerts: {str(e)}', 'error')
            return redirect(url_for('MonitoringView.index'))
    
    @expose('/processes/')
    @has_access
    def processes(self):
        """Real-time process monitoring."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get currently running processes
            running_processes = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == 'running'
            ).order_by(ProcessInstance.started_at.desc()).limit(50).all()
            
            return self.render_template(
                'monitoring/processes.html',
                running_processes=running_processes,
                refresh_interval=10  # 10 seconds refresh
            )
            
        except Exception as e:
            log.error(f"Error loading process monitoring: {str(e)}")
            flash(f'Error loading process monitoring: {str(e)}', 'error')
            return redirect(url_for('MonitoringView.index'))
    
    @expose('/system/')
    @has_access
    def system(self):
        """System health and performance monitoring."""
        try:
            analytics = ProcessAnalytics()
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get system metrics
            real_time_data = analytics._get_real_time_metrics(tenant_id)
            
            return self.render_template(
                'monitoring/system.html',
                system_metrics=real_time_data,
                refresh_interval=5  # 5 seconds refresh
            )
            
        except Exception as e:
            log.error(f"Error loading system monitoring: {str(e)}")
            flash(f'Error loading system monitoring: {str(e)}', 'error')
            return redirect(url_for('MonitoringView.index'))