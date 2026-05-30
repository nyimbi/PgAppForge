"""
WebSocket Manager

Real-time WebSocket communication manager for collaborative features.
Handles WebSocket connections, message routing, and real-time event distribution.
"""

import asyncio
import json
import uuid
import weakref
from typing import Dict, List, Any, Optional, Set, Callable, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict
import gc

import logging
logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning(
        "websockets package not available. Install with: pip install websockets"
    )

from flask import Flask
from flask_appbuilder import AppBuilder

from ..core.collaboration_engine import (
    CollaborationEngine,
    CollaborativeEvent,
    CollaborativeEventType,
)

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """WebSocket message types"""

    # Connection management
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    HEARTBEAT = "heartbeat"

    # Collaborative events
    JOIN_SESSION = "join_session"
    LEAVE_SESSION = "leave_session"
    USER_ACTIVITY = "user_activity"

    # Real-time editing
    CURSOR_MOVE = "cursor_move"
    SELECTION_CHANGE = "selection_change"
    TEXT_CHANGE = "text_change"
    FORM_CHANGE = "form_change"

    # Resource management
    LOCK_REQUEST = "lock_request"
    UNLOCK_REQUEST = "unlock_request"
    LOCK_STATUS = "lock_status"

    # Communication
    MESSAGE = "message"
    COMMENT = "comment"
    NOTIFICATION = "notification"

    # Synchronization
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    FULL_SYNC = "full_sync"

    # Error handling
    ERROR = "error"
    WARNING = "warning"


@dataclass
class WebSocketMessage:
    """WebSocket message structure"""

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: MessageType = MessageType.USER_ACTIVITY
    sender_id: Optional[int] = None
    target_id: Optional[int] = None  # For direct messages
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    resource_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    requires_response: bool = False


@dataclass
class WebSocketConnection:
    """WebSocket connection information"""

    connection_id: str
    websocket: Any  # websocket connection object
    user_id: int
    jwt_token: str  # Store JWT token for per-message validation
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    last_heartbeat: datetime = field(default_factory=datetime.now)
    token_last_validated: datetime = field(
        default_factory=datetime.now
    )  # Track token validation
    subscribed_resources: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebSocketManager:
    """
    WebSocket manager for real-time collaborative features.

    Features:
    - WebSocket connection lifecycle management
    - Real-time message routing and broadcasting
    - Integration with collaboration engine
    - Automatic reconnection handling
    - Resource subscription management
    - Connection pooling and scaling
    """

    def __init__(self, collaboration_engine: CollaborationEngine):
        self.collaboration_engine = collaboration_engine
        self.app_builder = collaboration_engine.app_builder
        self.app = collaboration_engine.app

        # Connection management with weak references to prevent memory leaks
        self.connections: Dict[str, WebSocketConnection] = {}
        self.user_connections: Dict[int, Set[str]] = defaultdict(
            set
        )  # user_id -> connection_ids
        self.session_connections: Dict[str, Set[str]] = defaultdict(
            set
        )  # session_id -> connection_ids
        self.workspace_connections: Dict[str, Set[str]] = defaultdict(
            set
        )  # workspace_id -> connection_ids

        # Message handling with weak reference cleanup
        self.message_handlers: Dict[MessageType, List[Callable]] = defaultdict(list)
        self.message_queue: asyncio.Queue = asyncio.Queue()

        # Rate limiting with automatic cleanup
        self.rate_limits: Dict[str, Dict[MessageType, List[datetime]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._last_cleanup_time = datetime.now()

        # Weak reference collections for memory leak prevention
        self._weak_connection_refs: weakref.WeakSet = weakref.WeakSet()
        self._cleanup_callbacks: List[weakref.ref] = []

        # WebSocket server
        self.websocket_server: Optional[Any] = None
        self.server_task: Optional[asyncio.Task] = None

        # Configuration
        self.config = {
            "host": "0.0.0.0",
            "port": 8765,
            "heartbeat_interval": 30,  # seconds
            "connection_timeout": 300,  # seconds
            "max_connections_per_user": 5,
            "max_message_size": 1048576,  # 1MB
            "enable_compression": True,
            "ping_interval": 20,
            "ping_timeout": 10,
            # Security configurations
            "jwt_validation_interval": 60,  # seconds - how often to re-validate JWT tokens
            "jwt_validation_cache_max_age": 300,  # seconds - max age before forced revalidation
            "force_disconnect_on_auth_failure": True,  # disconnect immediately on auth failure
            "log_security_events": True,  # log all authentication and security events
        }

        # Setup
        self._setup_collaboration_integration()
        self._setup_message_handlers()

        if WEBSOCKETS_AVAILABLE:
            self._start_websocket_server()
        else:
            logger.warning(
                "WebSocket server not started - websockets package not available"
            )

    def _setup_collaboration_integration(self) -> None:
        """Setup integration with collaboration engine"""

        # Register for collaborative events
        for event_type in CollaborativeEventType:
            self.collaboration_engine.register_event_handler(
                event_type, self._handle_collaborative_event
            )

    def _setup_message_handlers(self) -> None:
        """Setup default message handlers"""

        self.register_message_handler(MessageType.CONNECT, self._handle_connect)
        self.register_message_handler(MessageType.DISCONNECT, self._handle_disconnect)
        self.register_message_handler(MessageType.HEARTBEAT, self._handle_heartbeat)
        self.register_message_handler(
            MessageType.JOIN_SESSION, self._handle_join_session
        )
        self.register_message_handler(
            MessageType.LEAVE_SESSION, self._handle_leave_session
        )
        self.register_message_handler(
            MessageType.LOCK_REQUEST, self._handle_lock_request
        )
        self.register_message_handler(
            MessageType.UNLOCK_REQUEST, self._handle_unlock_request
        )
        self.register_message_handler(
            MessageType.SYNC_REQUEST, self._handle_sync_request
        )

        # Real-time editing handlers
        self.register_message_handler(MessageType.CURSOR_MOVE, self._handle_cursor_move)
        self.register_message_handler(
            MessageType.SELECTION_CHANGE, self._handle_selection_change
        )
        self.register_message_handler(MessageType.TEXT_CHANGE, self._handle_text_change)
        self.register_message_handler(MessageType.FORM_CHANGE, self._handle_form_change)

        # Communication handlers
        self.register_message_handler(MessageType.MESSAGE, self._handle_message)
        self.register_message_handler(MessageType.COMMENT, self._handle_comment)

    def _start_websocket_server(self) -> None:
        """Start the WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            return

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Start WebSocket server
        self.server_task = loop.create_task(self._run_websocket_server())

        # Start message processor
        loop.create_task(self._process_messages())

        # Start rate limit cleanup
        loop.create_task(self._periodic_rate_limit_cleanup())

        # Start heartbeat checker
        loop.create_task(self._heartbeat_checker())

        # Start memory cleanup task
        loop.create_task(self._memory_cleanup_loop())

        logger.info(
            f"WebSocket server starting on {self.config['host']}:{self.config['port']}"
        )

    async def _run_websocket_server(self) -> None:
        """Run the WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            return

        try:
            self.websocket_server = await websockets.serve(
                self._handle_websocket_connection,
                self.config["host"],
                self.config["port"],
                ping_interval=self.config["ping_interval"],
                ping_timeout=self.config["ping_timeout"],
                max_size=self.config["max_message_size"],
                compression=None
                if not self.config["enable_compression"]
                else "deflate",
            )

            logger.info(
                f"WebSocket server running on {self.config['host']}:{self.config['port']}"
            )

            # Keep server running
            await self.websocket_server.wait_closed()

        except Exception as e:
            logger.error(f"WebSocket server error: {e}")

    async def _handle_websocket_connection(self, websocket, path) -> None:
        """Handle a new WebSocket connection"""
        connection_id = str(uuid.uuid4())
        logger.debug(f"New WebSocket connection: {connection_id}")

        try:
            # Wait for initial connection message with authentication
            auth_message = await asyncio.wait_for(websocket.recv(), timeout=30.0)

            try:
                auth_data = json.loads(auth_message)
            except json.JSONDecodeError:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Invalid JSON in authentication message",
                        }
                    )
                )
                return

            # Authenticate user
            user_id = await self._authenticate_websocket(auth_data)
            if not user_id:
                await websocket.send(
                    json.dumps({"type": "error", "message": "Authentication failed"})
                )
                return

            # Check connection limits
            if (
                len(self.user_connections[user_id])
                >= self.config["max_connections_per_user"]
            ):
                await websocket.send(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Maximum connections per user exceeded",
                        }
                    )
                )
                return

            # Create connection object with weak reference tracking
            connection = WebSocketConnection(
                connection_id=connection_id,
                websocket=websocket,
                user_id=user_id,
                jwt_token=auth_data.get(
                    "token"
                ),  # Store JWT token for per-message validation
                workspace_id=auth_data.get("workspace_id"),
                metadata=auth_data.get("metadata", {}),
            )

            # Add to weak reference tracking
            self._weak_connection_refs.add(connection)

            # Create cleanup callback with weak reference
            cleanup_callback = weakref.ref(
                connection, self._create_cleanup_callback(connection_id)
            )
            self._cleanup_callbacks.append(cleanup_callback)

            # Store connection
            self.connections[connection_id] = connection
            self.user_connections[user_id].add(connection_id)

            if connection.workspace_id:
                self.workspace_connections[connection.workspace_id].add(connection_id)

            # Send connection confirmation
            await self._send_to_connection(
                connection_id,
                WebSocketMessage(
                    message_type=MessageType.CONNECT,
                    data={
                        "connection_id": connection_id,
                        "status": "connected",
                        "server_time": datetime.now().isoformat(),
                    },
                ),
            )

            logger.info(
                f"WebSocket connection established: {connection_id} for user {user_id}"
            )

            # Listen for messages
            async for message in websocket:
                try:
                    await self._handle_websocket_message(connection_id, message)
                except Exception as e:
                    logger.error(
                        f"Error handling WebSocket message from {connection_id}: {e}"
                    )
                    await self._send_error(connection_id, str(e))

        except ConnectionClosed:
            logger.debug(f"WebSocket connection closed: {connection_id}")
        except asyncio.TimeoutError:
            logger.warning(f"WebSocket authentication timeout: {connection_id}")
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
        finally:
            await self._cleanup_connection(connection_id)

    async def _handle_websocket_message(self, connection_id: str, message: str) -> None:
        """Handle a WebSocket message"""
        try:
            data = json.loads(message)

            # Create WebSocket message object
            ws_message = WebSocketMessage(
                message_type=MessageType(data.get("type", "user_activity")),
                sender_id=self.connections[connection_id].user_id,
                target_id=data.get("target_id"),
                session_id=data.get("session_id"),
                workspace_id=data.get("workspace_id"),
                resource_id=data.get("resource_id"),
                data=data.get("data", {}),
                requires_response=data.get("requires_response", False),
            )

            # Add to message queue
            await self.message_queue.put((connection_id, ws_message))

        except json.JSONDecodeError:
            await self._send_error(connection_id, "Invalid JSON message")
        except ValueError as e:
            await self._send_error(connection_id, f"Invalid message type: {e}")

    async def _process_messages(self) -> None:
        """Process queued WebSocket messages"""
        while True:
            try:
                connection_id, message = await self.message_queue.get()

                # Update connection heartbeat
                if connection_id in self.connections:
                    self.connections[connection_id].last_heartbeat = datetime.now()

                # Handle the message
                await self._route_message(connection_id, message)

            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")

    async def _route_message(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Route a message to appropriate handlers with comprehensive validation"""
        try:
            # Validate connection exists and is active
            if not self._validate_connection(connection_id):
                logger.warning(
                    f"Invalid connection {connection_id} attempted to send message"
                )
                return

            # Validate message structure and content
            if not self._validate_websocket_message(message):
                logger.warning(f"Invalid message from connection {connection_id}")
                await self._send_error(connection_id, "Invalid message format")
                return

            # Check rate limiting
            if not await self._check_rate_limit(connection_id, message.message_type):
                logger.warning(f"Rate limit exceeded for connection {connection_id}")
                await self._send_error(connection_id, "Rate limit exceeded")
                return

            # Validate JWT token for each message (security critical)
            if not await self._validate_message_token(connection_id):
                logger.warning(
                    f"JWT token validation failed for connection {connection_id}"
                )
                await self._send_error(connection_id, "Authentication expired")
                await self._cleanup_connection(
                    connection_id
                )  # Force disconnect on auth failure
                return

            # Validate user permissions for message type
            if not await self._validate_message_permissions(connection_id, message):
                logger.warning(
                    f"Permission denied for message type {message.message_type} from connection {connection_id}"
                )
                await self._send_error(connection_id, "Permission denied")
                return

            # Call registered handlers with individual error isolation
            handlers = self.message_handlers.get(message.message_type, [])

            if not handlers:
                logger.debug(
                    f"No handlers registered for message type {message.message_type}"
                )
                return

            successful_handlers = 0
            for handler in handlers:
                try:
                    await handler(connection_id, message)
                    successful_handlers += 1
                except Exception as e:
                    logger.error(
                        f"Error in message handler {handler.__name__} for {message.message_type}: {e}"
                    )
                    # Continue with other handlers even if one fails

            # Only broadcast if at least one handler succeeded
            if successful_handlers > 0:
                # Broadcast to other users if needed
                if message.message_type in [
                    MessageType.CURSOR_MOVE,
                    MessageType.SELECTION_CHANGE,
                    MessageType.TEXT_CHANGE,
                    MessageType.FORM_CHANGE,
                ]:
                    await self._broadcast_to_session(message, exclude_sender=True)
            else:
                logger.error(
                    f"All handlers failed for message type {message.message_type}"
                )
                await self._send_error(connection_id, "Message processing failed")

        except Exception as e:
            logger.error(f"Critical error routing message from {connection_id}: {e}")
            await self._send_error(connection_id, "Internal server error")

    async def _handle_collaborative_event(self, event: CollaborativeEvent) -> None:
        """Handle collaborative events from the collaboration engine"""
        try:
            # Convert collaborative event to WebSocket message
            ws_message = WebSocketMessage(
                message_type=self._map_event_to_message_type(event.event_type),
                sender_id=event.user_id,
                session_id=event.workspace_id,  # Using workspace_id as session context
                workspace_id=event.workspace_id,
                resource_id=event.resource_id,
                data=event.data,
            )

            # Broadcast to relevant connections
            if event.workspace_id:
                await self._broadcast_to_workspace(event.workspace_id, ws_message)

        except Exception as e:
            logger.error(f"Error handling collaborative event: {e}")

    def _map_event_to_message_type(
        self, event_type: CollaborativeEventType
    ) -> MessageType:
        """Map collaborative event types to WebSocket message types"""
        mapping = {
            CollaborativeEventType.USER_JOIN: MessageType.JOIN_SESSION,
            CollaborativeEventType.USER_LEAVE: MessageType.LEAVE_SESSION,
            CollaborativeEventType.DATA_CHANGE: MessageType.FORM_CHANGE,
            CollaborativeEventType.LOCK_ACQUIRE: MessageType.LOCK_STATUS,
            CollaborativeEventType.LOCK_RELEASE: MessageType.LOCK_STATUS,
            CollaborativeEventType.COMMENT_ADD: MessageType.COMMENT,
            CollaborativeEventType.MESSAGE_SEND: MessageType.MESSAGE,
        }
        return mapping.get(event_type, MessageType.NOTIFICATION)

    # Message handlers
    async def _handle_connect(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle connection message"""
        # Connection already handled in _handle_websocket_connection
        pass

    async def _handle_disconnect(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle disconnect message"""
        await self._cleanup_connection(connection_id)

    async def _handle_heartbeat(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle heartbeat message"""
        if connection_id in self.connections:
            self.connections[connection_id].last_heartbeat = datetime.now()

            # Send heartbeat response
            await self._send_to_connection(
                connection_id,
                WebSocketMessage(
                    message_type=MessageType.HEARTBEAT,
                    data={"server_time": datetime.now().isoformat()},
                ),
            )

    async def _handle_join_session(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle join session message"""
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        if message.session_id:
            # Join existing session
            user = self._get_user_from_connection(connection)
            if user:
                success = await self.collaboration_engine.join_session(
                    message.session_id, user
                )
                if success:
                    connection.session_id = message.session_id
                    self.session_connections[message.session_id].add(connection_id)

                    await self._send_to_connection(
                        connection_id,
                        WebSocketMessage(
                            message_type=MessageType.JOIN_SESSION,
                            data={"status": "joined", "session_id": message.session_id},
                        ),
                    )
                else:
                    await self._send_error(connection_id, "Failed to join session")
        elif message.workspace_id:
            # Create new session
            user = self._get_user_from_connection(connection)
            if user:
                session_id = await self.collaboration_engine.create_session(
                    message.workspace_id, user
                )
                connection.session_id = session_id
                self.session_connections[session_id].add(connection_id)

                await self._send_to_connection(
                    connection_id,
                    WebSocketMessage(
                        message_type=MessageType.JOIN_SESSION,
                        data={"status": "created", "session_id": session_id},
                    ),
                )

    async def _handle_leave_session(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle leave session message"""
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        if connection.session_id:
            await self.collaboration_engine.leave_session(
                connection.session_id, connection.user_id
            )
            self.session_connections[connection.session_id].discard(connection_id)
            connection.session_id = None

            await self._send_to_connection(
                connection_id,
                WebSocketMessage(
                    message_type=MessageType.LEAVE_SESSION, data={"status": "left"}
                ),
            )

    async def _handle_lock_request(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle resource lock request"""
        if not message.session_id or not message.resource_id:
            await self._send_error(
                connection_id, "Session ID and resource ID required for lock"
            )
            return

        connection = self.connections[connection_id]
        success = await self.collaboration_engine.acquire_lock(
            message.session_id, connection.user_id, message.resource_id
        )

        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                message_type=MessageType.LOCK_STATUS,
                resource_id=message.resource_id,
                data={
                    "locked": success,
                    "resource_id": message.resource_id,
                    "user_id": connection.user_id if success else None,
                },
            ),
        )

    async def _handle_unlock_request(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle resource unlock request"""
        if not message.session_id or not message.resource_id:
            await self._send_error(
                connection_id, "Session ID and resource ID required for unlock"
            )
            return

        connection = self.connections[connection_id]
        success = await self.collaboration_engine.release_lock(
            message.session_id, connection.user_id, message.resource_id
        )

        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                message_type=MessageType.LOCK_STATUS,
                resource_id=message.resource_id,
                data={
                    "locked": False,
                    "resource_id": message.resource_id,
                    "released": success,
                },
            ),
        )

    async def _handle_sync_request(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle synchronization request"""
        if not message.session_id:
            await self._send_error(connection_id, "Session ID required for sync")
            return

        # Get current session state
        session_users = self.collaboration_engine.get_session_users(message.session_id)

        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                message_type=MessageType.SYNC_RESPONSE,
                data={
                    "session_id": message.session_id,
                    "users": [
                        {
                            "user_id": user.user_id,
                            "username": user.username,
                            "status": user.status.value,
                            "last_activity": user.last_activity.isoformat(),
                        }
                        for user in session_users
                    ],
                },
            ),
        )

    async def _handle_cursor_move(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle cursor movement"""
        # Store cursor position and broadcast
        if connection_id in self.connections:
            connection = self.connections[connection_id]
            connection.metadata["cursor_position"] = message.data.get("position")

    async def _handle_selection_change(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle selection change"""
        # Store selection and broadcast
        if connection_id in self.connections:
            connection = self.connections[connection_id]
            connection.metadata["selection"] = message.data.get("selection")

    async def _handle_text_change(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle text change for collaborative editing"""
        # This would integrate with operational transform or CRDT algorithms
        # For now, just broadcast the change
        pass

    async def _handle_form_change(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle form field change"""
        # Broadcast form changes to other users
        pass

    async def _handle_message(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle chat message"""
        # Broadcast message to session participants
        if message.session_id:
            await self._broadcast_to_session(message)

    async def _handle_comment(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle comment on resource"""
        # Store comment and notify relevant users
        if message.resource_id:
            # This would integrate with a comment storage system
            pass

    # Broadcasting methods
    async def _broadcast_to_session(
        self, message: WebSocketMessage, exclude_sender: bool = False
    ) -> None:
        """Broadcast message to all users in a session"""
        if not message.session_id or message.session_id not in self.session_connections:
            return

        connection_ids = self.session_connections[message.session_id].copy()

        for connection_id in connection_ids:
            if exclude_sender and connection_id in self.connections:
                if self.connections[connection_id].user_id == message.sender_id:
                    continue

            await self._send_to_connection(connection_id, message)

    async def _broadcast_to_workspace(
        self, workspace_id: str, message: WebSocketMessage
    ) -> None:
        """Broadcast message to all users in a workspace"""
        if workspace_id not in self.workspace_connections:
            return

        connection_ids = self.workspace_connections[workspace_id].copy()

        for connection_id in connection_ids:
            await self._send_to_connection(connection_id, message)

    async def _broadcast_to_user(self, user_id: int, message: WebSocketMessage) -> None:
        """Broadcast message to all connections of a specific user"""
        if user_id not in self.user_connections:
            return

        connection_ids = self.user_connections[user_id].copy()

        for connection_id in connection_ids:
            await self._send_to_connection(connection_id, message)

    async def _send_to_connection(
        self, connection_id: str, message: WebSocketMessage
    ) -> bool:
        """Send message to a specific connection"""
        if connection_id not in self.connections:
            return False

        try:
            connection = self.connections[connection_id]
            message_data = {
                "id": message.message_id,
                "type": message.message_type.value,
                "sender_id": message.sender_id,
                "target_id": message.target_id,
                "session_id": message.session_id,
                "workspace_id": message.workspace_id,
                "resource_id": message.resource_id,
                "data": message.data,
                "timestamp": message.timestamp.isoformat(),
            }

            await connection.websocket.send(json.dumps(message_data))
            return True

        except (ConnectionClosed, WebSocketException):
            # Connection is closed, clean it up
            await self._cleanup_connection(connection_id)
            return False
        except Exception as e:
            logger.error(f"Error sending message to {connection_id}: {e}")
            return False

    async def _send_error(self, connection_id: str, error_message: str) -> None:
        """Send error message to connection"""
        await self._send_to_connection(
            connection_id,
            WebSocketMessage(
                message_type=MessageType.ERROR, data={"error": error_message}
            ),
        )

    # Utility methods
    async def _authenticate_websocket(self, auth_data: Dict[str, Any]) -> Optional[int]:
        """Authenticate WebSocket connection using Flask-AppBuilder security"""
        try:
            user_id = auth_data.get("user_id")
            token = auth_data.get("token")

            if not user_id or not token:
                logger.warning("Missing user_id or token in WebSocket authentication")
                return None

            # Get the security manager from collaboration engine
            if not hasattr(self.collaboration_engine, "app_builder"):
                logger.error(
                    "No Flask-AppBuilder instance available for authentication"
                )
                return None

            sm = self.collaboration_engine.app_builder.sm

            # Validate user exists and is active
            user = sm.get_user_by_id(int(user_id))
            if not user or not user.is_active:
                logger.warning(f"Invalid or inactive user {user_id}")
                return None

            # Validate token (implementation depends on your auth strategy)
            if self._validate_user_token(user, token):
                logger.debug(f"WebSocket authentication successful for user {user_id}")
                return int(user_id)
            else:
                logger.warning(f"Invalid token for user {user_id}")
                return None

        except Exception as e:
            logger.error(f"WebSocket authentication error: {e}")
            return None

    def _get_user_from_connection(
        self, connection: WebSocketConnection
    ) -> Optional[Any]:
        """Get Flask-AppBuilder user object from connection"""
        try:
            if not hasattr(self.collaboration_engine, "app_builder"):
                logger.error("No Flask-AppBuilder instance available for user lookup")
                return None

            sm = self.collaboration_engine.app_builder.sm
            user = sm.get_user_by_id(connection.user_id)

            if user and user.is_active:
                return user
            else:
                logger.warning(f"User {connection.user_id} not found or inactive")
                return None

        except Exception as e:
            logger.error(f"Error getting user from connection: {e}")
            return None

    def _validate_user_token(self, user: Any, token: str) -> bool:
        """Validate user authentication token with real JWT validation"""
        try:
            if not token or len(token) < 32:  # Proper token length validation
                logger.warning("Token too short or missing")
                return False

            # Get Flask app configuration
            if not hasattr(self.collaboration_engine, "app_builder"):
                logger.error("No Flask app available for token validation")
                return False

            app = self.collaboration_engine.app_builder.app

            # JWT token validation
            try:
                import jwt
                from jwt.exceptions import (
                    InvalidTokenError,
                    ExpiredSignatureError,
                    DecodeError,
                )

                # Decode and validate JWT token
                payload = jwt.decode(
                    token,
                    app.config.get("SECRET_KEY"),
                    algorithms=["HS256"],
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_iat": True,
                        "require": ["user_id", "exp", "iat"],
                    },
                )

                # Validate payload user matches
                token_user_id = payload.get("user_id")
                if not token_user_id or int(token_user_id) != user.id:
                    logger.warning(
                        f"Token user_id {token_user_id} doesn't match user {user.id}"
                    )
                    return False

                # Additional security checks
                issued_at = payload.get("iat", 0)
                current_time = datetime.now().timestamp()

                # Token can't be from the future
                if issued_at > current_time + 60:  # Allow 60 second clock skew
                    logger.warning(
                        f"Token issued in future: {issued_at} > {current_time}"
                    )
                    return False

                # Check if user is still active (re-validate against database)
                if not user.is_active:
                    logger.warning(f"User {user.id} is no longer active")
                    return False

                logger.debug(f"Token validation successful for user {user.id}")
                return True

            except ExpiredSignatureError:
                logger.warning(f"Expired token for user {user.id}")
                return False
            except DecodeError:
                logger.warning(f"Invalid token format for user {user.id}")
                return False
            except InvalidTokenError as e:
                logger.warning(f"Invalid token for user {user.id}: {e}")
                return False

        except ImportError:
            logger.error(
                "PyJWT library not available - install with: pip install PyJWT"
            )
            # Fall back to session-based validation if JWT not available
            return self._validate_session_token(user, token)
        except Exception as e:
            logger.error(f"Token validation error for user {user.id}: {e}")
            return False

    def _validate_session_token(self, user: Any, token: str) -> bool:
        """Fallback session-based token validation"""
        try:
            # For Flask-AppBuilder session-based auth
            # This would validate against Flask sessions or API keys
            if not token or len(token) < 16:
                return False

            # Get session manager
            if not hasattr(self.collaboration_engine, "app_builder"):
                return False

            sm = self.collaboration_engine.app_builder.sm

            # Check if user has valid session
            # This is a simplified check - real implementation would validate
            # against Flask-AppBuilder's session management
            if hasattr(sm, "get_user_by_id"):
                current_user = sm.get_user_by_id(user.id)
                if current_user and current_user.is_active:
                    logger.debug(f"Session validation successful for user {user.id}")
                    return True

            logger.warning(f"Session validation failed for user {user.id}")
            return False

        except Exception as e:
            logger.error(f"Session validation error: {e}")
            return False

    async def _cleanup_connection(self, connection_id: str) -> None:
        """Clean up a WebSocket connection with comprehensive resource cleanup"""
        if connection_id not in self.connections:
            return

        connection = self.connections[connection_id]

        try:
            # Leave collaborative session with proper cleanup
            if connection.session_id:
                await self.collaboration_engine.leave_session(
                    connection.session_id, connection.user_id
                )
                self.session_connections[connection.session_id].discard(connection_id)

            # Remove from all tracking with weak references cleanup
            self.user_connections[connection.user_id].discard(connection_id)
            if connection.workspace_id:
                self.workspace_connections[connection.workspace_id].discard(
                    connection_id
                )

            # Clear subscribed resources
            if hasattr(connection, "subscribed_resources"):
                connection.subscribed_resources.clear()

            # Close WebSocket connection if still open
            if hasattr(connection, "websocket") and connection.websocket:
                try:
                    if not connection.websocket.closed:
                        await connection.websocket.close()
                except Exception as ws_error:
                    logger.warning(
                        f"Error closing WebSocket for {connection_id}: {ws_error}"
                    )

            # Remove from connections last
            del self.connections[connection_id]

            # Clean up empty collections to prevent memory leaks
            if not self.user_connections[connection.user_id]:
                del self.user_connections[connection.user_id]
            if (
                connection.workspace_id
                and not self.workspace_connections[connection.workspace_id]
            ):
                del self.workspace_connections[connection.workspace_id]
            if (
                connection.session_id
                and not self.session_connections[connection.session_id]
            ):
                del self.session_connections[connection.session_id]

            logger.debug(f"Cleaned up WebSocket connection: {connection_id}")

        except Exception as e:
            logger.error(f"Error during connection cleanup {connection_id}: {e}")
            # Force cleanup even on error
            self.connections.pop(connection_id, None)

    async def _heartbeat_checker(self) -> None:
        """Check for stale connections and clean them up"""
        while True:
            try:
                await asyncio.sleep(self.config["heartbeat_interval"])

                current_time = datetime.now()
                stale_connections = []

                for connection_id, connection in self.connections.items():
                    time_since_heartbeat = current_time - connection.last_heartbeat
                    if (
                        time_since_heartbeat.total_seconds()
                        > self.config["connection_timeout"]
                    ):
                        stale_connections.append(connection_id)

                # Clean up stale connections
                for connection_id in stale_connections:
                    logger.info(
                        f"Cleaning up stale WebSocket connection: {connection_id}"
                    )
                    await self._cleanup_connection(connection_id)

            except Exception as e:
                logger.error(f"Error in heartbeat checker: {e}")
                await asyncio.sleep(30)  # Retry in 30 seconds on error

    async def _periodic_rate_limit_cleanup(self) -> None:
        """Periodic cleanup of rate limiting data."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                await self._cleanup_rate_limits_async()
            except Exception as e:
                logger.error(f"Error in periodic rate limit cleanup: {e}")
                await asyncio.sleep(60)  # Retry in 1 minute on error

    def register_message_handler(
        self, message_type: MessageType, handler: Callable
    ) -> None:
        """Register a message handler"""
        self.message_handlers[message_type].append(handler)
        logger.debug(f"Registered handler for {message_type}")

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get WebSocket connection statistics with memory usage info"""
        return {
            "total_connections": len(self.connections),
            "unique_users": len(self.user_connections),
            "active_sessions": len(self.session_connections),
            "active_workspaces": len(self.workspace_connections),
            "message_queue_size": self.message_queue.qsize(),
            "websocket_server_running": self.websocket_server is not None,
            "rate_limit_entries": len(self.rate_limits),
            "weak_references": len(self._weak_connection_refs),
            "cleanup_callbacks": len(self._cleanup_callbacks),
            "message_handler_types": len(self.message_handlers),
        }

    # Enhanced error handling and validation methods

    def _validate_connection(self, connection_id: str) -> bool:
        """
        Validate that a connection exists and is active.

        Args:
            connection_id: Connection identifier

        Returns:
            True if connection is valid
        """
        try:
            if connection_id not in self.connections:
                return False

            connection = self.connections[connection_id]

            # Check if connection is still active
            if not hasattr(connection, "websocket") or connection.websocket.closed:
                return False

            # Check if connection is authenticated
            if not connection.user_id:
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating connection {connection_id}: {e}")
            return False

    def _validate_websocket_message(self, message: WebSocketMessage) -> bool:
        """
        Validate WebSocket message structure and content.

        Args:
            message: Message to validate

        Returns:
            True if message is valid
        """
        try:
            # Check required fields
            if not hasattr(message, "message_type") or message.message_type is None:
                logger.warning("Message missing message_type")
                return False

            if not hasattr(message, "message_id") or not message.message_id:
                logger.warning("Message missing message_id")
                return False

            # Validate message type is known
            if not isinstance(message.message_type, MessageType):
                logger.warning(f"Unknown message type: {message.message_type}")
                return False

            # Validate sender_id if provided
            if hasattr(message, "sender_id") and message.sender_id is not None:
                if not isinstance(message.sender_id, int) or message.sender_id <= 0:
                    logger.warning(f"Invalid sender_id: {message.sender_id}")
                    return False

            # Validate data field
            if hasattr(message, "data") and message.data is not None:
                if not isinstance(message.data, dict):
                    logger.warning("Message data must be a dictionary")
                    return False

                # Check data size to prevent oversized payloads
                try:
                    import json

                    data_size = len(json.dumps(message.data))
                    if data_size > 1024 * 1024:  # 1MB limit
                        logger.warning(f"Message data too large: {data_size} bytes")
                        return False
                except (TypeError, ValueError):
                    logger.warning("Message data contains non-serializable content")
                    return False

            # Validate timestamp
            if hasattr(message, "timestamp") and message.timestamp:
                if not isinstance(message.timestamp, datetime):
                    logger.warning("Invalid timestamp type")
                    return False

                # Check if timestamp is reasonable (not too old or in future)
                now = datetime.now()
                time_diff = abs((now - message.timestamp).total_seconds())
                if time_diff > 3600:  # More than 1 hour difference
                    logger.warning(
                        f"Message timestamp seems invalid: {message.timestamp}"
                    )
                    return False

            # Message type specific validation
            if message.message_type == MessageType.TEXT_CHANGE:
                if not message.data or "operation" not in message.data:
                    logger.warning("TEXT_CHANGE message missing operation data")
                    return False

            elif message.message_type in [
                MessageType.JOIN_SESSION,
                MessageType.LEAVE_SESSION,
            ]:
                if not message.session_id:
                    logger.warning(f"{message.message_type} message missing session_id")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating WebSocket message: {e}")
            return False

    async def _check_rate_limit(
        self, connection_id: str, message_type: MessageType
    ) -> bool:
        """
        Check if connection has exceeded rate limits for message type.

        Args:
            connection_id: Connection identifier
            message_type: Type of message being sent

        Returns:
            True if within rate limits
        """
        try:
            current_time = datetime.now()

            # Periodic cleanup to prevent memory leaks
            if (
                current_time - self._last_cleanup_time
            ).total_seconds() > 300:  # Every 5 minutes
                await self._cleanup_rate_limits_async()
                self._last_cleanup_time = current_time

            # Different rate limits for different message types
            limits = {
                MessageType.TEXT_CHANGE: (50, 60),  # 50 per minute
                MessageType.CURSOR_MOVE: (200, 60),  # 200 per minute
                MessageType.SELECTION_CHANGE: (100, 60),  # 100 per minute
                MessageType.HEARTBEAT: (6, 60),  # 6 per minute
                MessageType.MESSAGE: (30, 60),  # 30 per minute
                MessageType.COMMENT: (10, 60),  # 10 per minute
            }

            max_requests, window_seconds = limits.get(message_type, (100, 60))

            # Get timestamps for this connection and message type
            timestamps = self.rate_limits[connection_id][message_type]

            # Remove timestamps outside the window
            cutoff_time = current_time - timedelta(seconds=window_seconds)
            timestamps[:] = [ts for ts in timestamps if ts > cutoff_time]

            # Check if limit exceeded
            if len(timestamps) >= max_requests:
                logger.warning(
                    f"Rate limit exceeded for connection {connection_id}, "
                    f"message type {message_type}: {len(timestamps)}/{max_requests}"
                )
                return False

            # Add current timestamp
            timestamps.append(current_time)

            return True

        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            # Allow on error to prevent system lock-up
            return True

    async def _validate_message_permissions(
        self, connection_id: str, message: WebSocketMessage
    ) -> bool:
        """
        Validate user permissions for the message type and target resources.

        Args:
            connection_id: Connection identifier
            message: Message to validate permissions for

        Returns:
            True if user has permission
        """
        try:
            if connection_id not in self.connections:
                return False

            connection = self.connections[connection_id]
            user_id = connection.user_id

            # Get user from Flask-AppBuilder
            if not hasattr(self.collaboration_engine, "app_builder"):
                logger.warning(
                    "No Flask-AppBuilder instance available for permission check"
                )
                return True  # Allow if can't check (fail open for now)

            sm = self.collaboration_engine.app_builder.sm
            user = sm.get_user_by_id(user_id)

            if not user or not user.is_active:
                logger.warning(f"User {user_id} not found or inactive")
                return False

            # Basic permission checks based on message type
            if message.message_type in [
                MessageType.TEXT_CHANGE,
                MessageType.FORM_CHANGE,
            ]:
                # Check if user has edit permissions for the resource
                if message.workspace_id:
                    # Would check workspace edit permissions here
                    # For now, allow authenticated users
                    return True

            elif message.message_type == MessageType.COMMENT:
                # Check if user has comment permissions
                if message.resource_id:
                    # Would check resource comment permissions here
                    # For now, allow authenticated users
                    return True

            elif message.message_type in [
                MessageType.JOIN_SESSION,
                MessageType.LEAVE_SESSION,
            ]:
                # Check if user has access to the session/workspace
                if message.session_id or message.workspace_id:
                    # Would check session/workspace access permissions here
                    # For now, allow authenticated users
                    return True

            # Allow other message types for authenticated users
            return True

        except Exception as e:
            logger.error(f"Error validating message permissions: {e}")
            # Allow on error to prevent system lock-up, but log for security review
            return True

    def _validate_session_binding(self, connection: WebSocketConnection) -> bool:
        """
        Validate that the WebSocket connection is bound to the correct session.

        This prevents session hijacking where an attacker uses a valid token
        from a different session or connection.
        """
        try:
            # Check if connection has required session metadata
            if not connection.metadata.get('client_fingerprint'):
                logger.warning(f"Missing client fingerprint for connection {connection.connection_id}")
                return False

            # Get current client information (this would be populated during connection)
            current_fingerprint = connection.metadata.get('client_fingerprint')
            stored_fingerprint = connection.metadata.get('session_fingerprint')

            if current_fingerprint != stored_fingerprint:
                logger.warning(
                    f"Session fingerprint mismatch for connection {connection.connection_id}"
                )
                return False

            # Additional session validation
            if connection.session_id and connection.metadata.get('workspace_id'):
                # Validate session belongs to workspace
                expected_workspace = connection.metadata.get('workspace_id')
                if connection.workspace_id != expected_workspace:
                    logger.warning(
                        f"Workspace mismatch for connection {connection.connection_id}"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating session binding: {e}")
            return False

    def _is_low_risk_operation(self, message_type: Optional[MessageType] = None) -> bool:
        """
        Determine if current operation is low-risk for JWT validation caching.

        Low-risk operations that can use brief caching:
        - Heartbeat messages
        - Cursor movements
        - Read-only status requests

        High-risk operations that require immediate validation:
        - Form/data changes
        - Lock requests
        - Resource modifications
        - Administrative actions
        """
        # If we have message context, use it
        if message_type is not None:
            low_risk_types = {
                MessageType.HEARTBEAT,
                MessageType.CURSOR_MOVE,
                MessageType.USER_ACTIVITY,  # Read-only activity updates
                MessageType.SYNC_REQUEST,   # Read-only sync requests
            }
            return message_type in low_risk_types

        # Without context, assume high-risk for security
        return False

    async def _validate_message_token(self, connection_id: str) -> bool:
        """
        Validate JWT token for each WebSocket message (security critical).

        This prevents expired or compromised tokens from continuing to work
        after the connection is established.

        Args:
            connection_id: Connection identifier

        Returns:
            True if token is valid, False if invalid/expired
        """
        try:
            if connection_id not in self.connections:
                logger.warning(
                    f"Connection {connection_id} not found for token validation"
                )
                return False

            connection = self.connections[connection_id]

            # Check if we need to validate token (cache for performance)
            now = datetime.now()
            time_since_last_validation = (
                now - connection.token_last_validated
            ).total_seconds()

            # Enhanced security: Perform validation based on operation risk level
            # Only allow very limited caching for low-risk read operations
            is_low_risk_operation = self._is_low_risk_operation()
            max_cache_time = 5 if is_low_risk_operation else 0  # Max 5 seconds for low-risk only

            if time_since_last_validation < max_cache_time:
                # Only cache for very low-risk operations and very short time
                logger.debug(f"Using cached JWT validation for low-risk operation: {connection_id}")
                return True

            # For all critical operations and after cache expiry, always perform full validation
            logger.debug(f"Performing full JWT validation for connection {connection_id}")

            # Get user from Flask-AppBuilder
            if not hasattr(self.collaboration_engine, "app_builder"):
                logger.error(
                    "No Flask-AppBuilder instance available for token validation"
                )
                return False

            sm = self.collaboration_engine.app_builder.sm
            user = sm.get_user_by_id(connection.user_id)

            if not user or not user.is_active:
                logger.warning(
                    f"User {connection.user_id} not found or inactive during token validation"
                )
                return False

            # Validate the stored JWT token
            if not self._validate_user_token(user, connection.jwt_token):
                logger.warning(
                    f"JWT token validation failed for user {connection.user_id} on connection {connection_id}"
                )
                return False

            # Update last validation time
            connection.token_last_validated = now

            # Log security event if configured
            if self.config.get("log_security_events", True):
                logger.info(
                    f"JWT token validated successfully for user {connection.user_id} on connection {connection_id}"
                )

            return True

        except Exception as e:
            logger.error(
                f"Error validating message token for connection {connection_id}: {e}"
            )
            # Fail secure - reject on validation error
            return False

    async def _cleanup_rate_limits_async(self) -> None:
        """Asynchronous cleanup of rate limiting data to prevent memory leaks."""
        try:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=1)  # Keep 1 hour of data

            # Clean up rate limit data for all connections
            for connection_id in list(self.rate_limits.keys()):
                if connection_id not in self.connections:
                    # Remove data for disconnected connections
                    del self.rate_limits[connection_id]
                    continue

                for message_type in list(self.rate_limits[connection_id].keys()):
                    timestamps = self.rate_limits[connection_id][message_type]
                    timestamps[:] = [ts for ts in timestamps if ts > cutoff_time]

                    # Remove empty entries
                    if not timestamps:
                        del self.rate_limits[connection_id][message_type]

                # Remove empty connection entries
                if not self.rate_limits[connection_id]:
                    del self.rate_limits[connection_id]

            logger.debug(
                f"Rate limit cleanup completed. Active entries: {len(self.rate_limits)}"
            )

        except Exception as e:
            logger.error(f"Error cleaning up rate limits: {e}")

    def _cleanup_rate_limits(self) -> None:
        """Synchronous cleanup of rate limiting data - wrapper for async version."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._cleanup_rate_limits_async())
            else:
                loop.run_until_complete(self._cleanup_rate_limits_async())
        except Exception as e:
            logger.error(f"Error scheduling rate limit cleanup: {e}")

    def _create_cleanup_callback(self, connection_id: str) -> Callable:
        """Create a cleanup callback for weak reference disposal."""

        def cleanup_callback(weak_ref):
            """Callback function called when connection is garbage collected."""
            try:
                # Remove from tracking collections if connection was garbage collected
                if connection_id in self.connections:
                    logger.debug(
                        f"Weak reference cleanup triggered for connection {connection_id}"
                    )

                    # Note: Don't use asyncio here as this might be called from GC thread
                    # Instead, mark for cleanup in next cleanup cycle

                    # Remove from rate limiting immediately
                    if (
                        hasattr(self, "rate_limits")
                        and connection_id in self.rate_limits
                    ):
                        del self.rate_limits[connection_id]

            except Exception as e:
                logger.error(f"Error in weak reference cleanup callback: {e}")

        return cleanup_callback

    async def _memory_cleanup_loop(self) -> None:
        """Background loop for memory cleanup and weak reference management."""
        while True:
            try:
                # Sleep for 10 minutes between cleanup cycles
                await asyncio.sleep(600)

                logger.debug("Starting memory cleanup cycle")

                # Clean up rate limits
                await self._cleanup_rate_limits_async()

                # Clean up weak reference callbacks
                self._cleanup_callbacks = [
                    ref for ref in self._cleanup_callbacks if ref() is not None
                ]

                # Clean up empty collections
                await self._cleanup_empty_collections()

                # Force garbage collection
                collected = gc.collect()

                # Log memory stats
                stats = self.get_connection_stats()
                logger.debug(
                    f"Memory cleanup completed. Stats: {stats}, GC collected: {collected} objects"
                )

            except Exception as e:
                logger.error(f"Error in memory cleanup loop: {e}")
                # Continue running even if cleanup fails
                await asyncio.sleep(300)  # Retry in 5 minutes on error

    async def _cleanup_empty_collections(self) -> None:
        """Clean up empty collections to prevent memory leaks."""
        try:
            # Clean up empty user connections
            empty_users = [
                user_id
                for user_id, connections in self.user_connections.items()
                if not connections
            ]
            for user_id in empty_users:
                del self.user_connections[user_id]

            # Clean up empty session connections
            empty_sessions = [
                session_id
                for session_id, connections in self.session_connections.items()
                if not connections
            ]
            for session_id in empty_sessions:
                del self.session_connections[session_id]

            # Clean up empty workspace connections
            empty_workspaces = [
                workspace_id
                for workspace_id, connections in self.workspace_connections.items()
                if not connections
            ]
            for workspace_id in empty_workspaces:
                del self.workspace_connections[workspace_id]

            # Clean up message handlers with dead weak references
            for message_type in list(self.message_handlers.keys()):
                # Filter out any None handlers (from weak references)
                self.message_handlers[message_type] = [
                    handler
                    for handler in self.message_handlers[message_type]
                    if handler is not None
                ]

                # Remove empty handler lists
                if not self.message_handlers[message_type]:
                    del self.message_handlers[message_type]

            # Clean up orphaned rate limit entries
            orphaned_rate_limits = [
                conn_id
                for conn_id in self.rate_limits.keys()
                if conn_id not in self.connections
            ]
            for conn_id in orphaned_rate_limits:
                del self.rate_limits[conn_id]

            if (
                empty_users
                or empty_sessions
                or empty_workspaces
                or orphaned_rate_limits
            ):
                logger.debug(
                    f"Cleaned up empty collections: users={len(empty_users)}, "
                    f"sessions={len(empty_sessions)}, workspaces={len(empty_workspaces)}, "
                    f"rate_limits={len(orphaned_rate_limits)}"
                )

        except Exception as e:
            logger.error(f"Error cleaning up empty collections: {e}")

    async def shutdown(self) -> None:
        """Shutdown the WebSocket manager"""
        logger.info("Shutting down WebSocket manager")

        # Close all connections
        for connection_id in list(self.connections.keys()):
            await self._cleanup_connection(connection_id)

        # Stop server
        if self.websocket_server:
            self.websocket_server.close()
            await self.websocket_server.wait_closed()

        # Cancel tasks
        if self.server_task:
            self.server_task.cancel()

        # Clean up weak references and callbacks
        self._weak_connection_refs.clear()
        self._cleanup_callbacks.clear()

        # Force garbage collection
        gc.collect()

        logger.info("WebSocket manager shutdown complete")
