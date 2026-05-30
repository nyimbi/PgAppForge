"""
Smart Triggers and ML Integration for Process Automation.

Provides intelligent process triggering based on data conditions, events,
and machine learning predictions with anomaly detection and optimization.
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
import threading
from dataclasses import dataclass

try:
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import IsolationForest, RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    ML_AVAILABLE = True
except ImportError:
    # Fallback implementations when ML libraries are not available
    np = None
    pd = None
    ML_AVAILABLE = False

from flask import current_app
from pgappforge import db

from ..models.process_models import (
    ProcessDefinition, ProcessInstance, SmartTrigger,
    ProcessMetric, TriggerCondition, TriggerAction
)
from ..engine.process_engine import ProcessEngine
from ...tenants.context import TenantContext

log = logging.getLogger(__name__)


class TriggerType(Enum):
    """Types of smart triggers."""
    SCHEDULE = "schedule"
    DATA_CONDITION = "data_condition"
    EVENT_DRIVEN = "event_driven"
    ML_PREDICTION = "ml_prediction"
    ANOMALY_DETECTION = "anomaly_detection"
    THRESHOLD_BREACH = "threshold_breach"


class MLModel:
    """Base class for ML models used in process automation."""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.model = None
        self.scaler = None
        self.is_trained = False
        self.last_training = None
        
    def train(self, training_data: List[Dict[str, Any]]) -> bool:
        """Train the ML model with provided data."""
        raise NotImplementedError("Subclasses must implement train method")
    
    def predict(self, input_data: Dict[str, Any]) -> Any:
        """Make prediction based on input data."""
        raise NotImplementedError("Subclasses must implement predict method")
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the model."""
        return {
            'name': self.model_name,
            'is_trained': self.is_trained,
            'last_training': self.last_training.isoformat() if self.last_training else None
        }


class ProcessOutcomePredictor(MLModel):
    """ML model for predicting process outcomes and durations."""
    
    def __init__(self):
        super().__init__("process_outcome_predictor")
        if ML_AVAILABLE:
            self.model = RandomForestClassifier(n_estimators=100, random_state=42)
            self.scaler = StandardScaler()
    
    def train(self, training_data: List[Dict[str, Any]]) -> bool:
        """Train the process outcome prediction model."""
        if not ML_AVAILABLE:
            log.warning("ML libraries not available, using fallback predictor")
            return self._train_fallback(training_data)
            
        try:
            if len(training_data) < 10:
                log.warning("Insufficient training data for ML model")
                return False
                
            df = pd.DataFrame(training_data)
            
            # Feature engineering
            features = [
                'definition_complexity', 'input_data_size', 'historical_duration',
                'time_of_day', 'day_of_week', 'initiator_experience'
            ]
            
            X = df[features].fillna(0)
            y = df['outcome']  # 'success', 'failure', 'timeout'
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            
            # Scale features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Train model
            self.model.fit(X_train_scaled, y_train)
            
            # Evaluate
            y_pred = self.model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            self.is_trained = True
            self.last_training = datetime.now(tz=timezone.utc)
            
            log.info(f"Process outcome predictor trained with accuracy: {accuracy:.3f}")
            return True
            
        except Exception as e:
            log.error(f"Failed to train outcome predictor: {str(e)}")
            return False
    
    def predict(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict process outcome and estimated duration."""
        if not ML_AVAILABLE:
            return self._predict_fallback(input_data)
            
        try:
            if not self.is_trained:
                return self._predict_fallback(input_data)
                
            # Extract features
            features = np.array([[
                input_data.get('definition_complexity', 5),
                input_data.get('input_data_size', 100),
                input_data.get('historical_duration', 3600),
                datetime.now().hour,
                datetime.now().weekday(),
                input_data.get('initiator_experience', 3)
            ]])
            
            features_scaled = self.scaler.transform(features)
            
            # Predict outcome
            outcome_proba = self.model.predict_proba(features_scaled)[0]
            outcome_classes = self.model.classes_
            
            prediction = {
                'predicted_outcome': outcome_classes[np.argmax(outcome_proba)],
                'confidence': float(np.max(outcome_proba)),
                'outcome_probabilities': {
                    cls: float(prob) for cls, prob in zip(outcome_classes, outcome_proba)
                }
            }
            
            # Estimate duration based on historical data and prediction
            base_duration = input_data.get('historical_duration', 3600)
            if prediction['predicted_outcome'] == 'success':
                estimated_duration = base_duration * 0.9
            elif prediction['predicted_outcome'] == 'failure':
                estimated_duration = base_duration * 1.3
            else:  # timeout
                estimated_duration = base_duration * 2.0
                
            prediction['estimated_duration_seconds'] = int(estimated_duration)
            
            return prediction
            
        except Exception as e:
            log.error(f"Prediction failed: {str(e)}")
            return self._predict_fallback(input_data)
    
    def _train_fallback(self, training_data: List[Dict[str, Any]]) -> bool:
        """Fallback training using simple statistics."""
        if len(training_data) < 5:
            return False
            
        outcomes = [data.get('outcome', 'success') for data in training_data]
        success_rate = outcomes.count('success') / len(outcomes)
        
        self.fallback_stats = {
            'success_rate': success_rate,
            'avg_duration': sum(data.get('duration', 3600) for data in training_data) / len(training_data)
        }
        
        self.is_trained = True
        self.last_training = datetime.now(tz=timezone.utc)
        return True
    
    def _predict_fallback(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback prediction using simple heuristics."""
        if hasattr(self, 'fallback_stats'):
            success_rate = self.fallback_stats['success_rate']
            avg_duration = self.fallback_stats['avg_duration']
        else:
            success_rate = 0.8  # Default assumption
            avg_duration = 3600
            
        return {
            'predicted_outcome': 'success' if success_rate > 0.6 else 'failure',
            'confidence': 0.6,
            'outcome_probabilities': {
                'success': success_rate,
                'failure': 1 - success_rate
            },
            'estimated_duration_seconds': int(avg_duration)
        }


class AnomalyDetector(MLModel):
    """ML model for detecting anomalies in process execution."""
    
    def __init__(self):
        super().__init__("anomaly_detector")
        if ML_AVAILABLE:
            self.model = IsolationForest(contamination=0.1, random_state=42)
    
    def train(self, training_data: List[Dict[str, Any]]) -> bool:
        """Train the anomaly detection model."""
        if not ML_AVAILABLE:
            return self._train_fallback(training_data)
            
        try:
            if len(training_data) < 50:
                log.warning("Insufficient data for anomaly detection training")
                return False
                
            df = pd.DataFrame(training_data)
            
            # Features for anomaly detection
            features = [
                'duration', 'steps_count', 'failure_count',
                'memory_usage', 'cpu_usage', 'error_rate'
            ]
            
            X = df[features].fillna(df[features].mean())
            
            # Train isolation forest
            self.model.fit(X)
            
            self.is_trained = True
            self.last_training = datetime.now(tz=timezone.utc)
            
            log.info("Anomaly detector trained successfully")
            return True
            
        except Exception as e:
            log.error(f"Failed to train anomaly detector: {str(e)}")
            return False
    
    def predict(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Detect if process metrics indicate an anomaly."""
        if not ML_AVAILABLE:
            return self._predict_fallback(input_data)
            
        try:
            if not self.is_trained:
                return self._predict_fallback(input_data)
                
            features = np.array([[
                input_data.get('duration', 0),
                input_data.get('steps_count', 0),
                input_data.get('failure_count', 0),
                input_data.get('memory_usage', 0),
                input_data.get('cpu_usage', 0),
                input_data.get('error_rate', 0)
            ]])
            
            anomaly_score = self.model.decision_function(features)[0]
            is_anomaly = self.model.predict(features)[0] == -1
            
            return {
                'is_anomaly': bool(is_anomaly),
                'anomaly_score': float(anomaly_score),
                'confidence': min(abs(anomaly_score), 1.0)
            }
            
        except Exception as e:
            log.error(f"Anomaly detection failed: {str(e)}")
            return self._predict_fallback(input_data)
    
    def _train_fallback(self, training_data: List[Dict[str, Any]]) -> bool:
        """Fallback training using statistical thresholds."""
        if len(training_data) < 10:
            return False
            
        durations = [data.get('duration', 0) for data in training_data]
        error_rates = [data.get('error_rate', 0) for data in training_data]
        
        self.fallback_thresholds = {
            'duration_mean': sum(durations) / len(durations),
            'duration_std': (sum((x - sum(durations) / len(durations)) ** 2 for x in durations) / len(durations)) ** 0.5,
            'error_rate_threshold': max(error_rates) * 0.8
        }
        
        self.is_trained = True
        self.last_training = datetime.now(tz=timezone.utc)
        return True
    
    def _predict_fallback(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback anomaly detection using simple thresholds."""
        if not hasattr(self, 'fallback_thresholds'):
            return {'is_anomaly': False, 'anomaly_score': 0.0, 'confidence': 0.5}
            
        thresholds = self.fallback_thresholds
        duration = input_data.get('duration', 0)
        error_rate = input_data.get('error_rate', 0)
        
        # Check if duration is outside 2 standard deviations
        duration_anomaly = abs(duration - thresholds['duration_mean']) > 2 * thresholds['duration_std']
        
        # Check if error rate exceeds threshold
        error_anomaly = error_rate > thresholds['error_rate_threshold']
        
        is_anomaly = duration_anomaly or error_anomaly
        
        return {
            'is_anomaly': is_anomaly,
            'anomaly_score': 1.0 if is_anomaly else 0.0,
            'confidence': 0.7
        }


@dataclass
class TriggerEvent:
    """Represents a trigger event that may start a process."""
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime
    tenant_id: Optional[int] = None
    source: Optional[str] = None


class SmartTriggerEngine:
    """Engine for managing and evaluating smart triggers."""
    
    def __init__(self):
        self._lock = threading.RLock()
        self.active_triggers = {}
        self.ml_models = {}
        self.event_handlers = {}
        
        # Initialize ML models
        self._initialize_ml_models()
        
        # Background tasks
        self.monitoring_active = False
        self.monitoring_thread = None
    
    def _initialize_ml_models(self):
        """Initialize ML models for intelligent triggering."""
        self.ml_models['outcome_predictor'] = ProcessOutcomePredictor()
        self.ml_models['anomaly_detector'] = AnomalyDetector()
        
        log.info("Smart trigger engine initialized with ML models")
    
    async def start_monitoring(self):
        """Start the trigger monitoring system."""
        with self._lock:
            if self.monitoring_active:
                return
                
            self.monitoring_active = True
            self.monitoring_thread = threading.Thread(
                target=self._monitoring_loop,
                daemon=True
            )
            self.monitoring_thread.start()
            
        log.info("Smart trigger monitoring started")
    
    async def stop_monitoring(self):
        """Stop the trigger monitoring system."""
        with self._lock:
            self.monitoring_active = False
            
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
            
        log.info("Smart trigger monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop for trigger evaluation."""
        while self.monitoring_active:
            try:
                self._evaluate_triggers()
                self._train_ml_models()
                
                # Sleep for monitoring interval
                monitoring_interval = current_app.config.get('TRIGGER_MONITORING_INTERVAL', 60)
                threading.Event().wait(monitoring_interval)
                
            except Exception as e:
                log.error(f"Error in trigger monitoring loop: {str(e)}")
                threading.Event().wait(10)  # Brief pause on error
    
    def _evaluate_triggers(self):
        """Evaluate all active triggers."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            # Get active triggers for current tenant
            triggers = db.session.query(SmartTrigger).filter(
                SmartTrigger.tenant_id == tenant_id,
                SmartTrigger.is_active == True
            ).all()
            
            for trigger in triggers:
                try:
                    self._evaluate_single_trigger(trigger)
                except Exception as e:
                    log.error(f"Error evaluating trigger {trigger.id}: {str(e)}")
                    
        except Exception as e:
            log.error(f"Error in trigger evaluation: {str(e)}")
    
    def _evaluate_single_trigger(self, trigger: SmartTrigger):
        """Evaluate a single trigger for activation."""
        try:
            trigger_config = json.loads(trigger.configuration) if trigger.configuration else {}
            
            # Check trigger type and evaluate accordingly
            if trigger.trigger_type == TriggerType.SCHEDULE.value:
                self._evaluate_schedule_trigger(trigger, trigger_config)
            elif trigger.trigger_type == TriggerType.DATA_CONDITION.value:
                self._evaluate_data_condition_trigger(trigger, trigger_config)
            elif trigger.trigger_type == TriggerType.ML_PREDICTION.value:
                self._evaluate_ml_prediction_trigger(trigger, trigger_config)
            elif trigger.trigger_type == TriggerType.ANOMALY_DETECTION.value:
                self._evaluate_anomaly_trigger(trigger, trigger_config)
            elif trigger.trigger_type == TriggerType.THRESHOLD_BREACH.value:
                self._evaluate_threshold_trigger(trigger, trigger_config)
                
        except Exception as e:
            log.error(f"Error evaluating trigger {trigger.name}: {str(e)}")
    
    def _evaluate_schedule_trigger(self, trigger: SmartTrigger, config: Dict[str, Any]):
        """Evaluate schedule-based trigger."""
        schedule = config.get('schedule', {})
        
        # Check if it's time to trigger
        now = datetime.now(tz=timezone.utc)
        last_triggered = trigger.last_triggered_at
        
        if self._should_trigger_by_schedule(schedule, now, last_triggered):
            self._activate_trigger(trigger, {'scheduled_time': now.isoformat()})
    
    def _evaluate_data_condition_trigger(self, trigger: SmartTrigger, config: Dict[str, Any]):
        """Evaluate data condition-based trigger."""
        conditions = config.get('conditions', [])
        
        if self._evaluate_conditions(conditions):
            self._activate_trigger(trigger, {'conditions_met': True})
    
    def _evaluate_ml_prediction_trigger(self, trigger: SmartTrigger, config: Dict[str, Any]):
        """Evaluate ML prediction-based trigger."""
        model_name = config.get('model', 'outcome_predictor')
        threshold = config.get('threshold', 0.8)
        
        if model_name not in self.ml_models:
            log.warning(f"ML model {model_name} not found")
            return
            
        model = self.ml_models[model_name]
        if not model.is_trained:
            return
            
        # Get prediction data
        prediction_data = self._get_prediction_data(trigger, config)
        prediction = model.predict(prediction_data)
        
        # Check if prediction meets threshold
        if prediction.get('confidence', 0) >= threshold:
            self._activate_trigger(trigger, {
                'ml_prediction': prediction,
                'threshold_met': True
            })
    
    def _evaluate_anomaly_trigger(self, trigger: SmartTrigger, config: Dict[str, Any]):
        """Evaluate anomaly detection trigger."""
        detector = self.ml_models.get('anomaly_detector')
        if not detector or not detector.is_trained:
            return
            
        # Get current process metrics
        metrics_data = self._get_current_metrics(trigger, config)
        anomaly_result = detector.predict(metrics_data)
        
        if anomaly_result.get('is_anomaly', False):
            self._activate_trigger(trigger, {
                'anomaly_detected': True,
                'anomaly_score': anomaly_result.get('anomaly_score', 0)
            })
    
    def _evaluate_threshold_trigger(self, trigger: SmartTrigger, config: Dict[str, Any]):
        """Evaluate threshold-based trigger."""
        metric = config.get('metric')
        threshold = config.get('threshold')
        operator = config.get('operator', '>')
        
        if not metric or threshold is None:
            return
            
        current_value = self._get_metric_value(metric)
        
        if self._compare_threshold(current_value, threshold, operator):
            self._activate_trigger(trigger, {
                'threshold_breach': True,
                'metric': metric,
                'current_value': current_value,
                'threshold': threshold
            })
    
    def _activate_trigger(self, trigger: SmartTrigger, context: Dict[str, Any]):
        """Activate a trigger and start associated process."""
        try:
            log.info(f"Activating trigger: {trigger.name}")
            
            # Update trigger last activated time
            trigger.last_triggered_at = datetime.now(tz=timezone.utc)
            trigger.trigger_count += 1
            db.session.commit()
            
            # Start process if configured
            if trigger.process_definition_id:
                engine = ProcessEngine()
                
                # Prepare input data from trigger context
                input_data = {
                    'trigger_id': trigger.id,
                    'trigger_type': trigger.trigger_type,
                    'trigger_context': context,
                    'auto_started': True
                }
                
                # Merge with any configured input data
                trigger_config = json.loads(trigger.configuration) if trigger.configuration else {}
                input_data.update(trigger_config.get('input_data', {}))
                
                instance = await engine.start_process(
                    definition_id=trigger.process_definition_id,
                    input_data=input_data,
                    initiated_by=None  # System-initiated
                )
                
                log.info(f"Process {instance.id} started by trigger {trigger.name}")
            
            # Execute any additional actions
            self._execute_trigger_actions(trigger, context)
            
        except Exception as e:
            log.error(f"Failed to activate trigger {trigger.name}: {str(e)}")
    
    def _execute_trigger_actions(self, trigger: SmartTrigger, context: Dict[str, Any]):
        """Execute additional actions configured for the trigger."""
        try:
            config = json.loads(trigger.configuration) if trigger.configuration else {}
            actions = config.get('actions', [])
            
            for action in actions:
                action_type = action.get('type')
                
                if action_type == 'webhook':
                    self._execute_webhook_action(action, context)
                elif action_type == 'notification':
                    self._execute_notification_action(action, context)
                elif action_type == 'data_update':
                    self._execute_data_update_action(action, context)
                    
        except Exception as e:
            log.error(f"Error executing trigger actions: {str(e)}")
    
    def _train_ml_models(self):
        """Periodically train ML models with latest data."""
        try:
            # Only train every few hours to avoid overhead
            last_training_key = 'last_ml_training'
            now = datetime.now(tz=timezone.utc)
            
            # Simple in-memory check (in production, use Redis or database)
            if not hasattr(self, '_last_training_check'):
                self._last_training_check = now
                
            time_since_check = now - self._last_training_check
            if time_since_check.total_seconds() < 3600:  # 1 hour
                return
                
            self._last_training_check = now
            
            # Get training data
            training_data = self._get_ml_training_data()
            
            if len(training_data) >= 10:
                # Train outcome predictor
                outcome_data = [d for d in training_data if 'outcome' in d]
                if outcome_data:
                    self.ml_models['outcome_predictor'].train(outcome_data)
                
                # Train anomaly detector
                metrics_data = [d for d in training_data if 'duration' in d]
                if metrics_data:
                    self.ml_models['anomaly_detector'].train(metrics_data)
                    
                log.info("ML models retrained with latest data")
                
        except Exception as e:
            log.error(f"Error training ML models: {str(e)}")
    
    def _get_ml_training_data(self) -> List[Dict[str, Any]]:
        """Get training data for ML models from process history."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            
            # Get completed process instances
            instances = db.session.query(ProcessInstance).filter(
                ProcessInstance.tenant_id == tenant_id,
                ProcessInstance.completed_at >= cutoff_date,
                ProcessInstance.status.in_(['completed', 'failed'])
            ).limit(1000).all()
            
            training_data = []
            
            for instance in instances:
                duration = 0
                if instance.completed_at and instance.started_at:
                    duration = (instance.completed_at - instance.started_at).total_seconds()
                
                data_point = {
                    'definition_complexity': len(json.loads(instance.definition.process_graph).get('nodes', [])),
                    'input_data_size': len(str(instance.input_data)),
                    'historical_duration': duration,
                    'time_of_day': instance.started_at.hour,
                    'day_of_week': instance.started_at.weekday(),
                    'initiator_experience': 3,  # Default value
                    'outcome': 'success' if instance.status == 'completed' else 'failure',
                    'duration': duration,
                    'steps_count': len(instance.steps),
                    'failure_count': len([s for s in instance.steps if s.status == 'failed']),
                    'memory_usage': 0,  # Would need actual metrics
                    'cpu_usage': 0,     # Would need actual metrics
                    'error_rate': len([s for s in instance.steps if s.status == 'failed']) / max(len(instance.steps), 1)
                }
                
                training_data.append(data_point)
            
            return training_data
            
        except Exception as e:
            log.error(f"Error getting ML training data: {str(e)}")
            return []
    
    def _should_trigger_by_schedule(self, schedule: Dict[str, Any], 
                                  current_time: datetime, 
                                  last_triggered: Optional[datetime]) -> bool:
        """Check if schedule-based trigger should activate."""
        try:
            # Parse schedule configuration
            cron_expression = schedule.get('cron')
            interval_seconds = schedule.get('interval_seconds')
            
            if interval_seconds:
                if not last_triggered:
                    return True
                    
                time_since_last = (current_time - last_triggered).total_seconds()
                return time_since_last >= interval_seconds
            
            # For cron expressions, would need cron parsing library
            # Simplified implementation for hourly/daily schedules
            frequency = schedule.get('frequency', 'hourly')
            
            if frequency == 'hourly':
                if not last_triggered:
                    return True
                return (current_time - last_triggered).total_seconds() >= 3600
            elif frequency == 'daily':
                target_hour = schedule.get('hour', 9)
                if current_time.hour == target_hour:
                    if not last_triggered:
                        return True
                    return (current_time - last_triggered).total_seconds() >= 86400
                    
            return False
            
        except Exception as e:
            log.error(f"Error evaluating schedule: {str(e)}")
            return False
    
    def _evaluate_conditions(self, conditions: List[Dict[str, Any]]) -> bool:
        """Evaluate data conditions for triggering."""
        try:
            for condition in conditions:
                if not self._evaluate_single_condition(condition):
                    return False
            return True
            
        except Exception as e:
            log.error(f"Error evaluating conditions: {str(e)}")
            return False
    
    def _evaluate_single_condition(self, condition: Dict[str, Any]) -> bool:
        """Evaluate a single data condition."""
        try:
            source = condition.get('source')  # database, api, file, etc.
            query = condition.get('query')
            operator = condition.get('operator', '==')
            value = condition.get('value')
            
            current_value = self._get_condition_value(source, query)
            
            return self._compare_values(current_value, value, operator)
            
        except Exception as e:
            log.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_condition_value(self, source: str, query: str) -> Any:
        """Get current value for condition evaluation."""
        # Implementation would depend on source type
        # This is a simplified version
        if source == 'database':
            # Execute database query (with safety checks)
            pass
        elif source == 'metric':
            return self._get_metric_value(query)
        
        return None
    
    def _get_prediction_data(self, trigger: SmartTrigger, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get data for ML prediction."""
        # This would gather relevant data for prediction
        return {
            'definition_complexity': 5,
            'input_data_size': 100,
            'historical_duration': 3600,
            'initiator_experience': 3
        }
    
    def _get_current_metrics(self, trigger: SmartTrigger, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get current system metrics for anomaly detection."""
        # This would gather current system/process metrics
        return {
            'duration': 0,
            'steps_count': 0,
            'failure_count': 0,
            'memory_usage': 0,
            'cpu_usage': 0,
            'error_rate': 0
        }
    
    def _get_metric_value(self, metric: str) -> float:
        """Get current value of a specific metric."""
        # Implementation would fetch from monitoring system
        metrics = {
            'cpu_usage': 45.0,
            'memory_usage': 60.0,
            'error_rate': 0.05,
            'process_count': 10
        }
        
        return metrics.get(metric, 0.0)
    
    def _compare_threshold(self, value: float, threshold: float, operator: str) -> bool:
        """Compare value against threshold using operator."""
        operators = {
            '>': lambda x, y: x > y,
            '<': lambda x, y: x < y,
            '>=': lambda x, y: x >= y,
            '<=': lambda x, y: x <= y,
            '==': lambda x, y: x == y,
            '!=': lambda x, y: x != y
        }
        
        return operators.get(operator, operators['=='])(value, threshold)
    
    def _compare_values(self, value1: Any, value2: Any, operator: str) -> bool:
        """Compare two values using the specified operator."""
        try:
            if operator in ['>', '<', '>=', '<=']:
                return self._compare_threshold(float(value1), float(value2), operator)
            elif operator == '==':
                return value1 == value2
            elif operator == '!=':
                return value1 != value2
            elif operator == 'contains':
                return str(value2) in str(value1)
            elif operator == 'startswith':
                return str(value1).startswith(str(value2))
                
        except (ValueError, TypeError):
            pass
            
        return False
    
    def _execute_webhook_action(self, action: Dict[str, Any], context: Dict[str, Any]):
        """Execute webhook action."""
        # Implementation would make HTTP request
        log.info(f"Webhook action would be executed: {action.get('url')}")
    
    def _execute_notification_action(self, action: Dict[str, Any], context: Dict[str, Any]):
        """Execute notification action."""
        # Implementation would send notification
        log.info(f"Notification would be sent: {action.get('message')}")
    
    def _execute_data_update_action(self, action: Dict[str, Any], context: Dict[str, Any]):
        """Execute data update action."""
        # Implementation would update data
        log.info(f"Data update would be executed: {action.get('target')}")
    
    async def register_event_handler(self, event_type: str, handler: Callable[[TriggerEvent], None]):
        """Register event handler for trigger events."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        
        self.event_handlers[event_type].append(handler)
    
    async def fire_event(self, event: TriggerEvent):
        """Fire a trigger event for evaluation."""
        try:
            # Execute registered handlers
            handlers = self.event_handlers.get(event.event_type, [])
            
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    log.error(f"Error in event handler: {str(e)}")
            
            # Check for event-driven triggers
            await self._evaluate_event_triggers(event)
            
        except Exception as e:
            log.error(f"Error firing event: {str(e)}")
    
    async def _evaluate_event_triggers(self, event: TriggerEvent):
        """Evaluate triggers that respond to specific events."""
        try:
            tenant_id = event.tenant_id or TenantContext.get_current_tenant_id()
            
            triggers = db.session.query(SmartTrigger).filter(
                SmartTrigger.tenant_id == tenant_id,
                SmartTrigger.trigger_type == TriggerType.EVENT_DRIVEN.value,
                SmartTrigger.is_active == True
            ).all()
            
            for trigger in triggers:
                config = json.loads(trigger.configuration) if trigger.configuration else {}
                event_filters = config.get('event_filters', {})
                
                if self._event_matches_filters(event, event_filters):
                    self._activate_trigger(trigger, {
                        'event_type': event.event_type,
                        'event_data': event.data,
                        'event_timestamp': event.timestamp.isoformat()
                    })
                    
        except Exception as e:
            log.error(f"Error evaluating event triggers: {str(e)}")
    
    def _event_matches_filters(self, event: TriggerEvent, filters: Dict[str, Any]) -> bool:
        """Check if event matches trigger filters."""
        try:
            # Check event type
            if 'event_types' in filters:
                if event.event_type not in filters['event_types']:
                    return False
            
            # Check data filters
            if 'data_filters' in filters:
                for filter_expr in filters['data_filters']:
                    if not self._evaluate_data_filter(event.data, filter_expr):
                        return False
            
            return True
            
        except Exception as e:
            log.error(f"Error matching event filters: {str(e)}")
            return False
    
    def _evaluate_data_filter(self, data: Dict[str, Any], filter_expr: Dict[str, Any]) -> bool:
        """Evaluate data filter expression."""
        try:
            field = filter_expr.get('field')
            operator = filter_expr.get('operator', '==')
            value = filter_expr.get('value')
            
            if field not in data:
                return False
                
            return self._compare_values(data[field], value, operator)
            
        except Exception as e:
            log.error(f"Error evaluating data filter: {str(e)}")
            return False
    
    def get_model_status(self) -> Dict[str, Any]:
        """Get status of all ML models."""
        return {
            name: model.get_model_info() 
            for name, model in self.ml_models.items()
        }
    
    def get_trigger_statistics(self) -> Dict[str, Any]:
        """Get statistics about trigger performance."""
        try:
            tenant_id = TenantContext.get_current_tenant_id()
            
            stats = db.session.execute("""
                SELECT 
                    trigger_type,
                    COUNT(*) as total_triggers,
                    SUM(trigger_count) as total_activations,
                    AVG(trigger_count) as avg_activations
                FROM smart_triggers 
                WHERE tenant_id = :tenant_id
                GROUP BY trigger_type
            """, {'tenant_id': tenant_id}).fetchall()
            
            return {
                'trigger_types': {
                    row[0]: {
                        'total_triggers': row[1],
                        'total_activations': row[2],
                        'avg_activations': float(row[3]) if row[3] else 0
                    }
                    for row in stats
                }
            }
            
        except Exception as e:
            log.error(f"Error getting trigger statistics: {str(e)}")
            return {'trigger_types': {}}