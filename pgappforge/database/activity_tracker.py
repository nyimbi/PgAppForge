"""
Database Activity Tracking System

Provides comprehensive tracking of database operations and user activities
for the ERD management system with complete audit logging capabilities.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import sqlalchemy as sa
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


class ActivityType(Enum):
    """Types of database activities that can be tracked"""

    # Table operations
    TABLE_CREATED = "table_created"
    TABLE_DROPPED = "table_dropped"
    TABLE_ALTERED = "table_altered"
    TABLE_RENAMED = "table_renamed"

    # Column operations
    COLUMN_ADDED = "column_added"
    COLUMN_DROPPED = "column_dropped"
    COLUMN_MODIFIED = "column_modified"

    # Constraint operations
    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_DROPPED = "constraint_dropped"

    # Index operations
    INDEX_ADDED = "index_added"
    INDEX_DROPPED = "index_dropped"

    # Data operations
    QUERY_EXECUTED = "query_executed"
    DATA_IMPORTED = "data_imported"
    DATA_EXPORTED = "data_exported"

    # Schema operations
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    MIGRATION_EXECUTED = "migration_executed"
    MIGRATION_ROLLED_BACK = "migration_rolled_back"


class ActivitySeverity(Enum):
    """Severity levels for activities"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DatabaseActivity:
    """
    Represents a database activity with complete metadata

    Attributes:
        activity_id: Unique activity identifier
        activity_type: Type of activity performed
        user_id: ID of user who performed the activity
        username: Username of user who performed the activity
        target: Target object (table name, query, etc.)
        description: Human-readable description
        details: Additional activity details as JSON
        severity: Activity severity level
        timestamp: When activity occurred
        ip_address: IP address of user (optional)
        user_agent: User agent string (optional)
        success: Whether operation was successful
        error_message: Error message if operation failed
    """

    activity_id: str
    activity_type: ActivityType
    user_id: str
    username: str
    target: str
    description: str
    details: Dict[str, Any]
    severity: ActivitySeverity
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert activity to dictionary for serialization"""
        return {
            "activity_id": self.activity_id,
            "activity_type": self.activity_type.value,
            "user_id": self.user_id,
            "username": self.username,
            "target": self.target,
            "description": self.description,
            "details": self.details,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
            "error_message": self.error_message,
        }


class DatabaseActivityTracker:
    """
    Comprehensive database activity tracking system

    Tracks all database operations, user activities, and system events
    with complete audit logging and reporting capabilities.
    """

    def __init__(self, database_uri: str = None):
        """
        Initialize activity tracker with database connection

        Args:
            database_uri: Database connection URI for activity storage
        """
        self.database_uri = database_uri
        self.engine = None
        self._initialize_connection()
        self._initialize_activity_tables()

    def _initialize_connection(self):
        """Initialize database connection for activity storage"""
        try:
            if self.database_uri:
                self.engine = create_engine(self.database_uri)
            else:
                # Try to get from Flask app context
                from flask import current_app

                if current_app and hasattr(current_app, "extensions"):
                    if "sqlalchemy" in current_app.extensions:
                        self.engine = current_app.extensions["sqlalchemy"].db.engine

            if self.engine:
                logger.info("Activity tracker initialized successfully")
            else:
                logger.warning("No database connection available for activity tracking")

        except Exception as e:
            logger.error(f"Failed to initialize activity tracker: {e}")

    def _initialize_activity_tables(self):
        """Create activity tracking tables if they don't exist"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                # Create database activities table
                conn.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS db_activities (
                        activity_id VARCHAR(36) PRIMARY KEY,
                        activity_type VARCHAR(50) NOT NULL,
                        user_id VARCHAR(36) NOT NULL,
                        username VARCHAR(255) NOT NULL,
                        target TEXT NOT NULL,
                        description TEXT NOT NULL,
                        details TEXT,
                        severity VARCHAR(20) NOT NULL,
                        timestamp TIMESTAMP NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent TEXT,
                        success BOOLEAN DEFAULT TRUE,
                        error_message TEXT,
                        INDEX idx_activity_timestamp (timestamp),
                        INDEX idx_activity_user (user_id),
                        INDEX idx_activity_type (activity_type),
                        INDEX idx_activity_target (target(255))
                    )
                """
                    )
                )

                logger.info("Activity tracking tables initialized")

        except Exception as e:
            logger.error(f"Failed to initialize activity tracking tables: {e}")

    def track_activity(
        self,
        activity_type: ActivityType,
        user_id: str,
        username: str,
        target: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        severity: ActivitySeverity = ActivitySeverity.MEDIUM,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> str:
        """
        Track a database activity

        Args:
            activity_type: Type of activity performed
            user_id: ID of user performing activity
            username: Username of user
            target: Target object (table, query, etc.)
            description: Human-readable description
            details: Additional activity details
            severity: Activity severity level
            ip_address: User's IP address
            user_agent: User's browser agent
            success: Whether operation succeeded
            error_message: Error message if failed

        Returns:
            Activity ID
        """
        import uuid

        activity_id = str(uuid.uuid4())

        activity = DatabaseActivity(
            activity_id=activity_id,
            activity_type=activity_type,
            user_id=user_id,
            username=username,
            target=target,
            description=description,
            details=details or {},
            severity=severity,
            timestamp=datetime.now(tz=timezone.utc),
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )

        self._store_activity(activity)

        # Log activity
        log_level = logging.ERROR if not success else logging.INFO
        logger.log(log_level, f"Activity tracked: {description} by {username}")

        return activity_id

    def _store_activity(self, activity: DatabaseActivity):
        """Store activity in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    INSERT INTO db_activities (
                        activity_id, activity_type, user_id, username, target,
                        description, details, severity, timestamp, ip_address,
                        user_agent, success, error_message
                    ) VALUES (
                        :activity_id, :activity_type, :user_id, :username, :target,
                        :description, :details, :severity, :timestamp, :ip_address,
                        :user_agent, :success, :error_message
                    )
                """
                    ),
                    {
                        "activity_id": activity.activity_id,
                        "activity_type": activity.activity_type.value,
                        "user_id": activity.user_id,
                        "username": activity.username,
                        "target": activity.target,
                        "description": activity.description,
                        "details": json.dumps(activity.details),
                        "severity": activity.severity.value,
                        "timestamp": activity.timestamp,
                        "ip_address": activity.ip_address,
                        "user_agent": activity.user_agent,
                        "success": activity.success,
                        "error_message": activity.error_message,
                    },
                )

        except Exception as e:
            logger.error(f"Failed to store activity: {e}")

    def get_recent_activities(
        self,
        limit: int = 20,
        hours_back: int = 24,
        user_id: Optional[str] = None,
        activity_types: Optional[List[ActivityType]] = None,
    ) -> List[DatabaseActivity]:
        """
        Get recent database activities

        Args:
            limit: Maximum number of activities to return
            hours_back: How many hours back to look
            user_id: Filter by specific user (optional)
            activity_types: Filter by activity types (optional)

        Returns:
            List of recent activities
        """
        if not self.engine:
            return []

        try:
            # Build query conditions
            conditions = ["timestamp >= :since"]
            params = {
                "since": datetime.now(tz=timezone.utc) - timedelta(hours=hours_back),
                "limit": limit,
            }

            if user_id:
                conditions.append("user_id = :user_id")
                params["user_id"] = user_id

            if activity_types:
                type_values = [t.value for t in activity_types]
                type_placeholders = ",".join(
                    [f":type_{i}" for i in range(len(type_values))]
                )
                conditions.append(f"activity_type IN ({type_placeholders})")
                for i, type_val in enumerate(type_values):
                    params[f"type_{i}"] = type_val

            query = f"""
                SELECT * FROM db_activities
                WHERE {" AND ".join(conditions)}
                ORDER BY timestamp DESC
                LIMIT :limit
            """

            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)

                activities = []
                for row in result:
                    activity = DatabaseActivity(
                        activity_id=row.activity_id,
                        activity_type=ActivityType(row.activity_type),
                        user_id=row.user_id,
                        username=row.username,
                        target=row.target,
                        description=row.description,
                        details=json.loads(row.details) if row.details else {},
                        severity=ActivitySeverity(row.severity),
                        timestamp=row.timestamp,
                        ip_address=row.ip_address,
                        user_agent=row.user_agent,
                        success=row.success,
                        error_message=row.error_message,
                    )
                    activities.append(activity)

                return activities

        except Exception as e:
            logger.error(f"Failed to get recent activities: {e}")
            return []

    def get_activity_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Get activity summary statistics

        Args:
            hours_back: How many hours back to analyze

        Returns:
            Activity summary with counts and stats
        """
        if not self.engine:
            return {}

        try:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)

            with self.engine.connect() as conn:
                # Get total activity count
                result = conn.execute(
                    text(
                        """
                    SELECT COUNT(*) as total_count
                    FROM db_activities
                    WHERE timestamp >= :since
                """
                    ),
                    {"since": since},
                )
                total_count = result.scalar()

                # Get activity counts by type
                result = conn.execute(
                    text(
                        """
                    SELECT activity_type, COUNT(*) as count
                    FROM db_activities
                    WHERE timestamp >= :since
                    GROUP BY activity_type
                    ORDER BY count DESC
                """
                    ),
                    {"since": since},
                )
                activity_by_type = {row.activity_type: row.count for row in result}

                # Get error count
                result = conn.execute(
                    text(
                        """
                    SELECT COUNT(*) as error_count
                    FROM db_activities
                    WHERE timestamp >= :since AND success = FALSE
                """
                    ),
                    {"since": since},
                )
                error_count = result.scalar()

                # Get unique users count
                result = conn.execute(
                    text(
                        """
                    SELECT COUNT(DISTINCT user_id) as unique_users
                    FROM db_activities
                    WHERE timestamp >= :since
                """
                    ),
                    {"since": since},
                )
                unique_users = result.scalar()

                return {
                    "total_activities": total_count,
                    "activity_by_type": activity_by_type,
                    "error_count": error_count,
                    "success_rate": ((total_count - error_count) / total_count * 100)
                    if total_count > 0
                    else 100,
                    "unique_users": unique_users,
                    "hours_analyzed": hours_back,
                }

        except Exception as e:
            logger.error(f"Failed to get activity summary: {e}")
            return {}

    def cleanup_old_activities(self, days_to_keep: int = 30):
        """
        Clean up old activity records to prevent database bloat

        Args:
            days_to_keep: Number of days of activities to keep
        """
        if not self.engine:
            return

        try:
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days_to_keep)

            with self.engine.begin() as conn:
                result = conn.execute(
                    text(
                        """
                    DELETE FROM db_activities
                    WHERE timestamp < :cutoff_date
                """
                    ),
                    {"cutoff_date": cutoff_date},
                )

                deleted_count = result.rowcount
                logger.info(f"Cleaned up {deleted_count} old activity records")

        except Exception as e:
            logger.error(f"Failed to cleanup old activities: {e}")


# Global activity tracker instance
database_activity_tracker = None


def get_activity_tracker(database_uri: str = None) -> DatabaseActivityTracker:
    """Get or create the global activity tracker instance"""
    global database_activity_tracker
    if database_activity_tracker is None:
        database_activity_tracker = DatabaseActivityTracker(database_uri)
    return database_activity_tracker


def track_database_activity(
    activity_type: ActivityType,
    target: str,
    description: str,
    user_info: Optional[Dict[str, str]] = None,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
):
    """
    Convenience function to track database activities

    Args:
        activity_type: Type of activity
        target: Target object
        description: Description of activity
        user_info: User information dict with id, username, etc.
        details: Additional details
        success: Whether operation succeeded
        error_message: Error message if failed
    """
    try:
        # Get user information from Flask context if not provided
        if not user_info:
            try:
                from flask_login import current_user
                from flask import request

                if current_user and current_user.is_authenticated:
                    user_info = {
                        "user_id": str(current_user.id)
                        if hasattr(current_user, "id")
                        else "unknown",
                        "username": getattr(
                            current_user,
                            "username",
                            getattr(current_user, "email", "unknown"),
                        ),
                        "ip_address": request.remote_addr if request else None,
                        "user_agent": request.headers.get("User-Agent")
                        if request
                        else None,
                    }
                else:
                    user_info = {
                        "user_id": "system",
                        "username": "system",
                        "ip_address": None,
                        "user_agent": None,
                    }
            except Exception:
                user_info = {
                    "user_id": "unknown",
                    "username": "unknown",
                    "ip_address": None,
                    "user_agent": None,
                }

        tracker = get_activity_tracker()
        tracker.track_activity(
            activity_type=activity_type,
            user_id=user_info.get("user_id", "unknown"),
            username=user_info.get("username", "unknown"),
            target=target,
            description=description,
            details=details,
            ip_address=user_info.get("ip_address"),
            user_agent=user_info.get("user_agent"),
            success=success,
            error_message=error_message,
        )

    except Exception as e:
        logger.error(f"Failed to track database activity: {e}")
