"""
Tests for PgAppForge Workflow AI Optimization

Tests the AI-powered workflow optimization using Ollama and performance analytics.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime, timedelta
import asyncio

import pytest
from flask import Flask
from pgappforge import AppBuilder
from flask_sqlalchemy import SQLAlchemy

from pgappforge.workflow.ai_optimization import (
    AIWorkflowOptimizer, WorkflowInsight, PerformanceMetrics, OptimizationType,
    get_ai_optimizer, analyze_workflow, get_workflow_insights
)


class TestPerformanceMetrics(unittest.TestCase):
    """Test PerformanceMetrics class."""

    def setUp(self):
        self.metrics = PerformanceMetrics()

    def test_metrics_initialization(self):
        """Test metrics initialization."""
        self.assertEqual(len(self.metrics.query_times), 0)
        self.assertEqual(self.metrics.cache_hits, 0)
        self.assertEqual(self.metrics.cache_misses, 0)

    def test_record_query_time(self):
        """Test recording query times."""
        self.metrics.record_query_time(0.5)
        self.metrics.record_query_time(1.2)
        
        self.assertEqual(len(self.metrics.query_times), 2)
        self.assertEqual(self.metrics.get_avg_query_time(), 0.85)

    def test_cache_metrics(self):
        """Test cache hit/miss recording."""
        self.metrics.record_cache_hit()
        self.metrics.record_cache_hit()
        self.metrics.record_cache_miss()
        
        self.assertEqual(self.metrics.cache_hits, 2)
        self.assertEqual(self.metrics.cache_misses, 1)
        self.assertEqual(self.metrics.get_cache_hit_ratio(), 2/3)

    def test_query_time_limit(self):
        """Test query time list size limit."""
        # Add more than 1000 queries
        for i in range(1100):
            self.metrics.record_query_time(i * 0.001)
        
        # Should keep only latest 1000
        self.assertEqual(len(self.metrics.query_times), 1000)


class TestAIWorkflowOptimizer(unittest.TestCase):
    """Test AIWorkflowOptimizer class."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        
        # Mock Ollama configuration
        self.app.config['OLLAMA_HOST'] = 'http://localhost:11434'
        self.app.config['OLLAMA_MODEL'] = 'gpt-oss'
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)
            self.optimizer = AIWorkflowOptimizer()

    def test_optimizer_initialization(self):
        """Test optimizer initialization."""
        with self.app.app_context():
            self.assertIsNotNone(self.optimizer.models)
            self.assertIsNotNone(self.optimizer.insights_cache)
            self.assertIsNotNone(self.optimizer.performance_cache)

    def test_ai_providers_setup(self):
        """Test AI providers setup."""
        with self.app.app_context():
            # Test Ollama setup
            with patch('requests.get') as mock_get:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_get.return_value = mock_response
                
                optimizer = AIWorkflowOptimizer()
                
                # Should have Ollama provider
                self.assertIn('ollama', optimizer.ai_providers)
                self.assertTrue(optimizer.ai_providers['ollama']['available'])

    @patch('pgappforge.workflow.ai_optimization.db')
    async def test_analyze_workflow_performance(self, mock_db):
        """Test workflow performance analysis."""
        with self.app.app_context():
            # Mock analytics data
            mock_analytics = [
                Mock(
                    event_type='completed',
                    duration_seconds=120.0,
                    step_id='step_1',
                    success=True
                ),
                Mock(
                    event_type='completed',
                    duration_seconds=180.0,
                    step_id='step_2',
                    success=True
                ),
                Mock(
                    event_type='completed',
                    duration_seconds=90.0,
                    step_id='step_1',
                    success=False
                )
            ]
            
            mock_query = Mock()
            mock_query.filter.return_value.all.return_value = mock_analytics
            mock_db.session.query.return_value = mock_query
            
            metrics = await self.optimizer.analyze_workflow_performance('test_workflow')
            
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics.avg_completion_time, 150.0)  # (120 + 180) / 2
            self.assertIn('step_1', metrics.step_durations)
            self.assertIn('step_2', metrics.step_durations)

    async def test_generate_workflow_insights(self):
        """Test workflow insights generation."""
        with self.app.app_context():
            with patch.object(self.optimizer, 'analyze_workflow_performance') as mock_analyze:
                # Mock performance metrics
                mock_metrics = PerformanceMetrics()
                mock_metrics.avg_completion_time = 600.0  # 10 minutes
                mock_metrics.bottleneck_steps = ['step_2']
                mock_metrics.success_rate = 0.7
                mock_analyze.return_value = mock_metrics
                
                insights = await self.optimizer.generate_workflow_insights('test_workflow')
                
                self.assertIsInstance(insights, list)
                self.assertTrue(len(insights) > 0)
                
                # Should detect bottleneck
                bottleneck_insights = [i for i in insights if i.insight_type == OptimizationType.BOTTLENECK_DETECTION]
                self.assertTrue(len(bottleneck_insights) > 0)
                
                # Should detect performance issues
                perf_insights = [i for i in insights if i.insight_type == OptimizationType.PERFORMANCE_OPTIMIZATION]
                self.assertTrue(len(perf_insights) > 0)

    @patch('requests.post')
    async def test_generate_ollama_insights(self, mock_post):
        """Test Ollama insights generation."""
        with self.app.app_context():
            # Mock Ollama response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'response': '1. Optimize step validation\n2. Add progress indicators\n3. Implement auto-save'
            }
            mock_post.return_value = mock_response
            
            context = {
                'workflow_name': 'test_workflow',
                'avg_completion_time': 300.0,
                'step_durations': {'step_1': 100.0, 'step_2': 200.0},
                'bottleneck_steps': ['step_2'],
                'success_rate': 0.8
            }
            
            insights = await self.optimizer._generate_ollama_insights(context)
            
            self.assertEqual(len(insights), 1)
            insight = insights[0]
            self.assertEqual(insight.insight_type, OptimizationType.PERFORMANCE_OPTIMIZATION)
            self.assertTrue(len(insight.recommendations) > 0)
            self.assertIn('ollama', insight.data['source'])

    def test_predict_form_values(self):
        """Test form value prediction."""
        with self.app.app_context():
            with patch('pgappforge.workflow.ai_optimization.db') as mock_db:
                # Mock historical form data
                mock_analytics = [
                    Mock(event_data={'form_data': {'field1': 'value1', 'field2': 'common_value'}}),
                    Mock(event_data={'form_data': {'field1': 'value2', 'field2': 'common_value'}}),
                    Mock(event_data={'form_data': {'field1': 'value1', 'field2': 'common_value'}})
                ]
                
                mock_query = Mock()
                mock_query.filter.return_value.limit.return_value.all.return_value = mock_analytics
                mock_db.session.query.return_value = mock_query
                
                predictions = self.optimizer.predict_form_values(
                    'test_workflow', 'step_1', {'existing_field': 'value'}
                )
                
                self.assertIn('field1', predictions)
                self.assertIn('field2', predictions)
                # Most common value for field1 should be 'value1' (appears twice)
                self.assertEqual(predictions['field1']['value'], 'value1')
                self.assertEqual(predictions['field2']['value'], 'common_value')

    def test_detect_workflow_anomalies(self):
        """Test workflow anomaly detection."""
        with self.app.app_context():
            with patch('pgappforge.workflow.ai_optimization.db') as mock_db:
                # Mock analytics with anomalous data
                normal_times = [100.0, 110.0, 105.0, 95.0, 120.0]  # Normal completion times
                anomalous_times = [500.0, 600.0]  # Unusually long times
                
                mock_analytics = []
                for time in normal_times + anomalous_times:
                    mock_analytics.append(Mock(
                        event_type='completed',
                        duration_seconds=time,
                        success=True,
                        step_id='step_1'
                    ))
                
                # Add some errors
                for i in range(3):
                    mock_analytics.append(Mock(
                        event_type='completed',
                        success=False,
                        step_id='step_2'
                    ))
                
                mock_query = Mock()
                mock_query.filter.return_value.all.return_value = mock_analytics
                mock_db.session.query.return_value = mock_query
                
                anomalies = self.optimizer.detect_workflow_anomalies('test_workflow')
                
                self.assertIsInstance(anomalies, list)
                self.assertTrue(len(anomalies) > 0)
                
                # Should detect unusual completion times
                time_anomalies = [a for a in anomalies if 'unusual' in a.description.lower()]
                self.assertTrue(len(time_anomalies) > 0)

    def test_suggest_optimal_routing(self):
        """Test optimal routing suggestions."""
        with self.app.app_context():
            # Mock workflow state
            mock_state = Mock()
            mock_state.workflow_name = 'test_workflow'
            mock_state.available_next_steps = ['step_2', 'step_3']
            
            # Mock workflow engine and definition
            with patch('pgappforge.workflow.ai_optimization.get_workflow_engine') as mock_engine:
                mock_workflow_def = Mock()
                mock_step2 = Mock()
                mock_step2.id = 'step_2'
                mock_step2.required_role = 'admin'
                mock_step3 = Mock()
                mock_step3.id = 'step_3'
                mock_step3.required_role = None
                
                mock_engine.return_value.workflow_definitions = {'test_workflow': mock_workflow_def}
                mock_engine.return_value._find_step_definition.side_effect = lambda wd, sid: {
                    'step_2': mock_step2,
                    'step_3': mock_step3
                }.get(sid)
                
                user_context = {'user_roles': ['admin']}
                
                suggestion = self.optimizer.suggest_optimal_routing(mock_state, user_context)
                
                # Should suggest step_2 because user has admin role
                self.assertEqual(suggestion, 'step_2')

    def test_record_workflow_event(self):
        """Test workflow event recording."""
        with self.app.app_context():
            with patch('pgappforge.workflow.ai_optimization.db') as mock_db:
                with patch('pgappforge.workflow.ai_optimization.current_user') as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.id = 1
                    
                    self.optimizer.record_workflow_event(
                        workflow_name='test_workflow',
                        event_type='step_completed',
                        step_id='step_1',
                        duration_seconds=120.0,
                        event_data={'form_data': {'field1': 'value1'}}
                    )
                    
                    # Verify database session was used
                    mock_db.session.add.assert_called_once()
                    mock_db.session.commit.assert_called_once()

    def test_store_insight(self):
        """Test storing AI insights."""
        with self.app.app_context():
            with patch('pgappforge.workflow.ai_optimization.db') as mock_db:
                insight = WorkflowInsight(
                    insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                    workflow_name='test_workflow',
                    confidence=0.85,
                    description='Test insight',
                    recommendations=['Recommendation 1', 'Recommendation 2'],
                    data={'test': 'data'},
                    timestamp=datetime.utcnow()
                )
                
                insight_id = self.optimizer.store_insight(insight)
                
                self.assertIsNotNone(insight_id)
                mock_db.session.add.assert_called_once()
                mock_db.session.commit.assert_called_once()


class TestWorkflowInsights(unittest.TestCase):
    """Test WorkflowInsight data structure."""

    def test_insight_creation(self):
        """Test insight creation."""
        insight = WorkflowInsight(
            insight_type=OptimizationType.BOTTLENECK_DETECTION,
            workflow_name='test_workflow',
            confidence=0.9,
            description='Bottleneck detected in step 2',
            recommendations=['Optimize step validation', 'Add parallel processing'],
            data={'bottleneck_step': 'step_2'},
            timestamp=datetime.utcnow()
        )
        
        self.assertEqual(insight.insight_type, OptimizationType.BOTTLENECK_DETECTION)
        self.assertEqual(insight.workflow_name, 'test_workflow')
        self.assertEqual(insight.confidence, 0.9)
        self.assertEqual(len(insight.recommendations), 2)


class TestAsyncOperations(unittest.TestCase):
    """Test async operations in AI optimization."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_async_analyze_workflow(self):
        """Test async workflow analysis."""
        with self.app.app_context():
            async def test_analysis():
                with patch('pgappforge.workflow.ai_optimization.get_ai_optimizer') as mock_optimizer:
                    mock_instance = Mock()
                    mock_metrics = PerformanceMetrics()
                    mock_instance.analyze_workflow_performance.return_value = mock_metrics
                    mock_optimizer.return_value = mock_instance
                    
                    result = await analyze_workflow('test_workflow')
                    
                    self.assertEqual(result, mock_metrics)
                    mock_instance.analyze_workflow_performance.assert_called_once_with('test_workflow')
            
            # Run async test
            asyncio.run(test_analysis())

    def test_async_get_insights(self):
        """Test async insights generation."""
        with self.app.app_context():
            async def test_insights():
                with patch('pgappforge.workflow.ai_optimization.get_ai_optimizer') as mock_optimizer:
                    mock_instance = Mock()
                    mock_insights = [
                        WorkflowInsight(
                            insight_type=OptimizationType.PERFORMANCE_OPTIMIZATION,
                            workflow_name='test_workflow',
                            confidence=0.8,
                            description='Test insight',
                            recommendations=['Test recommendation'],
                            data={},
                            timestamp=datetime.utcnow()
                        )
                    ]
                    mock_instance.generate_workflow_insights.return_value = mock_insights
                    mock_optimizer.return_value = mock_instance
                    
                    result = await get_workflow_insights('test_workflow')
                    
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].workflow_name, 'test_workflow')
            
            # Run async test
            asyncio.run(test_insights())


class TestIntegration(unittest.TestCase):
    """Integration tests for AI optimization."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_full_optimization_workflow(self):
        """Test complete optimization workflow."""
        with self.app.app_context():
            self.db.create_all()
            
            # Get optimizer instance
            optimizer = get_ai_optimizer()
            self.assertIsNotNone(optimizer)
            
            # Test recording events
            optimizer.record_workflow_event(
                workflow_name='integration_test',
                event_type='workflow_started',
                step_id='step_1'
            )
            
            # Test insights retrieval
            recommendations = optimizer.get_workflow_recommendations('integration_test')
            self.assertIsInstance(recommendations, list)


if __name__ == '__main__':
    unittest.main()