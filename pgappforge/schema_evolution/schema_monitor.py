"""
Schema Monitor for Real-Time Database Schema Change Detection

This module provides comprehensive database schema monitoring capabilities with
real-time change detection, event handling, and integration with code generation pipelines.
"""

import asyncio
import json
import time
import threading
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging
from datetime import datetime
import hashlib

from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Table, Column

from ..cli.generators.database_inspector import EnhancedDatabaseInspector, TableInfo


class ChangeType(Enum):
    """Schema change type enumeration."""
    TABLE_ADDED = "table_added"
    TABLE_REMOVED = "table_removed"
    TABLE_RENAMED = "table_renamed"
    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_MODIFIED = "column_modified"
    COLUMN_RENAMED = "column_renamed"
    INDEX_ADDED = "index_added"
    INDEX_REMOVED = "index_removed"
    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_REMOVED = "constraint_removed"
    FOREIGN_KEY_ADDED = "foreign_key_added"
    FOREIGN_KEY_REMOVED = "foreign_key_removed"


@dataclass
class SchemaChange:
    """Represents a detected schema change."""
    change_type: ChangeType
    table_name: str
    change_details: Dict[str, Any]
    timestamp: datetime
    change_id: str
    priority: int = 1  # 1=low, 2=medium, 3=high, 4=critical

    def __post_init__(self):
        if not self.change_id:
            # Generate unique change ID
            content = f"{self.change_type.value}_{self.table_name}_{self.timestamp.isoformat()}"
            self.change_id = hashlib.md5(content.encode()).hexdigest()[:12]


@dataclass
class SchemaSnapshot:
    """Represents a complete database schema snapshot."""
    timestamp: datetime
    schema_hash: str
    tables: Dict[str, Dict[str, Any]]
    metadata_version: str


class SchemaMonitor:
    """
    Real-time database schema monitor with change detection and event handling.

    Features:
    - Continuous schema monitoring with configurable intervals
    - Intelligent change detection with detailed analysis
    - Event-driven architecture for immediate response
    - Historical change tracking and versioning
    - Integration with code generation pipelines
    - Support for multiple database engines
    - Configurable monitoring sensitivity
    - Async/sync operation modes
    """

    def __init__(self, database_url: str, config: Optional[Dict[str, Any]] = None):
        self.database_url = database_url
        self.config = config or {}
        self.engine = create_engine(database_url)
        self.inspector = EnhancedDatabaseInspector(database_url)

        # Configuration
        self.monitor_interval = self.config.get("monitor_interval", 30)  # seconds
        self.sensitivity = self.config.get("sensitivity", "medium")  # low, medium, high
        self.storage_path = Path(self.config.get("storage_path", "./schema_monitor_data"))
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # State management
        self._is_monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._current_snapshot: Optional[SchemaSnapshot] = None
        self._change_handlers: List[Callable[[SchemaChange], None]] = []
        self._batch_change_handlers: List[Callable[[List[SchemaChange]], None]] = []

        # Setup logging
        self.logger = self._setup_logger()

        # Load previous snapshot if exists
        self._load_last_snapshot()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging for schema monitor."""
        logger = logging.getLogger("SchemaMonitor")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def start_monitoring(self):
        """Start continuous schema monitoring."""
        if self._is_monitoring:
            self.logger.warning("Schema monitoring is already active")
            return

        self.logger.info(f"Starting schema monitoring with {self.monitor_interval}s interval")
        self._is_monitoring = True

        # Take initial snapshot if none exists
        if not self._current_snapshot:
            self._current_snapshot = self._take_schema_snapshot()
            self._save_snapshot(self._current_snapshot)

        # Start monitoring thread
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop schema monitoring."""
        if not self._is_monitoring:
            return

        self.logger.info("Stopping schema monitoring")
        self._is_monitoring = False

        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def add_change_handler(self, handler: Callable[[SchemaChange], None]):
        """Add a handler for individual schema changes."""
        self._change_handlers.append(handler)
        self.logger.debug(f"Added change handler: {handler.__name__}")

    def add_batch_change_handler(self, handler: Callable[[List[SchemaChange]], None]):
        """Add a handler for batches of schema changes."""
        self._batch_change_handlers.append(handler)
        self.logger.debug(f"Added batch change handler: {handler.__name__}")

    def remove_change_handler(self, handler: Callable[[SchemaChange], None]):
        """Remove a change handler."""
        if handler in self._change_handlers:
            self._change_handlers.remove(handler)

    def force_check(self) -> List[SchemaChange]:
        """Force an immediate schema check and return detected changes."""
        self.logger.info("Forcing schema check")
        return self._check_for_changes()

    def get_current_snapshot(self) -> Optional[SchemaSnapshot]:
        """Get the current schema snapshot."""
        return self._current_snapshot

    def get_change_history(self, limit: int = 100) -> List[SchemaChange]:
        """Get historical schema changes."""
        history_file = self.storage_path / "change_history.json"

        if not history_file.exists():
            return []

        try:
            with open(history_file, 'r') as f:
                history_data = json.load(f)

            changes = []
            for change_data in history_data[-limit:]:
                change = SchemaChange(
                    change_type=ChangeType(change_data["change_type"]),
                    table_name=change_data["table_name"],
                    change_details=change_data["change_details"],
                    timestamp=datetime.fromisoformat(change_data["timestamp"]),
                    change_id=change_data["change_id"],
                    priority=change_data.get("priority", 1)
                )
                changes.append(change)

            return changes

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.error(f"Error loading change history: {e}")
            return []

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._is_monitoring:
            try:
                changes = self._check_for_changes()

                if changes:
                    self.logger.info(f"Detected {len(changes)} schema changes")

                    # Process individual change handlers
                    for change in changes:
                        self._process_change_handlers(change)

                    # Process batch change handlers
                    self._process_batch_change_handlers(changes)

                    # Store changes in history
                    self._store_changes(changes)

                # Wait for next check
                time.sleep(self.monitor_interval)

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.monitor_interval)

    def _check_for_changes(self) -> List[SchemaChange]:
        """Check for schema changes by comparing with previous snapshot."""
        current_snapshot = self._take_schema_snapshot()

        if not self._current_snapshot:
            self.logger.info("No previous snapshot found, storing current as baseline")
            self._current_snapshot = current_snapshot
            self._save_snapshot(current_snapshot)
            return []

        # Detect changes between snapshots
        changes = self._compare_snapshots(self._current_snapshot, current_snapshot)

        if changes:
            # Update current snapshot
            self._current_snapshot = current_snapshot
            self._save_snapshot(current_snapshot)

        return changes

    def _take_schema_snapshot(self) -> SchemaSnapshot:
        """Take a complete snapshot of the current database schema."""
        tables_info = {}

        # Get all table information
        all_tables = self.inspector.get_all_tables()

        for table_info in all_tables:
            tables_info[table_info.name] = {
                "columns": [
                    {
                        "name": col.name,
                        "type": str(col.type),
                        "nullable": col.nullable,
                        "primary_key": col.primary_key,
                        "autoincrement": col.autoincrement,
                        "default": str(col.default) if col.default else None
                    }
                    for col in table_info.columns
                ],
                "indexes": [
                    {
                        "name": idx.name,
                        "columns": idx.columns,
                        "unique": idx.unique
                    }
                    for idx in table_info.indexes
                ],
                "foreign_keys": [
                    {
                        "name": fk.name,
                        "columns": fk.columns,
                        "referred_table": fk.referred_table,
                        "referred_columns": fk.referred_columns
                    }
                    for fk in table_info.foreign_keys
                ],
                "relationships": self.inspector.get_relationships(table_info.name)
            }

        # Generate schema hash
        schema_content = json.dumps(tables_info, sort_keys=True)
        schema_hash = hashlib.sha256(schema_content.encode()).hexdigest()

        return SchemaSnapshot(
            timestamp=datetime.now(),
            schema_hash=schema_hash,
            tables=tables_info,
            metadata_version="1.0"
        )

    def _compare_snapshots(self, old_snapshot: SchemaSnapshot,
                         new_snapshot: SchemaSnapshot) -> List[SchemaChange]:
        """Compare two schema snapshots and detect changes."""
        changes = []

        # Quick check - if hashes are same, no changes
        if old_snapshot.schema_hash == new_snapshot.schema_hash:
            return changes

        old_tables = set(old_snapshot.tables.keys())
        new_tables = set(new_snapshot.tables.keys())

        # Detect table-level changes
        added_tables = new_tables - old_tables
        removed_tables = old_tables - new_tables
        common_tables = old_tables & new_tables

        # Process added tables
        for table_name in added_tables:
            change = SchemaChange(
                change_type=ChangeType.TABLE_ADDED,
                table_name=table_name,
                change_details={
                    "table_info": new_snapshot.tables[table_name]
                },
                timestamp=new_snapshot.timestamp,
                change_id="",
                priority=3  # High priority for new tables
            )
            changes.append(change)

        # Process removed tables
        for table_name in removed_tables:
            change = SchemaChange(
                change_type=ChangeType.TABLE_REMOVED,
                table_name=table_name,
                change_details={
                    "table_info": old_snapshot.tables[table_name]
                },
                timestamp=new_snapshot.timestamp,
                change_id="",
                priority=4  # Critical priority for removed tables
            )
            changes.append(change)

        # Process modified tables
        for table_name in common_tables:
            table_changes = self._compare_table_definitions(
                table_name,
                old_snapshot.tables[table_name],
                new_snapshot.tables[table_name],
                new_snapshot.timestamp
            )
            changes.extend(table_changes)

        return changes

    def _compare_table_definitions(self, table_name: str, old_table: Dict[str, Any],
                                 new_table: Dict[str, Any], timestamp: datetime) -> List[SchemaChange]:
        """Compare table definitions and detect column/constraint changes."""
        changes = []

        # Compare columns
        old_columns = {col["name"]: col for col in old_table["columns"]}
        new_columns = {col["name"]: col for col in new_table["columns"]}

        added_columns = set(new_columns.keys()) - set(old_columns.keys())
        removed_columns = set(old_columns.keys()) - set(new_columns.keys())
        common_columns = set(old_columns.keys()) & set(new_columns.keys())

        # Process added columns
        for col_name in added_columns:
            change = SchemaChange(
                change_type=ChangeType.COLUMN_ADDED,
                table_name=table_name,
                change_details={
                    "column_name": col_name,
                    "column_info": new_columns[col_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=2  # Medium priority
            )
            changes.append(change)

        # Process removed columns
        for col_name in removed_columns:
            change = SchemaChange(
                change_type=ChangeType.COLUMN_REMOVED,
                table_name=table_name,
                change_details={
                    "column_name": col_name,
                    "column_info": old_columns[col_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=3  # High priority for removed columns
            )
            changes.append(change)

        # Process modified columns
        for col_name in common_columns:
            old_col = old_columns[col_name]
            new_col = new_columns[col_name]

            if self._column_has_changed(old_col, new_col):
                change = SchemaChange(
                    change_type=ChangeType.COLUMN_MODIFIED,
                    table_name=table_name,
                    change_details={
                        "column_name": col_name,
                        "old_column_info": old_col,
                        "new_column_info": new_col,
                        "changes": self._identify_column_changes(old_col, new_col)
                    },
                    timestamp=timestamp,
                    change_id="",
                    priority=2  # Medium priority
                )
                changes.append(change)

        # Compare indexes
        old_indexes = {idx["name"]: idx for idx in old_table["indexes"]}
        new_indexes = {idx["name"]: idx for idx in new_table["indexes"]}

        added_indexes = set(new_indexes.keys()) - set(old_indexes.keys())
        removed_indexes = set(old_indexes.keys()) - set(new_indexes.keys())

        # Process index changes
        for idx_name in added_indexes:
            change = SchemaChange(
                change_type=ChangeType.INDEX_ADDED,
                table_name=table_name,
                change_details={
                    "index_name": idx_name,
                    "index_info": new_indexes[idx_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=1  # Low priority
            )
            changes.append(change)

        for idx_name in removed_indexes:
            change = SchemaChange(
                change_type=ChangeType.INDEX_REMOVED,
                table_name=table_name,
                change_details={
                    "index_name": idx_name,
                    "index_info": old_indexes[idx_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=1  # Low priority
            )
            changes.append(change)

        # Compare foreign keys
        old_fks = {fk["name"]: fk for fk in old_table["foreign_keys"] if fk["name"]}
        new_fks = {fk["name"]: fk for fk in new_table["foreign_keys"] if fk["name"]}

        added_fks = set(new_fks.keys()) - set(old_fks.keys())
        removed_fks = set(old_fks.keys()) - set(new_fks.keys())

        # Process foreign key changes
        for fk_name in added_fks:
            change = SchemaChange(
                change_type=ChangeType.FOREIGN_KEY_ADDED,
                table_name=table_name,
                change_details={
                    "foreign_key_name": fk_name,
                    "foreign_key_info": new_fks[fk_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=2  # Medium priority
            )
            changes.append(change)

        for fk_name in removed_fks:
            change = SchemaChange(
                change_type=ChangeType.FOREIGN_KEY_REMOVED,
                table_name=table_name,
                change_details={
                    "foreign_key_name": fk_name,
                    "foreign_key_info": old_fks[fk_name]
                },
                timestamp=timestamp,
                change_id="",
                priority=2  # Medium priority
            )
            changes.append(change)

        return changes

    def _column_has_changed(self, old_col: Dict[str, Any], new_col: Dict[str, Any]) -> bool:
        """Check if a column definition has changed."""
        # Compare relevant column properties
        comparable_fields = ["type", "nullable", "default", "primary_key", "autoincrement"]

        for field in comparable_fields:
            if old_col.get(field) != new_col.get(field):
                return True

        return False

    def _identify_column_changes(self, old_col: Dict[str, Any],
                               new_col: Dict[str, Any]) -> Dict[str, Any]:
        """Identify specific changes in a column definition."""
        changes = {}
        comparable_fields = ["type", "nullable", "default", "primary_key", "autoincrement"]

        for field in comparable_fields:
            old_value = old_col.get(field)
            new_value = new_col.get(field)

            if old_value != new_value:
                changes[field] = {
                    "old_value": old_value,
                    "new_value": new_value
                }

        return changes

    def _process_change_handlers(self, change: SchemaChange):
        """Process individual change handlers."""
        for handler in self._change_handlers:
            try:
                handler(change)
            except Exception as e:
                self.logger.error(f"Error in change handler {handler.__name__}: {e}")

    def _process_batch_change_handlers(self, changes: List[SchemaChange]):
        """Process batch change handlers."""
        for handler in self._batch_change_handlers:
            try:
                handler(changes)
            except Exception as e:
                self.logger.error(f"Error in batch change handler {handler.__name__}: {e}")

    def _store_changes(self, changes: List[SchemaChange]):
        """Store changes in history file."""
        history_file = self.storage_path / "change_history.json"

        # Load existing history
        history = []
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    history = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                history = []

        # Add new changes
        for change in changes:
            change_data = asdict(change)
            change_data["timestamp"] = change.timestamp.isoformat()
            change_data["change_type"] = change.change_type.value
            history.append(change_data)

        # Keep only last 1000 changes
        history = history[-1000:]

        # Save updated history
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)

    def _save_snapshot(self, snapshot: SchemaSnapshot):
        """Save schema snapshot to disk."""
        snapshot_file = self.storage_path / "current_snapshot.json"

        snapshot_data = {
            "timestamp": snapshot.timestamp.isoformat(),
            "schema_hash": snapshot.schema_hash,
            "tables": snapshot.tables,
            "metadata_version": snapshot.metadata_version
        }

        with open(snapshot_file, 'w') as f:
            json.dump(snapshot_data, f, indent=2)

    def _load_last_snapshot(self):
        """Load the last saved schema snapshot."""
        snapshot_file = self.storage_path / "current_snapshot.json"

        if not snapshot_file.exists():
            return

        try:
            with open(snapshot_file, 'r') as f:
                snapshot_data = json.load(f)

            self._current_snapshot = SchemaSnapshot(
                timestamp=datetime.fromisoformat(snapshot_data["timestamp"]),
                schema_hash=snapshot_data["schema_hash"],
                tables=snapshot_data["tables"],
                metadata_version=snapshot_data.get("metadata_version", "1.0")
            )

            self.logger.info(f"Loaded previous snapshot from {self._current_snapshot.timestamp}")

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.warning(f"Could not load previous snapshot: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        history = self.get_change_history()

        change_types = {}
        for change in history:
            change_type = change.change_type.value
            change_types[change_type] = change_types.get(change_type, 0) + 1

        return {
            "monitoring_active": self._is_monitoring,
            "monitor_interval": self.monitor_interval,
            "total_changes": len(history),
            "change_types": change_types,
            "last_check": self._current_snapshot.timestamp.isoformat() if self._current_snapshot else None,
            "handlers_registered": len(self._change_handlers) + len(self._batch_change_handlers)
        }

    async def async_check_for_changes(self) -> List[SchemaChange]:
        """Async version of change checking."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._check_for_changes)

    def __enter__(self):
        """Context manager entry."""
        self.start_monitoring()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop_monitoring()


# Utility functions for common monitoring patterns
def create_file_change_handler(output_file: str) -> Callable[[List[SchemaChange]], None]:
    """Create a handler that writes changes to a file."""
    def handler(changes: List[SchemaChange]):
        with open(output_file, 'a') as f:
            for change in changes:
                f.write(f"{change.timestamp}: {change.change_type.value} in {change.table_name}\n")

    return handler


def create_webhook_handler(webhook_url: str) -> Callable[[List[SchemaChange]], None]:
    """Create a handler that posts changes to a webhook."""
    def handler(changes: List[SchemaChange]):
        import requests

        payload = {
            "timestamp": datetime.now().isoformat(),
            "changes": [asdict(change) for change in changes]
        }

        try:
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            print(f"Failed to send webhook: {e}")

    return handler