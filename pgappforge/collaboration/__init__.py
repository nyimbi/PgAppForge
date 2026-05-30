"""
PgForge Real-Time Collaboration Engine

This module provides comprehensive real-time collaboration capabilities including:
- WebSocket-based communication
- Session management and presence tracking
- Conflict resolution for concurrent edits
- Integration with PgForge security and permissions
"""

from .websocket_manager import CollaborationWebSocketManager
from .session_manager import CollaborationSessionManager
from .sync_engine import RealtimeDataSyncEngine
from .conflict_resolver import ConflictResolutionEngine

__all__ = [
    'CollaborationWebSocketManager',
    'CollaborationSessionManager', 
    'RealtimeDataSyncEngine',
    'ConflictResolutionEngine'
]

# Global collaboration manager instance
_collaboration_manager = None

def get_collaboration_manager():
    """Get the global collaboration manager instance"""
    global _collaboration_manager
    return _collaboration_manager

def init_collaboration(app, db, security_manager):
    """Initialize collaboration system with Flask app"""
    global _collaboration_manager
    
    from .collaboration_manager import CollaborationManager
    _collaboration_manager = CollaborationManager(app, db, security_manager)
    _collaboration_manager.init_app()
    
    return _collaboration_manager