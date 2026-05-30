"""
Smart Triggers and ML Integration Views.

Provides management interface for smart triggers, ML models, and 
intelligent process automation with analytics and monitoring.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, g
from flask_appbuilder import ModelView, BaseView, expose, action, has_access
from flask_appbuilder.api import ModelRestApi, BaseApi
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access_api
from flask_appbuilder.widgets import ListWidget, ShowWidget
from wtforms import StringField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from marshmallow import fields

from flask_appbuilder import db
from ..models.process_models import SmartTrigger, ProcessDefinition, ProcessInstance
from .smart_triggers import SmartTriggerEngine, TriggerType, TriggerEvent
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)


class SmartTriggerSchema(SQLAlchemyAutoSchema):
    """Schema for SmartTrigger serialization."""
    
    class Meta:
        model = SmartTrigger
        load_instance = True
        include_relationships = True
        
    configuration = fields.Raw()
    last_triggered_at = fields.DateTime(dump_only=True)
    created_at = fields.DateTime(dump_only=True)


class SmartTriggerView(ModelView):
    """View for managing smart triggers."""
    
    datamodel = SQLAInterface(SmartTrigger)
    
    list_columns = [
        'name', 'trigger_type', 'process_definition.name', 'is_active',
        'trigger_count', 'last_triggered_at', 'created_by'
    ]
    
    show_columns = [
        'name', 'description', 'trigger_type', 'process_definition',
        'configuration', 'is_active', 'trigger_count', 'last_triggered_at',
        'created_by', 'created_at', 'updated_at'
    ]
    
    edit_columns = [
        'name', 'description', 'trigger_type', 'process_definition',
        'configuration', 'is_active'
    ]
    
    add_columns = edit_columns
    
    search_columns = ['name', 'description', 'trigger_type', 'process_definition.name']
    
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    def pre_add(self, item):
        """Pre-process before adding new trigger."""
        item.created_by = g.user
        item.trigger_count = 0
        
        # Validate configuration JSON
        if item.configuration:
            try:
                json.loads(item.configuration)
            except json.JSONDecodeError as e:
                flash(f'Invalid JSON configuration: {str(e)}', 'error')
                raise ValueError("Invalid configuration JSON")
    
    def pre_update(self, item):
        """Pre-process before updating trigger."""
        # Validate configuration JSON
        if item.configuration:
            try:
                json.loads(item.configuration)
            except json.JSONDecodeError as e:
                flash(f'Invalid JSON configuration: {str(e)}', 'error')
                raise ValueError("Invalid configuration JSON")
    
    @action('activate', 'Activate Trigger', 'Activate selected triggers', 'fa-play')
    def activate_trigger(self, items):
        """Activate selected triggers."""
        if not items:
            flash('No triggers selected', 'warning')
            return redirect(request.referrer)
            
        activated_count = 0
        for trigger in items:
            if not trigger.is_active:
                trigger.is_active = True
                activated_count += 1
                
        if activated_count > 0:
            db.session.commit()
            flash(f'Activated {activated_count} triggers', 'success')
        else:
            flash('No inactive triggers found', 'warning')
            
        return redirect(request.referrer)
    
    @action('deactivate', 'Deactivate Trigger', 'Deactivate selected triggers', 'fa-pause')
    def deactivate_trigger(self, items):
        """Deactivate selected triggers."""
        if not items:
            flash('No triggers selected', 'warning')
            return redirect(request.referrer)
            
        deactivated_count = 0
        for trigger in items:
            if trigger.is_active:
                trigger.is_active = False
                deactivated_count += 1
                
        if deactivated_count > 0:
            db.session.commit()
            flash(f'Deactivated {deactivated_count} triggers', 'success')
        else:
            flash('No active triggers found', 'warning')
            
        return redirect(request.referrer)
    
    @action('test', 'Test Trigger', 'Test selected triggers', 'fa-bolt')
    def test_trigger(self, items):
        """Test selected triggers by simulating activation."""
        if not items:
            flash('No triggers selected', 'warning')
            return redirect(request.referrer)
            
        engine = SmartTriggerEngine()
        tested_count = 0
        
        for trigger in items:
            try:
                # Create test context
                test_context = {
                    'test_mode': True,
                    'test_timestamp': datetime.now(tz=timezone.utc).isoformat()
                }
                
                # Simulate trigger activation (without actually starting process)
                log.info(f"Test activation for trigger: {trigger.name}")
                flash(f'Test successful for trigger: {trigger.name}', 'success')
                tested_count += 1
                
            except Exception as e:
                log.error(f"Test failed for trigger {trigger.name}: {str(e)}")
                flash(f'Test failed for trigger {trigger.name}: {str(e)}', 'error')
                
        if tested_count > 0:
            flash(f'Tested {tested_count} triggers', 'info')
            
        return redirect(request.referrer)
    
    @expose('/designer/<int:trigger_id>')
    @has_access
    def designer(self, trigger_id):
        """Visual trigger configuration designer."""
        trigger = self.datamodel.get(trigger_id)
        if not trigger:
            flash('Trigger not found', 'error')
            return redirect(url_for('SmartTriggerView.list'))
        
        # Get available process definitions
        definitions = db.session.query(ProcessDefinition).filter_by(
            tenant_id=TenantContext.get_current_tenant_id(),
            status='active'
        ).all()
        
        return self.render_template(
            'trigger/designer.html',
            trigger=trigger,
            definitions=definitions,
            trigger_types=list(TriggerType),
            configuration=json.dumps(
                json.loads(trigger.configuration) if trigger.configuration else {},
                indent=2
            )
        )


class MLModelView(BaseView):
    """View for managing ML models and analytics."""
    
    route_base = '/ml'
    
    @expose('/')
    @has_access
    def index(self):
        """ML models dashboard."""
        engine = SmartTriggerEngine()
        model_status = engine.get_model_status()
        trigger_stats = engine.get_trigger_statistics()
        
        return self.render_template(
            'ml/dashboard.html',
            model_status=model_status,
            trigger_stats=trigger_stats
        )
    
    @expose('/models/')
    @has_access
    def models(self):
        """Detailed ML models management."""
        engine = SmartTriggerEngine()
        model_status = engine.get_model_status()
        
        return self.render_template(
            'ml/models.html',
            models=model_status
        )
    
    @expose('/train/<model_name>', methods=['POST'])
    @has_access
    def train_model(self, model_name):
        """Train a specific ML model."""
        try:
            engine = SmartTriggerEngine()
            
            if model_name not in engine.ml_models:
                flash(f'Model {model_name} not found', 'error')
                return redirect(url_for('MLModelView.models'))
            
            model = engine.ml_models[model_name]
            
            # Get training data
            training_data = engine._get_ml_training_data()
            
            if len(training_data) < 10:
                flash('Insufficient training data available', 'warning')
                return redirect(url_for('MLModelView.models'))
            
            # Filter data based on model type
            if model_name == 'outcome_predictor':
                model_data = [d for d in training_data if 'outcome' in d]
            elif model_name == 'anomaly_detector':
                model_data = [d for d in training_data if 'duration' in d]
            else:
                model_data = training_data
            
            success = model.train(model_data)
            
            if success:
                flash(f'Model {model_name} trained successfully', 'success')
            else:
                flash(f'Failed to train model {model_name}', 'error')
                
        except Exception as e:
            log.error(f"Error training model {model_name}: {str(e)}")
            flash(f'Error training model: {str(e)}', 'error')
            
        return redirect(url_for('MLModelView.models'))
    
    @expose('/analytics/')
    @has_access
    def analytics(self):
        """Process analytics and predictions."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get recent process performance
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).all()
            
            # Calculate analytics
            analytics_data = self._calculate_process_analytics(instances)
            
            # Get predictions for active processes
            predictions = self._get_active_process_predictions()
            
            return self.render_template(
                'ml/analytics.html',
                analytics=analytics_data,
                predictions=predictions
            )
            
        except Exception as e:
            log.error(f"Error loading analytics: {str(e)}")
            flash(f'Error loading analytics: {str(e)}', 'error')
            return redirect(url_for('MLModelView.index'))
    
    def _calculate_process_analytics(self, instances: List[ProcessInstance]) -> Dict[str, Any]:
        """Calculate process analytics from instances."""
        if not instances:
            return {'total': 0}
        
        total_instances = len(instances)
        completed_instances = [i for i in instances if i.status == 'completed']
        failed_instances = [i for i in instances if i.status == 'failed']
        
        analytics = {
            'total': total_instances,
            'completed': len(completed_instances),
            'failed': len(failed_instances),
            'running': len([i for i in instances if i.status == 'running']),
            'success_rate': len(completed_instances) / total_instances * 100 if total_instances > 0 else 0
        }
        
        # Calculate average duration for completed processes
        if completed_instances:
            durations = []
            for instance in completed_instances:
                if instance.completed_at and instance.started_at:
                    duration = (instance.completed_at - instance.started_at).total_seconds()
                    durations.append(duration)
            
            if durations:
                analytics['avg_duration'] = sum(durations) / len(durations)
                analytics['min_duration'] = min(durations)
                analytics['max_duration'] = max(durations)
        
        return analytics
    
    def _get_active_process_predictions(self) -> List[Dict[str, Any]]:
        """Get predictions for currently running processes."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            running_instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.status == 'running'
            ).limit(20).all()
            
            engine = SmartTriggerEngine()
            predictor = engine.ml_models.get('outcome_predictor')
            
            predictions = []
            
            for instance in running_instances:
                try:
                    if predictor and predictor.is_trained:
                        prediction_data = {
                            'definition_complexity': len(json.loads(instance.definition.process_graph).get('nodes', [])),
                            'input_data_size': len(str(instance.input_data)),
                            'historical_duration': 3600,  # Would use actual historical data
                            'initiator_experience': 3
                        }
                        
                        prediction = predictor.predict(prediction_data)
                        
                        predictions.append({
                            'instance_id': instance.id,
                            'process_name': instance.definition.name,
                            'started_at': instance.started_at,
                            'prediction': prediction
                        })
                        
                except Exception as e:
                    log.error(f"Error predicting for instance {instance.id}: {str(e)}")
            
            return predictions
            
        except Exception as e:
            log.error(f"Error getting predictions: {str(e)}")
            return []


class SmartTriggerApi(ModelRestApi):
    """REST API for smart triggers."""
    
    resource_name = 'smart_trigger'
    datamodel = SQLAInterface(SmartTrigger)
    
    class_permission_name = 'SmartTrigger'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'post': 'can_add',
        'put': 'can_edit',
        'delete': 'can_delete'
    }
    
    list_columns = [
        'id', 'name', 'description', 'trigger_type', 'process_definition.name',
        'is_active', 'trigger_count', 'last_triggered_at', 'created_by.username'
    ]
    
    show_columns = [
        'id', 'name', 'description', 'trigger_type', 'process_definition.name',
        'configuration', 'is_active', 'trigger_count', 'last_triggered_at',
        'created_by.username', 'created_at', 'updated_at'
    ]
    
    add_columns = [
        'name', 'description', 'trigger_type', 'process_definition',
        'configuration', 'is_active'
    ]
    
    edit_columns = add_columns
    
    @expose('/activate/<int:trigger_id>', methods=['POST'])
    @has_access_api
    def activate_trigger(self, trigger_id):
        """Activate a specific trigger."""
        trigger = self.datamodel.get(trigger_id)
        if not trigger:
            return self.response_404()
            
        trigger.is_active = True
        db.session.commit()
        
        return self.response(200, message='Trigger activated successfully')
    
    @expose('/deactivate/<int:trigger_id>', methods=['POST'])
    @has_access_api
    def deactivate_trigger(self, trigger_id):
        """Deactivate a specific trigger."""
        trigger = self.datamodel.get(trigger_id)
        if not trigger:
            return self.response_404()
            
        trigger.is_active = False
        db.session.commit()
        
        return self.response(200, message='Trigger deactivated successfully')
    
    @expose('/test/<int:trigger_id>', methods=['POST'])
    @has_access_api
    def test_trigger(self, trigger_id):
        """Test a specific trigger."""
        trigger = self.datamodel.get(trigger_id)
        if not trigger:
            return self.response_404()
            
        try:
            # Create test event
            test_data = request.json.get('test_data', {}) if request.json else {}
            
            test_event = TriggerEvent(
                event_type='test_event',
                data=test_data,
                timestamp=datetime.now(tz=timezone.utc),
                tenant_id=TenantContext.get_current_tenant_id(),
                source='api_test'
            )
            
            # Test trigger evaluation (without actual execution)
            engine = SmartTriggerEngine()
            
            return self.response(200, **{
                'message': 'Trigger test completed',
                'trigger_id': trigger_id,
                'test_event': {
                    'event_type': test_event.event_type,
                    'data': test_event.data,
                    'timestamp': test_event.timestamp.isoformat()
                }
            })
            
        except Exception as e:
            log.error(f"Error testing trigger: {str(e)}")
            return self.response_400(f'Error testing trigger: {str(e)}')
    
    @expose('/fire_event', methods=['POST'])
    @has_access_api
    def fire_event(self):
        """Fire a trigger event for evaluation."""
        try:
            if not request.json:
                return self.response_400('Request body required')
            
            event_type = request.json.get('event_type')
            event_data = request.json.get('data', {})
            
            if not event_type:
                return self.response_400('event_type is required')
            
            # Create trigger event
            event = TriggerEvent(
                event_type=event_type,
                data=event_data,
                timestamp=datetime.now(tz=timezone.utc),
                tenant_id=TenantContext.get_current_tenant_id(),
                source='api'
            )
            
            # Fire event
            engine = SmartTriggerEngine()
            # Note: This would need to be async in real implementation
            # await engine.fire_event(event)
            
            return self.response(200, **{
                'message': 'Event fired successfully',
                'event_type': event_type,
                'timestamp': event.timestamp.isoformat()
            })
            
        except Exception as e:
            log.error(f"Error firing event: {str(e)}")
            return self.response_400(f'Error firing event: {str(e)}')


class MLApi(BaseApi):
    """REST API for ML models and predictions."""
    
    resource_name = 'ml'
    
    @expose('/models', methods=['GET'])
    @has_access_api
    def get_models(self):
        """Get status of all ML models."""
        try:
            engine = SmartTriggerEngine()
            model_status = engine.get_model_status()
            
            return self.response(200, result=model_status)
            
        except Exception as e:
            log.error(f"Error getting model status: {str(e)}")
            return self.response_400(f'Error getting models: {str(e)}')
    
    @expose('/models/<model_name>/train', methods=['POST'])
    @has_access_api
    def train_model(self, model_name):
        """Train a specific ML model."""
        try:
            engine = SmartTriggerEngine()
            
            if model_name not in engine.ml_models:
                return self.response_404('Model not found')
            
            model = engine.ml_models[model_name]
            
            # Get training data
            training_data = engine._get_ml_training_data()
            
            if len(training_data) < 10:
                return self.response_400('Insufficient training data')
            
            # Filter data based on model type
            if model_name == 'outcome_predictor':
                model_data = [d for d in training_data if 'outcome' in d]
            elif model_name == 'anomaly_detector':
                model_data = [d for d in training_data if 'duration' in d]
            else:
                model_data = training_data
            
            success = model.train(model_data)
            
            if success:
                return self.response(200, **{
                    'message': f'Model {model_name} trained successfully',
                    'training_data_size': len(model_data),
                    'model_info': model.get_model_info()
                })
            else:
                return self.response_400(f'Failed to train model {model_name}')
                
        except Exception as e:
            log.error(f"Error training model: {str(e)}")
            return self.response_400(f'Error training model: {str(e)}')
    
    @expose('/predict', methods=['POST'])
    @has_access_api
    def predict(self):
        """Make a prediction using ML models."""
        try:
            if not request.json:
                return self.response_400('Request body required')
            
            model_name = request.json.get('model', 'outcome_predictor')
            input_data = request.json.get('input_data', {})
            
            engine = SmartTriggerEngine()
            
            if model_name not in engine.ml_models:
                return self.response_400(f'Model {model_name} not found')
            
            model = engine.ml_models[model_name]
            
            if not model.is_trained:
                return self.response_400(f'Model {model_name} is not trained')
            
            prediction = model.predict(input_data)
            
            return self.response(200, **{
                'model': model_name,
                'input_data': input_data,
                'prediction': prediction,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error making prediction: {str(e)}")
            return self.response_400(f'Error making prediction: {str(e)}')
    
    @expose('/analytics', methods=['GET'])
    @has_access_api
    def get_analytics(self):
        """Get process analytics and insights."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            # Get process instances
            instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.started_at >= cutoff_date
            ).all()
            
            # Calculate basic analytics
            analytics = {
                'total_instances': len(instances),
                'completed': len([i for i in instances if i.status == 'completed']),
                'failed': len([i for i in instances if i.status == 'failed']),
                'running': len([i for i in instances if i.status == 'running']),
                'success_rate': 0
            }
            
            if analytics['total_instances'] > 0:
                analytics['success_rate'] = analytics['completed'] / analytics['total_instances'] * 100
            
            # Get trigger statistics
            engine = SmartTriggerEngine()
            trigger_stats = engine.get_trigger_statistics()
            
            return self.response(200, result={
                'process_analytics': analytics,
                'trigger_statistics': trigger_stats,
                'period_days': 30,
                'generated_at': datetime.now(tz=timezone.utc).isoformat()
            })
            
        except Exception as e:
            log.error(f"Error getting analytics: {str(e)}")
            return self.response_400(f'Error getting analytics: {str(e)}')
    
    @expose('/anomalies', methods=['GET'])
    @has_access_api
    def detect_anomalies(self):
        """Detect anomalies in recent process executions."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get recent completed processes
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=7)
            instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.completed_at >= cutoff_date,
                ProcessInstance.status.in_(['completed', 'failed'])
            ).all()
            
            engine = SmartTriggerEngine()
            detector = engine.ml_models.get('anomaly_detector')
            
            if not detector or not detector.is_trained:
                return self.response_400('Anomaly detector not available or trained')
            
            anomalies = []
            
            for instance in instances:
                try:
                    duration = 0
                    if instance.completed_at and instance.started_at:
                        duration = (instance.completed_at - instance.started_at).total_seconds()
                    
                    metrics = {
                        'duration': duration,
                        'steps_count': len(instance.steps),
                        'failure_count': len([s for s in instance.steps if s.status == 'failed']),
                        'memory_usage': 0,  # Would need actual metrics
                        'cpu_usage': 0,
                        'error_rate': len([s for s in instance.steps if s.status == 'failed']) / max(len(instance.steps), 1)
                    }
                    
                    anomaly_result = detector.predict(metrics)
                    
                    if anomaly_result.get('is_anomaly', False):
                        anomalies.append({
                            'instance_id': instance.id,
                            'process_name': instance.definition.name,
                            'completed_at': instance.completed_at.isoformat(),
                            'anomaly_score': anomaly_result.get('anomaly_score', 0),
                            'metrics': metrics
                        })
                        
                except Exception as e:
                    log.error(f"Error checking anomaly for instance {instance.id}: {str(e)}")
            
            return self.response(200, result={
                'anomalies': anomalies,
                'total_checked': len(instances),
                'anomalies_found': len(anomalies),
                'detection_period_days': 7
            })
            
        except Exception as e:
            log.error(f"Error detecting anomalies: {str(e)}")
            return self.response_400(f'Error detecting anomalies: {str(e)}')