"""
Advanced Analytics and Reporting System for Wizard Forms

Provides comprehensive analytics, reporting, and insights for wizard form
usage, completion rates, user behavior, and performance metrics.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
import statistics

logger = logging.getLogger(__name__)


@dataclass
class WizardAnalyticsEvent:
    """Represents a single analytics event in the wizard system"""
    event_id: str
    wizard_id: str
    session_id: str
    user_id: Optional[str]
    event_type: str
    event_data: Dict[str, Any]
    timestamp: datetime
    step_index: Optional[int] = None
    field_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'event_id': self.event_id,
            'wizard_id': self.wizard_id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'event_type': self.event_type,
            'event_data': self.event_data,
            'timestamp': self.timestamp.isoformat(),
            'step_index': self.step_index,
            'field_id': self.field_id,
            'user_agent': self.user_agent,
            'ip_address': self.ip_address
        }


@dataclass
class WizardCompletionStats:
    """Wizard completion statistics"""
    wizard_id: str
    total_starts: int
    total_completions: int
    completion_rate: float
    average_time_to_complete: float  # minutes
    drop_off_by_step: Dict[int, int]
    most_abandoned_step: Optional[int]
    field_validation_errors: Dict[str, int]
    device_breakdown: Dict[str, int]
    time_period: str


@dataclass
class WizardFieldAnalytics:
    """Analytics for individual form fields"""
    field_id: str
    field_type: str
    field_label: str
    total_interactions: int
    validation_errors: int
    skip_rate: float
    average_completion_time: float  # seconds
    value_distribution: Dict[str, int]  # for select/radio fields
    error_patterns: List[str]


@dataclass
class WizardUserJourney:
    """Represents a user's journey through a wizard"""
    session_id: str
    wizard_id: str
    user_id: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    completed: bool
    steps_completed: List[int]
    time_per_step: Dict[int, float]  # seconds
    errors_encountered: List[Dict[str, Any]]
    final_step_reached: int
    total_time: Optional[float]  # minutes


class WizardAnalyticsEngine:
    """
    Advanced analytics engine for wizard forms
    
    Provides comprehensive tracking, analysis, and reporting capabilities
    for wizard form usage and performance.
    """
    
    def __init__(self):
        """
        Initialize the wizard analytics engine with empty storage containers.
        
        Sets up in-memory storage for:
        - Analytics events list for tracking all interactions
        - User journeys dictionary mapping session IDs to journey objects
        
        In production, these would typically be backed by persistent storage
        like a time-series database or data warehouse.
        """
        self.events: List[WizardAnalyticsEvent] = []
        self.user_journeys: Dict[str, WizardUserJourney] = {}
        
    def track_event(self, 
                   wizard_id: str,
                   session_id: str,
                   event_type: str,
                   event_data: Dict[str, Any],
                   user_id: Optional[str] = None,
                   step_index: Optional[int] = None,
                   field_id: Optional[str] = None,
                   user_agent: Optional[str] = None,
                   ip_address: Optional[str] = None) -> str:
        """Track a wizard analytics event"""
        import uuid
        
        event = WizardAnalyticsEvent(
            event_id=str(uuid.uuid4()),
            wizard_id=wizard_id,
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            event_data=event_data,
            timestamp=datetime.now(tz=timezone.utc),
            step_index=step_index,
            field_id=field_id,
            user_agent=user_agent,
            ip_address=ip_address
        )
        
        self.events.append(event)
        self._update_user_journey(event)
        
        return event.event_id
    
    def _update_user_journey(self, event: WizardAnalyticsEvent):
        """Update user journey based on event"""
        session_id = event.session_id
        
        if session_id not in self.user_journeys:
            self.user_journeys[session_id] = WizardUserJourney(
                session_id=session_id,
                wizard_id=event.wizard_id,
                user_id=event.user_id,
                start_time=event.timestamp,
                end_time=None,
                completed=False,
                steps_completed=[],
                time_per_step={},
                errors_encountered=[],
                final_step_reached=0,
                total_time=None
            )
        
        journey = self.user_journeys[session_id]
        
        # Update journey based on event type
        if event.event_type == 'wizard_started':
            journey.start_time = event.timestamp
            
        elif event.event_type == 'step_completed':
            if event.step_index is not None:
                if event.step_index not in journey.steps_completed:
                    journey.steps_completed.append(event.step_index)
                journey.final_step_reached = max(journey.final_step_reached, event.step_index)
                
        elif event.event_type == 'wizard_completed':
            journey.completed = True
            journey.end_time = event.timestamp
            journey.total_time = (event.timestamp - journey.start_time).total_seconds() / 60
            
        elif event.event_type == 'validation_error':
            journey.errors_encountered.append({
                'timestamp': event.timestamp,
                'step_index': event.step_index,
                'field_id': event.field_id,
                'error_data': event.event_data
            })
            
        elif event.event_type == 'step_abandoned':
            journey.end_time = event.timestamp
            if journey.start_time:
                journey.total_time = (event.timestamp - journey.start_time).total_seconds() / 60
    
    def get_wizard_completion_stats(self, 
                                   wizard_id: str,
                                   start_date: Optional[datetime] = None,
                                   end_date: Optional[datetime] = None) -> WizardCompletionStats:
        """Get completion statistics for a wizard"""
        if not start_date:
            start_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(tz=timezone.utc)
        
        # Filter events for this wizard and date range
        wizard_events = [
            e for e in self.events 
            if e.wizard_id == wizard_id 
            and start_date <= e.timestamp <= end_date
        ]
        
        # Filter journeys for this wizard and date range  
        wizard_journeys = [
            j for j in self.user_journeys.values()
            if j.wizard_id == wizard_id 
            and start_date <= j.start_time <= end_date
        ]
        
        total_starts = len([e for e in wizard_events if e.event_type == 'wizard_started'])
        total_completions = len([j for j in wizard_journeys if j.completed])
        
        completion_rate = (total_completions / total_starts * 100) if total_starts > 0 else 0
        
        # Calculate average completion time
        completed_journeys = [j for j in wizard_journeys if j.completed and j.total_time]
        avg_completion_time = statistics.mean([j.total_time for j in completed_journeys]) if completed_journeys else 0
        
        # Calculate drop-off by step
        drop_off_by_step = defaultdict(int)
        for journey in wizard_journeys:
            if not journey.completed:
                drop_off_by_step[journey.final_step_reached] += 1
        
        most_abandoned_step = max(drop_off_by_step.keys(), key=drop_off_by_step.get) if drop_off_by_step else None
        
        # Field validation errors
        validation_errors = Counter()
        for event in wizard_events:
            if event.event_type == 'validation_error' and event.field_id:
                validation_errors[event.field_id] += 1
        
        # Device breakdown from user agents
        device_breakdown = self._analyze_user_agents([e.user_agent for e in wizard_events if e.user_agent])
        
        return WizardCompletionStats(
            wizard_id=wizard_id,
            total_starts=total_starts,
            total_completions=total_completions,
            completion_rate=completion_rate,
            average_time_to_complete=avg_completion_time,
            drop_off_by_step=dict(drop_off_by_step),
            most_abandoned_step=most_abandoned_step,
            field_validation_errors=dict(validation_errors),
            device_breakdown=device_breakdown,
            time_period=f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
    
    def get_field_analytics(self, 
                           wizard_id: str,
                           field_id: str,
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> WizardFieldAnalytics:
        """Get detailed analytics for a specific field"""
        if not start_date:
            start_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(tz=timezone.utc)
        
        # Filter events for this field
        field_events = [
            e for e in self.events 
            if e.wizard_id == wizard_id 
            and e.field_id == field_id
            and start_date <= e.timestamp <= end_date
        ]
        
        total_interactions = len([e for e in field_events if e.event_type == 'field_interaction'])
        validation_errors = len([e for e in field_events if e.event_type == 'validation_error'])
        
        # Calculate skip rate
        field_views = len([e for e in field_events if e.event_type == 'field_viewed'])
        field_completions = len([e for e in field_events if e.event_type == 'field_completed'])
        skip_rate = ((field_views - field_completions) / field_views * 100) if field_views > 0 else 0
        
        # Calculate average completion time
        completion_times = []
        for event in field_events:
            if event.event_type == 'field_completed' and 'completion_time' in event.event_data:
                completion_times.append(event.event_data['completion_time'])
        
        avg_completion_time = statistics.mean(completion_times) if completion_times else 0
        
        # Value distribution for select/radio fields
        value_distribution = Counter()
        for event in field_events:
            if event.event_type == 'field_completed' and 'value' in event.event_data:
                value = str(event.event_data['value'])
                value_distribution[value] += 1
        
        # Error patterns
        error_patterns = []
        for event in field_events:
            if event.event_type == 'validation_error' and 'error_message' in event.event_data:
                error_patterns.append(event.event_data['error_message'])
        
        # Get field metadata (type, label) - this would typically come from wizard config
        field_type = 'text'  # Default, should be looked up from wizard config
        field_label = field_id  # Default, should be looked up from wizard config
        
        return WizardFieldAnalytics(
            field_id=field_id,
            field_type=field_type,
            field_label=field_label,
            total_interactions=total_interactions,
            validation_errors=validation_errors,
            skip_rate=skip_rate,
            average_completion_time=avg_completion_time,
            value_distribution=dict(value_distribution),
            error_patterns=error_patterns
        )
    
    def get_user_journey_analysis(self, 
                                 wizard_id: str,
                                 start_date: Optional[datetime] = None,
                                 end_date: Optional[datetime] = None) -> List[WizardUserJourney]:
        """Get user journey analysis for a wizard"""
        if not start_date:
            start_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(tz=timezone.utc)
        
        return [
            journey for journey in self.user_journeys.values()
            if journey.wizard_id == wizard_id
            and start_date <= journey.start_time <= end_date
        ]
    
    def get_conversion_funnel(self, wizard_id: str) -> Dict[str, Any]:
        """Get conversion funnel data for a wizard"""
        journeys = [j for j in self.user_journeys.values() if j.wizard_id == wizard_id]
        
        if not journeys:
            return {'steps': [], 'total_started': 0}
        
        # Determine total number of steps from journeys
        max_steps = max(j.final_step_reached for j in journeys) + 1
        
        funnel_data = []
        total_started = len(journeys)
        
        for step in range(max_steps):
            users_reached = len([j for j in journeys if j.final_step_reached >= step])
            completion_rate = (users_reached / total_started * 100) if total_started > 0 else 0
            
            # Calculate average time spent on this step
            step_times = []
            for journey in journeys:
                if step in journey.time_per_step:
                    step_times.append(journey.time_per_step[step])
            
            avg_time = statistics.mean(step_times) if step_times else 0
            
            funnel_data.append({
                'step_index': step,
                'users_reached': users_reached,
                'completion_rate': completion_rate,
                'drop_off': total_started - users_reached if step == 0 else funnel_data[step-1]['users_reached'] - users_reached,
                'average_time_seconds': avg_time
            })
        
        return {
            'steps': funnel_data,
            'total_started': total_started,
            'final_completion_rate': funnel_data[-1]['completion_rate'] if funnel_data else 0
        }
    
    def get_performance_metrics(self, wizard_id: str) -> Dict[str, Any]:
        """Get performance metrics for a wizard"""
        events = [e for e in self.events if e.wizard_id == wizard_id]
        journeys = [j for j in self.user_journeys.values() if j.wizard_id == wizard_id]
        
        # Response time analysis
        load_times = []
        for event in events:
            if event.event_type == 'wizard_loaded' and 'load_time' in event.event_data:
                load_times.append(event.event_data['load_time'])
        
        # Error analysis
        error_events = [e for e in events if 'error' in e.event_type.lower()]
        error_rate = (len(error_events) / len(events) * 100) if events else 0
        
        # Browser/device performance
        browser_performance = defaultdict(list)
        for event in events:
            if event.event_type == 'wizard_loaded' and event.user_agent and 'load_time' in event.event_data:
                browser = self._extract_browser(event.user_agent)
                browser_performance[browser].append(event.event_data['load_time'])
        
        browser_avg_performance = {
            browser: statistics.mean(times) 
            for browser, times in browser_performance.items()
        }
        
        return {
            'average_load_time': statistics.mean(load_times) if load_times else 0,
            'p95_load_time': statistics.quantiles(load_times, n=20)[18] if len(load_times) > 20 else 0,
            'error_rate': error_rate,
            'total_events': len(events),
            'total_sessions': len(journeys),
            'browser_performance': browser_avg_performance
        }
    
    def generate_insights(self, wizard_id: str) -> List[Dict[str, Any]]:
        """Generate actionable insights based on analytics data"""
        insights = []
        
        stats = self.get_wizard_completion_stats(wizard_id)
        funnel = self.get_conversion_funnel(wizard_id)
        
        # Completion rate insights
        if stats.completion_rate < 50:
            insights.append({
                'type': 'warning',
                'category': 'conversion',
                'title': 'Low Completion Rate',
                'description': f'Only {stats.completion_rate:.1f}% of users complete this wizard',
                'recommendation': 'Consider simplifying steps or reducing required fields',
                'priority': 'high'
            })
        
        # Drop-off analysis
        if stats.most_abandoned_step is not None:
            drop_off_rate = stats.drop_off_by_step[stats.most_abandoned_step]
            if drop_off_rate > stats.total_starts * 0.3:  # More than 30% drop off
                insights.append({
                    'type': 'warning',
                    'category': 'user_experience',
                    'title': f'High Drop-off at Step {stats.most_abandoned_step + 1}',
                    'description': f'{drop_off_rate} users abandon the form at this step',
                    'recommendation': 'Review step complexity and field requirements',
                    'priority': 'high'
                })
        
        # Validation errors
        if stats.field_validation_errors:
            most_problematic_field = max(stats.field_validation_errors.keys(), 
                                       key=stats.field_validation_errors.get)
            error_count = stats.field_validation_errors[most_problematic_field]
            
            if error_count > 10:  # Arbitrary threshold
                insights.append({
                    'type': 'warning',
                    'category': 'validation',
                    'title': 'Validation Issues',
                    'description': f'Field "{most_problematic_field}" has {error_count} validation errors',
                    'recommendation': 'Review validation rules and provide better user guidance',
                    'priority': 'medium'
                })
        
        # Completion time insights
        if stats.average_time_to_complete > 10:  # More than 10 minutes
            insights.append({
                'type': 'info',
                'category': 'performance',
                'title': 'Long Completion Time',
                'description': f'Average completion time is {stats.average_time_to_complete:.1f} minutes',
                'recommendation': 'Consider breaking into smaller chunks or optimizing field layout',
                'priority': 'low'
            })
        
        # Mobile usage insights
        mobile_usage = stats.device_breakdown.get('mobile', 0)
        total_usage = sum(stats.device_breakdown.values())
        if mobile_usage / total_usage > 0.6:  # More than 60% mobile
            insights.append({
                'type': 'info',
                'category': 'mobile',
                'title': 'High Mobile Usage',
                'description': f'{mobile_usage/total_usage*100:.1f}% of users access on mobile',
                'recommendation': 'Ensure optimal mobile experience and touch-friendly design',
                'priority': 'medium'
            })
        
        return insights
    
    def _analyze_user_agents(self, user_agents: List[str]) -> Dict[str, int]:
        """Analyze user agents to determine device breakdown"""
        device_counts = defaultdict(int)
        
        for ua in user_agents:
            if not ua:
                continue
                
            ua_lower = ua.lower()
            if any(mobile in ua_lower for mobile in ['mobile', 'android', 'iphone', 'ipad']):
                device_counts['mobile'] += 1
            elif 'tablet' in ua_lower:
                device_counts['tablet'] += 1
            else:
                device_counts['desktop'] += 1
        
        return dict(device_counts)
    
    def _extract_browser(self, user_agent: str) -> str:
        """Extract browser name from user agent"""
        if not user_agent:
            return 'unknown'
        
        ua_lower = user_agent.lower()
        
        if 'chrome' in ua_lower:
            return 'chrome'
        elif 'firefox' in ua_lower:
            return 'firefox'
        elif 'safari' in ua_lower:
            return 'safari'
        elif 'edge' in ua_lower:
            return 'edge'
        else:
            return 'other'
    
    def export_analytics_data(self, 
                             wizard_id: str,
                             format_type: str = 'json',
                             start_date: Optional[datetime] = None,
                             end_date: Optional[datetime] = None) -> str:
        """Export analytics data in various formats"""
        
        stats = self.get_wizard_completion_stats(wizard_id, start_date, end_date)
        funnel = self.get_conversion_funnel(wizard_id)
        insights = self.generate_insights(wizard_id)
        performance = self.get_performance_metrics(wizard_id)
        
        export_data = {
            'wizard_id': wizard_id,
            'export_timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'date_range': {
                'start': start_date.isoformat() if start_date else None,
                'end': end_date.isoformat() if end_date else None
            },
            'completion_stats': asdict(stats),
            'conversion_funnel': funnel,
            'insights': insights,
            'performance_metrics': performance
        }
        
        if format_type == 'json':
            return json.dumps(export_data, indent=2, default=str)
        else:
            # Could implement CSV, Excel, etc.
            return json.dumps(export_data, indent=2, default=str)


# Global analytics engine instance
wizard_analytics = WizardAnalyticsEngine()


def track_wizard_event(wizard_id: str, 
                      session_id: str,
                      event_type: str, 
                      event_data: Dict[str, Any],
                      **kwargs) -> str:
    """Convenience function to track wizard events"""
    return wizard_analytics.track_event(
        wizard_id=wizard_id,
        session_id=session_id, 
        event_type=event_type,
        event_data=event_data,
        **kwargs
    )