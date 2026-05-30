"""
Conflict Resolution Engine

Advanced conflict resolution for concurrent edits including operational transform
for text conflicts, JSON merge strategies, and user-mediated resolution.
"""

import logging
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple, Union
from collections import defaultdict
import difflib

try:
    # Operational transform library for text conflicts
    from operational_transform import TextOperation
    OPERATIONAL_TRANSFORM_AVAILABLE = True
except ImportError:
    OPERATIONAL_TRANSFORM_AVAILABLE = False

from .models import CollaborationConflict

log = logging.getLogger(__name__)


class ConflictResolutionEngine:
    """
    Handles concurrent editing conflicts with intelligent merge strategies
    including operational transform, JSON merging, and user-mediated resolution.
    """
    
    def __init__(self, session_manager=None, db_session=None, websocket_manager=None):
        self.session_manager = session_manager
        self.db = db_session
        self.websocket_manager = websocket_manager
        
        # Conflict resolution strategies
        self.conflict_resolvers = {
            'text': self._resolve_text_conflict,
            'string': self._resolve_string_conflict,
            'json': self._resolve_json_conflict,
            'list': self._resolve_list_conflict,
            'number': self._resolve_number_conflict,
            'boolean': self._resolve_boolean_conflict,
            'default': self._resolve_default_conflict
        }
        
        # Configuration
        self.auto_resolve_threshold = 0.8  # Auto-resolve if confidence > 80%
        self.max_conflict_history = 100  # Keep last 100 conflicts for analysis
        
        log.info("Conflict resolution engine initialized")
        
    def resolve_conflict(self, session_id: str, field_name: str, 
                        local_change: Dict[str, Any], remote_change: Dict[str, Any],
                        base_value: Any = None, strategy: str = 'auto') -> Dict[str, Any]:
        """
        Resolve conflicts between concurrent changes with multiple strategies.
        
        :param session_id: Collaboration session ID
        :param field_name: Name of the field with conflict
        :param local_change: Local user's change data
        :param remote_change: Remote user's change data  
        :param base_value: Original value before both changes
        :param strategy: Resolution strategy ('auto', 'manual', 'last_write', etc.)
        :return: Resolution result with resolved value and metadata
        """
        try:
            # Detect field type for appropriate resolution strategy
            field_type = self._detect_field_type(local_change.get('new_value'))
            resolver = self.conflict_resolvers.get(field_type, self.conflict_resolvers['default'])
            
            # Attempt automatic resolution
            if strategy == 'auto':
                resolution = resolver(local_change, remote_change, base_value)
                
                # Check confidence level
                if resolution.get('confidence', 0) >= self.auto_resolve_threshold:
                    resolution['resolution_type'] = 'automatic'
                    resolution['strategy'] = field_type
                else:
                    # Escalate to user choice
                    resolution = self._create_user_resolution_prompt(
                        local_change, remote_change, base_value, field_name
                    )
                    resolution['resolution_type'] = 'manual_required'
                    
            elif strategy == 'last_write':
                resolution = self._resolve_last_write_wins(local_change, remote_change)
                resolution['resolution_type'] = 'automatic'
                resolution['strategy'] = 'last_write_wins'
                
            elif strategy == 'first_write':
                resolution = self._resolve_first_write_wins(local_change, remote_change, base_value)
                resolution['resolution_type'] = 'automatic'
                resolution['strategy'] = 'first_write_wins'
                
            elif strategy == 'manual':
                resolution = self._create_user_resolution_prompt(
                    local_change, remote_change, base_value, field_name
                )
                resolution['resolution_type'] = 'manual_required'
                
            else:
                # Default to automatic with detected type
                resolution = resolver(local_change, remote_change, base_value)
                resolution['resolution_type'] = 'automatic'
                resolution['strategy'] = field_type
                
            # Log conflict resolution
            conflict_record = self._log_conflict_resolution(
                session_id, field_name, local_change, remote_change, resolution
            )
            
            resolution['conflict_id'] = conflict_record.id if conflict_record else None
            resolution['timestamp'] = datetime.now(tz=timezone.utc).isoformat()
            
            return resolution
            
        except Exception as e:
            log.error(f"Error resolving conflict: {e}")
            # Fallback to simple resolution
            return self._create_error_resolution(str(e), local_change, remote_change)
            
    def resolve_user_choice(self, conflict_id: int, chosen_resolution: str,
                           custom_value: Any = None, user_id: int = None) -> Dict[str, Any]:
        """
        Resolve a conflict based on user choice.
        
        :param conflict_id: ID of the conflict record
        :param chosen_resolution: User's choice ('local', 'remote', 'merge', 'custom')
        :param custom_value: Custom value if chosen_resolution is 'custom'
        :param user_id: ID of user making the resolution
        :return: Final resolution result
        """
        try:
            if not self.db:
                return {'status': 'error', 'message': 'Database not available'}
                
            # Get conflict record
            conflict = self.db.query(CollaborationConflict).get(conflict_id)
            if not conflict:
                return {'status': 'error', 'message': 'Conflict not found'}
                
            # Determine resolved value based on choice
            if chosen_resolution == 'local':
                resolved_value = conflict.local_change.get('new_value')
            elif chosen_resolution == 'remote':
                resolved_value = conflict.remote_change.get('new_value')
            elif chosen_resolution == 'merge':
                # Attempt automatic merge
                local_val = conflict.local_change.get('new_value')
                remote_val = conflict.remote_change.get('new_value')
                resolved_value = self._attempt_auto_merge(local_val, remote_val)
            elif chosen_resolution == 'custom':
                resolved_value = custom_value
            else:
                return {'status': 'error', 'message': 'Invalid resolution choice'}
                
            # Update conflict record
            conflict.resolution = {
                'type': 'user_choice',
                'choice': chosen_resolution,
                'resolved_value': resolved_value,
                'resolved_by': user_id
            }
            conflict.resolution_method = 'manual'
            conflict.resolved_by = user_id
            conflict.resolved_at = datetime.now(tz=timezone.utc)
            
            self.db.commit()
            
            # Broadcast resolution to session participants
            if self.websocket_manager and conflict.session_id:
                self._broadcast_resolution(conflict.session_id, conflict, resolved_value)
                
            return {
                'status': 'resolved',
                'conflict_id': conflict_id,
                'resolved_value': resolved_value,
                'resolution_method': 'manual',
                'choice': chosen_resolution
            }
            
        except Exception as e:
            log.error(f"Error resolving user choice: {e}")
            return {'status': 'error', 'message': str(e)}
            
    def get_conflict_history(self, session_id: str, field_name: str = None,
                           limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get conflict resolution history for a session.
        
        :param session_id: Collaboration session ID
        :param field_name: Specific field name (optional)
        :param limit: Maximum number of conflicts to return
        :return: List of conflict records
        """
        try:
            if not self.db:
                return []
                
            query = self.db.query(CollaborationConflict).filter(
                CollaborationConflict.session_id == session_id
            )
            
            if field_name:
                query = query.filter(CollaborationConflict.field_name == field_name)
                
            conflicts = query.order_by(CollaborationConflict.created_at.desc()).limit(limit).all()
            
            return [
                {
                    'conflict_id': conflict.id,
                    'field_name': conflict.field_name,
                    'conflict_type': conflict.conflict_type,
                    'local_change': conflict.local_change,
                    'remote_change': conflict.remote_change,
                    'resolution': conflict.resolution,
                    'resolution_method': conflict.resolution_method,
                    'resolved_by': conflict.resolved_by,
                    'created_at': conflict.created_at.isoformat(),
                    'resolved_at': conflict.resolved_at.isoformat() if conflict.resolved_at else None
                }
                for conflict in conflicts
            ]
            
        except Exception as e:
            log.error(f"Error getting conflict history: {e}")
            return []
            
    def _resolve_text_conflict(self, local_change: Dict, remote_change: Dict, 
                              base_value: Any = None) -> Dict[str, Any]:
        """Resolve text conflicts using operational transform or diff merging"""
        try:
            if not OPERATIONAL_TRANSFORM_AVAILABLE:
                return self._resolve_text_diff(local_change, remote_change, base_value)
                
            local_text = str(local_change.get('new_value', ''))
            remote_text = str(remote_change.get('new_value', ''))
            base_text = str(base_value or local_change.get('old_value', ''))
            
            # If we have operational transform operations, use them
            if 'operation' in local_change and 'operation' in remote_change:
                return self._resolve_with_operational_transform(local_change, remote_change)
                
            # Otherwise, use 3-way merge
            return self._resolve_text_three_way_merge(base_text, local_text, remote_text)
            
        except Exception as e:
            log.error(f"Error in text conflict resolution: {e}")
            return self._resolve_string_conflict(local_change, remote_change, base_value)
            
    def _resolve_with_operational_transform(self, local_change: Dict, remote_change: Dict) -> Dict[str, Any]:
        """Resolve using operational transform operations"""
        try:
            local_op = TextOperation.from_json(local_change['operation'])
            remote_op = TextOperation.from_json(remote_change['operation'])
            base_text = local_change.get('old_value', '')
            
            # Transform operations against each other
            local_prime, remote_prime = local_op.transform(remote_op)
            
            # Apply both transformations
            result_text = remote_prime.apply(local_prime.apply(base_text))
            
            return {
                'resolved_value': result_text,
                'method': 'operational_transform',
                'confidence': 0.95,
                'operations_applied': [local_prime.to_json(), remote_prime.to_json()],
                'metadata': {
                    'base_length': len(base_text),
                    'result_length': len(result_text),
                    'operations_count': 2
                }
            }
            
        except Exception as e:
            log.error(f"Operational transform failed: {e}")
            # Fallback to simple text merge
            return self._resolve_text_diff(local_change, remote_change)
            
    def _resolve_text_three_way_merge(self, base_text: str, local_text: str, 
                                     remote_text: str) -> Dict[str, Any]:
        """Perform 3-way text merge using difflib"""
        try:
            # If one side didn't change, use the other
            if base_text == local_text:
                return {
                    'resolved_value': remote_text,
                    'method': 'three_way_merge',
                    'confidence': 1.0,
                    'reason': 'local_unchanged'
                }
            elif base_text == remote_text:
                return {
                    'resolved_value': local_text,
                    'method': 'three_way_merge',
                    'confidence': 1.0,
                    'reason': 'remote_unchanged'
                }
                
            # Both sides changed, attempt merge
            local_lines = local_text.splitlines(keepends=True)
            remote_lines = remote_text.splitlines(keepends=True)
            base_lines = base_text.splitlines(keepends=True)
            
            # Create unified diff
            local_diff = list(difflib.unified_diff(base_lines, local_lines, lineterm=''))
            remote_diff = list(difflib.unified_diff(base_lines, remote_lines, lineterm=''))
            
            # Check if changes are non-overlapping
            if self._are_changes_non_overlapping(local_diff, remote_diff):
                # Merge non-overlapping changes
                merged_lines = self._merge_non_overlapping_changes(base_lines, local_diff, remote_diff)
                return {
                    'resolved_value': ''.join(merged_lines),
                    'method': 'three_way_merge',
                    'confidence': 0.85,
                    'reason': 'non_overlapping_changes'
                }
            else:
                # Overlapping changes - require user input
                return {
                    'resolved_value': None,
                    'method': 'three_way_merge',
                    'confidence': 0.0,
                    'reason': 'overlapping_changes',
                    'merge_conflicts': True
                }
                
        except Exception as e:
            log.error(f"Error in three-way merge: {e}")
            return self._resolve_text_diff(local_change={'new_value': local_text}, 
                                         remote_change={'new_value': remote_text})
            
    def _resolve_text_diff(self, local_change: Dict, remote_change: Dict, 
                          base_value: Any = None) -> Dict[str, Any]:
        """Simple text diff resolution"""
        local_text = str(local_change.get('new_value', ''))
        remote_text = str(remote_change.get('new_value', ''))
        
        # Calculate similarity
        similarity = difflib.SequenceMatcher(None, local_text, remote_text).ratio()
        
        if similarity > 0.8:
            # Very similar - use longer version
            resolved = local_text if len(local_text) > len(remote_text) else remote_text
            return {
                'resolved_value': resolved,
                'method': 'text_diff',
                'confidence': similarity,
                'reason': 'high_similarity'
            }
        else:
            # Different - require user choice
            return {
                'resolved_value': None,
                'method': 'text_diff',
                'confidence': 0.0,
                'reason': 'low_similarity',
                'similarity': similarity
            }
            
    def _resolve_json_conflict(self, local_change: Dict, remote_change: Dict, 
                              base_value: Any = None) -> Dict[str, Any]:
        """Resolve JSON object conflicts by merging non-overlapping keys"""
        try:
            local_json = local_change.get('new_value', {})
            remote_json = remote_change.get('new_value', {})
            base_json = base_value or local_change.get('old_value', {})
            
            if not isinstance(local_json, dict) or not isinstance(remote_json, dict):
                return {'resolved_value': None, 'method': 'json', 'confidence': 0.0}
                
            # Find changed keys in each version
            local_changes = self._get_json_changes(base_json, local_json)
            remote_changes = self._get_json_changes(base_json, remote_json)
            
            # Check for overlapping changes
            overlapping_keys = set(local_changes.keys()) & set(remote_changes.keys())
            
            if not overlapping_keys:
                # No overlapping changes - merge both
                merged = base_json.copy()
                merged.update(local_changes)
                merged.update(remote_changes)
                
                return {
                    'resolved_value': merged,
                    'method': 'json_merge',
                    'confidence': 0.9,
                    'reason': 'non_overlapping_keys'
                }
            else:
                # Overlapping changes - attempt value merge
                merged = base_json.copy()
                conflicts = []
                
                # Apply non-conflicting changes
                for key in (set(local_changes.keys()) | set(remote_changes.keys())) - overlapping_keys:
                    if key in local_changes:
                        merged[key] = local_changes[key]
                    else:
                        merged[key] = remote_changes[key]
                        
                # Handle conflicting keys
                for key in overlapping_keys:
                    local_val = local_changes[key]
                    remote_val = remote_changes[key]
                    
                    if local_val == remote_val:
                        # Same value - no conflict
                        merged[key] = local_val
                    else:
                        # Different values - keep both for user choice
                        conflicts.append({
                            'key': key,
                            'local_value': local_val,
                            'remote_value': remote_val
                        })
                        # Use local value as default
                        merged[key] = local_val
                        
                return {
                    'resolved_value': merged if not conflicts else None,
                    'method': 'json_merge',
                    'confidence': 0.5 if conflicts else 0.9,
                    'conflicts': conflicts,
                    'reason': 'overlapping_keys' if conflicts else 'resolved_conflicts'
                }
                
        except Exception as e:
            log.error(f"Error in JSON conflict resolution: {e}")
            return {'resolved_value': None, 'method': 'json', 'confidence': 0.0, 'error': str(e)}
            
    def _resolve_list_conflict(self, local_change: Dict, remote_change: Dict, 
                              base_value: Any = None) -> Dict[str, Any]:
        """Resolve list/array conflicts"""
        try:
            local_list = local_change.get('new_value', [])
            remote_list = remote_change.get('new_value', [])
            base_list = base_value or local_change.get('old_value', [])
            
            if not isinstance(local_list, list) or not isinstance(remote_list, list):
                return {'resolved_value': None, 'method': 'list', 'confidence': 0.0}
                
            # Simple strategies for list merging
            local_additions = [item for item in local_list if item not in base_list]
            remote_additions = [item for item in remote_list if item not in base_list]
            local_removals = [item for item in base_list if item not in local_list]
            remote_removals = [item for item in base_list if item not in remote_list]
            
            # Start with base list
            merged = base_list.copy()
            
            # Add items that were added by either side
            for item in local_additions:
                if item not in merged:
                    merged.append(item)
            for item in remote_additions:
                if item not in merged:
                    merged.append(item)
                    
            # Remove items that were removed by either side
            for item in set(local_removals) | set(remote_removals):
                while item in merged:
                    merged.remove(item)
                    
            return {
                'resolved_value': merged,
                'method': 'list_merge',
                'confidence': 0.8,
                'additions': len(local_additions) + len(remote_additions),
                'removals': len(set(local_removals) | set(remote_removals))
            }
            
        except Exception as e:
            log.error(f"Error in list conflict resolution: {e}")
            return {'resolved_value': None, 'method': 'list', 'confidence': 0.0, 'error': str(e)}
            
    def _resolve_number_conflict(self, local_change: Dict, remote_change: Dict, 
                               base_value: Any = None) -> Dict[str, Any]:
        """Resolve numeric conflicts"""
        try:
            local_num = local_change.get('new_value')
            remote_num = remote_change.get('new_value')
            base_num = base_value or local_change.get('old_value', 0)
            
            # Calculate the changes
            local_delta = local_num - base_num if isinstance(local_num, (int, float)) else 0
            remote_delta = remote_num - base_num if isinstance(remote_num, (int, float)) else 0
            
            # If both are additive/subtractive changes, combine them
            if (local_delta > 0 and remote_delta > 0) or (local_delta < 0 and remote_delta < 0):
                resolved = base_num + local_delta + remote_delta
                return {
                    'resolved_value': resolved,
                    'method': 'numeric_combine',
                    'confidence': 0.85,
                    'local_delta': local_delta,
                    'remote_delta': remote_delta
                }
            else:
                # Conflicting changes - use average or require user choice
                if abs(local_delta) == abs(remote_delta):
                    # Equal magnitude opposite changes - use base value
                    return {
                        'resolved_value': base_num,
                        'method': 'numeric_cancel',
                        'confidence': 0.7,
                        'reason': 'equal_opposite_changes'
                    }
                else:
                    # Use the larger absolute change
                    resolved = local_num if abs(local_delta) > abs(remote_delta) else remote_num
                    return {
                        'resolved_value': resolved,
                        'method': 'numeric_max_change',
                        'confidence': 0.6,
                        'reason': 'larger_change_wins'
                    }
                    
        except Exception as e:
            log.error(f"Error in numeric conflict resolution: {e}")
            return {'resolved_value': None, 'method': 'numeric', 'confidence': 0.0, 'error': str(e)}
            
    def _resolve_string_conflict(self, local_change: Dict, remote_change: Dict, 
                               base_value: Any = None) -> Dict[str, Any]:
        """Resolve simple string conflicts"""
        local_str = str(local_change.get('new_value', ''))
        remote_str = str(remote_change.get('new_value', ''))
        
        if local_str == remote_str:
            return {
                'resolved_value': local_str,
                'method': 'string_identical',
                'confidence': 1.0
            }
        else:
            # Check if one is a substring of the other
            if local_str in remote_str:
                return {
                    'resolved_value': remote_str,
                    'method': 'string_contains',
                    'confidence': 0.8,
                    'reason': 'remote_contains_local'
                }
            elif remote_str in local_str:
                return {
                    'resolved_value': local_str,
                    'method': 'string_contains',
                    'confidence': 0.8,
                    'reason': 'local_contains_remote'
                }
            else:
                return {
                    'resolved_value': None,
                    'method': 'string_different',
                    'confidence': 0.0,
                    'reason': 'strings_incompatible'
                }
                
    def _resolve_boolean_conflict(self, local_change: Dict, remote_change: Dict, 
                                base_value: Any = None) -> Dict[str, Any]:
        """Resolve boolean conflicts"""
        local_bool = local_change.get('new_value')
        remote_bool = remote_change.get('new_value')
        
        if local_bool == remote_bool:
            return {
                'resolved_value': local_bool,
                'method': 'boolean_identical',
                'confidence': 1.0
            }
        else:
            # Boolean conflicts require user choice
            return {
                'resolved_value': None,
                'method': 'boolean_conflict',
                'confidence': 0.0,
                'reason': 'boolean_values_differ'
            }
            
    def _resolve_default_conflict(self, local_change: Dict, remote_change: Dict, 
                                base_value: Any = None) -> Dict[str, Any]:
        """Default conflict resolution (last write wins)"""
        return self._resolve_last_write_wins(local_change, remote_change)
        
    def _resolve_last_write_wins(self, local_change: Dict, remote_change: Dict) -> Dict[str, Any]:
        """Last write wins conflict resolution"""
        local_time = local_change.get('timestamp', datetime.min.isoformat())
        remote_time = remote_change.get('timestamp', datetime.min.isoformat())
        
        if remote_time > local_time:
            return {
                'resolved_value': remote_change.get('new_value'),
                'method': 'last_write_wins',
                'confidence': 0.7,
                'winner': 'remote'
            }
        else:
            return {
                'resolved_value': local_change.get('new_value'),
                'method': 'last_write_wins',
                'confidence': 0.7,
                'winner': 'local'
            }
            
    def _resolve_first_write_wins(self, local_change: Dict, remote_change: Dict, 
                                base_value: Any = None) -> Dict[str, Any]:
        """First write wins conflict resolution"""
        local_time = local_change.get('timestamp', datetime.max.isoformat())
        remote_time = remote_change.get('timestamp', datetime.max.isoformat())
        
        if local_time < remote_time:
            return {
                'resolved_value': local_change.get('new_value'),
                'method': 'first_write_wins',
                'confidence': 0.7,
                'winner': 'local'
            }
        else:
            return {
                'resolved_value': remote_change.get('new_value'),
                'method': 'first_write_wins',
                'confidence': 0.7,
                'winner': 'remote'
            }
            
    def _create_user_resolution_prompt(self, local_change: Dict, remote_change: Dict, 
                                     base_value: Any, field_name: str) -> Dict[str, Any]:
        """Create a user resolution prompt for manual conflict resolution"""
        return {
            'resolution_type': 'manual_required',
            'field_name': field_name,
            'options': {
                'local': {
                    'value': local_change.get('new_value'),
                    'user_id': local_change.get('user_id'),
                    'timestamp': local_change.get('timestamp')
                },
                'remote': {
                    'value': remote_change.get('new_value'),
                    'user_id': remote_change.get('user_id'),
                    'timestamp': remote_change.get('timestamp')
                },
                'base': {
                    'value': base_value
                }
            },
            'suggested_merge': self._attempt_auto_merge(
                local_change.get('new_value'),
                remote_change.get('new_value')
            )
        }
        
    def _create_error_resolution(self, error_message: str, local_change: Dict, 
                               remote_change: Dict) -> Dict[str, Any]:
        """Create error resolution when conflict resolution fails"""
        return {
            'resolved_value': local_change.get('new_value'),  # Default to local
            'method': 'error_fallback',
            'confidence': 0.1,
            'error': error_message,
            'fallback_reason': 'resolution_error'
        }
        
    def _attempt_auto_merge(self, local_value: Any, remote_value: Any) -> Any:
        """Attempt simple auto-merge of two values"""
        if isinstance(local_value, str) and isinstance(remote_value, str):
            return f"{local_value}\n---MERGE---\n{remote_value}"
        elif isinstance(local_value, list) and isinstance(remote_value, list):
            return list(set(local_value + remote_value))
        elif isinstance(local_value, dict) and isinstance(remote_value, dict):
            merged = local_value.copy()
            merged.update(remote_value)
            return merged
        else:
            return local_value
            
    def _detect_field_type(self, value: Any) -> str:
        """Detect the type of field for appropriate conflict resolution"""
        if isinstance(value, str):
            if len(value) > 100:  # Longer strings treated as text
                return 'text'
            else:
                return 'string'
        elif isinstance(value, (int, float)):
            return 'number'
        elif isinstance(value, bool):
            return 'boolean'
        elif isinstance(value, list):
            return 'list'
        elif isinstance(value, dict):
            return 'json'
        else:
            return 'default'
            
    def _get_json_changes(self, base_dict: Dict, new_dict: Dict) -> Dict[str, Any]:
        """Get changes between two dictionaries"""
        changes = {}
        for key, value in new_dict.items():
            if key not in base_dict or base_dict[key] != value:
                changes[key] = value
        return changes
        
    def _are_changes_non_overlapping(self, local_diff: List, remote_diff: List) -> bool:
        """Check if two diffs have non-overlapping line changes"""
        # This is a simplified implementation
        # In practice, you'd need more sophisticated diff analysis
        local_lines = set()
        remote_lines = set()
        
        for line in local_diff:
            if line.startswith('@@'):
                # Extract line numbers from diff header
                match = re.search(r'\+(\d+)', line)
                if match:
                    local_lines.add(int(match.group(1)))
                    
        for line in remote_diff:
            if line.startswith('@@'):
                match = re.search(r'\+(\d+)', line)
                if match:
                    remote_lines.add(int(match.group(1)))
                    
        return len(local_lines & remote_lines) == 0
        
    def _merge_non_overlapping_changes(self, base_lines: List, local_diff: List, 
                                     remote_diff: List) -> List[str]:
        """Merge non-overlapping changes (simplified implementation)"""
        # This is a placeholder - real implementation would need proper diff merging
        return base_lines
        
    def _log_conflict_resolution(self, session_id: str, field_name: str,
                               local_change: Dict, remote_change: Dict,
                               resolution: Dict) -> Optional[CollaborationConflict]:
        """Log conflict resolution to database"""
        try:
            if not self.db:
                return None
                
            conflict_type = self._detect_field_type(local_change.get('new_value'))
            
            conflict = CollaborationConflict(
                session_id=session_id,
                field_name=field_name,
                conflict_type=conflict_type,
                local_change=local_change,
                remote_change=remote_change,
                resolution=resolution,
                resolution_method=resolution.get('method', 'unknown')
            )
            
            # Set resolved status if automatically resolved
            if resolution.get('resolution_type') == 'automatic':
                conflict.resolved_at = datetime.now(tz=timezone.utc)
                
            self.db.add(conflict)
            self.db.commit()
            
            return conflict
            
        except Exception as e:
            log.error(f"Error logging conflict resolution: {e}")
            return None
            
    def _broadcast_resolution(self, session_id: str, conflict: CollaborationConflict, 
                            resolved_value: Any):
        """Broadcast conflict resolution to session participants"""
        try:
            if not self.websocket_manager:
                return
                
            session_info = self.session_manager.get_session_info(session_id) if self.session_manager else None
            if not session_info:
                return
                
            room_id = f"collaboration_{session_info['model_name']}_{session_info['record_id'] or 'new'}"
            
            resolution_event = {
                'type': 'conflict_resolved',
                'conflict_id': conflict.id,
                'session_id': session_id,
                'field_name': conflict.field_name,
                'resolved_value': resolved_value,
                'resolution_method': conflict.resolution_method,
                'resolved_by': conflict.resolved_by,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
            self.websocket_manager.broadcast_to_room(room_id, 'conflict_resolved', resolution_event)
            
        except Exception as e:
            log.error(f"Error broadcasting resolution: {e}")
            
    def get_resolution_stats(self) -> Dict[str, Any]:
        """Get conflict resolution statistics"""
        try:
            if not self.db:
                return {'total_conflicts': 0, 'resolution_methods': {}}
                
            # Get total conflicts
            total_conflicts = self.db.query(CollaborationConflict).count()
            
            # Get resolution method breakdown
            method_counts = self.db.query(
                CollaborationConflict.resolution_method,
                self.db.func.count(CollaborationConflict.id)
            ).group_by(CollaborationConflict.resolution_method).all()
            
            resolution_methods = {method: count for method, count in method_counts}
            
            # Get auto-resolution rate
            auto_resolved = self.db.query(CollaborationConflict).filter(
                CollaborationConflict.resolution_method.in_(['automatic', 'text', 'json', 'list'])
            ).count()
            
            auto_resolution_rate = (auto_resolved / total_conflicts * 100) if total_conflicts > 0 else 0
            
            return {
                'total_conflicts': total_conflicts,
                'resolution_methods': resolution_methods,
                'auto_resolution_rate': auto_resolution_rate,
                'manual_resolution_rate': 100 - auto_resolution_rate
            }
            
        except Exception as e:
            log.error(f"Error getting resolution stats: {e}")
            return {'total_conflicts': 0, 'resolution_methods': {}, 'error': str(e)}