"""
Analytics Dashboard Views for Wizard Forms

Provides comprehensive analytics dashboards and reporting interfaces
for monitoring wizard form performance, user behavior, and insights.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from flask import request, render_template, jsonify, flash, redirect, url_for
from flask_login import current_user

from ..views import BaseView, expose, has_access
from ..analytics.wizard_analytics import wizard_analytics

logger = logging.getLogger(__name__)


class WizardAnalyticsView(BaseView):
    """
    Analytics dashboard for wizard forms
    
    Provides comprehensive reporting and insights interface for
    monitoring wizard performance and user behavior.
    """
    
    route_base = "/wizard-analytics"
    default_view = "dashboard"
    
    @expose('/')
    @expose('/dashboard')
    @has_access
    def dashboard(self):
        """Main analytics dashboard"""
        # Get list of wizards for dropdown
        wizards = self._get_available_wizards()
        
        # Default date range (last 30 days)
        end_date = datetime.now(tz=timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        return render_template(
            'analytics/dashboard.html',
            wizards=wizards,
            default_start_date=start_date.strftime('%Y-%m-%d'),
            default_end_date=end_date.strftime('%Y-%m-%d')
        )
    
    @expose('/wizard/<wizard_id>')
    @has_access
    def wizard_detail(self, wizard_id: str):
        """Detailed analytics for a specific wizard"""
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # Parse date range
        try:
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            else:
                start_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            else:
                end_date = datetime.now(tz=timezone.utc)
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('.dashboard'))
        
        # Get analytics data
        completion_stats = wizard_analytics.get_wizard_completion_stats(
            wizard_id, start_date, end_date
        )
        
        conversion_funnel = wizard_analytics.get_conversion_funnel(wizard_id)
        performance_metrics = wizard_analytics.get_performance_metrics(wizard_id)
        insights = wizard_analytics.generate_insights(wizard_id)
        user_journeys = wizard_analytics.get_user_journey_analysis(
            wizard_id, start_date, end_date
        )
        
        return render_template(
            'analytics/wizard_detail.html',
            wizard_id=wizard_id,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            completion_stats=completion_stats,
            conversion_funnel=conversion_funnel,
            performance_metrics=performance_metrics,
            insights=insights,
            user_journeys=user_journeys[:50]  # Limit for display
        )
    
    @expose('/field/<wizard_id>/<field_id>')
    @has_access
    def field_analytics(self, wizard_id: str, field_id: str):
        """Detailed analytics for a specific field"""
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # Parse date range
        try:
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            else:
                start_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            else:
                end_date = datetime.now(tz=timezone.utc)
        except ValueError:
            flash('Invalid date format', 'error')
            return redirect(url_for('.dashboard'))
        
        field_analytics = wizard_analytics.get_field_analytics(
            wizard_id, field_id, start_date, end_date
        )
        
        return render_template(
            'analytics/field_detail.html',
            wizard_id=wizard_id,
            field_id=field_id,
            field_analytics=field_analytics,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )
    
    @expose('/api/completion-stats/<wizard_id>')
    @has_access
    def api_completion_stats(self, wizard_id: str):
        """API endpoint for completion statistics"""
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        
        stats = wizard_analytics.get_wizard_completion_stats(
            wizard_id, start_date, end_date
        )
        
        return jsonify({
            'success': True,
            'data': {
                'wizard_id': stats.wizard_id,
                'total_starts': stats.total_starts,
                'total_completions': stats.total_completions,
                'completion_rate': stats.completion_rate,
                'average_time_to_complete': stats.average_time_to_complete,
                'drop_off_by_step': stats.drop_off_by_step,
                'most_abandoned_step': stats.most_abandoned_step,
                'field_validation_errors': stats.field_validation_errors,
                'device_breakdown': stats.device_breakdown,
                'time_period': stats.time_period
            }
        })
    
    @expose('/api/conversion-funnel/<wizard_id>')
    @has_access
    def api_conversion_funnel(self, wizard_id: str):
        """API endpoint for conversion funnel data"""
        funnel_data = wizard_analytics.get_conversion_funnel(wizard_id)
        
        return jsonify({
            'success': True,
            'data': funnel_data
        })
    
    @expose('/api/performance-metrics/<wizard_id>')
    @has_access
    def api_performance_metrics(self, wizard_id: str):
        """API endpoint for performance metrics"""
        metrics = wizard_analytics.get_performance_metrics(wizard_id)
        
        return jsonify({
            'success': True,
            'data': metrics
        })
    
    @expose('/api/insights/<wizard_id>')
    @has_access
    def api_insights(self, wizard_id: str):
        """API endpoint for insights and recommendations"""
        insights = wizard_analytics.generate_insights(wizard_id)
        
        return jsonify({
            'success': True,
            'data': insights
        })
    
    @expose('/api/user-journeys/<wizard_id>')
    @has_access
    def api_user_journeys(self, wizard_id: str):
        """API endpoint for user journey data"""
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        limit = int(request.args.get('limit', 100))
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        
        journeys = wizard_analytics.get_user_journey_analysis(
            wizard_id, start_date, end_date
        )
        
        # Convert journeys to dict for JSON serialization
        journey_data = []
        for journey in journeys[:limit]:
            journey_data.append({
                'session_id': journey.session_id,
                'user_id': journey.user_id,
                'start_time': journey.start_time.isoformat(),
                'end_time': journey.end_time.isoformat() if journey.end_time else None,
                'completed': journey.completed,
                'steps_completed': journey.steps_completed,
                'time_per_step': journey.time_per_step,
                'errors_encountered': journey.errors_encountered,
                'final_step_reached': journey.final_step_reached,
                'total_time': journey.total_time
            })
        
        return jsonify({
            'success': True,
            'data': journey_data,
            'total_count': len(journeys)
        })
    
    @expose('/api/export/<wizard_id>')
    @has_access
    def api_export_data(self, wizard_id: str):
        """API endpoint for exporting analytics data"""
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        format_type = request.args.get('format', 'json')
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') if end_date_str else None
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        
        export_data = wizard_analytics.export_analytics_data(
            wizard_id, format_type, start_date, end_date
        )
        
        if format_type == 'json':
            return jsonify({
                'success': True,
                'data': json.loads(export_data)
            })
        else:
            # For other formats, return as downloadable file
            from flask import Response
            return Response(
                export_data,
                mimetype='application/octet-stream',
                headers={
                    'Content-Disposition': f'attachment; filename=wizard_{wizard_id}_analytics.{format_type}'
                }
            )
    
    @expose('/api/track-event', methods=['POST'])
    def api_track_event(self):
        """API endpoint for tracking analytics events"""
        try:
            data = request.get_json()
            
            required_fields = ['wizard_id', 'session_id', 'event_type', 'event_data']
            if not all(field in data for field in required_fields):
                return jsonify({
                    'success': False,
                    'error': 'Missing required fields'
                }), 400
            
            event_id = wizard_analytics.track_event(
                wizard_id=data['wizard_id'],
                session_id=data['session_id'],
                event_type=data['event_type'],
                event_data=data['event_data'],
                user_id=data.get('user_id'),
                step_index=data.get('step_index'),
                field_id=data.get('field_id'),
                user_agent=request.headers.get('User-Agent'),
                ip_address=request.remote_addr
            )
            
            return jsonify({
                'success': True,
                'event_id': event_id
            })
            
        except Exception as e:
            logger.error(f"Error tracking analytics event: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to track event'
            }), 500
    
    @expose('/real-time/<wizard_id>')
    @has_access
    def real_time_monitoring(self, wizard_id: str):
        """Real-time monitoring dashboard for a wizard"""
        return render_template(
            'analytics/real_time.html',
            wizard_id=wizard_id
        )
    
    @expose('/api/real-time-stats/<wizard_id>')
    @has_access
    def api_real_time_stats(self, wizard_id: str):
        """API endpoint for real-time statistics"""
        # Get stats for the last 24 hours
        end_date = datetime.now(tz=timezone.utc)
        start_date = end_date - timedelta(hours=24)
        
        # Real-time metrics
        recent_events = [
            e for e in wizard_analytics.events
            if e.wizard_id == wizard_id and e.timestamp >= start_date
        ]
        
        # Active sessions (users who started in last hour)
        active_start_time = end_date - timedelta(hours=1)
        active_sessions = len([
            e for e in recent_events
            if e.event_type == 'wizard_started' and e.timestamp >= active_start_time
        ])
        
        # Current completions (in last hour)
        recent_completions = len([
            e for e in recent_events
            if e.event_type == 'wizard_completed' and e.timestamp >= active_start_time
        ])
        
        # Live error rate
        error_events = len([
            e for e in recent_events
            if 'error' in e.event_type.lower()
        ])
        
        error_rate = (error_events / len(recent_events) * 100) if recent_events else 0
        
        return jsonify({
            'success': True,
            'data': {
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'active_sessions': active_sessions,
                'recent_completions': recent_completions,
                'error_rate': error_rate,
                'total_events_24h': len(recent_events)
            }
        })
    
    def _get_available_wizards(self) -> List[Dict[str, str]]:
        """Get list of available wizards for analytics"""
        # This would typically query from database
        # For now, return sample data based on tracked wizards
        unique_wizard_ids = list(set(event.wizard_id for event in wizard_analytics.events))
        
        wizards = []
        for wizard_id in unique_wizard_ids:
            # In real implementation, would fetch wizard metadata from database
            wizards.append({
                'id': wizard_id,
                'title': f'Wizard {wizard_id}',  # Would be actual title
                'description': f'Analytics for wizard {wizard_id}'
            })
        
        # Add some default wizards if no events tracked yet
        if not wizards:
            wizards = [
                {
                    'id': 'wizard_001',
                    'title': 'Customer Registration Form',
                    'description': 'Multi-step customer onboarding'
                },
                {
                    'id': 'wizard_002', 
                    'title': 'Employee Feedback Survey',
                    'description': 'Anonymous employee satisfaction survey'
                }
            ]
        
        return wizards