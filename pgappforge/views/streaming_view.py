"""
Real-Time Graph Streaming View

Provides WebSocket endpoints and management interface for real-time graph streaming,
live updates, and change notifications.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden

from ..database.graph_streaming import (
    get_streaming_manager,
    get_change_detector,
    GraphStreamingManager,
    GraphChangeDetector,
    StreamingMode,
    GraphChangeType
)
from ..database.graph_manager import get_graph_manager
from ..database.activity_tracker import (
    track_database_activity,
    ActivityType,
    ActivitySeverity
)
from ..utils.error_handling import (
    WizardErrorHandler,
    WizardErrorType,
    WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class GraphStreamingView(BaseView):
    """
    Real-time graph streaming management interface
    
    Provides WebSocket session management, streaming controls,
    and real-time monitoring capabilities.
    """
    
    route_base = "/graph/streaming"
    default_view = "index"
    
    def __init__(self):
        """Initialize streaming view"""
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.streaming_manager = None
        self.change_detector = None
    
    def _ensure_admin_access(self):
        """Ensure current user has admin privileges"""
        try:
            from flask_login import current_user
            
            if not current_user or not current_user.is_authenticated:
                raise Forbidden("Authentication required")
            
            # Check if user has admin role
            if hasattr(current_user, "roles"):
                admin_roles = ["Admin", "admin", "Administrator", "administrator"]
                user_roles = [
                    role.name if hasattr(role, "name") else str(role)
                    for role in current_user.roles
                ]
                
                if not any(role in admin_roles for role in user_roles):
                    raise Forbidden("Administrator privileges required")
            else:
                # Fallback check for is_admin attribute
                if not getattr(current_user, "is_admin", False):
                    raise Forbidden("Administrator privileges required")
                    
        except Exception as e:
            logger.error(f"Admin access check failed: {e}")
            raise Forbidden("Access denied")
    
    def _get_streaming_manager(self) -> GraphStreamingManager:
        """Get or initialize streaming manager"""
        try:
            return get_streaming_manager()
        except Exception as e:
            logger.error(f"Failed to initialize streaming manager: {e}")
            self.error_handler.handle_error(
                e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
            )
            raise
    
    def _get_change_detector(self) -> GraphChangeDetector:
        """Get or initialize change detector"""
        try:
            return get_change_detector()
        except Exception as e:
            logger.error(f"Failed to initialize change detector: {e}")
            raise
    
    @expose("/")
    @has_access
    @permission_name("can_stream_graphs")
    def index(self):
        """Main streaming dashboard"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            statistics = streaming_manager.get_session_statistics()
            
            # Get graph schema for context
            graph_manager = get_graph_manager()
            schema = graph_manager.get_graph_schema()
            
            return render_template(
                "streaming/index.html",
                title="Real-Time Graph Streaming",
                statistics=statistics,
                schema=schema.to_dict()
            )
            
        except Exception as e:
            logger.error(f"Error in streaming dashboard: {e}")
            flash(f"Error loading streaming dashboard: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/monitor/")
    @has_access
    @permission_name("can_stream_graphs")
    def monitor(self):
        """Real-time monitoring interface"""
        try:
            self._ensure_admin_access()
            
            return render_template(
                "streaming/monitor.html",
                title="Real-Time Graph Monitor"
            )
            
        except Exception as e:
            logger.error(f"Error in streaming monitor: {e}")
            flash(f"Error loading streaming monitor: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    @expose("/sessions/")
    @has_access
    @permission_name("can_stream_graphs")
    def sessions(self):
        """Streaming sessions management"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            statistics = streaming_manager.get_session_statistics()
            
            return render_template(
                "streaming/sessions.html",
                title="Streaming Sessions",
                sessions=statistics.get("session_details", [])
            )
            
        except Exception as e:
            logger.error(f"Error in sessions interface: {e}")
            flash(f"Error loading sessions: {str(e)}", "error")
            return render_template("graph/error.html", error=str(e))
    
    # API Endpoints
    
    @expose_api("post", "/api/sessions/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_create_session(self):
        """API endpoint to create streaming session"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            
            # Get parameters
            user_id = data.get("user_id", "anonymous")
            graph_name = data.get("graph_name", "default_graph")
            filters = data.get("filters", {})
            mode = StreamingMode(data.get("mode", "real_time"))
            
            streaming_manager = self._get_streaming_manager()
            session = streaming_manager.create_session(
                session_id=session_id,
                user_id=user_id,
                graph_name=graph_name,
                filters=filters,
                mode=mode
            )
            
            return jsonify({
                "success": True,
                "session": session.to_dict()
            })
            
        except Exception as e:
            logger.error(f"API error creating streaming session: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/sessions/<session_id>/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_get_session(self, session_id: str):
        """API endpoint to get streaming session"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            session = streaming_manager.get_session(session_id)
            
            if not session:
                return jsonify({"success": False, "error": "Session not found"}), 404
            
            return jsonify({
                "success": True,
                "session": session.to_dict()
            })
            
        except Exception as e:
            logger.error(f"API error getting session: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("delete", "/api/sessions/<session_id>/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_close_session(self, session_id: str):
        """API endpoint to close streaming session"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            streaming_manager.close_session(session_id)
            
            return jsonify({
                "success": True,
                "message": f"Session {session_id} closed"
            })
            
        except Exception as e:
            logger.error(f"API error closing session: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/statistics/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_get_statistics(self):
        """API endpoint to get streaming statistics"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            statistics = streaming_manager.get_session_statistics()
            
            return jsonify({
                "success": True,
                "statistics": statistics
            })
            
        except Exception as e:
            logger.error(f"API error getting statistics: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/broadcast/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_broadcast_message(self):
        """API endpoint to broadcast message to sessions"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")
            
            graph_name = data.get("graph_name", "default_graph")
            message = data.get("message", {})
            
            if not message:
                raise BadRequest("Message is required")
            
            streaming_manager = self._get_streaming_manager()
            sent_count = streaming_manager.broadcast_to_graph(graph_name, message)
            
            # Track broadcast activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target="Broadcast Message",
                description=f"Broadcast message to {sent_count} streaming sessions",
                details={
                    "graph_name": graph_name,
                    "message_type": message.get("type", "unknown"),
                    "recipients": sent_count
                }
            )
            
            return jsonify({
                "success": True,
                "recipients": sent_count,
                "message": "Message broadcast successfully"
            })
            
        except Exception as e:
            logger.error(f"API error broadcasting message: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/simulate/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_simulate_activity(self):
        """API endpoint to simulate graph activity"""
        try:
            self._ensure_admin_access()
            
            data = request.get_json() or {}
            graph_name = data.get("graph_name", "default_graph")
            
            streaming_manager = self._get_streaming_manager()
            streaming_manager.simulate_graph_activity(graph_name)
            
            # Track simulation activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target="Activity Simulation",
                description=f"Simulated graph activity for testing",
                details={
                    "graph_name": graph_name,
                    "simulated_events": 5
                }
            )
            
            return jsonify({
                "success": True,
                "message": "Graph activity simulated successfully"
            })
            
        except Exception as e:
            logger.error(f"API error simulating activity: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("post", "/api/cleanup/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_cleanup_sessions(self):
        """API endpoint to cleanup inactive sessions"""
        try:
            self._ensure_admin_access()
            
            streaming_manager = self._get_streaming_manager()
            
            # Get count before cleanup
            before_count = len(streaming_manager.sessions)
            
            streaming_manager.cleanup_inactive_sessions()
            
            # Get count after cleanup
            after_count = len(streaming_manager.sessions)
            cleaned_count = before_count - after_count
            
            return jsonify({
                "success": True,
                "sessions_cleaned": cleaned_count,
                "active_sessions": after_count
            })
            
        except Exception as e:
            logger.error(f"API error cleaning up sessions: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/change-types/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_get_change_types(self):
        """API endpoint to get available change types"""
        try:
            self._ensure_admin_access()
            
            change_types = [
                {
                    "value": change_type.value,
                    "name": change_type.value.replace("_", " ").title(),
                    "category": "node" if "node" in change_type.value else 
                               "edge" if "edge" in change_type.value else "schema"
                }
                for change_type in GraphChangeType
            ]
            
            return jsonify({
                "success": True,
                "change_types": change_types
            })
            
        except Exception as e:
            logger.error(f"API error getting change types: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    @expose_api("get", "/api/streaming-modes/")
    @has_access
    @permission_name("can_stream_graphs")
    def api_get_streaming_modes(self):
        """API endpoint to get available streaming modes"""
        try:
            self._ensure_admin_access()
            
            streaming_modes = [
                {
                    "value": mode.value,
                    "name": mode.value.replace("_", " ").title(),
                    "description": self._get_mode_description(mode)
                }
                for mode in StreamingMode
            ]
            
            return jsonify({
                "success": True,
                "streaming_modes": streaming_modes
            })
            
        except Exception as e:
            logger.error(f"API error getting streaming modes: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    
    def _get_mode_description(self, mode: StreamingMode) -> str:
        """Get description for streaming mode"""
        descriptions = {
            StreamingMode.REAL_TIME: "Immediate delivery of graph changes",
            StreamingMode.BATCH: "Batched delivery of multiple changes",
            StreamingMode.PERIODIC: "Periodic delivery at fixed intervals",
            StreamingMode.ON_DEMAND: "Manual delivery when requested"
        }
        return descriptions.get(mode, "Unknown mode")


# WebSocket handler class (pseudo-implementation)
class GraphWebSocketHandler:
    """
    WebSocket handler for real-time graph streaming
    
    Note: This is a conceptual implementation. Actual WebSocket integration
    would depend on the specific WebSocket library used (e.g., Flask-SocketIO).
    """
    
    def __init__(self):
        self.streaming_manager = get_streaming_manager()
    
    def on_connect(self, websocket):
        """Handle WebSocket connection"""
        logger.info(f"WebSocket connected: {websocket}")
    
    def on_disconnect(self, websocket):
        """Handle WebSocket disconnection"""
        self.streaming_manager.unregister_connection(websocket)
        logger.info(f"WebSocket disconnected: {websocket}")
    
    def on_message(self, websocket, message):
        """Handle WebSocket message"""
        try:
            data = json.loads(message)
            message_type = data.get("type")
            
            if message_type == "subscribe":
                self._handle_subscribe(websocket, data)
            elif message_type == "unsubscribe":
                self._handle_unsubscribe(websocket, data)
            elif message_type == "ping":
                self._handle_ping(websocket, data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
            self._send_error(websocket, str(e))
    
    def _handle_subscribe(self, websocket, data):
        """Handle subscription request"""
        session_id = data.get("session_id")
        
        if not session_id:
            self._send_error(websocket, "Session ID required")
            return
        
        session = self.streaming_manager.get_session(session_id)
        
        if not session:
            self._send_error(websocket, "Invalid session ID")
            return
        
        # Register connection
        self.streaming_manager.register_connection(session_id, websocket)
        
        # Send confirmation
        self._send_message(websocket, {
            "type": "subscribed",
            "session_id": session_id,
            "message": "Successfully subscribed to graph changes"
        })
        
        logger.info(f"WebSocket subscribed to session {session_id}")
    
    def _handle_unsubscribe(self, websocket, data):
        """Handle unsubscription request"""
        self.streaming_manager.unregister_connection(websocket)
        
        self._send_message(websocket, {
            "type": "unsubscribed",
            "message": "Successfully unsubscribed"
        })
        
        logger.info("WebSocket unsubscribed")
    
    def _handle_ping(self, websocket, data):
        """Handle ping request"""
        self._send_message(websocket, {
            "type": "pong",
            "timestamp": datetime.now(tz=timezone.utc).isoformat()
        })
    
    def _send_message(self, websocket, message):
        """Send message to WebSocket"""
        try:
            # In actual implementation, this would send to WebSocket
            logger.debug(f"Sending WebSocket message: {message}")
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
    
    def _send_error(self, websocket, error_message):
        """Send error message to WebSocket"""
        self._send_message(websocket, {
            "type": "error",
            "error": error_message,
            "timestamp": datetime.now(tz=timezone.utc).isoformat()
        })


# Global WebSocket handler instance
_websocket_handler = None


def get_websocket_handler() -> GraphWebSocketHandler:
    """Get or create global WebSocket handler instance"""
    global _websocket_handler
    if _websocket_handler is None:
        _websocket_handler = GraphWebSocketHandler()
    return _websocket_handler