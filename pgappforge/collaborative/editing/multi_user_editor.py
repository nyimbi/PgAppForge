"""
Multi-User Editor

Real-time collaborative editing system with operational transformation and conflict resolution.
Enables multiple users to edit the same document simultaneously with automatic conflict resolution
and consistency guarantees.
"""

import uuid
import json
import asyncio
from typing import Dict, List, Any, Optional, Set, Union, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import deque, defaultdict
import threading
from copy import deepcopy

from flask import Flask, g, current_app
from pgappforge import AppBuilder

from ..core.collaboration_engine import (
    CollaborationEngine,
    CollaborativeEvent,
    CollaborativeEventType,
)
from ..realtime.websocket_manager import WebSocketManager, WebSocketMessage, MessageType
from ..core.workspace_manager import WorkspaceManager, WorkspaceResource

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Types of operations in operational transformation"""

    INSERT = "insert"
    DELETE = "delete"
    RETAIN = "retain"
    FORMAT = "format"
    CURSOR = "cursor"
    SELECTION = "selection"


class OperationState(Enum):
    """Operation processing states"""

    PENDING = "pending"
    APPLIED = "applied"
    TRANSFORMED = "transformed"
    REJECTED = "rejected"


class ConflictResolutionStrategy(Enum):
    """Conflict resolution strategies"""

    OPERATIONAL_TRANSFORM = "operational_transform"
    LAST_WRITE_WINS = "last_write_wins"
    MANUAL_RESOLUTION = "manual_resolution"
    COLLABORATIVE_RESOLUTION = "collaborative_resolution"


@dataclass
class Operation:
    """Represents a single editing operation"""

    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    operation_type: OperationType = OperationType.INSERT
    position: int = 0
    content: str = ""
    length: int = 0
    author_id: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    vector_clock: Dict[int, int] = field(default_factory=dict)
    format_attributes: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.operation_type == OperationType.INSERT:
            self.length = len(self.content)
        elif self.operation_type == OperationType.DELETE:
            self.length = max(self.length, 0)


@dataclass
class EditorState:
    """Current state of the document being edited"""

    document_id: str
    content: str = ""
    cursors: Dict[int, int] = field(default_factory=dict)  # user_id -> cursor_position
    selections: Dict[int, Tuple[int, int]] = field(
        default_factory=dict
    )  # user_id -> (start, end)
    format_spans: List[Dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    last_modified: datetime = field(default_factory=datetime.now)
    collaborators: Set[int] = field(default_factory=set)


@dataclass
class ConflictResolution:
    """Represents a conflict and its resolution"""

    conflict_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflicting_operations: List[Operation] = field(default_factory=list)
    resolution_strategy: ConflictResolutionStrategy = (
        ConflictResolutionStrategy.OPERATIONAL_TRANSFORM
    )
    resolved_operation: Optional[Operation] = None
    resolution_timestamp: Optional[datetime] = None
    resolved_by: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class OperationalTransformer:
    """
    Operational transformation engine for conflict-free collaborative editing.
    Implements the core OT algorithms for transforming operations.
    """

    def __init__(self):
        self.transformation_matrix = self._build_transformation_matrix()

    def transform(
        self, op1: Operation, op2: Operation, priority: bool = True
    ) -> Tuple[Operation, Operation]:
        """
        Transform two concurrent operations to maintain consistency.

        Args:
            op1: First operation
            op2: Second operation
            priority: Whether op1 has priority over op2

        Returns:
            Tuple of transformed operations (op1', op2')
        """
        try:
            transformation_key = (op1.operation_type, op2.operation_type)

            if transformation_key in self.transformation_matrix:
                transformer = self.transformation_matrix[transformation_key]
                return transformer(op1, op2, priority)
            else:
                # Default: no transformation needed
                return op1, op2

        except Exception as e:
            logger.error(f"Error transforming operations: {e}")
            return op1, op2

    def _build_transformation_matrix(
        self,
    ) -> Dict[Tuple[OperationType, OperationType], Callable]:
        """Build the operation transformation matrix"""
        return {
            (OperationType.INSERT, OperationType.INSERT): self._transform_insert_insert,
            (OperationType.INSERT, OperationType.DELETE): self._transform_insert_delete,
            (OperationType.DELETE, OperationType.INSERT): self._transform_delete_insert,
            (OperationType.DELETE, OperationType.DELETE): self._transform_delete_delete,
            (OperationType.INSERT, OperationType.RETAIN): self._transform_insert_retain,
            (OperationType.DELETE, OperationType.RETAIN): self._transform_delete_retain,
            (OperationType.RETAIN, OperationType.INSERT): self._transform_retain_insert,
            (OperationType.RETAIN, OperationType.DELETE): self._transform_retain_delete,
        }

    def _transform_insert_insert(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform two concurrent insert operations"""
        op1_prime = deepcopy(op1)
        op2_prime = deepcopy(op2)

        if op1.position <= op2.position:
            # op1 comes first
            op2_prime.position += op1.length
            if op1.position == op2.position and not priority:
                # Same position, use author ID for deterministic ordering
                if op1.author_id > op2.author_id:
                    op1_prime.position += op2.length
                    op2_prime.position = op2.position
                else:
                    op2_prime.position += op1.length
        else:
            # op2 comes first
            op1_prime.position += op2.length

        return op1_prime, op2_prime

    def _transform_insert_delete(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform insert vs delete operations"""
        op1_prime = deepcopy(op1)
        op2_prime = deepcopy(op2)

        if op1.position <= op2.position:
            # Insert comes before delete
            op2_prime.position += op1.length
        elif op1.position < op2.position + op2.length:
            # Insert is within delete range - split the delete
            op2_prime.length += op1.length
        else:
            # Insert comes after delete
            op1_prime.position -= op2.length

        return op1_prime, op2_prime

    def _transform_delete_insert(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform delete vs insert operations"""
        op2_prime, op1_prime = self._transform_insert_delete(op2, op1, not priority)
        return op1_prime, op2_prime

    def _transform_delete_delete(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform two concurrent delete operations"""
        op1_prime = deepcopy(op1)
        op2_prime = deepcopy(op2)

        if op1.position + op1.length <= op2.position:
            # op1 comes entirely before op2
            op2_prime.position -= op1.length
        elif op2.position + op2.length <= op1.position:
            # op2 comes entirely before op1
            op1_prime.position -= op2.length
        else:
            # Overlapping deletes - need to resolve overlap
            start1, end1 = op1.position, op1.position + op1.length
            start2, end2 = op2.position, op2.position + op2.length

            overlap_start = max(start1, start2)
            overlap_end = min(end1, end2)
            overlap_length = max(0, overlap_end - overlap_start)

            if overlap_length > 0:
                # Reduce delete lengths by overlap
                op1_prime.length -= overlap_length
                op2_prime.length -= overlap_length

                # Adjust positions
                if start2 < start1:
                    op1_prime.position -= start1 - start2
                if start1 < start2:
                    op2_prime.position -= start2 - start1

        return op1_prime, op2_prime

    def _transform_insert_retain(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform insert vs retain operations"""
        op1_prime = deepcopy(op1)
        op2_prime = deepcopy(op2)

        if op1.position <= op2.position:
            op2_prime.position += op1.length

        return op1_prime, op2_prime

    def _transform_delete_retain(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform delete vs retain operations"""
        op1_prime = deepcopy(op1)
        op2_prime = deepcopy(op2)

        if op1.position < op2.position:
            op2_prime.position -= min(op1.length, op2.position - op1.position)

        return op1_prime, op2_prime

    def _transform_retain_insert(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform retain vs insert operations"""
        op2_prime, op1_prime = self._transform_insert_retain(op2, op1, not priority)
        return op1_prime, op2_prime

    def _transform_retain_delete(
        self, op1: Operation, op2: Operation, priority: bool
    ) -> Tuple[Operation, Operation]:
        """Transform retain vs delete operations"""
        op2_prime, op1_prime = self._transform_delete_retain(op2, op1, not priority)
        return op1_prime, op2_prime


class DocumentSynchronizer:
    """
    Document synchronization manager using vector clocks and operation ordering.
    """

    def __init__(self):
        self.vector_clocks: Dict[str, Dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.operation_buffers: Dict[str, List[Operation]] = defaultdict(list)
        self.pending_operations: Dict[str, deque] = defaultdict(deque)

    def can_apply_operation(self, document_id: str, operation: Operation) -> bool:
        """Check if an operation can be applied based on vector clock"""
        doc_clock = self.vector_clocks[document_id]
        op_clock = operation.vector_clock

        # Check if all dependencies are satisfied
        for user_id, timestamp in op_clock.items():
            if user_id == operation.author_id:
                # Check if this is the next operation from this user
                if timestamp != doc_clock[user_id] + 1:
                    return False
            else:
                # Check if we have all operations from other users up to this timestamp
                if timestamp > doc_clock[user_id]:
                    return False

        return True

    def update_vector_clock(self, document_id: str, operation: Operation) -> None:
        """Update the document's vector clock after applying an operation"""
        doc_clock = self.vector_clocks[document_id]
        doc_clock[operation.author_id] = operation.vector_clock[operation.author_id]

    def generate_vector_clock(self, document_id: str, user_id: int) -> Dict[int, int]:
        """Generate vector clock for a new operation"""
        doc_clock = self.vector_clocks[document_id].copy()
        doc_clock[user_id] += 1
        return doc_clock


class MultiUserEditor:
    """
    Multi-user collaborative editor with operational transformation.

    Features:
    - Real-time collaborative editing
    - Operational transformation for conflict resolution
    - Cursor and selection synchronization
    - Document state management
    - Integration with workspace and collaboration systems
    """

    def __init__(
        self,
        collaboration_engine: CollaborationEngine,
        websocket_manager: WebSocketManager,
        workspace_manager: WorkspaceManager,
    ):
        self.collaboration_engine = collaboration_engine
        self.websocket_manager = websocket_manager
        self.workspace_manager = workspace_manager

        # Core components
        self.transformer = OperationalTransformer()
        self.synchronizer = DocumentSynchronizer()

        # State management
        self.editor_states: Dict[str, EditorState] = {}
        self.operation_history: Dict[str, List[Operation]] = defaultdict(list)
        self.active_sessions: Dict[str, Set[int]] = defaultdict(
            set
        )  # document_id -> user_ids

        # Conflict resolution
        self.conflicts: Dict[str, List[ConflictResolution]] = defaultdict(list)
        self.pending_resolutions: Dict[str, deque] = defaultdict(deque)

        # Configuration
        self.config = {
            "max_operation_history": 1000,
            "operation_timeout": timedelta(minutes=5),
            "auto_save_interval": 30,  # seconds
            "conflict_resolution_timeout": timedelta(minutes=2),
            "enable_real_time_sync": True,
            "batch_operations": True,
            "max_batch_size": 10,
        }

        # Setup
        self._setup_websocket_integration()
        self._setup_collaboration_integration()
        self._start_background_tasks()

    def _setup_websocket_integration(self) -> None:
        """Setup integration with WebSocket manager"""
        # Register message handlers
        self.websocket_manager.register_message_handler(
            MessageType.TEXT_CHANGE, self._handle_text_change
        )
        self.websocket_manager.register_message_handler(
            MessageType.CURSOR_MOVE, self._handle_cursor_move
        )
        self.websocket_manager.register_message_handler(
            MessageType.SELECTION_CHANGE, self._handle_selection_change
        )
        self.websocket_manager.register_message_handler(
            MessageType.SYNC_REQUEST, self._handle_sync_request
        )

    def _setup_collaboration_integration(self) -> None:
        """Setup integration with collaboration engine"""
        # Register for collaborative events
        self.collaboration_engine.register_event_handler(
            CollaborativeEventType.USER_JOIN, self._handle_user_join
        )
        self.collaboration_engine.register_event_handler(
            CollaborativeEventType.USER_LEAVE, self._handle_user_leave
        )

    def _start_background_tasks(self) -> None:
        """Start background tasks for the editor"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Start operation processor
        loop.create_task(self._process_operations())

        # Start auto-save task
        if self.config["auto_save_interval"] > 0:
            loop.create_task(self._auto_save_documents())

        # Start conflict resolution processor
        loop.create_task(self._process_conflicts())

    async def open_document(
        self, document_id: str, user_id: int, initial_content: str = ""
    ) -> EditorState:
        """
        Open a document for collaborative editing.

        Args:
            document_id: Unique document identifier
            user_id: User opening the document
            initial_content: Initial document content

        Returns:
            Current editor state
        """
        try:
            # Initialize editor state if not exists
            if document_id not in self.editor_states:
                self.editor_states[document_id] = EditorState(
                    document_id=document_id, content=initial_content
                )

            editor_state = self.editor_states[document_id]

            # Add user to active session
            self.active_sessions[document_id].add(user_id)
            editor_state.collaborators.add(user_id)

            # Initialize cursor position
            if user_id not in editor_state.cursors:
                editor_state.cursors[user_id] = 0

            # Initialize vector clock for user
            if document_id not in self.synchronizer.vector_clocks:
                self.synchronizer.vector_clocks[document_id] = defaultdict(int)

            # Emit user join event
            await self._emit_editor_event(
                document_id,
                user_id,
                "document_opened",
                {
                    "document_id": document_id,
                    "collaborators_count": len(editor_state.collaborators),
                },
            )

            logger.info(f"User {user_id} opened document {document_id}")
            return editor_state

        except Exception as e:
            logger.error(f"Error opening document: {e}")
            raise

    async def close_document(self, document_id: str, user_id: int) -> None:
        """
        Close a document for a user.

        Args:
            document_id: Document identifier
            user_id: User closing the document
        """
        try:
            if document_id not in self.editor_states:
                return

            editor_state = self.editor_states[document_id]

            # Remove user from active session
            self.active_sessions[document_id].discard(user_id)
            editor_state.collaborators.discard(user_id)

            # Remove cursor and selection
            editor_state.cursors.pop(user_id, None)
            editor_state.selections.pop(user_id, None)

            # Auto-save document
            await self._save_document(document_id)

            # Clean up if no active users
            if not self.active_sessions[document_id]:
                await self._cleanup_document(document_id)

            # Emit user leave event
            await self._emit_editor_event(
                document_id,
                user_id,
                "document_closed",
                {
                    "document_id": document_id,
                    "collaborators_count": len(editor_state.collaborators),
                },
            )

            logger.info(f"User {user_id} closed document {document_id}")

        except Exception as e:
            logger.error(f"Error closing document: {e}")

    async def apply_operation(self, document_id: str, operation: Operation) -> bool:
        """
        Apply an operation to a document with comprehensive error handling.

        Args:
            document_id: Document identifier
            operation: Operation to apply

        Returns:
            True if operation was applied successfully
        """
        try:
            # Validate operation before processing
            if not self._validate_operation(operation):
                logger.warning(
                    f"Invalid operation {operation.operation_id}: validation failed"
                )
                return False

            if document_id not in self.editor_states:
                logger.error(
                    f"Document {document_id} not found for operation {operation.operation_id}"
                )
                return False

            editor_state = self.editor_states[document_id]

            # Create backup for rollback capability
            backup_state = self._create_state_backup(editor_state)

            try:
                # Generate vector clock for operation
                operation.vector_clock = self.synchronizer.generate_vector_clock(
                    document_id, operation.author_id
                )

                # Check if operation can be applied immediately
                if self.synchronizer.can_apply_operation(document_id, operation):
                    # Apply operation with atomic transaction
                    success = await self._apply_operation_with_rollback(
                        editor_state, operation, backup_state
                    )

                    if success:
                        # Update vector clock
                        self.synchronizer.update_vector_clock(document_id, operation)

                        # Add to history
                        self.operation_history[document_id].append(operation)
                        self._trim_operation_history(document_id)

                        # Broadcast to other users
                        await self._broadcast_operation(document_id, operation)

                        # Process any pending operations that can now be applied
                        await self._process_pending_operations(document_id)

                        logger.debug(
                            f"Applied operation {operation.operation_id} to document {document_id}"
                        )
                        return True
                    else:
                        logger.error(
                            f"Failed to apply operation {operation.operation_id} to document {document_id}"
                        )
                        return False
                else:
                    # Validate operation can be queued
                    if not self._validate_operation_for_queuing(document_id, operation):
                        logger.warning(
                            f"Operation {operation.operation_id} cannot be queued for document {document_id}"
                        )
                        return False

                    # Queue operation for later processing
                    self.synchronizer.pending_operations[document_id].append(operation)
                    logger.debug(
                        f"Queued operation {operation.operation_id} for document {document_id}"
                    )
                    return True

            except Exception as apply_error:
                # Rollback on any failure during application
                logger.error(
                    f"Operation {operation.operation_id} failed, rolling back: {apply_error}"
                )
                self._restore_state_from_backup(editor_state, backup_state)
                return False

        except Exception as e:
            logger.error(
                f"Critical error applying operation {operation.operation_id}: {e}"
            )
            return False

    async def _apply_operation_to_state(
        self, state: EditorState, operation: Operation
    ) -> bool:
        """Apply an operation to the editor state"""
        try:
            if operation.operation_type == OperationType.INSERT:
                # Insert text at position
                if 0 <= operation.position <= len(state.content):
                    state.content = (
                        state.content[: operation.position]
                        + operation.content
                        + state.content[operation.position :]
                    )

                    # Update cursors after the insertion point
                    for user_id, cursor_pos in state.cursors.items():
                        if cursor_pos >= operation.position:
                            state.cursors[user_id] = cursor_pos + operation.length

                    # Update selections
                    for user_id, (start, end) in state.selections.items():
                        if start >= operation.position:
                            state.selections[user_id] = (
                                start + operation.length,
                                end + operation.length,
                            )
                        elif end > operation.position:
                            state.selections[user_id] = (start, end + operation.length)

                    return True

            elif operation.operation_type == OperationType.DELETE:
                # Delete text from position
                if 0 <= operation.position <= len(state.content):
                    end_position = min(
                        operation.position + operation.length, len(state.content)
                    )
                    actual_length = end_position - operation.position

                    state.content = (
                        state.content[: operation.position]
                        + state.content[end_position:]
                    )

                    # Update cursors after the deletion point
                    for user_id, cursor_pos in state.cursors.items():
                        if cursor_pos > operation.position:
                            if cursor_pos <= end_position:
                                # Cursor was in deleted range
                                state.cursors[user_id] = operation.position
                            else:
                                # Cursor was after deleted range
                                state.cursors[user_id] = cursor_pos - actual_length

                    # Update selections
                    for user_id, (start, end) in state.selections.items():
                        if start >= end_position:
                            # Selection after deletion
                            state.selections[user_id] = (
                                start - actual_length,
                                end - actual_length,
                            )
                        elif end <= operation.position:
                            # Selection before deletion - no change needed
                            pass
                        else:
                            # Selection overlaps with deletion
                            new_start = min(start, operation.position)
                            new_end = max(operation.position, end - actual_length)
                            state.selections[user_id] = (new_start, new_end)

                    return True

            elif operation.operation_type == OperationType.CURSOR:
                # Update cursor position
                state.cursors[operation.author_id] = operation.position
                return True

            elif operation.operation_type == OperationType.SELECTION:
                # Update selection
                if "start" in operation.metadata and "end" in operation.metadata:
                    start = operation.metadata["start"]
                    end = operation.metadata["end"]
                    state.selections[operation.author_id] = (start, end)
                return True

            # Update state metadata
            state.revision += 1
            state.last_modified = datetime.now()

            return False

        except Exception as e:
            logger.error(f"Error applying operation to state: {e}")
            return False

    async def _process_pending_operations(self, document_id: str) -> None:
        """Process pending operations that can now be applied"""
        try:
            pending = self.synchronizer.pending_operations[document_id]
            applied_count = 0

            while pending:
                operation = pending[0]

                if self.synchronizer.can_apply_operation(document_id, operation):
                    # Remove from pending and apply
                    pending.popleft()

                    editor_state = self.editor_states[document_id]
                    success = await self._apply_operation_to_state(
                        editor_state, operation
                    )

                    if success:
                        self.synchronizer.update_vector_clock(document_id, operation)
                        self.operation_history[document_id].append(operation)
                        await self._broadcast_operation(document_id, operation)
                        applied_count += 1
                    else:
                        # If we can't apply this operation, we likely can't apply subsequent ones
                        break
                else:
                    # Can't apply this operation yet
                    break

            if applied_count > 0:
                logger.debug(
                    f"Applied {applied_count} pending operations for document {document_id}"
                )

        except Exception as e:
            logger.error(f"Error processing pending operations: {e}")

    async def _handle_text_change(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle text change from WebSocket"""
        try:
            document_id = message.resource_id
            if not document_id:
                return

            # Parse operation from message
            operation_data = message.data
            operation = Operation(
                operation_type=OperationType(operation_data.get("type", "insert")),
                position=operation_data.get("position", 0),
                content=operation_data.get("content", ""),
                length=operation_data.get("length", 0),
                author_id=message.sender_id,
                format_attributes=operation_data.get("format_attributes", {}),
                metadata=operation_data.get("metadata", {}),
            )

            # Apply operation
            await self.apply_operation(document_id, operation)

        except Exception as e:
            logger.error(f"Error handling text change: {e}")

    async def _handle_cursor_move(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle cursor movement from WebSocket"""
        try:
            document_id = message.resource_id
            if not document_id or document_id not in self.editor_states:
                return

            position = message.data.get("position", 0)

            # Create cursor operation
            operation = Operation(
                operation_type=OperationType.CURSOR,
                position=position,
                author_id=message.sender_id,
            )

            # Apply operation
            await self.apply_operation(document_id, operation)

        except Exception as e:
            logger.error(f"Error handling cursor move: {e}")

    async def _handle_selection_change(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle selection change from WebSocket"""
        try:
            document_id = message.resource_id
            if not document_id or document_id not in self.editor_states:
                return

            selection_data = message.data.get("selection", {})
            start = selection_data.get("start", 0)
            end = selection_data.get("end", 0)

            # Create selection operation
            operation = Operation(
                operation_type=OperationType.SELECTION,
                position=start,
                author_id=message.sender_id,
                metadata={"start": start, "end": end},
            )

            # Apply operation
            await self.apply_operation(document_id, operation)

        except Exception as e:
            logger.error(f"Error handling selection change: {e}")

    async def _handle_sync_request(
        self, connection_id: str, message: WebSocketMessage
    ) -> None:
        """Handle synchronization request"""
        try:
            document_id = message.resource_id
            if not document_id or document_id not in self.editor_states:
                return

            editor_state = self.editor_states[document_id]

            # Send full document state
            sync_message = WebSocketMessage(
                message_type=MessageType.FULL_SYNC,
                sender_id=0,  # System message
                resource_id=document_id,
                data={
                    "content": editor_state.content,
                    "revision": editor_state.revision,
                    "cursors": editor_state.cursors,
                    "selections": dict(editor_state.selections),
                    "collaborators": list(editor_state.collaborators),
                },
            )

            await self.websocket_manager._send_to_connection(
                connection_id, sync_message
            )

        except Exception as e:
            logger.error(f"Error handling sync request: {e}")

    async def _handle_user_join(self, event: CollaborativeEvent) -> None:
        """Handle user joining collaborative session"""
        try:
            user_id = event.user_id
            workspace_id = event.workspace_id

            # Notify all active documents in the workspace about new user
            for document_id, state in self.editor_states.items():
                if state.collaborators:
                    await self._emit_editor_event(
                        document_id,
                        user_id,
                        "user_available",
                        {"user_id": user_id, "workspace_id": workspace_id},
                    )

        except Exception as e:
            logger.error(f"Error handling user join: {e}")

    async def _handle_user_leave(self, event: CollaborativeEvent) -> None:
        """Handle user leaving collaborative session"""
        try:
            user_id = event.user_id

            # Close all documents for this user
            documents_to_close = []
            for document_id, state in self.editor_states.items():
                if user_id in state.collaborators:
                    documents_to_close.append(document_id)

            for document_id in documents_to_close:
                await self.close_document(document_id, user_id)

        except Exception as e:
            logger.error(f"Error handling user leave: {e}")

    async def _broadcast_operation(
        self, document_id: str, operation: Operation
    ) -> None:
        """Broadcast operation to all collaborators except the author"""
        try:
            if document_id not in self.editor_states:
                return

            editor_state = self.editor_states[document_id]

            # Create WebSocket message
            operation_message = WebSocketMessage(
                message_type=MessageType.TEXT_CHANGE,
                sender_id=operation.author_id,
                resource_id=document_id,
                data={
                    "operation_id": operation.operation_id,
                    "type": operation.operation_type.value,
                    "position": operation.position,
                    "content": operation.content,
                    "length": operation.length,
                    "format_attributes": operation.format_attributes,
                    "metadata": operation.metadata,
                    "vector_clock": operation.vector_clock,
                    "timestamp": operation.timestamp.isoformat(),
                },
            )

            # Broadcast to workspace
            workspace = await self._get_document_workspace(document_id)
            if workspace:
                await self.websocket_manager._broadcast_to_workspace(
                    str(workspace.id), operation_message
                )

        except Exception as e:
            logger.error(f"Error broadcasting operation: {e}")

    async def _process_operations(self) -> None:
        """Background task to process operations"""
        while True:
            try:
                await asyncio.sleep(0.1)  # Process at 10Hz

                # Process any pending transformations
                for document_id in list(self.editor_states.keys()):
                    await self._check_for_conflicts(document_id)

            except Exception as e:
                logger.error(f"Error in operation processor: {e}")
                await asyncio.sleep(1)

    async def _check_for_conflicts(self, document_id: str) -> None:
        """Check for and resolve conflicts in a document"""
        try:
            if document_id not in self.operation_history:
                return

            operations = self.operation_history[document_id]

            # Look for concurrent operations that might conflict
            for i, op1 in enumerate(operations[-10:]):  # Check last 10 operations
                for j, op2 in enumerate(operations[-10:]):
                    if i >= j:
                        continue

                    # Check if operations are concurrent and conflicting
                    if self._are_concurrent(op1, op2) and self._do_operations_conflict(
                        op1, op2
                    ):
                        # Create conflict resolution
                        conflict = ConflictResolution(
                            conflicting_operations=[op1, op2],
                            resolution_strategy=ConflictResolutionStrategy.OPERATIONAL_TRANSFORM,
                        )

                        # Resolve using operational transformation
                        await self._resolve_conflict_with_ot(document_id, conflict)

        except Exception as e:
            logger.error(f"Error checking for conflicts: {e}")

    def _are_concurrent(self, op1: Operation, op2: Operation) -> bool:
        """Check if two operations are concurrent"""
        # Operations are concurrent if neither happened-before the other
        clock1 = op1.vector_clock
        clock2 = op2.vector_clock

        # Check if op1 happened before op2
        op1_before_op2 = True
        for user_id, timestamp in clock1.items():
            if timestamp > clock2.get(user_id, 0):
                op1_before_op2 = False
                break

        # Check if op2 happened before op1
        op2_before_op1 = True
        for user_id, timestamp in clock2.items():
            if timestamp > clock1.get(user_id, 0):
                op2_before_op1 = False
                break

        # Concurrent if neither happened before the other
        return not (op1_before_op2 or op2_before_op1)

    def _do_operations_conflict(self, op1: Operation, op2: Operation) -> bool:
        """Check if two operations conflict"""
        # Operations conflict if they affect overlapping text regions
        if op1.operation_type in [
            OperationType.INSERT,
            OperationType.DELETE,
        ] and op2.operation_type in [OperationType.INSERT, OperationType.DELETE]:
            end1 = op1.position + (
                op1.length if op1.operation_type == OperationType.DELETE else 0
            )
            end2 = op2.position + (
                op2.length if op2.operation_type == OperationType.DELETE else 0
            )

            # Check for overlap
            return not (end1 <= op2.position or end2 <= op1.position)

        return False

    async def _resolve_conflict_with_ot(
        self, document_id: str, conflict: ConflictResolution
    ) -> None:
        """Resolve conflict using operational transformation"""
        try:
            if len(conflict.conflicting_operations) != 2:
                return

            op1, op2 = conflict.conflicting_operations

            # Transform operations
            op1_prime, op2_prime = self.transformer.transform(
                op1, op2, op1.author_id < op2.author_id
            )

            # Apply transformed operations
            editor_state = self.editor_states[document_id]

            # Note: In a full implementation, you would need to carefully manage
            # the application of transformed operations to maintain consistency

            conflict.resolved_operation = op1_prime  # For simplicity
            conflict.resolution_timestamp = datetime.now()

            self.conflicts[document_id].append(conflict)

            logger.debug(f"Resolved conflict using OT for document {document_id}")

        except Exception as e:
            logger.error(f"Error resolving conflict with OT: {e}")

    async def _process_conflicts(self) -> None:
        """Background task to process conflicts"""
        while True:
            try:
                await asyncio.sleep(1)  # Process every second

                # Check for conflicts that need resolution
                for document_id, pending in self.pending_resolutions.items():
                    while pending:
                        conflict = pending.popleft()

                        if (
                            conflict.resolution_strategy
                            == ConflictResolutionStrategy.OPERATIONAL_TRANSFORM
                        ):
                            await self._resolve_conflict_with_ot(document_id, conflict)
                        # Add other resolution strategies here

            except Exception as e:
                logger.error(f"Error in conflict processor: {e}")
                await asyncio.sleep(5)

    async def _auto_save_documents(self) -> None:
        """Auto-save documents periodically"""
        while True:
            try:
                await asyncio.sleep(self.config["auto_save_interval"])

                for document_id in list(self.editor_states.keys()):
                    if self.active_sessions[
                        document_id
                    ]:  # Only save if users are active
                        await self._save_document(document_id)

            except Exception as e:
                logger.error(f"Error in auto-save: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying

    async def _save_document(self, document_id: str) -> bool:
        """Save document to persistent storage"""
        try:
            if document_id not in self.editor_states:
                return False

            editor_state = self.editor_states[document_id]

            # This would integrate with the workspace manager to save the document
            # For now, we'll just log the save operation
            logger.debug(
                f"Auto-saved document {document_id} with {len(editor_state.content)} characters"
            )

            return True

        except Exception as e:
            logger.error(f"Error saving document {document_id}: {e}")
            return False

    async def _cleanup_document(self, document_id: str) -> None:
        """Clean up document resources when no users are active"""
        try:
            # Save final state
            await self._save_document(document_id)

            # Clean up memory
            self.editor_states.pop(document_id, None)
            self.operation_history.pop(document_id, None)
            self.active_sessions.pop(document_id, None)
            self.conflicts.pop(document_id, None)
            self.pending_resolutions.pop(document_id, None)

            # Clean up synchronizer state
            self.synchronizer.vector_clocks.pop(document_id, None)
            self.synchronizer.operation_buffers.pop(document_id, None)
            self.synchronizer.pending_operations.pop(document_id, None)

            logger.info(f"Cleaned up document {document_id}")

        except Exception as e:
            logger.error(f"Error cleaning up document {document_id}: {e}")

    def _trim_operation_history(self, document_id: str) -> None:
        """Trim operation history to stay within limits"""
        history = self.operation_history[document_id]
        max_history = self.config["max_operation_history"]

        if len(history) > max_history:
            self.operation_history[document_id] = history[-max_history:]

    async def _get_document_workspace(self, document_id: str) -> Optional[Any]:
        """Get workspace for a document"""
        try:
            # This would integrate with workspace manager to get workspace
            # For now, return None
            return None
        except Exception as e:
            logger.error(f"Error getting document workspace: {e}")
            return None

    async def _emit_editor_event(
        self, document_id: str, user_id: int, action: str, data: Dict[str, Any]
    ) -> None:
        """Emit collaborative event for editor actions"""
        try:
            import asyncio

            event = CollaborativeEvent(
                event_type=CollaborativeEventType.DATA_CHANGE,
                user_id=user_id,
                resource_id=document_id,
                data={"action": action, "document_id": document_id, **data},
            )

            await self.collaboration_engine.emit_event(event)

        except Exception as e:
            logger.error(f"Error emitting editor event: {e}")

    def get_editor_stats(self) -> Dict[str, Any]:
        """Get editor statistics"""
        total_operations = sum(
            len(history) for history in self.operation_history.values()
        )
        total_conflicts = sum(len(conflicts) for conflicts in self.conflicts.values())

        return {
            "active_documents": len(self.editor_states),
            "total_collaborators": sum(
                len(state.collaborators) for state in self.editor_states.values()
            ),
            "total_operations": total_operations,
            "total_conflicts": total_conflicts,
            "average_document_size": sum(
                len(state.content) for state in self.editor_states.values()
            )
            / len(self.editor_states)
            if self.editor_states
            else 0,
        }

    # Error handling and validation helper methods

    def _validate_operation(self, operation: Operation) -> bool:
        """
        Validate operation before processing to prevent data corruption.

        Args:
            operation: Operation to validate

        Returns:
            True if operation is valid
        """
        try:
            # Check required fields
            if not operation.operation_id:
                logger.warning("Operation missing operation_id")
                return False

            if (
                not hasattr(operation, "operation_type")
                or operation.operation_type is None
            ):
                logger.warning("Operation missing operation_type")
                return False

            if not hasattr(operation, "author_id") or operation.author_id is None:
                logger.warning("Operation missing author_id")
                return False

            if not hasattr(operation, "position") or operation.position < 0:
                logger.warning("Operation has invalid position")
                return False

            # Validate operation type specific requirements
            if operation.operation_type == OperationType.INSERT:
                if not hasattr(operation, "content") or not operation.content:
                    logger.warning("INSERT operation missing content")
                    return False

            elif operation.operation_type == OperationType.DELETE:
                if not hasattr(operation, "length") or operation.length <= 0:
                    logger.warning("DELETE operation has invalid length")
                    return False

            elif operation.operation_type == OperationType.RETAIN:
                if not hasattr(operation, "length") or operation.length <= 0:
                    logger.warning("RETAIN operation has invalid length")
                    return False

            # Validate timestamp
            if hasattr(operation, "timestamp") and operation.timestamp:
                # Check if timestamp is reasonable (not too old or in future)
                now = datetime.now()
                time_diff = abs((now - operation.timestamp).total_seconds())
                if time_diff > 3600:  # More than 1 hour difference
                    logger.warning(
                        f"Operation timestamp seems invalid: {operation.timestamp}"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating operation: {e}")
            return False

    def _create_state_backup(self, editor_state: EditorState) -> Dict[str, Any]:
        """
        Create a backup of editor state for rollback capability.

        Args:
            editor_state: State to backup

        Returns:
            Backup data
        """
        try:
            return {
                "content": editor_state.content,
                "collaborators": deepcopy(editor_state.collaborators),
                "cursor_positions": deepcopy(editor_state.cursor_positions),
                "selections": deepcopy(editor_state.selections),
                "last_modified": editor_state.last_modified,
                "version": editor_state.version
                if hasattr(editor_state, "version")
                else 0,
            }
        except Exception as e:
            logger.error(f"Error creating state backup: {e}")
            return {}

    def _restore_state_from_backup(
        self, editor_state: EditorState, backup: Dict[str, Any]
    ) -> None:
        """
        Restore editor state from backup.

        Args:
            editor_state: State to restore
            backup: Backup data
        """
        try:
            if not backup:
                logger.warning("Cannot restore from empty backup")
                return

            editor_state.content = backup.get("content", "")
            editor_state.collaborators = backup.get("collaborators", set())
            editor_state.cursor_positions = backup.get("cursor_positions", {})
            editor_state.selections = backup.get("selections", {})
            editor_state.last_modified = backup.get("last_modified", datetime.now())

            if hasattr(editor_state, "version"):
                editor_state.version = backup.get("version", 0)

            logger.debug("Successfully restored editor state from backup")

        except Exception as e:
            logger.error(f"Error restoring state from backup: {e}")

    async def _apply_operation_with_rollback(
        self, editor_state: EditorState, operation: Operation, backup: Dict[str, Any]
    ) -> bool:
        """
        Apply operation with rollback capability on failure.

        Args:
            editor_state: Editor state to modify
            operation: Operation to apply
            backup: Backup data for rollback

        Returns:
            True if operation applied successfully
        """
        try:
            # Attempt to apply the operation
            success = await self._apply_operation_to_state(editor_state, operation)

            if not success:
                # Rollback on failure
                self._restore_state_from_backup(editor_state, backup)
                logger.warning(
                    f"Operation {operation.operation_id} failed, state rolled back"
                )
                return False

            # Validate state after operation
            if not self._validate_editor_state(editor_state):
                # Rollback if state is invalid after operation
                self._restore_state_from_backup(editor_state, backup)
                logger.warning(
                    f"Editor state invalid after operation {operation.operation_id}, rolled back"
                )
                return False

            return True

        except Exception as e:
            # Rollback on any exception
            self._restore_state_from_backup(editor_state, backup)
            logger.error(
                f"Exception during operation {operation.operation_id}, rolled back: {e}"
            )
            return False

    def _validate_operation_for_queuing(
        self, document_id: str, operation: Operation
    ) -> bool:
        """
        Validate if operation can be safely queued.

        Args:
            document_id: Document identifier
            operation: Operation to validate for queuing

        Returns:
            True if operation can be queued
        """
        try:
            # Check if document still exists
            if document_id not in self.editor_states:
                logger.warning(
                    f"Cannot queue operation for non-existent document {document_id}"
                )
                return False

            # Check queue size limits
            max_pending = 1000  # Maximum pending operations
            current_pending = len(
                self.synchronizer.pending_operations.get(document_id, [])
            )

            if current_pending >= max_pending:
                logger.warning(
                    f"Too many pending operations for document {document_id}: {current_pending}"
                )
                return False

            # Check operation age - don't queue very old operations
            if hasattr(operation, "timestamp") and operation.timestamp:
                age_seconds = (datetime.now() - operation.timestamp).total_seconds()
                if age_seconds > 300:  # 5 minutes
                    logger.warning(
                        f"Operation {operation.operation_id} too old to queue: {age_seconds}s"
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating operation for queuing: {e}")
            return False

    def _validate_editor_state(self, editor_state: EditorState) -> bool:
        """
        Validate editor state for consistency.

        Args:
            editor_state: State to validate

        Returns:
            True if state is valid
        """
        try:
            # Check if content is valid
            if not isinstance(editor_state.content, str):
                logger.error("Editor state content is not a string")
                return False

            # Check cursor positions are within content bounds
            content_length = len(editor_state.content)
            for user_id, position in editor_state.cursor_positions.items():
                if (
                    not isinstance(position, int)
                    or position < 0
                    or position > content_length
                ):
                    logger.error(
                        f"Invalid cursor position for user {user_id}: {position}"
                    )
                    return False

            # Check selections are within content bounds
            for user_id, selection in editor_state.selections.items():
                if hasattr(selection, "start") and hasattr(selection, "end"):
                    if (
                        selection.start < 0
                        or selection.start > content_length
                        or selection.end < 0
                        or selection.end > content_length
                        or selection.start > selection.end
                    ):
                        logger.error(
                            f"Invalid selection for user {user_id}: {selection.start}-{selection.end}"
                        )
                        return False

            return True

        except Exception as e:
            logger.error(f"Error validating editor state: {e}")
            return False
