"""
AI-Powered Workflow Optimization Engine for Flask-AppBuilder

Provides intelligent workflow optimization using machine learning and AI:
- Smart workflow suggestions based on historical data
- Automatic bottleneck detection and performance optimization
- Form field value predictions and auto-completion
- Workflow performance analytics and insights
- Intelligent step routing optimization
- Anomaly detection in workflow patterns
- ML-driven workflow personalization
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass, asdict
from enum import Enum
import numpy as np
from collections import defaultdict, Counter
import pickle
from threading import Lock

from flask import current_app, g
from flask_login import current_user
from sqlalchemy import Column, String, Text, DateTime, Boolean, Float, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ..models.mixins import AuditMixin
from .core import WorkflowState, WorkflowDefinition, get_workflow_engine

if TYPE_CHECKING:
    from .core import WorkflowStepDefinition

log = logging.getLogger(__name__)


class OptimizationType(Enum):
    """Types of AI optimizations."""
    STEP_ROUTING = "step_routing"
    FORM_PREDICTION = "form_prediction"
    BOTTLENECK_DETECTION = "bottleneck_detection"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    ANOMALY_DETECTION = "anomaly_detection"
    PERSONALIZATION = "personalization"
    SMART_DEFAULTS = "smart_defaults"
    COMPLETION_PREDICTION = "completion_prediction"


@dataclass
class WorkflowInsight:
    """Represents an AI-generated workflow insight."""
    insight_type: OptimizationType
    workflow_name: str
    confidence: float
    description: str
    recommendations: List[str]
    data: Dict[str, Any]
    timestamp: datetime
    user_id: Optional[str] = None
    step_id: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """Workflow performance metrics."""
    avg_completion_time: float
    step_durations: Dict[str, float]
    bottleneck_steps: List[str]
    success_rate: float
    user_satisfaction: float
    revision_rate: float
    abandonment_rate: float


class WorkflowAnalytics(AuditMixin):
    """
    Stores workflow analytics and performance data.
    """
    __tablename__ = 'ab_workflow_analytics'

    id = Column(String(36), primary_key=True)
    workflow_name = Column(String(100), nullable=False)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=True)
    user_id = Column(Integer, nullable=True)
    step_id = Column(String(100), nullable=True)
    event_type = Column(String(50), nullable=False)  # started, step_completed, completed, abandoned
    event_data = Column(JSON, default=lambda: {})
    duration_seconds = Column(Float, nullable=True)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    metadata = Column(JSON, default=lambda: {})

    # Relationships
    workflow_state = relationship("WorkflowState", backref="analytics")


class AIWorkflowInsight(AuditMixin):
    """
    Stores AI-generated workflow insights and recommendations.
    """
    __tablename__ = 'ab_workflow_ai_insights'

    id = Column(String(36), primary_key=True)
    workflow_name = Column(String(100), nullable=False)
    insight_type = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    recommendations = Column(JSON, default=lambda: [])
    insight_data = Column(JSON, default=lambda: {})
    user_id = Column(Integer, nullable=True)
    step_id = Column(String(100), nullable=True)
    applied = Column(Boolean, default=False)
    applied_at = Column(DateTime, nullable=True)
    feedback_rating = Column(Integer, nullable=True)  # 1-5 star rating
    feedback_text = Column(Text, nullable=True)


class WorkflowMLModel(AuditMixin):
    """
    Stores ML models and their configurations for workflow optimization.
    """
    __tablename__ = 'ab_workflow_ml_models'

    id = Column(String(36), primary_key=True)
    workflow_name = Column(String(100), nullable=False)
    model_type = Column(String(50), nullable=False)  # routing, prediction, anomaly_detection
    model_version = Column(String(20), default='1.0')
    model_data = Column(Text, nullable=False)  # Serialized model
    training_data_count = Column(Integer, default=0)
    accuracy_score = Column(Float, nullable=True)
    last_trained = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    configuration = Column(JSON, default=lambda: {})


class AIWorkflowOptimizer:
    """
    AI-powered workflow optimization engine.
    """

    def __init__(self):
        self.models: Dict[str, Any] = {}
        self.insights_cache: Dict[str, List[WorkflowInsight]] = {}
        self.performance_cache: Dict[str, PerformanceMetrics] = {}
        self._model_lock = Lock()
        self._setup_ai_providers()

    def _setup_ai_providers(self):
        """Setup AI provider connections with focus on Ollama."""
        self.ai_providers = {}
        
        # Ollama setup (primary AI provider)
        ollama_host = current_app.config.get('OLLAMA_HOST', 'http://localhost:11434')
        ollama_model = current_app.config.get('OLLAMA_MODEL', 'gpt-oss')
        
        try:
            import requests
            # Test Ollama connection
            response = requests.get(f"{ollama_host}/api/tags", timeout=5)
            if response.status_code == 200:
                self.ai_providers['ollama'] = {
                    'host': ollama_host,
                    'model': ollama_model,
                    'available': True
                }
                log.info(f"Ollama connected successfully at {ollama_host} with model {ollama_model}")
            else:
                log.warning(f"Ollama not available at {ollama_host}")
        except Exception as e:
            log.warning(f"Failed to connect to Ollama: {e}")

        # Fallback external providers (optional)
        if current_app.config.get('ENABLE_EXTERNAL_AI_PROVIDERS', False):
            # OpenAI setup (fallback)
            openai_key = current_app.config.get('OPENAI_API_KEY')
            if openai_key:
                try:
                    import openai
                    self.ai_providers['openai'] = openai
                    openai.api_key = openai_key
                except ImportError:
                    log.warning("OpenAI package not available")

            # Anthropic setup (fallback)
            anthropic_key = current_app.config.get('ANTHROPIC_API_KEY')
            if anthropic_key:
                try:
                    import anthropic
                    self.ai_providers['anthropic'] = anthropic.Anthropic(api_key=anthropic_key)
                except ImportError:
                    log.warning("Anthropic package not available")

    async def analyze_workflow_performance(self, workflow_name: str) -> PerformanceMetrics:
        """Analyze workflow performance using historical data."""
        from ..models import db

        # Query analytics data
        analytics = db.session.query(WorkflowAnalytics).filter(
            WorkflowAnalytics.workflow_name == workflow_name,
            WorkflowAnalytics.created_on >= datetime.now(tz=timezone.utc) - timedelta(days=30)
        ).all()

        if not analytics:
            return PerformanceMetrics(
                avg_completion_time=0.0,
                step_durations={},
                bottleneck_steps=[],
                success_rate=0.0,
                user_satisfaction=0.0,
                revision_rate=0.0,
                abandonment_rate=0.0
            )

        # Calculate metrics
        completion_times = []
        step_durations = defaultdict(list)
        success_count = 0
        total_count = len(analytics)
        
        for record in analytics:
            if record.event_type == 'completed' and record.duration_seconds:
                completion_times.append(record.duration_seconds)
            
            if record.step_id and record.duration_seconds:
                step_durations[record.step_id].append(record.duration_seconds)
            
            if record.success:
                success_count += 1

        # Calculate averages
        avg_completion_time = np.mean(completion_times) if completion_times else 0.0
        step_avg_durations = {
            step: np.mean(durations) 
            for step, durations in step_durations.items()
        }

        # Identify bottlenecks (steps taking >2 std deviations above mean)
        if step_avg_durations:
            durations_array = list(step_avg_durations.values())
            mean_duration = np.mean(durations_array)
            std_duration = np.std(durations_array)
            threshold = mean_duration + (2 * std_duration)
            
            bottleneck_steps = [
                step for step, duration in step_avg_durations.items()
                if duration > threshold
            ]
        else:
            bottleneck_steps = []

        return PerformanceMetrics(
            avg_completion_time=avg_completion_time,
            step_durations=step_avg_durations,
            bottleneck_steps=bottleneck_steps,
            success_rate=success_count / total_count if total_count > 0 else 0.0,
            user_satisfaction=0.0,  # Would need survey data
            revision_rate=0.0,      # Would need revision tracking
            abandonment_rate=0.0    # Would need abandonment tracking
        )

    async def generate_workflow_insights(self, workflow_name: str) -> List[WorkflowInsight]:
        """Generate AI-powered insights for workflow optimization."""
        insights = []

        # Get performance metrics
        performance = await self.analyze_workflow_performance(workflow_name)

        # Bottleneck detection
        if performance.bottleneck_steps:
            insights.append(WorkflowInsight(
                insight_type=OptimizationType.BOTTLENECK_DETECTION,
                workflow_name=workflow_name,
                confidence=0.85,
                description=f"Detected bottlenecks in steps: {', '.join(performance.bottleneck_steps)}",
                recommendations=[
                    f"Consider simplifying step '{step}'" for step in performance.bottleneck_steps
                ] + [
                    "Add parallel processing where possible",
                    "Review field requirements for bottleneck steps"
                ],
                data={'bottleneck_steps': performance.bottleneck_steps},
                timestamp=datetime.now(tz=timezone.utc)
            ))

        # Performance optimization
        if performance.avg_completion_time > 300:  # > 5 minutes
            insights.append(WorkflowInsight(
                insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                workflow_name=workflow_name,
                confidence=0.75,
                description=f"Workflow completion time is {performance.avg_completion_time:.1f} seconds, which may be too long",
                recommendations=[
                    "Consider breaking workflow into smaller phases",
                    "Add progress indicators to improve user experience",
                    "Implement auto-save to prevent data loss"
                ],
                data={'avg_completion_time': performance.avg_completion_time},
                timestamp=datetime.now(tz=timezone.utc)
            ))

        # Success rate analysis
        if performance.success_rate < 0.8:
            insights.append(WorkflowInsight(
                insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                workflow_name=workflow_name,
                confidence=0.90,
                description=f"Success rate is {performance.success_rate:.1%}, indicating potential issues",
                recommendations=[
                    "Review validation rules for common failure points",
                    "Add better error messages and guidance",
                    "Consider adding help text or examples"
                ],
                data={'success_rate': performance.success_rate},
                timestamp=datetime.now(tz=timezone.utc)
            ))

        # Generate AI-powered insights using LLM
        llm_insights = await self._generate_llm_insights(workflow_name, performance)
        insights.extend(llm_insights)

        # Cache insights
        self.insights_cache[workflow_name] = insights

        return insights

    async def _generate_llm_insights(self, workflow_name: str, performance: PerformanceMetrics) -> List[WorkflowInsight]:
        """Generate insights using Large Language Models."""
        insights = []

        # Prepare context for LLM
        context = {
            'workflow_name': workflow_name,
            'avg_completion_time': performance.avg_completion_time,
            'step_durations': performance.step_durations,
            'bottleneck_steps': performance.bottleneck_steps,
            'success_rate': performance.success_rate
        }

        # Try AI providers with Ollama as primary
        if 'ollama' in self.ai_providers and self.ai_providers['ollama'].get('available'):
            insights.extend(await self._generate_ollama_insights(context))
        elif 'openai' in self.ai_providers:
            insights.extend(await self._generate_openai_insights(context))
        elif 'anthropic' in self.ai_providers:
            insights.extend(await self._generate_anthropic_insights(context))

        return insights

    async def _generate_ollama_insights(self, context: Dict[str, Any]) -> List[WorkflowInsight]:
        """Generate insights using Ollama with gpt-oss model."""
        try:
            import requests
            import json

            ollama_config = self.ai_providers['ollama']
            host = ollama_config['host']
            model = ollama_config['model']

            prompt = f"""
            You are a workflow optimization expert for Flask-AppBuilder applications. 
            Analyze the following workflow performance data and provide specific, actionable optimization recommendations.

            Workflow Analysis:
            - Name: {context['workflow_name']}
            - Average completion time: {context['avg_completion_time']:.1f} seconds
            - Step durations: {context['step_durations']}
            - Bottleneck steps: {context['bottleneck_steps']}
            - Success rate: {context['success_rate']:.1%}

            Please provide 3-5 specific recommendations for improving this workflow's performance and user experience.
            Focus on practical improvements that can be implemented in a Flask-AppBuilder application.
            Each recommendation should be actionable and specific.

            Format your response as a numbered list of recommendations.
            """

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 500
                }
            }

            response = requests.post(
                f"{host}/api/generate",
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '')
                
                # Parse recommendations from response
                lines = content.split('\n')
                recommendations = []
                
                for line in lines:
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-') or line.startswith('*')):
                        # Clean up the recommendation text
                        cleaned = line.lstrip('0123456789.-* ')
                        if cleaned:
                            recommendations.append(cleaned)

                # Ensure we have at least some recommendations
                if not recommendations:
                    recommendations = [
                        "Review workflow step sequence for optimization opportunities",
                        "Implement progress indicators to improve user experience",
                        "Add validation to prevent common errors",
                        "Consider parallel processing for independent steps"
                    ]

                return [WorkflowInsight(
                    insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                    workflow_name=context['workflow_name'],
                    confidence=0.85,
                    description="AI-generated workflow optimization recommendations using Ollama",
                    recommendations=recommendations[:5],
                    data={
                        'source': 'ollama', 
                        'model': model,
                        'host': host,
                        'full_response': content
                    },
                    timestamp=datetime.now(tz=timezone.utc)
                )]

            else:
                log.error(f"Ollama API error: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            log.error(f"Error generating Ollama insights: {e}")
            return []

    async def _generate_openai_insights(self, context: Dict[str, Any]) -> List[WorkflowInsight]:
        """Generate insights using OpenAI."""
        try:
            prompt = f"""
            Analyze the following workflow performance data and provide optimization recommendations:

            Workflow: {context['workflow_name']}
            Average completion time: {context['avg_completion_time']:.1f} seconds
            Step durations: {context['step_durations']}
            Bottleneck steps: {context['bottleneck_steps']}
            Success rate: {context['success_rate']:.1%}

            Please provide 3-5 specific, actionable recommendations for improving this workflow's performance and user experience.
            Focus on practical improvements that can be implemented in a Flask-AppBuilder application.
            """

            response = await self.ai_providers['openai'].ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a workflow optimization expert for Flask-AppBuilder applications."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )

            content = response.choices[0].message.content
            recommendations = content.split('\n')
            recommendations = [r.strip() for r in recommendations if r.strip()]

            return [WorkflowInsight(
                insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                workflow_name=context['workflow_name'],
                confidence=0.80,
                description="AI-generated workflow optimization recommendations",
                recommendations=recommendations[:5],
                data={'source': 'openai', 'model': 'gpt-4'},
                timestamp=datetime.now(tz=timezone.utc)
            )]

        except Exception as e:
            log.error(f"Error generating OpenAI insights: {e}")
            return []

    async def _generate_anthropic_insights(self, context: Dict[str, Any]) -> List[WorkflowInsight]:
        """Generate insights using Anthropic Claude."""
        try:
            prompt = f"""
            Analyze this Flask-AppBuilder workflow performance data:

            Workflow: {context['workflow_name']}
            Average completion time: {context['avg_completion_time']:.1f} seconds
            Step durations: {context['step_durations']}
            Bottleneck steps: {context['bottleneck_steps']}
            Success rate: {context['success_rate']:.1%}

            Provide specific recommendations for optimization.
            """

            message = await self.ai_providers['anthropic'].messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            content = message.content[0].text
            recommendations = content.split('\n')
            recommendations = [r.strip() for r in recommendations if r.strip()]

            return [WorkflowInsight(
                insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                workflow_name=context['workflow_name'],
                confidence=0.85,
                description="AI-generated workflow optimization recommendations",
                recommendations=recommendations[:5],
                data={'source': 'anthropic', 'model': 'claude-3'},
                timestamp=datetime.now(tz=timezone.utc)
            )]

        except Exception as e:
            log.error(f"Error generating Anthropic insights: {e}")
            return []

    async def _generate_google_insights(self, context: Dict[str, Any]) -> List[WorkflowInsight]:
        """Generate insights using Google Gemini."""
        try:
            model = self.ai_providers['google'].GenerativeModel('gemini-pro')
            
            prompt = f"""
            Workflow Performance Analysis:
            
            Name: {context['workflow_name']}
            Avg completion: {context['avg_completion_time']:.1f}s
            Step durations: {context['step_durations']}
            Bottlenecks: {context['bottleneck_steps']}
            Success rate: {context['success_rate']:.1%}
            
            Provide 3-5 optimization recommendations for this Flask-AppBuilder workflow.
            """

            response = await model.generate_content_async(prompt)
            content = response.text
            recommendations = content.split('\n')
            recommendations = [r.strip() for r in recommendations if r.strip()]

            return [WorkflowInsight(
                insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                workflow_name=context['workflow_name'],
                confidence=0.80,
                description="AI-generated workflow optimization recommendations",
                recommendations=recommendations[:5],
                data={'source': 'google', 'model': 'gemini-pro'},
                timestamp=datetime.now(tz=timezone.utc)
            )]

        except Exception as e:
            log.error(f"Error generating Google insights: {e}")
            return []

    def predict_form_values(self, workflow_name: str, step_id: str, 
                           partial_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict form field values based on historical data and partial input."""
        from ..models import db

        # Get historical form data for this workflow and step
        analytics = db.session.query(WorkflowAnalytics).filter(
            WorkflowAnalytics.workflow_name == workflow_name,
            WorkflowAnalytics.step_id == step_id,
            WorkflowAnalytics.event_type == 'step_completed'
        ).limit(1000).all()

        predictions = {}
        
        for record in analytics:
            form_data = record.event_data.get('form_data', {})
            
            # Simple prediction based on frequency
            for field_name, value in form_data.items():
                if field_name not in partial_data and field_name not in predictions:
                    # Find most common value for this field
                    field_values = [
                        r.event_data.get('form_data', {}).get(field_name)
                        for r in analytics
                        if r.event_data.get('form_data', {}).get(field_name) is not None
                    ]
                    
                    if field_values:
                        most_common = Counter(field_values).most_common(1)[0]
                        predictions[field_name] = {
                            'value': most_common[0],
                            'confidence': most_common[1] / len(field_values)
                        }

        return predictions

    def detect_workflow_anomalies(self, workflow_name: str) -> List[WorkflowInsight]:
        """Detect anomalies in workflow execution patterns."""
        from ..models import db

        # Get recent analytics data
        recent_analytics = db.session.query(WorkflowAnalytics).filter(
            WorkflowAnalytics.workflow_name == workflow_name,
            WorkflowAnalytics.created_on >= datetime.now(tz=timezone.utc) - timedelta(days=7)
        ).all()

        anomalies = []

        # Detect unusual completion times
        completion_times = [
            r.duration_seconds for r in recent_analytics
            if r.event_type == 'completed' and r.duration_seconds
        ]

        if len(completion_times) >= 10:
            mean_time = np.mean(completion_times)
            std_time = np.std(completion_times)
            threshold = mean_time + (3 * std_time)  # 3 sigma rule

            unusual_times = [t for t in completion_times if t > threshold]
            
            if unusual_times:
                anomalies.append(WorkflowInsight(
                    insight_type=OptimizationType.ANOMALY_DETECTION,
                    workflow_name=workflow_name,
                    confidence=0.75,
                    description=f"Detected {len(unusual_times)} workflows with unusually long completion times",
                    recommendations=[
                        "Investigate system performance during peak times",
                        "Check for complex validation rules causing delays",
                        "Consider user training if steps are taking longer than expected"
                    ],
                    data={
                        'unusual_times': unusual_times,
                        'mean_time': mean_time,
                        'threshold': threshold
                    },
                    timestamp=datetime.now(tz=timezone.utc)
                ))

        # Detect unusual error patterns
        error_analytics = [r for r in recent_analytics if not r.success]
        if len(error_analytics) > len(recent_analytics) * 0.1:  # > 10% error rate
            error_steps = [r.step_id for r in error_analytics if r.step_id]
            common_error_steps = Counter(error_steps).most_common(3)

            anomalies.append(WorkflowInsight(
                insight_type=OptimizationType.ANOMALY_DETECTION,
                workflow_name=workflow_name,
                confidence=0.85,
                description=f"High error rate detected: {len(error_analytics)/len(recent_analytics):.1%}",
                recommendations=[
                    f"Review validation rules for step '{step}'" for step, count in common_error_steps
                ] + [
                    "Improve error messages and user guidance",
                    "Consider adding field examples or help text"
                ],
                data={
                    'error_rate': len(error_analytics) / len(recent_analytics),
                    'common_error_steps': dict(common_error_steps)
                },
                timestamp=datetime.now(tz=timezone.utc)
            ))

        return anomalies

    def suggest_optimal_routing(self, workflow_state: WorkflowState, 
                              user_context: Dict[str, Any]) -> Optional[str]:
        """Suggest optimal next step based on ML models and user context."""
        
        # Simple rule-based routing for now
        # In production, this would use trained ML models
        
        engine = get_workflow_engine()
        workflow_def = engine.workflow_definitions.get(workflow_state.workflow_name)
        
        if not workflow_def or not workflow_state.available_next_steps:
            return None

        # If only one option, return it
        if len(workflow_state.available_next_steps) == 1:
            return workflow_state.available_next_steps[0]

        # Simple scoring based on user context
        scores = {}
        for step_id in workflow_state.available_next_steps:
            step_def = engine._find_step_definition(workflow_def, step_id)
            if not step_def:
                continue

            score = 1.0

            # Score based on user role
            if step_def.required_role and 'user_roles' in user_context:
                if step_def.required_role in user_context['user_roles']:
                    score += 0.5

            # Score based on historical patterns (simplified)
            if 'user_id' in user_context:
                # Would query historical data for this user's preferences
                pass

            scores[step_id] = score

        # Return step with highest score
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]

        return workflow_state.available_next_steps[0]

    def record_workflow_event(self, workflow_name: str, event_type: str,
                            workflow_state_id: Optional[str] = None,
                            step_id: Optional[str] = None,
                            duration_seconds: Optional[float] = None,
                            success: bool = True,
                            event_data: Optional[Dict[str, Any]] = None):
        """Record workflow analytics event."""
        from ..models import db
        from uuid_extensions import uuid7str

        analytics = WorkflowAnalytics(
            id=uuid7str(),
            workflow_name=workflow_name,
            workflow_state_id=workflow_state_id,
            user_id=current_user.id if current_user.is_authenticated else None,
            step_id=step_id,
            event_type=event_type,
            event_data=event_data or {},
            duration_seconds=duration_seconds,
            success=success
        )

        db.session.add(analytics)
        db.session.commit()

    def store_insight(self, insight: WorkflowInsight) -> str:
        """Store AI insight in database."""
        from ..models import db
        from uuid_extensions import uuid7str

        ai_insight = AIWorkflowInsight(
            id=uuid7str(),
            workflow_name=insight.workflow_name,
            insight_type=insight.insight_type.value,
            confidence=insight.confidence,
            description=insight.description,
            recommendations=insight.recommendations,
            insight_data=insight.data,
            user_id=int(insight.user_id) if insight.user_id else None,
            step_id=insight.step_id
        )

        db.session.add(ai_insight)
        db.session.commit()

        return ai_insight.id

    def get_workflow_recommendations(self, workflow_name: str) -> List[Dict[str, Any]]:
        """Get stored recommendations for a workflow."""
        from ..models import db

        insights = db.session.query(AIWorkflowInsight).filter(
            AIWorkflowInsight.workflow_name == workflow_name,
            AIWorkflowInsight.applied == False
        ).order_by(AIWorkflowInsight.confidence.desc()).limit(10).all()

        return [
            {
                'id': insight.id,
                'type': insight.insight_type,
                'confidence': insight.confidence,
                'description': insight.description,
                'recommendations': insight.recommendations,
                'created_on': insight.created_on.isoformat()
            }
            for insight in insights
        ]

    async def generate_smart_defaults(self, workflow_name: str, step_id: str,
                                    user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate smart default values for form fields."""
        
        # Get user's historical data
        predictions = self.predict_form_values(workflow_name, step_id, {})
        
        # Apply business rules for defaults
        smart_defaults = {}
        
        for field_name, prediction in predictions.items():
            if prediction['confidence'] > 0.7:  # High confidence threshold
                smart_defaults[field_name] = prediction['value']

        # Add user-specific defaults based on profile
        if 'user_profile' in user_context:
            profile = user_context['user_profile']
            
            # Example: auto-fill common fields
            if 'email' in profile and 'email' not in smart_defaults:
                smart_defaults['email'] = profile['email']
            
            if 'department' in profile and 'department' not in smart_defaults:
                smart_defaults['department'] = profile['department']

        return smart_defaults


# Global optimizer instance
_ai_optimizer = None
_optimizer_lock = Lock()


def get_ai_optimizer() -> AIWorkflowOptimizer:
    """Get the global AI optimizer instance."""
    global _ai_optimizer
    with _optimizer_lock:
        if _ai_optimizer is None:
            _ai_optimizer = AIWorkflowOptimizer()
    return _ai_optimizer


# Helper functions for easy integration
async def analyze_workflow(workflow_name: str) -> PerformanceMetrics:
    """Convenience function to analyze workflow performance."""
    optimizer = get_ai_optimizer()
    return await optimizer.analyze_workflow_performance(workflow_name)


async def get_workflow_insights(workflow_name: str) -> List[WorkflowInsight]:
    """Convenience function to get workflow insights."""
    optimizer = get_ai_optimizer()
    return await optimizer.generate_workflow_insights(workflow_name)


def predict_next_step(workflow_state: WorkflowState, user_context: Dict[str, Any]) -> Optional[str]:
    """Convenience function to predict optimal next step."""
    optimizer = get_ai_optimizer()
    return optimizer.suggest_optimal_routing(workflow_state, user_context)


def record_analytics(workflow_name: str, event_type: str, **kwargs):
    """Convenience function to record analytics."""
    optimizer = get_ai_optimizer()
    optimizer.record_workflow_event(workflow_name, event_type, **kwargs)


# Decorator for automatic analytics tracking
def track_workflow_analytics(event_type: str):
    """Decorator to automatically track workflow analytics."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = datetime.now(tz=timezone.utc)
            success = True
            error_message = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                end_time = datetime.now(tz=timezone.utc)
                duration = (end_time - start_time).total_seconds()
                
                # Extract workflow context from args/kwargs
                workflow_name = kwargs.get('workflow_name')
                step_id = kwargs.get('step_id')
                workflow_state_id = kwargs.get('workflow_state_id')
                
                if workflow_name:
                    record_analytics(
                        workflow_name=workflow_name,
                        event_type=event_type,
                        workflow_state_id=workflow_state_id,
                        step_id=step_id,
                        duration_seconds=duration,
                        success=success,
                        event_data={'error_message': error_message} if error_message else {}
                    )
        
        return wrapper
    return decorator