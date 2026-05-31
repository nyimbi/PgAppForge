"""VersionControlWidget — PgAppForge widget(s)."""

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

class VersionControlWidget(BS3TextFieldWidget):
    """
    Widget for tracking and managing version history of records/documents in a table.

    This widget provides comprehensive version control functionality including diff viewing,
    rollback, branching, and conflict resolution. It tracks changes to specified fields
    and maintains a full audit trail with comments and notifications.

    Features:
    - Version history tracking and visualization
    - Side-by-side diff viewing with syntax highlighting
    - Point-in-time restore/rollback capability
    - Git-style branching and merging
    - Conflict detection and resolution
    - Comments and annotations on changes
    - Interactive timeline visualization
    - Version comparison and diff exports
    - Complete audit trail with user tracking
    - Real-time change notifications
    - Role-based access control
    - Bulk restore/rollback support
    - Full text search across versions
    - Customizable diff rules and displays
    - Branch visualization
    - Performance optimized for large histories

    Database Type:
        PostgreSQL: JSONB for storing version history, metadata and configurations
        SQLAlchemy: JSON type with validation

    Required Dependencies:
    - diff-match-patch >= 1.0.1 (diffing engine)
    - CodeMirror >= 5.65.0 (syntax highlighting)
    - vis-timeline >= 7.4.0 (timeline visualization)
    - merge-deep >= 3.0.0 (merge handling)
    - jsondiffpatch >= 0.4.1 (JSON diffing)

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79
    - Opera >= 47
    - iOS Safari >= 12
    - Chrome for Android >= 89

    Required Permissions:
    - Database write access for version storage
    - File system access for exports
    - WebSocket for real-time updates
    - LocalStorage for preferences

    Performance Considerations:
    - Use lazy loading for version history
    - Implement pagination for large histories
    - Cache frequently accessed versions
    - Compress version storage
    - Optimize diff computation
    - Clean up old versions
    - Monitor memory usage

    Security Implications:
    - Validate all version data
    - Sanitize user comments
    - Enforce access control
    - Audit all operations
    - Rate limit operations
    - Encrypt sensitive diffs
    - Handle PII appropriately

    Example:
        version_control = db.Column(db.JSON,
            info={'widget': VersionControlWidget(
                track_fields=['content', 'metadata'],
                diff_view=True,
                restore=True,
                comments=True,
                max_versions=100,
                branch_support=True,
                merge_strategy='recursive',
                notification_rules={
                    'email': ['major_version'],
                    'ui': ['all']
                }
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/diff_match_patch/20121119/diff_match_patch.js",
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/codemirror.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/mode/javascript/javascript.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/7.4.0/vis-timeline-graph2d.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jsondiffpatch/0.4.1/jsondiffpatch.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "/static/js/version-control.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.0/codemirror.min.css",
        "https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/7.4.0/vis-timeline-graph2d.min.css",
        "/static/css/version-control.css",
    ]

    # Default merge strategies
    MERGE_STRATEGIES = {
        "latest": "Take latest version",
        "recursive": "Recursive merge",
        "manual": "Manual conflict resolution",
    }

    def __init__(self, **kwargs):
        """
        Initialize VersionControlWidget with custom settings.

        Args:
            track_fields (list): Fields to track changes
            diff_view (bool): Enable diff viewing
            restore (bool): Enable version restore
            comments (bool): Enable version comments
            max_versions (int): Maximum versions to keep
            branch_support (bool): Enable branching
            merge_strategy (str): Conflict resolution strategy
            notification_rules (dict): Change notification settings
            cache_versions (bool): Enable version caching
            compress_storage (bool): Enable storage compression
            exclude_fields (list): Fields to exclude from versioning
            diff_context_lines (int): Number of context lines in diffs
            retention_period (int): Days to retain versions
            auto_prune (bool): Auto remove old versions
            access_control (dict): Access control rules
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.track_fields = kwargs.get("track_fields", [])
        self.diff_view = kwargs.get("diff_view", True)
        self.restore = kwargs.get("restore", True)
        self.comments = kwargs.get("comments", True)
        self.max_versions = kwargs.get("max_versions", 100)
        self.branch_support = kwargs.get("branch_support", False)
        self.merge_strategy = kwargs.get("merge_strategy", "recursive")
        self.notification_rules = kwargs.get("notification_rules", {"ui": ["all"]})

        # Advanced Settings
        self.cache_versions = kwargs.get("cache_versions", True)
        self.compress_storage = kwargs.get("compress_storage", True)
        self.exclude_fields = kwargs.get("exclude_fields", ["created_at", "updated_at"])
        self.diff_context_lines = min(max(kwargs.get("diff_context_lines", 3), 0), 10)
        self.retention_period = kwargs.get("retention_period", 365)
        self.auto_prune = kwargs.get("auto_prune", True)
        self.access_control = kwargs.get("access_control", {})
        self.debug_mode = kwargs.get("debug_mode", False)

        # Validate settings
        self._validate_config()

    def render_field(self, field, **kwargs):
        """
        Render the version control widget with all controls and visualizations.

        Args:
            field: The form field instance
            **kwargs: Additional HTML attributes

        Returns:
            str: Rendered HTML for the widget
        """
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        js_config = {
            "trackFields": self.track_fields,
            "diffView": self.diff_view,
            "restore": self.restore,
            "comments": self.comments,
            "maxVersions": self.max_versions,
            "branchSupport": self.branch_support,
            "mergeStrategy": self.merge_strategy,
            "notificationRules": self.notification_rules,
            "cacheVersions": self.cache_versions,
            "compressStorage": self.compress_storage,
            "excludeFields": self.exclude_fields,
            "diffContextLines": self.diff_context_lines,
            "retentionPeriod": self.retention_period,
            "autoPrune": self.auto_prune,
            "accessControl": self.access_control,
            "debugMode": self.debug_mode,
        }

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="version-control-widget" id="{field.id}-container">
                <!-- Version History Timeline -->
                <div class="version-timeline mb-3">
                    <div id="{field.id}-timeline"></div>
                </div>

                <!-- Diff Viewer -->
                {self._render_diff_viewer(field.id) if self.diff_view else ''}

                <!-- Version Controls -->
                <div class="version-controls mb-3">
                    {self._render_version_controls(field.id)}
                </div>

                <!-- Branch Management -->
                {self._render_branch_controls(field.id) if self.branch_support else ''}

                <!-- Comments Section -->
                {self._render_comments_section(field.id) if self.comments else ''}

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner-border"></div>
                    <span class="sr-only">Loading version history...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    var versionControl = new VersionControl('{field.id}', {_js_json(js_config)});

                    // Error handler
                    function showError(error) {{
                        $('.version-control-widget .alert').text(error).show().delay(5000).fadeOut();
                    }}

                    // Loading state handler
                    function toggleLoading(show) {{
                        $('.loading-overlay').toggle(show);
                    }}

                    // Diff view update handler
                    function updateDiffView(version) {{
                        if ({str(self.diff_view).lower()}) {{
                            versionControl.renderDiff(version);
                        }}
                    }}

                    // Load initial data if exists
                    var existingData = $('#{field.id}').val();
                    if (existingData) {{
                        versionControl.loadVersions(JSON.parse(existingData));
                    }}

                    // Cleanup
                    window.addEventListener('unload', function() {{
                        versionControl.cleanup();
                    }});
                }});
            </script>
        """
        )

    def _include_dependencies(self):
        """Include required JavaScript and CSS dependencies"""
        js_includes = "\n".join(
            f'<script src="{url}"></script>' for url in self.JS_DEPENDENCIES
        )
        css_includes = "\n".join(
            f'<link rel="stylesheet" href="{url}">' for url in self.CSS_DEPENDENCIES
        )
        return f"{css_includes}\n{js_includes}"

    def _render_diff_viewer(self, field_id):
        """Render the diff viewer interface"""
        return f"""
            <div class="diff-viewer mb-3">
                <div class="diff-controls">
                    <select id="{field_id}-version1" class="form-control"></select>
                    <select id="{field_id}-version2" class="form-control"></select>
                </div>
                <div id="{field_id}-diff" class="diff-content"></div>
            </div>
        """

    def _render_version_controls(self, field_id):
        """Render version control buttons"""
        controls = []
        if self.restore:
            controls.append(
                f"""
                <button type="button" class="btn btn-primary"
                        id="{field_id}-restore">
                    Restore Version
                </button>
            """
            )

        controls.append(
            f"""
            <button type="button" class="btn btn-secondary"
                    id="{field_id}-export">
                Export History
            </button>
        """
        )

        return "\n".join(controls)

    def _render_branch_controls(self, field_id):
        """Render branch management controls"""
        return f"""
            <div class="branch-controls mb-3">
                <select id="{field_id}-branch" class="form-control">
                    <option value="main">main</option>
                </select>
                <button type="button" class="btn btn-secondary"
                        id="{field_id}-create-branch">
                    Create Branch
                </button>
                <button type="button" class="btn btn-primary"
                        id="{field_id}-merge">
                    Merge
                </button>
            </div>
        """

    def _render_comments_section(self, field_id):
        """Render version comments section"""
        return f"""
            <div class="comments-section mb-3">
                <div class="comment-list" id="{field_id}-comments"></div>
                <div class="comment-input">
                    <textarea class="form-control"
                             id="{field_id}-comment"
                             placeholder="Add a comment..."></textarea>
                    <button type="button" class="btn btn-primary mt-2"
                            id="{field_id}-add-comment">
                        Add Comment
                    </button>
                </div>
            </div>
        """

    def _validate_config(self):
        """Validate widget configuration settings"""
        if not self.track_fields:
            raise ValueError("At least one field must be tracked")

        if self.merge_strategy not in self.MERGE_STRATEGIES:
            raise ValueError(f"Invalid merge strategy: {self.merge_strategy}")

        if self.max_versions and self.max_versions < 1:
            raise ValueError("max_versions must be greater than 0")

    def process_formdata(self, valuelist):
        """Process form data and validate"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_version_data(data)
                self.data = data
            except json.JSONDecodeError:
                raise ValueError("Invalid version data format")
            except ValueError as e:
                raise ValueError(str(e))
        else:
            self.data = None

    def _validate_version_data(self, data):
        """Validate version data structure and content"""
        if not isinstance(data, dict):
            raise ValueError("Invalid version data structure")

        required_keys = ["versions", "current", "branches"]
        if not all(key in data for key in required_keys):
            raise ValueError("Missing required version data keys")

        if not isinstance(data["versions"], list):
            raise ValueError("Versions must be a list")

        for version in data["versions"]:
            if not isinstance(version, dict):
                raise ValueError("Each version must be a dictionary")

            required_version_keys = ["id", "timestamp", "changes"]
            if not all(key in version for key in required_version_keys):
                raise ValueError("Missing required version keys")

    def pre_validate(self, form):
        """Validate before form processing"""
        if self.data is not None:
            try:
                self._validate_version_data(self.data)
            except ValueError as e:
                raise ValueError(str(e))
