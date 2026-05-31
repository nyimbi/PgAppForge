"""CommentAndLikeWidget — PgAppForge widget(s)."""

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

class CommentAndLikeWidget(BS3TextFieldWidget):
    """
    Interactive widget for social interactions including comments and likes/reactions.

    Features:
    - Nested comments/replies with infinite depth
    - Rich text comments with image embedding
    - Multiple reaction types with custom emoji support
    - Real-time updates via WebSockets
    - Mention support (@username) with autocomplete
    - File attachments with preview
    - Comment editing with version history
    - Moderation tools with spam detection
    - Notification system with email/push
    - Vote/Rating system with analytics
    - Comment sorting and filtering
    - Thread collapsing and expansion
    - Report abuse with automated flagging
    - User avatars with Gravatar fallback
    - Emoji picker with custom sets
    - Full-text comment search
    - Analytics tracking and reporting
    - Mobile-first responsive design
    - Accessibility compliance (WCAG 2.1)
    - Internationalization support
    - Rate limiting protection
    - XSS/CSRF prevention
    - Offline support
    - Performance optimization

    Database Type:
        PostgreSQL: JSONB for comments/reactions
        SQLAlchemy: JSON

    Required Dependencies:
    - Socket.io 4.0+
    - TinyMCE 5.0+
    - EmojiPicker 3.0+
    - Moment.js 2.29+
    - Lodash 4.17+
    - AutoLinker 3.0+

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
    - LocalStorage/IndexedDB
    - File system (uploads)
    - Push notifications
    - Service Workers
    - Camera/Microphone (optional)

    Performance Considerations:
    - Lazy load comments
    - Optimize images
    - Cache resources
    - Debounce real-time updates
    - Paginate long threads
    - Compress payloads
    - Index search fields
    - Monitor memory usage
    - Background processing
    - CDN integration

    Security Implications:
    - Input sanitization
    - File upload scanning
    - Rate limiting
    - User authentication
    - Content moderation
    - CSRF protection
    - XSS prevention
    - SQL injection prevention
    - Data encryption
    - Access control

    Example:
        social_interaction = db.Column(db.JSON,
            info={'widget': CommentAndLikeWidget(
                enable_replies=True,
                reaction_types=['like', 'love', 'laugh'],
                enable_attachments=True,
                realtime=True,
                moderation=True,
                max_comment_length=1000,
                allowed_file_types=['image/*', 'pdf'],
                sort_options=['newest', 'oldest', 'popular'],
                notification_config={
                    'email': True,
                    'push': True,
                    'in_app': True
                }
            )})
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.1/socket.io.min.js",
        "https://cdn.tiny.cloud/1/no-api-key/tinymce/5/tinymce.min.js",
        "https://cdn.jsdelivr.net/npm/emoji-picker-element@^1",
        "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.1/moment.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/autolinker/3.14.3/Autolinker.min.js",
        "/static/js/comment-widget.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/tinymce/5.10.0/skins/ui/oxide/skin.min.css",
        "https://cdn.jsdelivr.net/npm/emoji-picker-element@^1/css/emoji-picker.css",
        "/static/css/comment-widget.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize CommentAndLikeWidget with custom settings.

        Args:
            enable_replies (bool): Allow nested replies
            reaction_types (list): Available reaction types
            enable_attachments (bool): Allow file attachments
            realtime (bool): Enable real-time updates
            moderation (bool): Enable moderation features
            max_comment_length (int): Maximum comment length
            allowed_file_types (list): Allowed attachment types
            sort_options (list): Available sort methods
            notification_config (dict): Notification settings
            max_nest_level (int): Maximum nesting level
            max_attachments (int): Maximum attachments per comment
            attachment_size_limit (int): Max file size in bytes
            mention_min_chars (int): Min chars for mention trigger
            cache_duration (int): Cache duration in seconds
            rate_limit (dict): Rate limiting configuration
            moderation_config (dict): Moderation settings
            analytics_config (dict): Analytics settings
            search_config (dict): Search configuration
            offline_config (dict): Offline mode settings
            accessibility_config (dict): A11y settings
            localization (dict): i18n configuration
        """
        super().__init__(**kwargs)

        # Core Features
        self.enable_replies = kwargs.get("enable_replies", True)
        self.reaction_types = kwargs.get("reaction_types", ["like"])
        self.enable_attachments = kwargs.get("enable_attachments", False)
        self.realtime = kwargs.get("realtime", True)
        self.moderation = kwargs.get("moderation", False)
        self.max_comment_length = kwargs.get("max_comment_length", 1000)
        self.allowed_file_types = kwargs.get("allowed_file_types", ["image/*", "pdf"])
        self.sort_options = kwargs.get("sort_options", ["newest", "oldest", "popular"])
        self.notification_config = kwargs.get("notification_config", {})

        # Advanced Settings
        self.max_nest_level = kwargs.get("max_nest_level", 5)
        self.max_attachments = kwargs.get("max_attachments", 5)
        self.attachment_size_limit = kwargs.get(
            "attachment_size_limit", 5 * 1024 * 1024
        )
        self.mention_min_chars = kwargs.get("mention_min_chars", 2)
        self.cache_duration = kwargs.get("cache_duration", 3600)

        # Security Settings
        self.rate_limit = kwargs.get(
            "rate_limit",
            {
                "comments": {"count": 10, "interval": 60},
                "reactions": {"count": 30, "interval": 60},
                "uploads": {"count": 10, "interval": 300},
            },
        )

        # Moderation Settings
        self.moderation_config = kwargs.get(
            "moderation_config",
            {
                "auto_approve": False,
                "spam_check": True,
                "profanity_filter": True,
                "min_length": 2,
                "max_links": 3,
                "require_verification": False,
            },
        )

        # Feature Configurations
        self.analytics_config = kwargs.get(
            "analytics_config",
            {
                "enabled": True,
                "track_views": True,
                "track_engagement": True,
                "track_performance": True,
            },
        )

        self.search_config = kwargs.get(
            "search_config",
            {
                "enabled": True,
                "min_length": 3,
                "fuzzy_match": True,
                "include_replies": True,
            },
        )

        self.offline_config = kwargs.get(
            "offline_config",
            {"enabled": True, "sync_interval": 300, "max_offline_items": 100},
        )

        self.accessibility_config = kwargs.get(
            "accessibility_config",
            {
                "aria_labels": True,
                "keyboard_nav": True,
                "high_contrast": False,
                "screen_reader_support": True,
            },
        )

        self.localization = kwargs.get(
            "localization",
            {
                "enabled": True,
                "default_locale": "en",
                "available_locales": ["en"],
                "rtl_support": False,
            },
        )

    def render_field(self, field, **kwargs):
        """Render the comment and like widget with all controls"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="comment-widget" id="{field.id}-container">
                <!-- Comment Form -->
                <div class="comment-form" role="form">
                    <div class="rich-text-editor"></div>
                    {self._render_attachment_upload(field.id) if self.enable_attachments else ''}
                    <div class="emoji-picker-container"></div>
                    <div class="mentions-container"></div>
                </div>

                <!-- Comment List -->
                <div class="comments-list" role="log" aria-live="polite">
                    <div class="sort-controls">
                        {self._render_sort_options()}
                    </div>
                    <div class="comments-container"></div>
                    <div class="load-more" style="display:none;">
                        <button class="btn btn-link">Load More</button>
                    </div>
                </div>

                <!-- Loading States -->
                <div class="loading-overlay" style="display:none;" role="alert" aria-busy="true">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading comments...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const comments = new CommentWidget('{field.id}', {{
                        enableReplies: {str(self.enable_replies).lower()},
                        reactionTypes: {_js_json(self.reaction_types)},
                        enableAttachments: {str(self.enable_attachments).lower()},
                        realtime: {str(self.realtime).lower()},
                        moderation: {str(self.moderation).lower()},
                        maxLength: {self.max_comment_length},
                        allowedTypes: {_js_json(self.allowed_file_types)},
                        sortOptions: {_js_json(self.sort_options)},
                        maxNestLevel: {self.max_nest_level},
                        maxAttachments: {self.max_attachments},
                        sizeLimit: {self.attachment_size_limit},
                        mentionMinChars: {self.mention_min_chars},
                        rateLimit: {_js_json(self.rate_limit)},
                        moderationConfig: {_js_json(self.moderation_config)},
                        analyticsConfig: {_js_json(self.analytics_config)},
                        searchConfig: {_js_json(self.search_config)},
                        offlineConfig: {_js_json(self.offline_config)},
                        a11yConfig: {_js_json(self.accessibility_config)},
                        localization: {_js_json(self.localization)},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onUpdate: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    // Error handling
                    function showError(error) {{
                        const alert = $('.comment-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    // Loading state
                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize if data exists
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        comments.loadData(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        comments.cleanup();
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

    def _render_attachment_upload(self, field_id):
        """Render file attachment upload area"""
        return f"""
            <div class="attachment-upload" role="region" aria-label="File attachments">
                <input type="file" id="{field_id}-upload" multiple
                       accept="{','.join(self.allowed_file_types)}"
                       aria-describedby="{field_id}-upload-help">
                <small id="{field_id}-upload-help" class="form-text text-muted">
                    Allowed files: {', '.join(self.allowed_file_types)}.
                    Max size: {self.attachment_size_limit/1024/1024}MB
                </small>
                <div class="upload-preview"></div>
            </div>
        """

    def _render_sort_options(self):
        """Render comment sort options"""
        return f"""
            <select class="form-control sort-select" aria-label="Sort comments">
                {' '.join([f'<option value="{opt}">{opt.title()}</option>'
                          for opt in self.sort_options])}
            </select>
        """

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_comment_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid comment data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_comment_data(self, data):
        """Validate comment data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid comment data structure")

        required_keys = ["comments", "reactions", "metadata"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required data keys")

        # Validate individual comments
        for comment in data.get("comments", []):
            if not all(k in comment for k in ["id", "content", "user", "timestamp"]):
                raise ValueError("Invalid comment structure")

            # Content length validation
            if len(comment["content"]) > self.max_comment_length:
                raise ValueError(
                    f"Comment exceeds maximum length of {self.max_comment_length}"
                )

            # Attachment validation
            attachments = comment.get("attachments", [])
            if len(attachments) > self.max_attachments:
                raise ValueError(f"Too many attachments (max: {self.max_attachments})")

            for attachment in attachments:
                if not self._validate_attachment(attachment):
                    raise ValueError("Invalid attachment")

    def _validate_attachment(self, attachment):
        """Validate file attachment metadata"""
        required_keys = ["filename", "size", "type"]
        if not all(key in attachment for key in required_keys):
            return False

        # Size validation
        if attachment["size"] > self.attachment_size_limit:
            return False

        # Type validation
        if not any(fnmatch(attachment["type"], pat) for pat in self.allowed_file_types):
            return False

        return True

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_comment_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))
