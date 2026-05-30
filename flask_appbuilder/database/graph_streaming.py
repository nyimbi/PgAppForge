"""
Real-Time Graph Streaming System

Provides live updates, change detection, and real-time graph monitoring
using WebSocket connections and event-driven architecture.
"""

import json
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, asdict
from enum import Enum
import sqlalchemy as sa
from sqlalchemy import text, event
from sqlalchemy.pool import Pool
import weakref
from concurrent.futures import ThreadPoolExecutor

from .graph_manager import GraphDatabaseManager, get_graph_manager
from .activity_tracker import track_database_activity, ActivityType

logger = logging.getLogger(__name__)


class GraphChangeType(Enum):
	"""Types of graph changes"""
	NODE_CREATED = "node_created"
	NODE_UPDATED = "node_updated"
	NODE_DELETED = "node_deleted"
	EDGE_CREATED = "edge_created"
	EDGE_UPDATED = "edge_updated"
	EDGE_DELETED = "edge_deleted"
	SCHEMA_CHANGED = "schema_changed"
	BATCH_UPDATE = "batch_update"


class StreamingMode(Enum):
	"""Streaming operation modes"""
	REAL_TIME = "real_time"
	BATCH = "batch"
	PERIODIC = "periodic"
	ON_DEMAND = "on_demand"


@dataclass
class GraphChangeEvent:
	"""
	Represents a graph change event
	
	Attributes:
		id: Unique event identifier
		timestamp: When the change occurred
		change_type: Type of change
		graph_name: Target graph name
		element_id: Changed element ID
		element_type: Element type (node/edge)
		old_data: Previous state data
		new_data: New state data
		metadata: Additional event metadata
	"""
	
	id: str
	timestamp: datetime
	change_type: GraphChangeType
	graph_name: str
	element_id: str
	element_type: str
	old_data: Dict[str, Any] = None
	new_data: Dict[str, Any] = None
	metadata: Dict[str, Any] = None
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		return {
			"id": self.id,
			"timestamp": self.timestamp.isoformat(),
			"change_type": self.change_type.value,
			"graph_name": self.graph_name,
			"element_id": self.element_id,
			"element_type": self.element_type,
			"old_data": self.old_data,
			"new_data": self.new_data,
			"metadata": self.metadata or {}
		}


@dataclass
class StreamingSession:
	"""
	Represents a streaming session
	
	Attributes:
		session_id: Unique session identifier
		user_id: Associated user ID
		graph_name: Target graph name
		filters: Event filters
		mode: Streaming mode
		last_activity: Last activity timestamp
		connection: WebSocket connection reference
		statistics: Session statistics
	"""
	
	session_id: str
	user_id: str
	graph_name: str
	filters: Dict[str, Any]
	mode: StreamingMode
	last_activity: datetime
	connection: Any = None
	statistics: Dict[str, Any] = None
	
	def __post_init__(self):
		if self.statistics is None:
			self.statistics = {
				"events_sent": 0,
				"events_filtered": 0,
				"start_time": datetime.now(tz=timezone.utc),
				"last_event_time": None
			}
	
	def is_active(self) -> bool:
		"""Check if session is still active"""
		timeout = timedelta(minutes=30)  # 30 minute timeout
		return datetime.now(tz=timezone.utc) - self.last_activity < timeout
	
	def matches_filter(self, event: GraphChangeEvent) -> bool:
		"""Check if event matches session filters"""
		if not self.filters:
			return True
		
		# Graph name filter
		if "graphs" in self.filters:
			if event.graph_name not in self.filters["graphs"]:
				return False
		
		# Change type filter
		if "change_types" in self.filters:
			if event.change_type.value not in self.filters["change_types"]:
				return False
		
		# Element type filter
		if "element_types" in self.filters:
			if event.element_type not in self.filters["element_types"]:
				return False
		
		# Node label filter
		if "node_labels" in self.filters and event.element_type == "node":
			node_labels = event.new_data.get("labels", []) if event.new_data else []
			if not any(label in self.filters["node_labels"] for label in node_labels):
				return False
		
		# Edge label filter
		if "edge_labels" in self.filters and event.element_type == "edge":
			edge_label = event.new_data.get("label") if event.new_data else None
			if edge_label not in self.filters["edge_labels"]:
				return False
		
		return True
	
	def to_dict(self) -> Dict[str, Any]:
		"""Convert to dictionary for serialization"""
		return {
			"session_id": self.session_id,
			"user_id": self.user_id,
			"graph_name": self.graph_name,
			"filters": self.filters,
			"mode": self.mode.value,
			"last_activity": self.last_activity.isoformat(),
			"statistics": self.statistics,
			"is_active": self.is_active()
		}


class GraphChangeDetector:
	"""
	Detects changes in graph data using database triggers and polling
	
	Monitors graph modifications and generates change events for real-time streaming.
	"""
	
	def __init__(self, graph_manager: GraphDatabaseManager = None, poll_interval: int = 5):
		self.graph_manager = graph_manager or get_graph_manager()
		self.poll_interval = poll_interval
		self.last_check_time = {}
		self.change_callbacks = []
		self.is_monitoring = False
		self.monitor_thread = None
		self.executor = ThreadPoolExecutor(max_workers=4)
		
		# Setup database connection for monitoring
		self._setup_monitoring()
	
	def _setup_monitoring(self):
		"""Setup database monitoring infrastructure"""
		try:
			if not self.graph_manager.engine:
				logger.warning("No database engine available for change detection")
				return
			
			# Create change log table for tracking modifications
			self._create_change_log_table()
			
			# Setup database triggers (if supported)
			self._setup_database_triggers()
			
			logger.info("Graph change detection monitoring setup complete")
			
		except Exception as e:
			logger.error(f"Failed to setup change detection: {e}")
	
	def _create_change_log_table(self):
		"""Create table for logging graph changes"""
		try:
			with self.graph_manager.engine.begin() as conn:
				conn.execute(text("""
					CREATE TABLE IF NOT EXISTS graph_change_log (
						id SERIAL PRIMARY KEY,
						graph_name VARCHAR(255) NOT NULL,
						change_type VARCHAR(50) NOT NULL,
						element_id VARCHAR(255) NOT NULL,
						element_type VARCHAR(50) NOT NULL,
						old_data JSONB,
						new_data JSONB,
						change_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
						processed BOOLEAN DEFAULT FALSE
					)
				"""))
				
				# Create index for efficient querying
				conn.execute(text("""
					CREATE INDEX IF NOT EXISTS idx_graph_change_log_processed
					ON graph_change_log (processed, change_time)
				"""))
				
				logger.info("Graph change log table created successfully")
				
		except Exception as e:
			logger.error(f"Failed to create change log table: {e}")
	
	def _setup_database_triggers(self):
		"""Setup database triggers for automatic change detection"""
		try:
			# This would setup PostgreSQL triggers on AGE tables
			# Implementation depends on AGE table structure
			logger.info("Database triggers would be setup here for production use")
			
		except Exception as e:
			logger.error(f"Failed to setup database triggers: {e}")
	
	def start_monitoring(self):
		"""Start background monitoring for graph changes"""
		if self.is_monitoring:
			return
		
		self.is_monitoring = True
		self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
		self.monitor_thread.start()
		
		logger.info("Graph change monitoring started")
	
	def stop_monitoring(self):
		"""Stop background monitoring"""
		self.is_monitoring = False
		
		if self.monitor_thread and self.monitor_thread.is_alive():
			self.monitor_thread.join(timeout=5)
		
		logger.info("Graph change monitoring stopped")
	
	def _monitoring_loop(self):
		"""Main monitoring loop"""
		while self.is_monitoring:
			try:
				# Check for changes in each monitored graph
				graphs = self._get_monitored_graphs()
				
				for graph_name in graphs:
					changes = self._detect_changes_for_graph(graph_name)
					
					for change in changes:
						self._notify_change(change)
				
				# Sleep before next check
				threading.Event().wait(self.poll_interval)
				
			except Exception as e:
				logger.error(f"Error in monitoring loop: {e}")
				threading.Event().wait(self.poll_interval)
	
	def _get_monitored_graphs(self) -> List[str]:
		"""Get list of graphs to monitor"""
		# For now, return default graph
		# In production, this would query active graphs
		return ["default_graph"]
	
	def _detect_changes_for_graph(self, graph_name: str) -> List[GraphChangeEvent]:
		"""Detect changes for a specific graph"""
		changes = []
		
		try:
			# Check change log table for new entries
			changes.extend(self._check_change_log(graph_name))
			
			# Perform periodic full scan if needed
			if self._should_perform_full_scan(graph_name):
				changes.extend(self._perform_full_scan(graph_name))
			
		except Exception as e:
			logger.error(f"Error detecting changes for graph {graph_name}: {e}")
		
		return changes
	
	def _check_change_log(self, graph_name: str) -> List[GraphChangeEvent]:
		"""Check change log table for new entries"""
		changes = []
		
		try:
			if not self.graph_manager.engine:
				return changes
			
			with self.graph_manager.engine.connect() as conn:
				result = conn.execute(text("""
					SELECT id, graph_name, change_type, element_id, element_type,
						   old_data, new_data, change_time
					FROM graph_change_log
					WHERE graph_name = :graph_name AND processed = FALSE
					ORDER BY change_time ASC
				"""), {"graph_name": graph_name})
				
				rows = result.fetchall()
				
				for row in rows:
					change_event = GraphChangeEvent(
						id=f"change_{row[0]}",
						timestamp=row[7],
						change_type=GraphChangeType(row[2]),
						graph_name=row[1],
						element_id=row[3],
						element_type=row[4],
						old_data=row[5],
						new_data=row[6]
					)
					changes.append(change_event)
					
					# Mark as processed
					conn.execute(text("""
						UPDATE graph_change_log SET processed = TRUE WHERE id = :id
					"""), {"id": row[0]})
					conn.commit()
				
		except Exception as e:
			logger.error(f"Error checking change log: {e}")
		
		return changes
	
	def _should_perform_full_scan(self, graph_name: str) -> bool:
		"""Determine if full scan is needed"""
		last_scan = self.last_check_time.get(graph_name)
		
		if not last_scan:
			self.last_check_time[graph_name] = datetime.now(tz=timezone.utc)
			return True
		
		# Perform full scan every 5 minutes
		return datetime.now(tz=timezone.utc) - last_scan > timedelta(minutes=5)
	
	def _perform_full_scan(self, graph_name: str) -> List[GraphChangeEvent]:
		"""Perform full graph scan for changes"""
		changes = []
		
		try:
			# This is a simplified implementation
			# In production, this would compare current state with cached state
			
			# For demonstration, we'll just update last check time
			self.last_check_time[graph_name] = datetime.now(tz=timezone.utc)
			
		except Exception as e:
			logger.error(f"Error in full scan for {graph_name}: {e}")
		
		return changes
	
	def _notify_change(self, change: GraphChangeEvent):
		"""Notify registered callbacks about change"""
		for callback in self.change_callbacks:
			try:
				callback(change)
			except Exception as e:
				logger.error(f"Error in change callback: {e}")
	
	def register_change_callback(self, callback: Callable[[GraphChangeEvent], None]):
		"""Register callback for change notifications"""
		self.change_callbacks.append(callback)
	
	def unregister_change_callback(self, callback: Callable[[GraphChangeEvent], None]):
		"""Unregister change callback"""
		if callback in self.change_callbacks:
			self.change_callbacks.remove(callback)
	
	def simulate_change(self, graph_name: str, change_type: GraphChangeType, 
					   element_id: str, element_type: str, 
					   old_data: Dict[str, Any] = None, 
					   new_data: Dict[str, Any] = None):
		"""Simulate a graph change for testing"""
		change_event = GraphChangeEvent(
			id=f"sim_{datetime.now(tz=timezone.utc).timestamp()}",
			timestamp=datetime.now(tz=timezone.utc),
			change_type=change_type,
			graph_name=graph_name,
			element_id=element_id,
			element_type=element_type,
			old_data=old_data,
			new_data=new_data,
			metadata={"simulated": True}
		)
		
		self._notify_change(change_event)


class GraphStreamingManager:
	"""
	Manages real-time graph streaming sessions
	
	Handles WebSocket connections, event filtering, and real-time delivery
	of graph changes to connected clients.
	"""
	
	def __init__(self, change_detector: GraphChangeDetector = None):
		self.change_detector = change_detector or GraphChangeDetector()
		self.sessions: Dict[str, StreamingSession] = {}
		self.session_connections = weakref.WeakKeyDictionary()
		self.event_queue = asyncio.Queue()
		self.is_running = False
		
		# Register for change notifications
		self.change_detector.register_change_callback(self._handle_graph_change)
		
		# Start change detection
		self.change_detector.start_monitoring()
	
	def create_session(self, session_id: str, user_id: str, graph_name: str, 
					  filters: Dict[str, Any] = None, 
					  mode: StreamingMode = StreamingMode.REAL_TIME) -> StreamingSession:
		"""Create new streaming session"""
		session = StreamingSession(
			session_id=session_id,
			user_id=user_id,
			graph_name=graph_name,
			filters=filters or {},
			mode=mode,
			last_activity=datetime.now(tz=timezone.utc)
		)
		
		self.sessions[session_id] = session
		
		# Track session creation
		track_database_activity(
			activity_type=ActivityType.CONNECTION_OPENED,
			target=f"Graph Streaming Session: {session_id}",
			description=f"Created streaming session for graph '{graph_name}'",
			details={
				"session_id": session_id,
				"user_id": user_id,
				"graph_name": graph_name,
				"filters": filters,
				"mode": mode.value
			}
		)
		
		logger.info(f"Created streaming session {session_id} for user {user_id}")
		return session
	
	def get_session(self, session_id: str) -> Optional[StreamingSession]:
		"""Get streaming session by ID"""
		return self.sessions.get(session_id)
	
	def close_session(self, session_id: str):
		"""Close streaming session"""
		session = self.sessions.pop(session_id, None)
		
		if session:
			# Track session closure
			track_database_activity(
				activity_type=ActivityType.CONNECTION_CLOSED,
				target=f"Graph Streaming Session: {session_id}",
				description=f"Closed streaming session",
				details={
					"session_id": session_id,
					"duration_minutes": (datetime.now(tz=timezone.utc) - session.statistics["start_time"]).total_seconds() / 60,
					"events_sent": session.statistics["events_sent"],
					"events_filtered": session.statistics["events_filtered"]
				}
			)
			
			logger.info(f"Closed streaming session {session_id}")
	
	def register_connection(self, session_id: str, connection):
		"""Register WebSocket connection for session"""
		session = self.sessions.get(session_id)
		if session:
			session.connection = connection
			session.last_activity = datetime.now(tz=timezone.utc)
			self.session_connections[connection] = session_id
	
	def unregister_connection(self, connection):
		"""Unregister WebSocket connection"""
		session_id = self.session_connections.pop(connection, None)
		if session_id:
			session = self.sessions.get(session_id)
			if session:
				session.connection = None
	
	def _handle_graph_change(self, change: GraphChangeEvent):
		"""Handle graph change event from detector"""
		# Add to event queue for processing
		try:
			# Since we're in a sync context, we need to handle this carefully
			asyncio.run_coroutine_threadsafe(
				self.event_queue.put(change),
				asyncio.get_event_loop()
			)
		except RuntimeError:
			# No event loop running, process synchronously
			self._process_change_event(change)
	
	def _process_change_event(self, change: GraphChangeEvent):
		"""Process change event and send to matching sessions"""
		for session in list(self.sessions.values()):
			if not session.is_active():
				# Remove inactive sessions
				self.sessions.pop(session.session_id, None)
				continue
			
			if session.matches_filter(change):
				self._send_event_to_session(session, change)
			else:
				session.statistics["events_filtered"] += 1
	
	def _send_event_to_session(self, session: StreamingSession, change: GraphChangeEvent):
		"""Send change event to specific session"""
		try:
			if session.connection:
				# In a real WebSocket implementation, this would send the event
				event_data = {
					"type": "graph_change",
					"data": change.to_dict(),
					"session_id": session.session_id
				}
				
				# Simulated WebSocket send
				logger.debug(f"Sending event to session {session.session_id}: {change.change_type.value}")
				
				# Update session statistics
				session.statistics["events_sent"] += 1
				session.statistics["last_event_time"] = datetime.now(tz=timezone.utc)
				session.last_activity = datetime.now(tz=timezone.utc)
			
		except Exception as e:
			logger.error(f"Error sending event to session {session.session_id}: {e}")
	
	def get_session_statistics(self) -> Dict[str, Any]:
		"""Get streaming manager statistics"""
		active_sessions = [s for s in self.sessions.values() if s.is_active()]
		
		return {
			"total_sessions": len(self.sessions),
			"active_sessions": len(active_sessions),
			"total_events_sent": sum(s.statistics["events_sent"] for s in active_sessions),
			"total_events_filtered": sum(s.statistics["events_filtered"] for s in active_sessions),
			"session_details": [s.to_dict() for s in active_sessions]
		}
	
	def cleanup_inactive_sessions(self):
		"""Remove inactive sessions"""
		inactive_sessions = [
			session_id for session_id, session in self.sessions.items()
			if not session.is_active()
		]
		
		for session_id in inactive_sessions:
			self.close_session(session_id)
		
		logger.info(f"Cleaned up {len(inactive_sessions)} inactive sessions")
	
	def broadcast_to_graph(self, graph_name: str, message: Dict[str, Any]):
		"""Broadcast message to all sessions monitoring a graph"""
		count = 0
		
		for session in self.sessions.values():
			if session.graph_name == graph_name and session.is_active():
				try:
					if session.connection:
						# Send broadcast message
						broadcast_data = {
							"type": "broadcast",
							"data": message,
							"graph_name": graph_name,
							"timestamp": datetime.now(tz=timezone.utc).isoformat()
						}
						
						logger.debug(f"Broadcasting to session {session.session_id}")
						count += 1
						
				except Exception as e:
					logger.error(f"Error broadcasting to session {session.session_id}: {e}")
		
		logger.info(f"Broadcast message sent to {count} sessions for graph {graph_name}")
		return count
	
	def simulate_graph_activity(self, graph_name: str = "default_graph"):
		"""Simulate graph activity for testing"""
		import random
		
		# Simulate various types of changes
		change_types = [
			GraphChangeType.NODE_CREATED,
			GraphChangeType.NODE_UPDATED,
			GraphChangeType.EDGE_CREATED,
			GraphChangeType.EDGE_UPDATED
		]
		
		for i in range(5):
			change_type = random.choice(change_types)
			element_type = "node" if "NODE" in change_type.value else "edge"
			element_id = f"element_{random.randint(1000, 9999)}"
			
			new_data = {
				"id": element_id,
				"label": f"TestLabel{random.randint(1, 5)}",
				"properties": {
					"name": f"Test {element_type} {i}",
					"value": random.randint(1, 100)
				}
			}
			
			self.change_detector.simulate_change(
				graph_name=graph_name,
				change_type=change_type,
				element_id=element_id,
				element_type=element_type,
				new_data=new_data
			)
		
		logger.info(f"Simulated 5 graph changes for {graph_name}")


# Global instances
_change_detector = None
_streaming_manager = None


def get_change_detector() -> GraphChangeDetector:
	"""Get or create global change detector instance"""
	global _change_detector
	if _change_detector is None:
		_change_detector = GraphChangeDetector()
	return _change_detector


def get_streaming_manager() -> GraphStreamingManager:
	"""Get or create global streaming manager instance"""
	global _streaming_manager
	if _streaming_manager is None:
		_streaming_manager = GraphStreamingManager()
	return _streaming_manager