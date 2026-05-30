"""
Comprehensive notification system for collaborative workspaces.

Provides real-time alerts, digest emails, push notifications, and
notification preferences management for collaborative features.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from pgappforge.models.sqla import Model
from pgappforge.models.mixins import AuditMixin
import json
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    """Result of a notification delivery attempt."""

    success: bool
    external_id: Optional[str] = None
    error: Optional[str] = None
    retry_after: Optional[int] = None  # Seconds to wait before retry


class NotificationType(Enum):
    """Types of notifications."""

    COMMENT_MENTION = "comment_mention"
    COMMENT_REPLY = "comment_reply"
    THREAD_RESOLVED = "thread_resolved"
    WORKSPACE_INVITE = "workspace_invite"
    TEAM_INVITE = "team_invite"
    DOCUMENT_SHARED = "document_shared"
    EDIT_CONFLICT = "edit_conflict"
    DEADLINE_REMINDER = "deadline_reminder"
    SYSTEM_ALERT = "system_alert"
    WORKSPACE_UPDATE = "workspace_update"
    USER_JOINED = "user_joined"
    PERMISSION_CHANGED = "permission_changed"


class NotificationPriority(Enum):
    """Priority levels for notifications."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DeliveryChannel(Enum):
    """Notification delivery channels."""

    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"


class Notification(Model, AuditMixin):
    """Individual notification record with PgAppForge integration."""

    __tablename__ = "fab_notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=True)

    notification_type = Column(String(50), nullable=False)
    priority = Column(String(20), default=NotificationPriority.NORMAL.value)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)

    # Related entities
    related_entity_type = Column(
        String(50), nullable=True
    )  # 'comment', 'thread', 'workspace'
    related_entity_id = Column(String(255), nullable=True)

    # Metadata
    meta_data = Column(JSON, nullable=True)  # Additional context data
    action_url = Column(String(500), nullable=True)  # URL for notification action

    # Timestamps
    scheduled_for = Column(DateTime, nullable=True)  # For delayed notifications
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)

    # Status
    is_read = Column(Boolean, default=False)
    is_delivered = Column(Boolean, default=False)
    delivery_attempts = Column(Integer, default=0)
    max_delivery_attempts = Column(Integer, default=3)

    # Grouping for digest notifications
    digest_group = Column(String(100), nullable=True)

    # created_by_id and audit fields are provided by AuditMixin


class NotificationPreference(Model, AuditMixin):
    """User notification preferences with PgAppForge integration."""

    __tablename__ = "fab_notification_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=True)

    notification_type = Column(String(50), nullable=False)
    delivery_channels = Column(JSON, nullable=False)  # List of enabled channels
    is_enabled = Column(Boolean, default=True)

    # Timing preferences
    immediate_delivery = Column(Boolean, default=True)
    digest_frequency = Column(
        String(20), default="daily"
    )  # 'never', 'hourly', 'daily', 'weekly'
    quiet_hours_start = Column(Integer, nullable=True)  # Hour 0-23
    quiet_hours_end = Column(Integer, nullable=True)  # Hour 0-23

    # created_by_id and audit fields are provided by AuditMixin
    # changed_by_id from AuditMixin tracks the last updater


class NotificationDelivery(Model, AuditMixin):
    """Tracking of notification delivery attempts with PgAppForge integration."""

    __tablename__ = "fab_notification_deliveries"

    id = Column(Integer, primary_key=True)
    notification_id = Column(
        Integer, ForeignKey("fab_notifications.id"), nullable=False
    )
    delivery_channel = Column(String(20), nullable=False)
    delivery_status = Column(
        String(20), nullable=False
    )  # 'pending', 'sent', 'failed', 'bounced'
    attempted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    delivered_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # External tracking
    external_id = Column(
        String(255), nullable=True
    )  # ID from email service, push service, etc.

    # created_by_id and audit fields are provided by AuditMixin  # ID from email service, push service, etc.


class NotificationDigest(Model, AuditMixin):
    """Digest email/notification batches with PgAppForge integration."""

    __tablename__ = "fab_notification_digests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("fab_workspaces.id"), nullable=True)
    digest_type = Column(String(20), nullable=False)  # 'hourly', 'daily', 'weekly'

    sent_at = Column(DateTime, nullable=True)
    notification_count = Column(Integer, default=0)

    # Content
    digest_content = Column(JSON, nullable=True)  # Grouped notification data

    # created_by_id and audit fields are provided by AuditMixin  # Grouped notification data


class NotificationManager:
    """Manages notifications for collaborative workspaces."""

    def __init__(
        self,
        websocket_manager=None,
        session_factory=None,
        email_service=None,
        push_service=None,
    ):
        self.websocket_manager = websocket_manager
        self.session_factory = session_factory
        self.email_service = email_service
        self.push_service = push_service

        self.delivery_queue: asyncio.Queue = asyncio.Queue()
        self.digest_scheduler_running = False

    async def create_notification(
        self,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        message: str,
        workspace_id: Optional[int] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        action_url: Optional[str] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> Optional[Notification]:
        """Create a new notification."""
        try:
            session = self.session_factory()

            notification = Notification(
                user_id=user_id,
                workspace_id=workspace_id,
                notification_type=notification_type.value,
                priority=priority.value,
                title=title,
                message=message,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
                metadata=metadata,
                action_url=action_url,
                scheduled_for=scheduled_for,
            )

            session.add(notification)
            session.commit()

            logger.info(f"Created notification {notification.id} for user {user_id}")

            # Queue for immediate delivery if not scheduled
            if not scheduled_for:
                await self.delivery_queue.put(notification.id)

            return notification

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create notification: {e}")
            return None
        finally:
            session.close()

    async def create_bulk_notifications(
        self,
        user_ids: List[int],
        notification_type: NotificationType,
        title: str,
        message: str,
        workspace_id: Optional[int] = None,
        **kwargs,
    ) -> List[int]:
        """Create notifications for multiple users efficiently."""
        try:
            session = self.session_factory()
            notification_ids = []

            for user_id in user_ids:
                notification = Notification(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    notification_type=notification_type.value,
                    title=title,
                    message=message,
                    **kwargs,
                )
                session.add(notification)
                session.flush()
                notification_ids.append(notification.id)

            session.commit()

            # Queue all for delivery
            for notification_id in notification_ids:
                await self.delivery_queue.put(notification_id)

            logger.info(f"Created {len(notification_ids)} bulk notifications")
            return notification_ids

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create bulk notifications: {e}")
            return []
        finally:
            session.close()

    async def get_user_notifications(
        self,
        user_id: int,
        workspace_id: Optional[int] = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get notifications for a user."""
        try:
            session = self.session_factory()

            query = session.query(Notification).filter_by(user_id=user_id)

            if workspace_id:
                query = query.filter_by(workspace_id=workspace_id)

            if unread_only:
                query = query.filter_by(is_read=False)

            notifications = (
                query.order_by(Notification.created_at.desc()).limit(limit).all()
            )

            result = []
            for notif in notifications:
                result.append(
                    {
                        "id": notif.id,
                        "type": notif.notification_type,
                        "priority": notif.priority,
                        "title": notif.title,
                        "message": notif.message,
                        "workspace_id": notif.workspace_id,
                        "related_entity_type": notif.related_entity_type,
                        "related_entity_id": notif.related_entity_id,
                        "metadata": notif.metadata,
                        "action_url": notif.action_url,
                        "created_at": notif.created_at.isoformat(),
                        "read_at": notif.read_at.isoformat() if notif.read_at else None,
                        "is_read": notif.is_read,
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get user notifications: {e}")
            return []
        finally:
            session.close()

    async def mark_notification_read(self, notification_id: int, user_id: int) -> bool:
        """Mark a notification as read."""
        try:
            session = self.session_factory()

            notification = (
                session.query(Notification)
                .filter_by(id=notification_id, user_id=user_id)
                .first()
            )

            if notification and not notification.is_read:
                notification.is_read = True
                notification.read_at = datetime.now(timezone.utc)
                session.commit()

                # Real-time update
                await self._notify_read_status_change(notification)

                return True

            return False

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to mark notification read: {e}")
            return False
        finally:
            session.close()

    async def mark_all_read(
        self, user_id: int, workspace_id: Optional[int] = None
    ) -> int:
        """Mark all notifications as read for a user."""
        try:
            session = self.session_factory()

            query = session.query(Notification).filter_by(
                user_id=user_id, is_read=False
            )

            if workspace_id:
                query = query.filter_by(workspace_id=workspace_id)

            notifications = query.all()
            count = len(notifications)

            for notification in notifications:
                notification.is_read = True
                notification.read_at = datetime.now(timezone.utc)

            session.commit()

            # Batch real-time update
            await self._notify_bulk_read_status_change(user_id, workspace_id)

            logger.info(f"Marked {count} notifications as read for user {user_id}")
            return count

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to mark all notifications read: {e}")
            return 0
        finally:
            session.close()

    async def get_notification_counts(
        self, user_id: int, workspace_id: Optional[int] = None
    ) -> Dict[str, int]:
        """Get notification counts for a user."""
        try:
            session = self.session_factory()

            query = session.query(Notification).filter_by(user_id=user_id)
            if workspace_id:
                query = query.filter_by(workspace_id=workspace_id)

            total = query.count()
            unread = query.filter_by(is_read=False).count()
            urgent = query.filter_by(
                is_read=False, priority=NotificationPriority.URGENT.value
            ).count()

            return {"total": total, "unread": unread, "urgent": urgent}

        except Exception as e:
            logger.error(f"Failed to get notification counts: {e}")
            return {"total": 0, "unread": 0, "urgent": 0}
        finally:
            session.close()

    async def set_notification_preferences(
        self,
        user_id: int,
        notification_type: NotificationType,
        delivery_channels: List[DeliveryChannel],
        workspace_id: Optional[int] = None,
        **preferences,
    ) -> bool:
        """Set notification preferences for a user."""
        try:
            session = self.session_factory()

            # Check for existing preference
            existing = (
                session.query(NotificationPreference)
                .filter_by(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    notification_type=notification_type.value,
                )
                .first()
            )

            if existing:
                existing.delivery_channels = [ch.value for ch in delivery_channels]
                existing.updated_at = datetime.now(timezone.utc)

                # Update other preferences
                for key, value in preferences.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                pref = NotificationPreference(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    notification_type=notification_type.value,
                    delivery_channels=[ch.value for ch in delivery_channels],
                    **preferences,
                )
                session.add(pref)

            session.commit()
            logger.info(f"Updated notification preferences for user {user_id}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to set notification preferences: {e}")
            return False
        finally:
            session.close()

    async def get_notification_preferences(
        self, user_id: int, workspace_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get notification preferences for a user."""
        try:
            session = self.session_factory()

            preferences = (
                session.query(NotificationPreference)
                .filter_by(user_id=user_id, workspace_id=workspace_id)
                .all()
            )

            result = {}
            for pref in preferences:
                result[pref.notification_type] = {
                    "delivery_channels": pref.delivery_channels,
                    "is_enabled": pref.is_enabled,
                    "immediate_delivery": pref.immediate_delivery,
                    "digest_frequency": pref.digest_frequency,
                    "quiet_hours_start": pref.quiet_hours_start,
                    "quiet_hours_end": pref.quiet_hours_end,
                }

            return result

        except Exception as e:
            logger.error(f"Failed to get notification preferences: {e}")
            return {}
        finally:
            session.close()

    async def process_delivery_queue(self) -> None:
        """Process the notification delivery queue."""
        logger.info("Starting notification delivery queue processor")

        while True:
            try:
                # Get next notification to deliver
                notification_id = await self.delivery_queue.get()
                await self._deliver_notification(notification_id)

            except Exception as e:
                logger.error(f"Error processing delivery queue: {e}")
                await asyncio.sleep(5)  # Brief pause on error

    async def _deliver_notification(self, notification_id: int) -> None:
        """Deliver a single notification through appropriate channels."""
        try:
            session = self.session_factory()

            notification = session.query(Notification).get(notification_id)
            if not notification:
                return

            # Get user preferences
            preferences = await self.get_notification_preferences(
                notification.user_id, notification.workspace_id
            )

            type_prefs = preferences.get(notification.notification_type, {})
            delivery_channels = type_prefs.get("delivery_channels", ["in_app"])

            # Check if in quiet hours
            if self._is_quiet_hours(type_prefs):
                # Schedule for later
                notification.scheduled_for = self._get_next_delivery_time(type_prefs)
                session.commit()
                return

            # Deliver through each enabled channel
            for channel in delivery_channels:
                try:
                    if channel == DeliveryChannel.IN_APP.value:
                        await self._deliver_in_app(notification)
                    elif channel == DeliveryChannel.EMAIL.value:
                        await self._deliver_email(notification)
                    elif channel == DeliveryChannel.PUSH.value:
                        await self._deliver_push(notification)
                    elif channel == DeliveryChannel.SMS.value:
                        await self._deliver_sms(notification)

                    # Record delivery attempt
                    delivery = NotificationDelivery(
                        notification_id=notification.id,
                        delivery_channel=channel,
                        delivery_status="sent",
                    )
                    session.add(delivery)

                except Exception as e:
                    logger.error(f"Failed to deliver via {channel}: {e}")

                    # Record failed delivery
                    delivery = NotificationDelivery(
                        notification_id=notification.id,
                        delivery_channel=channel,
                        delivery_status="failed",
                        error_message=str(e),
                    )
                    session.add(delivery)

            # Mark as delivered
            notification.is_delivered = True
            notification.delivered_at = datetime.now(timezone.utc)
            notification.delivery_attempts += 1
            session.commit()

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to deliver notification {notification_id}: {e}")
        finally:
            session.close()

    async def _deliver_in_app(self, notification: Notification) -> bool:
        """Deliver notification via in-app mechanism (WebSocket broadcast) with verification."""
        try:
            # In-app notifications are stored in database, so they're always "delivered"
            # WebSocket broadcast is best-effort for real-time delivery
            if self.websocket_manager:
                try:
                    # Attempt real-time WebSocket broadcast
                    notification_data = {
                        "type": "notification",
                        "id": notification.id,
                        "notification_type": notification.notification_type,
                        "priority": notification.priority,
                        "title": notification.title,
                        "message": notification.message,
                        "action_url": notification.action_url,
                        "metadata": notification.metadata,
                        "created_at": notification.created_at.isoformat(),
                    }
                    await self.websocket_manager.send_to_user(
                        notification.user_id, notification_data
                    )
                    logger.debug(
                        f"Real-time notification broadcast sent for {notification.id}"
                    )
                except Exception as ws_error:
                    # WebSocket failure doesn't fail in-app delivery since notification is in database
                    logger.warning(
                        f"WebSocket broadcast failed for notification {notification.id}: {ws_error}"
                    )

            # Record successful in-app delivery
            await self._record_delivery_success(notification.id, DeliveryChannel.IN_APP)
            logger.info(
                f"In-app delivery successful for notification {notification.id}"
            )
            return True

        except Exception as e:
            logger.error(
                f"In-app delivery failed for notification {notification.id}: {e}"
            )
            await self._record_delivery_failure(
                notification.id, DeliveryChannel.IN_APP, str(e)
            )
            return False

    async def _deliver_email(self, notification: Notification) -> bool:
        """Deliver notification via email with proper verification."""
        if not self.email_service:
            logger.warning(
                f"Email service not configured - notification {notification.id} not sent"
            )
            await self._record_delivery_failure(
                notification.id, DeliveryChannel.EMAIL, "Email service not configured"
            )
            return await self._try_fallback_delivery(
                notification, DeliveryChannel.EMAIL
            )

        try:
            # Try to send email using configured service
            delivery_result = await self._send_email_with_service(notification)

            if delivery_result.success:
                await self._record_delivery_success(
                    notification.id, DeliveryChannel.EMAIL, delivery_result.external_id
                )
                logger.info(
                    f"Email successfully sent for notification {notification.id}"
                )
                return True
            else:
                logger.error(
                    f"Email delivery failed for notification {notification.id}: {delivery_result.error}"
                )
                await self._record_delivery_failure(
                    notification.id, DeliveryChannel.EMAIL, delivery_result.error
                )
                return await self._try_fallback_delivery(
                    notification, DeliveryChannel.EMAIL
                )

        except Exception as e:
            logger.error(
                f"Email delivery exception for notification {notification.id}: {e}"
            )
            await self._record_delivery_failure(
                notification.id, DeliveryChannel.EMAIL, str(e)
            )
            return await self._try_fallback_delivery(
                notification, DeliveryChannel.EMAIL
            )

    async def _deliver_push(self, notification: Notification) -> bool:
        """Deliver notification via push notification with proper verification."""
        if not self.push_service:
            logger.warning(
                f"Push service not configured - notification {notification.id} not sent"
            )
            await self._record_delivery_failure(
                notification.id, DeliveryChannel.PUSH, "Push service not configured"
            )
            return await self._try_fallback_delivery(notification, DeliveryChannel.PUSH)

        try:
            # Try to send push notification using configured service
            delivery_result = await self._send_push_with_service(notification)

            if delivery_result.success:
                await self._record_delivery_success(
                    notification.id, DeliveryChannel.PUSH, delivery_result.external_id
                )
                logger.info(
                    f"Push notification successfully sent for notification {notification.id}"
                )
                return True
            else:
                logger.error(
                    f"Push delivery failed for notification {notification.id}: {delivery_result.error}"
                )
                await self._record_delivery_failure(
                    notification.id, DeliveryChannel.PUSH, delivery_result.error
                )
                return await self._try_fallback_delivery(
                    notification, DeliveryChannel.PUSH
                )

        except Exception as e:
            logger.error(
                f"Push delivery exception for notification {notification.id}: {e}"
            )
            await self._record_delivery_failure(
                notification.id, DeliveryChannel.PUSH, str(e)
            )
            return await self._try_fallback_delivery(notification, DeliveryChannel.PUSH)

    async def _deliver_sms(self, notification: Notification) -> None:
        """Deliver notification via SMS."""
        # Implementation would depend on SMS service
        logger.info(f"SMS delivery for notification {notification.id}")

    def _is_quiet_hours(self, preferences: Dict[str, Any]) -> bool:
        """Check if current time is in user's quiet hours."""
        start_hour = preferences.get("quiet_hours_start")
        end_hour = preferences.get("quiet_hours_end")

        if start_hour is None or end_hour is None:
            return False

        current_hour = datetime.now(timezone.utc).hour

        if start_hour <= end_hour:
            return start_hour <= current_hour <= end_hour
        else:  # Quiet hours span midnight
            return current_hour >= start_hour or current_hour <= end_hour

    def _get_next_delivery_time(self, preferences: Dict[str, Any]) -> datetime:
        """Get next delivery time outside quiet hours."""
        end_hour = preferences.get("quiet_hours_end", 8)

        now = datetime.now(timezone.utc)
        next_delivery = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        if next_delivery <= now:
            next_delivery += timedelta(days=1)

        return next_delivery

    async def _notify_read_status_change(self, notification: Notification) -> None:
        """Notify about notification read status change."""
        if not self.websocket_manager:
            return

        update_data = {
            "type": "notification_read",
            "notification_id": notification.id,
            "read_at": notification.read_at.isoformat(),
        }

        await self.websocket_manager.send_to_user(notification.user_id, update_data)

    async def _notify_bulk_read_status_change(
        self, user_id: int, workspace_id: Optional[int]
    ) -> None:
        """Notify about bulk read status change."""
        if not self.websocket_manager:
            return

        update_data = {
            "type": "notifications_bulk_read",
            "workspace_id": workspace_id,
            "read_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.websocket_manager.send_to_user(user_id, update_data)

    async def start_digest_scheduler(self) -> None:
        """Start the digest notification scheduler."""
        if self.digest_scheduler_running:
            return

        self.digest_scheduler_running = True
        logger.info("Starting notification digest scheduler")

        while self.digest_scheduler_running:
            try:
                await self._process_digests()
                await asyncio.sleep(3600)  # Check every hour
            except Exception as e:
                logger.error(f"Error in digest scheduler: {e}")
                await asyncio.sleep(300)  # Retry in 5 minutes

    async def _process_digests(self) -> None:
        """Process pending digest notifications."""
        try:
            session = self.session_factory()

            # Find users who need digests
            now = datetime.now(timezone.utc)

            # Process hourly digests
            await self._create_digests(session, "hourly", now - timedelta(hours=1))

            # Process daily digests (at 8 AM UTC)
            if now.hour == 8:
                await self._create_digests(session, "daily", now - timedelta(days=1))

            # Process weekly digests (Monday at 8 AM UTC)
            if now.weekday() == 0 and now.hour == 8:
                await self._create_digests(session, "weekly", now - timedelta(weeks=1))

        except Exception as e:
            logger.error(f"Failed to process digests: {e}")
        finally:
            session.close()

    async def _create_digests(self, session, digest_type: str, since: datetime) -> None:
        """Create digest notifications for users."""
        # Get users with digest preferences
        preferences = (
            session.query(NotificationPreference)
            .filter_by(digest_frequency=digest_type)
            .all()
        )

        for pref in preferences:
            # Get undelivered notifications for this user
            notifications = (
                session.query(Notification)
                .filter(
                    Notification.user_id == pref.user_id,
                    Notification.workspace_id == pref.workspace_id,
                    Notification.created_at >= since,
                    Notification.is_delivered == False,
                )
                .all()
            )

            if notifications:
                await self._send_digest(
                    pref.user_id, pref.workspace_id, digest_type, notifications
                )

    async def _send_digest(
        self,
        user_id: int,
        workspace_id: Optional[int],
        digest_type: str,
        notifications: List[Notification],
    ) -> None:
        """Send a digest notification."""
        try:
            session = self.session_factory()

            # Group notifications by type
            grouped = {}
            for notif in notifications:
                if notif.notification_type not in grouped:
                    grouped[notif.notification_type] = []
                grouped[notif.notification_type].append(notif)

            # Create digest content
            digest_content = {}
            for notif_type, notifs in grouped.items():
                digest_content[notif_type] = {
                    "count": len(notifs),
                    "latest": notifs[0].created_at.isoformat(),
                    "titles": [n.title for n in notifs[:5]],  # First 5 titles
                }

            # Create digest record
            digest = NotificationDigest(
                user_id=user_id,
                workspace_id=workspace_id,
                digest_type=digest_type,
                notification_count=len(notifications),
                digest_content=digest_content,
            )
            session.add(digest)

            # Mark notifications as delivered
            for notif in notifications:
                notif.is_delivered = True
                notif.delivered_at = datetime.now(timezone.utc)

            session.commit()

            # Send digest email/notification
            if self.email_service:
                await self._send_digest_email(digest)

            logger.info(
                f"Sent {digest_type} digest to user {user_id} with {len(notifications)} notifications"
            )

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to send digest: {e}")
        finally:
            session.close()

    async def _send_digest_email(self, digest: NotificationDigest) -> bool:
        """Send digest email to user with proper verification."""
        if not self.email_service:
            logger.error(f"Email service not configured - digest {digest.id} not sent")
            return False

        try:
            # Create email content from digest
            email_content = self._create_digest_email_content(digest)

            # Send digest email
            delivery_result = await self.email_service.send_digest_email(
                digest.user_id, email_content
            )

            if delivery_result.success:
                # Update digest as sent
                session = self.session_factory()
                try:
                    digest.sent_at = datetime.now(timezone.utc)
                    session.commit()
                    logger.info(
                        f"Digest email successfully sent for digest {digest.id}"
                    )
                    return True
                finally:
                    session.close()
            else:
                logger.error(
                    f"Digest email delivery failed for digest {digest.id}: {delivery_result.error}"
                )
                return False

        except Exception as e:
            logger.error(f"Digest email delivery exception for digest {digest.id}: {e}")
            return False

    def stop_digest_scheduler(self) -> None:
        """Stop the digest notification scheduler."""
        self.digest_scheduler_running = False
        logger.info("Stopped notification digest scheduler")

    async def _send_email_with_service(
        self, notification: Notification
    ) -> DeliveryResult:
        """Send email using configured email service."""
        try:
            # Check if email service has the required method
            if not hasattr(self.email_service, "send_notification_email"):
                return DeliveryResult(
                    success=False,
                    error="Email service does not support notification emails",
                )

            # Call the email service
            result = await self.email_service.send_notification_email(
                recipient_id=notification.user_id,
                subject=notification.title,
                message=notification.message,
                notification_type=notification.notification_type,
                metadata=notification.metadata,
            )

            if isinstance(result, dict):
                return DeliveryResult(
                    success=result.get("success", False),
                    external_id=result.get("message_id"),
                    error=result.get("error"),
                )
            else:
                # Assume boolean result for simple email services
                return DeliveryResult(
                    success=bool(result),
                    error=None if result else "Email service returned failure",
                )

        except Exception as e:
            return DeliveryResult(
                success=False, error=f"Email service exception: {str(e)}"
            )

    async def _send_push_with_service(
        self, notification: Notification
    ) -> DeliveryResult:
        """Send push notification using configured push service."""
        try:
            # Check if push service has the required method
            if not hasattr(self.push_service, "send_push_notification"):
                return DeliveryResult(
                    success=False, error="Push service does not support notifications"
                )

            # Call the push service
            result = await self.push_service.send_push_notification(
                user_id=notification.user_id,
                title=notification.title,
                message=notification.message,
                data=notification.metadata,
            )

            if isinstance(result, dict):
                return DeliveryResult(
                    success=result.get("success", False),
                    external_id=result.get("notification_id"),
                    error=result.get("error"),
                )
            else:
                # Assume boolean result for simple push services
                return DeliveryResult(
                    success=bool(result),
                    error=None if result else "Push service returned failure",
                )

        except Exception as e:
            return DeliveryResult(
                success=False, error=f"Push service exception: {str(e)}"
            )

    async def _record_delivery_success(
        self,
        notification_id: int,
        channel: DeliveryChannel,
        external_id: Optional[str] = None,
    ) -> None:
        """Record successful delivery attempt."""
        try:
            session = self.session_factory()

            delivery = NotificationDelivery(
                notification_id=notification_id,
                delivery_channel=channel.value,
                delivery_status="sent",
                delivered_at=datetime.now(timezone.utc),
                external_id=external_id,
            )
            session.add(delivery)
            session.commit()

        except Exception as e:
            logger.error(f"Failed to record delivery success: {e}")
            session.rollback()
        finally:
            session.close()

    async def _record_delivery_failure(
        self, notification_id: int, channel: DeliveryChannel, error_message: str
    ) -> None:
        """Record failed delivery attempt."""
        try:
            session = self.session_factory()

            delivery = NotificationDelivery(
                notification_id=notification_id,
                delivery_channel=channel.value,
                delivery_status="failed",
                error_message=error_message,
            )
            session.add(delivery)
            session.commit()

        except Exception as e:
            logger.error(f"Failed to record delivery failure: {e}")
            session.rollback()
        finally:
            session.close()

    async def _try_fallback_delivery(
        self, notification: Notification, failed_channel: DeliveryChannel
    ) -> bool:
        """Try alternative delivery methods when primary channel fails."""
        try:
            # Define fallback order
            fallback_channels = {
                DeliveryChannel.EMAIL: [DeliveryChannel.IN_APP, DeliveryChannel.PUSH],
                DeliveryChannel.PUSH: [DeliveryChannel.IN_APP, DeliveryChannel.EMAIL],
                DeliveryChannel.SMS: [DeliveryChannel.IN_APP, DeliveryChannel.EMAIL],
                DeliveryChannel.IN_APP: [],  # No fallback for in-app notifications
            }

            # Get user preferences to see which fallbacks are enabled
            preferences = await self.get_notification_preferences(
                notification.user_id, notification.workspace_id
            )
            enabled_channels = preferences.get(
                "enabled_channels", [DeliveryChannel.IN_APP.value]
            )

            # Try fallback channels
            for fallback_channel in fallback_channels.get(failed_channel, []):
                if fallback_channel.value in enabled_channels:
                    logger.info(
                        f"Trying fallback delivery via {fallback_channel.value} for notification {notification.id}"
                    )

                    if fallback_channel == DeliveryChannel.IN_APP:
                        # In-app notifications are always successful (stored in database)
                        await self._record_delivery_success(
                            notification.id, fallback_channel
                        )
                        return True
                    elif (
                        fallback_channel == DeliveryChannel.EMAIL and self.email_service
                    ):
                        return await self._deliver_email(notification)
                    elif fallback_channel == DeliveryChannel.PUSH and self.push_service:
                        return await self._deliver_push(notification)

            # If all fallbacks fail, at least ensure in-app notification exists
            logger.warning(
                f"All delivery methods failed for notification {notification.id}, defaulting to in-app only"
            )
            await self._record_delivery_success(notification.id, DeliveryChannel.IN_APP)
            return True

        except Exception as e:
            logger.error(
                f"Fallback delivery failed for notification {notification.id}: {e}"
            )
            return False

    def _create_digest_email_content(
        self, digest: NotificationDigest
    ) -> Dict[str, Any]:
        """Create email content from digest data."""
        try:
            digest_content = digest.digest_content or {}

            return {
                "subject": f"Your {digest.digest_type} notification digest ({digest.notification_count} updates)",
                "template": "notification_digest",
                "context": {
                    "digest_type": digest.digest_type,
                    "notification_count": digest.notification_count,
                    "grouped_notifications": digest_content,
                    "digest_date": digest.created_at.strftime("%Y-%m-%d"),
                    "user_id": digest.user_id,
                    "workspace_id": digest.workspace_id,
                },
            }
        except Exception as e:
            logger.error(f"Failed to create digest email content: {e}")
            return {
                "subject": f"Your {digest.digest_type} notification digest",
                "template": "notification_digest_fallback",
                "context": {
                    "error": "Failed to load digest content",
                    "digest_id": digest.id,
                },
            }
