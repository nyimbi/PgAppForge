"""ChatMessagingWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class ChatMessagingWidget(BS3TextFieldWidget):
    """
    Real-time chat and messaging widget for internal communication.

    Features:
    - Real-time messaging with encrypted transport
    - File attachments with virus scanning
    - User presence tracking and status indicators
    - Message threading and conversation organization
    - Read receipts and delivery status
    - Typing indicators and activity states
    - Full emoji/GIF/sticker support
    - Full text message search with highlighting
    - Group chats with role management
    - Direct messages with privacy controls
    - Message reactions and quick responses
    - Audio/video calls with screen sharing
    - Message history with infinite scroll
    - Fully responsive mobile interface
    - Rich notification system
    - Message translation
    - Voice messages
    - Custom message formatting
    - Message forwarding
    - Mention notifications
    - Message editing/deletion
    - User blocking
    - Chat backup/export
    - Link previews
    - File previews

    Database Type:
        PostgreSQL: JSONB
        SQLAlchemy: JSON

    Required Dependencies:
    - Socket.io 4.5+ (real-time communication)
    - MediaStream API (audio/video)
    - SimpleWebRTC (WebRTC wrapper)
    - EmojiPicker 14+ (emoji support)
    - Linkify 4+ (link detection)
    - Moment.js 2.29+ (timestamps)
    - AutoLinker 3+ (URL parsing)
    - localforage 1.10+ (offline storage)
    - Notification API
    - Push API

    Browser Support:
    - Chrome 60+
    - Firefox 60+
    - Safari 12+
    - Edge 79+
    - Opera 47+
    - iOS Safari 12+
    - Chrome for Android 89+

    Required Permissions:
    - WebSocket connections
    - Media access (camera/mic)
    - Notifications
    - Storage/IndexedDB
    - File system access
    - Clipboard access
    - Service workers
    - Push notifications

    Performance Considerations:
    - Message pagination
    - Attachment chunking
    - WebSocket compression
    - Image optimization
    - Message caching
    - Lazy media loading
    - Connection pooling
    - Browser storage limits
    - Memory management
    - CPU usage monitoring

    Security Implications:
    - Message encryption
    - File scanning
    - XSS prevention
    - Input sanitization
    - Rate limiting
    - User authentication
    - Access control
    - Data retention
    - Audit logging
    - Privacy controls

    Best Practices:
    - Enable encryption
    - Set file limits
    - Configure moderation
    - Add rate limiting
    - Enable backups
    - Monitor usage
    - Train users
    - Test edge cases
    - Document policies
    - Regular updates

    Example:
        chat = db.Column(db.JSON, nullable=False,
            info={'widget': ChatMessagingWidget(
                enable_attachments=True,
                enable_groups=True,
                notifications=True,
                history_limit=1000,
                encryption=True,
                moderation=True
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/simple-peer/9.11.1/simplepeer.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/emoji-picker/14.0.0/emoji-picker.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/linkifyjs/4.1.1/linkify.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.4/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/autolinker/3.15.0/Autolinker.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/localforage/1.10.0/localforage.min.js",
        "/static/js/chat-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/emoji-picker/14.0.0/emoji-picker.min.css",
        "/static/css/chat-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize ChatMessagingWidget with custom settings.

        Args:
            enable_attachments (bool): Enable file attachments
            enable_groups (bool): Enable group chats
            notifications (bool): Enable notifications
            history_limit (int): Message history limit
            file_types (list): Allowed attachment types
            max_file_size (int): Maximum file size in bytes
            presence_tracking (bool): Enable presence tracking
            encryption (bool): Enable end-to-end encryption
            moderation (bool): Enable message moderation
            translation (bool): Enable message translation
            retention_days (int): Message retention period
            max_group_size (int): Maximum users per group
            typing_timeout (int): Typing indicator timeout
            offline_support (bool): Enable offline functionality
            giphy_key (str): Giphy API key for GIF support
            socket_url (str): Custom socket.io endpoint
            push_enabled (bool): Enable push notifications
            call_timeout (int): Call ring timeout
            message_edit_window (int): Edit time window
            file_scan_enabled (bool): Enable virus scanning
        """
        super().__init__(**kwargs)

        # Core features
        self.enable_attachments = kwargs.get("enable_attachments", True)
        self.enable_groups = kwargs.get("enable_groups", True)
        self.notifications = kwargs.get("notifications", True)
        self.history_limit = kwargs.get("history_limit", 1000)
        self.encryption = kwargs.get("encryption", True)
        self.moderation = kwargs.get("moderation", False)
        self.translation = kwargs.get("translation", False)
        self.offline_support = kwargs.get("offline_support", True)
        self.push_enabled = kwargs.get("push_enabled", True)

        # File handling
        self.file_types = kwargs.get(
            "file_types", ["image/*", "audio/*", "video/*", "application/pdf"]
        )
        self.max_file_size = kwargs.get("max_file_size", 10 * 1024 * 1024)  # 10MB
        self.file_scan_enabled = kwargs.get("file_scan_enabled", True)

        # User tracking
        self.presence_tracking = kwargs.get("presence_tracking", True)
        self.typing_timeout = kwargs.get("typing_timeout", 5000)

        # Group settings
        self.max_group_size = kwargs.get("max_group_size", 100)

        # Message settings
        self.retention_days = kwargs.get("retention_days", 365)
        self.message_edit_window = kwargs.get("message_edit_window", 300)  # 5 mins

        # Media
        self.giphy_key = kwargs.get("giphy_key", None)
        self.call_timeout = kwargs.get("call_timeout", 30)  # 30 secs

        # Endpoints
        self.socket_url = kwargs.get("socket_url", "/chat/ws")

    def render_field(self, field, **kwargs):
        """Render the chat widget with all controls and UI elements"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="chat-widget" role="region" aria-label="Chat Interface" id="{field.id}-container">
                <!-- Sidebar -->
                <div class="chat-sidebar">
                    <div class="user-profile">
                        <img src="/static/img/default-avatar.png" alt="User avatar" class="avatar">
                        <span class="username"></span>
                        <span class="status-indicator"></span>
                    </div>

                    <div class="chat-tabs" role="tablist">
                        <button class="tab active" role="tab" aria-selected="true">Chats</button>
                        <button class="tab" role="tab">Groups</button>
                        <button class="tab" role="tab">Contacts</button>
                    </div>

                    <div class="chat-list" role="tabpanel"></div>
                </div>

                <!-- Main Chat Area -->
                <div class="chat-main">
                    <div class="chat-header">
                        <div class="chat-info">
                            <h3 class="chat-title"></h3>
                            <span class="chat-status"></span>
                        </div>

                        <div class="chat-actions">
                            <button class="btn" aria-label="Start call">
                                <i class="fa fa-phone"></i>
                            </button>
                            <button class="btn" aria-label="Start video">
                                <i class="fa fa-video"></i>
                            </button>
                            <button class="btn" aria-label="Chat settings">
                                <i class="fa fa-cog"></i>
                            </button>
                        </div>
                    </div>

                    <div class="message-container" role="log" aria-live="polite">
                        <div class="messages"></div>
                        <div class="typing-indicator" aria-live="polite"></div>
                    </div>

                    <div class="composer">
                        <div class="attachment-preview"></div>

                        <div class="input-container">
                            {f'''
                            <button class="attach-btn" aria-label="Attach file">
                                <i class="fa fa-paperclip"></i>
                            </button>
                            ''' if self.enable_attachments else ''}

                            <div class="message-input" contenteditable="true"
                                 role="textbox" aria-label="Type a message"></div>

                            <button class="emoji-btn" aria-label="Add emoji">
                                <i class="fa fa-smile"></i>
                            </button>

                            <button class="send-btn" aria-label="Send message">
                                <i class="fa fa-paper-plane"></i>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Call/Video UI -->
                <div class="call-container" style="display:none;">
                    <video id="{field.id}-local-video" muted></video>
                    <video id="{field.id}-remote-video"></video>

                    <div class="call-controls">
                        <button class="btn-mute" aria-label="Mute audio">
                            <i class="fa fa-microphone"></i>
                        </button>
                        <button class="btn-camera" aria-label="Toggle camera">
                            <i class="fa fa-video"></i>
                        </button>
                        <button class="btn-screen" aria-label="Share screen">
                            <i class="fa fa-desktop"></i>
                        </button>
                        <button class="btn-end-call" aria-label="End call">
                            <i class="fa fa-phone"></i>
                        </button>
                    </div>
                </div>

                <!-- Loading States -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading chat...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const chat = new ChatWidget('{field.id}', {{
                        enableAttachments: {str(self.enable_attachments).lower()},
                        enableGroups: {str(self.enable_groups).lower()},
                        notifications: {str(self.notifications).lower()},
                        historyLimit: {self.history_limit},
                        encryption: {str(self.encryption).lower()},
                        moderation: {str(self.moderation).lower()},
                        translation: {str(self.translation).lower()},
                        offlineSupport: {str(self.offline_support).lower()},
                        pushEnabled: {str(self.push_enabled).lower()},
                        fileTypes: {_js_json(self.file_types)},
                        maxFileSize: {self.max_file_size},
                        fileScanEnabled: {str(self.file_scan_enabled).lower()},
                        presenceTracking: {str(self.presence_tracking).lower()},
                        typingTimeout: {self.typing_timeout},
                        maxGroupSize: {self.max_group_size},
                        retentionDays: {self.retention_days},
                        messageEditWindow: {self.message_edit_window},
                        giphyKey: {f"'{self.giphy_key}'" if self.giphy_key else 'null'},
                        callTimeout: {self.call_timeout},
                        socketUrl: '{self.socket_url}',

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onMessage: function(message) {{
                            handleMessage(message);
                        }},
                        onTyping: function(user) {{
                            showTypingIndicator(user);
                        }},
                        onPresence: function(user, status) {{
                            updatePresence(user, status);
                        }},
                        onCall: function(type, user) {{
                            handleIncomingCall(type, user);
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.chat-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Message handler
                    function handleMessage(message) {{
                        $('#{field.id}').val(JSON.stringify(message));
                        chat.scrollToBottom();
                    }}

                    // Typing indicator
                    function showTypingIndicator(user) {{
                        $('.typing-indicator').text(`${{user}} is typing...`);
                    }}

                    // Presence updates
                    function updatePresence(user, status) {{
                        $(`.user-${{user}} .status`).attr('data-status', status);
                    }}

                    // Call handling
                    function handleIncomingCall(type, user) {{
                        // Show call UI
                        $('.call-container').show();

                        // Initialize media
                        chat.initializeCallMedia(type);
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        chat.loadHistory(JSON.parse(existingData));
                    }}

                    // Request notification permission if needed
                    if (self.notifications && Notification.permission === 'default') {{
                        Notification.requestPermission();
                    }}

                    // Handle window focus
                    $(window).on('focus blur', function(e) {{
                        chat.updatePresence(e.type === 'focus');
                    }});

                    // Cleanup
                    $(window).on('unload', function() {{
                        chat.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            [f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES]
        )
        css_includes = "\n".join(
            [f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES]
        )
        return f"{css_includes}\n{js_includes}"

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_chat_data(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid chat data format") from e
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_chat_data(self, data):
        """Validate chat message data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid chat data structure")

        required_keys = ["type", "content", "timestamp", "sender"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required message keys")

        # Validate message type
        valid_types = ["text", "file", "call", "system"]
        if data["type"] not in valid_types:
            raise ValueError(f"Invalid message type: {data['type']}")

        # Validate content
        if not data["content"]:
            raise ValueError("Empty message content")

        # Validate file data if present
        if data["type"] == "file":
            if not all(k in data for k in ["filename", "size", "mime_type"]):
                raise ValueError("Missing file metadata")

            if data["size"] > self.max_file_size:
                raise ValueError(f"File size exceeds limit: {self.max_file_size} bytes")

            if not any(fnmatch(data["mime_type"], pat) for pat in self.file_types):
                raise ValueError(f"Unsupported file type: {data['mime_type']}")

    def pre_validate(self, form):
        """Validate chat data before form processing"""
        if self.data is not None:
            try:
                self._validate_chat_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))
