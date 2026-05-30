"""
Real-Time Data Synchronization Engine

Handles real-time synchronization of model data changes across all collaboration 
participants with conflict detection, change tracking, and event broadcasting.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Callable
from collections import defaultdict
import threading

from sqlalchemy import event, inspect
from flask import current_app, g

from .models import ModelChangeLog, CollaborationEvent

log = logging.getLogger(__name__)


class ModelChangeProcessor:
    """Processes and tracks changes for a specific model"""
    
    def __init__(self, model_class, sync_fields: List[str] = None):
        self.model_class = model_class
        self.model_name = model_class.__name__
        self.sync_fields = sync_fields or []
        self.change_handlers: List[Callable] = []
        
        # Set up SQLAlchemy event listeners
        self._setup_change_tracking()
        
    def _setup_change_tracking(self):
        """Set up SQLAlchemy event listeners for change detection"""
        
        @event.listens_for(self.model_class, 'after_insert')
        def after_insert(mapper, connection, target):
            self._handle_model_change('INSERT', target, {}, self._get_current_values(target))
            
        @event.listens_for(self.model_class, 'after_update')
        def after_update(mapper, connection, target):
            # Get the changes that were made
            state = inspect(target)
            changes = {}
            
            for attr in state.attrs:
                if attr.key in self.sync_fields or not self.sync_fields:
                    history = attr.load_history()
                    if history.has_changes():
                        old_value = history.deleted[0] if history.deleted else None
                        new_value = history.added[0] if history.added else None
                        changes[attr.key] = {'old': old_value, 'new': new_value}
                        
            if changes:
                old_values = {k: v['old'] for k, v in changes.items()}
                new_values = {k: v['new'] for k, v in changes.items()}
                self._handle_model_change('UPDATE', target, old_values, new_values)
                
        @event.listens_for(self.model_class, 'after_delete')
        def after_delete(mapper, connection, target):
            self._handle_model_change('DELETE', target, self._get_current_values(target), {})
            
    def _handle_model_change(self, change_type: str, target, old_values: Dict, new_values: Dict):
        """Handle a model change event"""
        try:
            record_id = str(getattr(target, 'id', 'unknown'))
            user_id = getattr(g, 'user', {}).get('id') if hasattr(g, 'user') else None
            session_id = getattr(g, 'collaboration_session_id', None) if hasattr(g, 'collaboration_session_id') else None
            
            # Create change log entry
            change_log = ModelChangeLog(
                model_name=self.model_name,
                record_id=record_id,
                change_type=change_type,
                user_id=user_id,
                session_id=session_id,
                old_value=json.dumps(old_values, default=str) if old_values else None,
                new_value=json.dumps(new_values, default=str) if new_values else None
            )
            
            # Note: We can't use the session here as we're in an after_* event
            # This would need to be handled by the sync engine
            
            # Notify change handlers
            change_data = {
                'model_name': self.model_name,
                'record_id': record_id,
                'change_type': change_type,
                'old_values': old_values,
                'new_values': new_values,
                'user_id': user_id,
                'session_id': session_id,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
            for handler in self.change_handlers:
                try:
                    handler(change_data)
                except Exception as e:
                    log.error(f"Error in change handler: {e}")
                    
        except Exception as e:
            log.error(f"Error handling model change: {e}")
            
    def _get_current_values(self, target) -> Dict[str, Any]:
        """Get current field values for a model instance"""
        values = {}
        for field in self.sync_fields or []:
            if hasattr(target, field):
                values[field] = getattr(target, field)
        return values
        
    def add_change_handler(self, handler: Callable):
        """Add a change handler function"""
        self.change_handlers.append(handler)


class RealtimeDataSyncEngine:
    """
    Handles real-time synchronization of model data changes across all 
    collaboration participants with conflict detection and broadcasting.
    """
    
    def __init__(self, websocket_manager=None, session_manager=None, db_session=None):
        self.websocket_manager = websocket_manager
        self.session_manager = session_manager
        self.db = db_session
        
        # Model processors for tracking changes
        self.model_processors: Dict[str, ModelChangeProcessor] = {}
        
        # Change queue for batching and processing
        self.change_queue = []
        self.queue_lock = threading.Lock()
        
        # Event handlers
        self.event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        log.info("Real-time data sync engine initialized")
        
    def register_model_sync(self, model_class, sync_fields: List[str] = None):
        """
        Register a model for real-time synchronization.
        
        :param model_class: SQLAlchemy model class to sync
        :param sync_fields: List of field names to sync (None = all fields)
        """
        try:
            model_name = model_class.__name__
            
            if model_name in self.model_processors:
                log.warning(f"Model {model_name} already registered for sync")
                return
                
            # Create processor for this model
            processor = ModelChangeProcessor(model_class, sync_fields)
            processor.add_change_handler(self._handle_model_change)
            
            self.model_processors[model_name] = processor
            
            log.info(f"Registered model {model_name} for real-time sync with fields: {sync_fields or 'all'}")
            
        except Exception as e:
            log.error(f"Error registering model for sync: {e}")
            
    def sync_model_change(self, model_name: str, record_id: str, 
                         field_changes: Dict[str, Any], user_id: int,
                         session_id: str = None):
        """
        Manually trigger synchronization of a model change.
        
        :param model_name: Name of the model that changed
        :param record_id: ID of the record that changed
        :param field_changes: Dictionary of field changes {field: {'old': val, 'new': val}}
        :param user_id: ID of user who made the change
        :param session_id: Collaboration session ID (optional)
        """
        try:
            # Find active collaboration sessions for this record
            if self.session_manager:
                sessions = self.session_manager.find_sessions_for_record(model_name, record_id)
            else:
                sessions = [session_id] if session_id else []
                
            # Broadcast changes to all relevant sessions
            for sess_id in sessions:
                self._broadcast_change_to_session(
                    sess_id, model_name, record_id, field_changes, user_id
                )
                
            # Log the change for audit trail
            self._log_model_change(model_name, record_id, field_changes, user_id, session_id)
            
        except Exception as e:
            log.error(f"Error syncing model change: {e}")
            
    def sync_field_change(self, session_id: str, model_name: str, record_id: str,
                         field_name: str, old_value: Any, new_value: Any,
                         user_id: int, conflict_resolution: str = 'last_write_wins'):
        """
        Synchronize a single field change with conflict detection.
        
        :param session_id: Collaboration session ID
        :param model_name: Model name
        :param record_id: Record ID
        :param field_name: Field that changed
        :param old_value: Previous field value
        :param new_value: New field value
        :param user_id: User who made the change
        :param conflict_resolution: Strategy for resolving conflicts
        """
        try:
            # Check for concurrent changes (conflict detection)
            conflict_detected = self._detect_field_conflict(
                model_name, record_id, field_name, old_value
            )
            
            if conflict_detected:
                # Handle conflict using specified resolution strategy
                resolution_result = self._resolve_field_conflict(
                    session_id, field_name, old_value, new_value, 
                    conflict_detected, conflict_resolution, user_id
                )
                
                if resolution_result:
                    # Broadcast conflict resolution
                    self._broadcast_conflict_resolution(
                        session_id, model_name, record_id, field_name, resolution_result
                    )
                    return resolution_result
            else:
                # No conflict, proceed with normal sync
                field_changes = {field_name: {'old': old_value, 'new': new_value}}
                self.sync_model_change(model_name, record_id, field_changes, user_id, session_id)
                
                return {
                    'status': 'synced',
                    'field': field_name,
                    'value': new_value
                }
                
        except Exception as e:
            log.error(f"Error syncing field change: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
            
    def register_event_handler(self, event_type: str, handler: Callable):
        """
        Register an event handler for sync events.
        
        :param event_type: Type of event (change, conflict, etc.)
        :param handler: Handler function
        """
        self.event_handlers[event_type].append(handler)
        
    def get_recent_changes(self, model_name: str, record_id: str, 
                          since: datetime = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent changes for a specific record.
        
        :param model_name: Model name
        :param record_id: Record ID
        :param since: Get changes since this timestamp
        :param limit: Maximum number of changes to return
        :return: List of change records
        """
        try:
            if not self.db:
                return []
                
            query = self.db.query(ModelChangeLog).filter(
                ModelChangeLog.model_name == model_name,
                ModelChangeLog.record_id == record_id
            )
            
            if since:
                query = query.filter(ModelChangeLog.created_at >= since)
                
            changes = query.order_by(ModelChangeLog.created_at.desc()).limit(limit).all()
            
            return [
                {
                    'id': change.id,
                    'change_type': change.change_type,
                    'field_name': change.field_name,
                    'old_value': json.loads(change.old_value) if change.old_value else None,
                    'new_value': json.loads(change.new_value) if change.new_value else None,
                    'user_id': change.user_id,
                    'session_id': change.session_id,
                    'timestamp': change.created_at.isoformat()
                }
                for change in changes
            ]
            
        except Exception as e:
            log.error(f"Error getting recent changes: {e}")
            return []
            
    def _handle_model_change(self, change_data: Dict[str, Any]):
        """Handle model change from SQLAlchemy event"""
        try:
            with self.queue_lock:
                self.change_queue.append(change_data)
                
            # Process change immediately for real-time sync
            self._process_change(change_data)
            
        except Exception as e:
            log.error(f"Error handling model change: {e}")
            
    def _process_change(self, change_data: Dict[str, Any]):
        """Process a model change for synchronization"""
        try:
            model_name = change_data['model_name']
            record_id = change_data['record_id']
            user_id = change_data['user_id']
            session_id = change_data.get('session_id')
            
            # Convert old/new values to field changes format
            old_values = change_data.get('old_values', {})
            new_values = change_data.get('new_values', {})
            
            field_changes = {}
            for field in set(old_values.keys()) | set(new_values.keys()):
                field_changes[field] = {
                    'old': old_values.get(field),
                    'new': new_values.get(field)
                }
                
            # Sync the change
            if field_changes:
                self.sync_model_change(model_name, record_id, field_changes, user_id, session_id)
                
        except Exception as e:
            log.error(f"Error processing change: {e}")
            
    def _broadcast_change_to_session(self, session_id: str, model_name: str,
                                   record_id: str, field_changes: Dict[str, Any],
                                   user_id: int):
        """Broadcast a change to all participants in a collaboration session"""
        try:
            if not self.websocket_manager:
                return
                
            # Create change event
            change_event = {
                'type': 'model_change',
                'session_id': session_id,
                'model': model_name,
                'record_id': record_id,
                'changes': field_changes,
                'user_id': user_id,
                'username': self._get_username(user_id),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
            # Broadcast to WebSocket room
            room_id = f"collaboration_{model_name}_{record_id or 'new'}"
            self.websocket_manager.broadcast_to_room(room_id, 'model_changed', change_event)
            
            # Store in event log if database available
            if self.db:
                for field_name, change in field_changes.items():
                    event = CollaborationEvent(
                        session_id=session_id,
                        event_type='model_change',
                        user_id=user_id,
                        model_name=model_name,
                        record_id=record_id,
                        field_name=field_name,
                        old_value=change.get('old'),
                        new_value=change.get('new'),
                        metadata={'broadcast_timestamp': datetime.now(tz=timezone.utc).isoformat()}
                    )
                    self.db.add(event)
                    
                self.db.commit()
                
            # Trigger event handlers
            for handler in self.event_handlers.get('model_change', []):
                try:
                    handler(change_event)
                except Exception as e:
                    log.error(f"Error in model change handler: {e}")
                    
        except Exception as e:
            log.error(f"Error broadcasting change to session: {e}")
            
    def _detect_field_conflict(self, model_name: str, record_id: str,
                              field_name: str, expected_old_value: Any) -> Optional[Dict[str, Any]]:
        """
        Detect if there's a conflict with a field change.
        
        :param model_name: Model name
        :param record_id: Record ID
        :param field_name: Field name
        :param expected_old_value: Expected previous value
        :return: Conflict information if detected, None otherwise
        """
        try:
            if not self.db:
                return None
                
            # Get the most recent change for this field
            recent_change = self.db.query(ModelChangeLog).filter(
                ModelChangeLog.model_name == model_name,
                ModelChangeLog.record_id == record_id,
                ModelChangeLog.field_name == field_name
            ).order_by(ModelChangeLog.created_at.desc()).first()
            
            if recent_change:
                # Parse the stored value
                recent_new_value = json.loads(recent_change.new_value) if recent_change.new_value else None
                
                # Check if the expected old value matches the most recent new value
                if recent_new_value != expected_old_value:
                    return {
                        'type': 'field_conflict',
                        'field': field_name,
                        'expected_old': expected_old_value,
                        'actual_current': recent_new_value,
                        'conflicting_change_id': recent_change.id,
                        'conflicting_user_id': recent_change.user_id,
                        'conflicting_timestamp': recent_change.created_at.isoformat()
                    }
                    
            return None
            
        except Exception as e:
            log.error(f"Error detecting field conflict: {e}")
            return None
            
    def _resolve_field_conflict(self, session_id: str, field_name: str,
                               local_value: Any, remote_value: Any,
                               conflict_info: Dict[str, Any], resolution_strategy: str,
                               user_id: int) -> Optional[Dict[str, Any]]:
        """
        Resolve a field conflict using the specified strategy.
        
        :param session_id: Collaboration session ID
        :param field_name: Field name
        :param local_value: Local user's value
        :param remote_value: Remote value
        :param conflict_info: Information about the conflict
        :param resolution_strategy: Strategy to use for resolution
        :param user_id: User ID requesting resolution
        :return: Resolution result
        """
        try:
            if resolution_strategy == 'last_write_wins':
                # Use the most recent change
                return {
                    'resolution_type': 'automatic',
                    'strategy': 'last_write_wins',
                    'resolved_value': remote_value,
                    'field': field_name
                }
                
            elif resolution_strategy == 'user_choice':
                # Escalate to user for manual resolution
                return {
                    'resolution_type': 'manual_required',
                    'strategy': 'user_choice',
                    'options': {
                        'local': local_value,
                        'remote': remote_value,
                        'merge_suggested': f"{local_value} | {remote_value}"
                    },
                    'field': field_name,
                    'conflict_info': conflict_info
                }
                
            else:
                # Default to last write wins
                return {
                    'resolution_type': 'automatic',
                    'strategy': 'default',
                    'resolved_value': remote_value,
                    'field': field_name
                }
                
        except Exception as e:
            log.error(f"Error resolving field conflict: {e}")
            return None
            
    def _broadcast_conflict_resolution(self, session_id: str, model_name: str,
                                     record_id: str, field_name: str,
                                     resolution_result: Dict[str, Any]):
        """Broadcast conflict resolution to session participants"""
        try:
            if not self.websocket_manager:
                return
                
            room_id = f"collaboration_{model_name}_{record_id or 'new'}"
            
            conflict_event = {
                'type': 'conflict_resolution',
                'session_id': session_id,
                'model': model_name,
                'record_id': record_id,
                'field_name': field_name,
                'resolution': resolution_result,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
            self.websocket_manager.broadcast_to_room(room_id, 'conflict_resolved', conflict_event)
            
        except Exception as e:
            log.error(f"Error broadcasting conflict resolution: {e}")
            
    def _log_model_change(self, model_name: str, record_id: str,
                         field_changes: Dict[str, Any], user_id: int,
                         session_id: str = None):
        """Log model change to database"""
        try:
            if not self.db:
                return
                
            for field_name, change in field_changes.items():
                change_log = ModelChangeLog(
                    model_name=model_name,
                    record_id=record_id,
                    field_name=field_name,
                    old_value=json.dumps(change.get('old'), default=str) if change.get('old') is not None else None,
                    new_value=json.dumps(change.get('new'), default=str) if change.get('new') is not None else None,
                    change_type='UPDATE',
                    user_id=user_id,
                    session_id=session_id
                )
                self.db.add(change_log)
                
            self.db.commit()
            
        except Exception as e:
            log.error(f"Error logging model change: {e}")
            
    def _get_username(self, user_id: int) -> str:
        """Get username from user ID"""
        # This would integrate with PgForge's user system
        return f"User{user_id}"  # Placeholder
        
    def get_sync_stats(self) -> Dict[str, Any]:
        """Get synchronization statistics"""
        return {
            'registered_models': len(self.model_processors),
            'queue_size': len(self.change_queue),
            'event_handlers': {event: len(handlers) for event, handlers in self.event_handlers.items()}
        }