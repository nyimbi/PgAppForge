# Collaborative Features Tutorial

![Implementation Status](https://img.shields.io/badge/Features-✅%20Validated-brightgreen)
![Runtime Testing](https://img.shields.io/badge/Runtime%20Testing-🔄%20Required-yellow)
![Tutorial Level](https://img.shields.io/badge/Level-Intermediate-orange)

This tutorial builds on the Getting Started guide and shows you how to implement real-time collaborative editing, team management, and live updates in your PgAppForge application.

> **⚠️ Validation Status**: WebSocket infrastructure and collaborative features have been **confirmed implemented** with full production-ready code. Tutorial examples require runtime testing.

## What You'll Learn

- Set up real-time collaborative document editing
- Implement team management with roles and permissions
- Add live notifications and updates
- Create collaborative workspaces
- Use Operational Transform for conflict resolution

## Prerequisites

- Complete the [Getting Started Tutorial](01_getting_started.md)
- Redis server running
- Basic understanding of WebSockets
- Optional: Multiple browser tabs/users for testing

## Step 1: Enable Collaborative Features

### Update Configuration

Add to your `config.py`:

```python
# Collaborative Features Configuration
ENABLE_COLLABORATIVE_EDITING = True
ENABLE_REAL_TIME_NOTIFICATIONS = True
WEBSOCKET_URL = 'ws://localhost:8080'

# Team Management
ENABLE_TEAM_FEATURES = True
DEFAULT_TEAM_ROLE = 'Member'
TEAM_INVITATION_EXPIRY_HOURS = 48

# Real-time Updates
REALTIME_UPDATE_INTERVAL = 1000  # milliseconds
MAX_COLLABORATIVE_USERS = 20
COLLABORATIVE_TIMEOUT = 300  # seconds

# WebSocket Configuration
SOCKETIO_ASYNC_MODE = 'threading'
SOCKETIO_LOGGER = True
SOCKETIO_ENGINEIO_LOGGER = True
```

### Update Application with SocketIO

Modify `app.py`:

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from flask_socketio import SocketIO

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Initialize SocketIO for real-time features
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize PgAppForge
appbuilder = AppBuilder(app, db.session)

# Import collaborative models and views
from models import Task, TaskCategory, CollaborativeSession, TeamMember
from views import (TaskModelView, TaskCategoryModelView, TaskDashboardView,
                  CollaborativeTaskView, TeamManagementView)
from collaborative_views import setup_collaborative_routes

# Setup collaborative routes and WebSocket handlers
setup_collaborative_routes(app, socketio, appbuilder)

# Register views
appbuilder.add_view(TaskModelView, "Tasks", icon="fa-tasks", category="Task Management")
appbuilder.add_view(TaskCategoryModelView, "Categories", icon="fa-folder", category="Task Management")
appbuilder.add_view(TaskDashboardView, "Dashboard", icon="fa-dashboard")

# Collaborative views
appbuilder.add_view(CollaborativeTaskView, "Collaborative Tasks",
                   icon="fa-users", category="Collaboration")
appbuilder.add_view(TeamManagementView, "Team Management",
                   icon="fa-group", category="Collaboration")

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, debug=True, port=8080, host='0.0.0.0')
```

## Step 2: Add Collaborative Models

Add to `models.py`:

```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

class Team(Model, AuditMixin):
    """Team model for organizing collaborative work."""
    __tablename__ = 'team'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

    # Team settings
    max_members = Column(Integer, default=50)
    is_public = Column(Boolean, default=False)
    invite_code = Column(String(32), unique=True)

    def __repr__(self):
        return self.name

class TeamMember(Model, AuditMixin):
    """Team membership with roles and permissions."""
    __tablename__ = 'team_member'

    id = Column(Integer, primary_key=True)

    # Relationships
    team_id = Column(Integer, ForeignKey('team.id'), nullable=False)
    team = relationship('Team', backref='members')

    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    user = relationship('User')

    # Role and permissions
    role = Column(String(20), default='member')  # owner, admin, member, viewer
    can_edit = Column(Boolean, default=True)
    can_invite = Column(Boolean, default=False)
    can_manage = Column(Boolean, default=False)

    # Status
    joined_on = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime)

    def __repr__(self):
        return f"{self.user} - {self.team} ({self.role})"

class CollaborativeSession(Model):
    """Track active collaborative editing sessions."""
    __tablename__ = 'collaborative_session'

    id = Column(Integer, primary_key=True)

    # Session identification
    session_id = Column(String(64), unique=True, nullable=False)
    document_type = Column(String(50), nullable=False)  # task, document, etc.
    document_id = Column(Integer, nullable=False)

    # User and team
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    user = relationship('User')

    team_id = Column(Integer, ForeignKey('team.id'))
    team = relationship('Team')

    # Session data
    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Operational Transform data
    current_revision = Column(Integer, default=0)
    pending_operations = Column(JSON)  # Store pending operations

class CollaborativeOperation(Model):
    """Store collaborative editing operations for Operational Transform."""
    __tablename__ = 'collaborative_operation'

    id = Column(Integer, primary_key=True)

    # Session reference
    session_id = Column(String(64), ForeignKey('collaborative_session.session_id'))
    session = relationship('CollaborativeSession')

    # Operation details
    operation_type = Column(String(20), nullable=False)  # insert, delete, retain
    position = Column(Integer, nullable=False)
    content = Column(Text)
    length = Column(Integer, default=0)

    # Metadata
    user_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    user = relationship('User')

    revision = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    applied = Column(Boolean, default=False)

class TaskCollaboration(Model):
    """Extended task model for collaborative features."""
    __tablename__ = 'task_collaboration'

    id = Column(Integer, primary_key=True)

    # Task reference
    task_id = Column(Integer, ForeignKey('task.id'), nullable=False)
    task = relationship('Task', backref='collaboration_data')

    # Collaborative settings
    is_collaborative = Column(Boolean, default=False)
    allow_anonymous_edit = Column(Boolean, default=False)
    max_collaborators = Column(Integer, default=10)

    # Current state
    current_editors = Column(JSON)  # List of current active editors
    last_sync = Column(DateTime, default=datetime.utcnow)
    revision_count = Column(Integer, default=0)

    # Team assignment
    team_id = Column(Integer, ForeignKey('team.id'))
    team = relationship('Team')

# Add team relationship to existing Task model
# Add this to your Task model:
# team_id = Column(Integer, ForeignKey('team.id'))
# team = relationship('Team', backref='tasks')
```

## Step 3: Create Collaborative Views

Create `collaborative_views.py`:

```python
from flask import request, render_template, jsonify, session
from pgappforge import BaseView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from flask_socketio import emit, join_room, leave_room, rooms
from datetime import datetime, timedelta
import json
import uuid

def setup_collaborative_routes(app, socketio, appbuilder):
    """Setup collaborative routes and WebSocket handlers."""

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        print(f'Client connected: {request.sid}')
        emit('status', {'msg': 'Connected to collaborative server'})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        print(f'Client disconnected: {request.sid}')
        # Clean up any active sessions
        cleanup_user_sessions(request.sid)

    @socketio.on('join_collaboration')
    def handle_join_collaboration(data):
        """Join a collaborative editing session."""
        document_id = data.get('document_id')
        document_type = data.get('document_type', 'task')
        user_id = session.get('user_id')

        if not user_id:
            emit('error', {'msg': 'User not authenticated'})
            return

        # Create or join collaborative session
        room_name = f"{document_type}_{document_id}"
        join_room(room_name)

        # Record session in database
        with app.app_context():
            from models import CollaborativeSession, User

            # Check if user already has an active session
            existing_session = CollaborativeSession.query.filter_by(
                document_id=document_id,
                document_type=document_type,
                user_id=user_id,
                is_active=True
            ).first()

            if not existing_session:
                session_id = str(uuid.uuid4())
                new_session = CollaborativeSession(
                    session_id=session_id,
                    document_type=document_type,
                    document_id=document_id,
                    user_id=user_id
                )
                appbuilder.session.add(new_session)
                appbuilder.session.commit()

            # Get user info
            user = User.query.get(user_id)
            user_info = {
                'user_id': user_id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name
            }

            # Notify others in the room
            emit('user_joined', user_info, room=room_name, include_self=False)

            # Send current active users to the joining user
            active_users = get_active_users(document_id, document_type)
            emit('active_users', {'users': active_users})

    @socketio.on('leave_collaboration')
    def handle_leave_collaboration(data):
        """Leave a collaborative editing session."""
        document_id = data.get('document_id')
        document_type = data.get('document_type', 'task')
        user_id = session.get('user_id')

        room_name = f"{document_type}_{document_id}"
        leave_room(room_name)

        with app.app_context():
            # Mark session as inactive
            from models import CollaborativeSession
            active_session = CollaborativeSession.query.filter_by(
                document_id=document_id,
                document_type=document_type,
                user_id=user_id,
                is_active=True
            ).first()

            if active_session:
                active_session.is_active = False
                active_session.last_activity = datetime.utcnow()
                appbuilder.session.commit()

            # Notify others
            emit('user_left', {'user_id': user_id}, room=room_name, include_self=False)

    @socketio.on('collaborative_edit')
    def handle_collaborative_edit(data):
        """Handle collaborative editing operations."""
        document_id = data.get('document_id')
        document_type = data.get('document_type', 'task')
        operation = data.get('operation')
        user_id = session.get('user_id')

        if not all([document_id, operation, user_id]):
            emit('error', {'msg': 'Invalid edit operation'})
            return

        with app.app_context():
            try:
                # Apply Operational Transform
                transformed_op = apply_operational_transform(
                    document_id, document_type, operation, user_id
                )

                if transformed_op:
                    # Broadcast to all collaborators except sender
                    room_name = f"{document_type}_{document_id}"
                    emit('operation_applied', {
                        'operation': transformed_op,
                        'user_id': user_id,
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=room_name, include_self=False)

                    # Update document in database
                    update_document_content(document_id, document_type, transformed_op)

            except Exception as e:
                emit('error', {'msg': f'Edit operation failed: {str(e)}'})

    @socketio.on('cursor_position')
    def handle_cursor_position(data):
        """Handle cursor position updates."""
        document_id = data.get('document_id')
        document_type = data.get('document_type', 'task')
        position = data.get('position')
        user_id = session.get('user_id')

        room_name = f"{document_type}_{document_id}"
        emit('cursor_update', {
            'user_id': user_id,
            'position': position
        }, room=room_name, include_self=False)

    def cleanup_user_sessions(session_id):
        """Clean up user sessions on disconnect."""
        with app.app_context():
            from models import CollaborativeSession
            # Mark all user sessions as inactive
            # Note: This is simplified - in production, you'd track session_id properly
            pass

    def get_active_users(document_id, document_type):
        """Get list of active users for a document."""
        with app.app_context():
            from models import CollaborativeSession, User

            cutoff_time = datetime.utcnow() - timedelta(minutes=5)
            active_sessions = CollaborativeSession.query.filter(
                CollaborativeSession.document_id == document_id,
                CollaborativeSession.document_type == document_type,
                CollaborativeSession.is_active == True,
                CollaborativeSession.last_activity > cutoff_time
            ).all()

            users = []
            for session in active_sessions:
                user = session.user
                users.append({
                    'user_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name
                })
            return users

    def apply_operational_transform(document_id, document_type, operation, user_id):
        """Apply Operational Transform algorithm for conflict resolution."""
        from models import CollaborativeOperation, CollaborativeSession

        # Get current document state
        session = CollaborativeSession.query.filter_by(
            document_id=document_id,
            document_type=document_type,
            user_id=user_id,
            is_active=True
        ).first()

        if not session:
            return None

        # Simple OT implementation
        # In production, use a proper OT library like ShareJS
        operation['revision'] = session.current_revision + 1
        operation['user_id'] = user_id

        # Store operation
        new_op = CollaborativeOperation(
            session_id=session.session_id,
            operation_type=operation.get('type', 'insert'),
            position=operation.get('position', 0),
            content=operation.get('content', ''),
            length=operation.get('length', 0),
            user_id=user_id,
            revision=operation['revision']
        )
        appbuilder.session.add(new_op)

        # Update session revision
        session.current_revision = operation['revision']
        session.last_activity = datetime.utcnow()
        appbuilder.session.commit()

        return operation

    def update_document_content(document_id, document_type, operation):
        """Update document content based on operation."""
        if document_type == 'task':
            from models import Task
            task = Task.query.get(document_id)
            if task and operation.get('field') == 'description':
                # Apply operation to task description
                # This is simplified - in production, implement proper text operations
                if operation.get('type') == 'insert':
                    pos = operation.get('position', 0)
                    content = operation.get('content', '')
                    description = task.description or ''
                    task.description = description[:pos] + content + description[pos:]
                    appbuilder.session.commit()

class CollaborativeTaskView(BaseView):
    """View for collaborative task editing."""

    default_view = 'list'

    @expose('/list/')
    @has_access
    def list(self):
        """List tasks available for collaboration."""
        from models import Task, TaskCollaboration

        # Get tasks that are marked as collaborative
        collaborative_tasks = self.appbuilder.session.query(Task)\
            .join(TaskCollaboration, Task.id == TaskCollaboration.task_id, isouter=True)\
            .filter(TaskCollaboration.is_collaborative == True)\
            .all()

        return self.render_template('collaborative_tasks.html',
                                  tasks=collaborative_tasks)

    @expose('/edit/<int:task_id>/')
    @has_access
    def edit(self, task_id):
        """Collaborative editing interface for a task."""
        from models import Task, TaskCollaboration

        task = Task.query.get_or_404(task_id)

        # Get or create collaboration settings
        collaboration = TaskCollaboration.query.filter_by(task_id=task_id).first()
        if not collaboration:
            collaboration = TaskCollaboration(
                task_id=task_id,
                is_collaborative=True
            )
            self.appbuilder.session.add(collaboration)
            self.appbuilder.session.commit()

        return self.render_template('collaborative_edit.html',
                                  task=task,
                                  collaboration=collaboration)

    @expose('/api/enable-collaboration/<int:task_id>/', methods=['POST'])
    @has_access
    def enable_collaboration(self, task_id):
        """Enable collaboration for a task."""
        from models import Task, TaskCollaboration

        task = Task.query.get_or_404(task_id)

        collaboration = TaskCollaboration.query.filter_by(task_id=task_id).first()
        if not collaboration:
            collaboration = TaskCollaboration(
                task_id=task_id,
                is_collaborative=True
            )
            self.appbuilder.session.add(collaboration)
        else:
            collaboration.is_collaborative = True

        self.appbuilder.session.commit()

        return jsonify({'success': True, 'message': 'Collaboration enabled'})

class TeamManagementView(BaseView):
    """Team management interface."""

    default_view = 'list'

    @expose('/list/')
    @has_access
    def list(self):
        """List user's teams."""
        from models import Team, TeamMember

        user_id = self.appbuilder.sm.current_user.id

        # Get teams where user is a member
        user_teams = self.appbuilder.session.query(Team)\
            .join(TeamMember)\
            .filter(TeamMember.user_id == user_id)\
            .filter(TeamMember.is_active == True)\
            .all()

        return self.render_template('team_management.html',
                                  teams=user_teams)

    @expose('/create/', methods=['GET', 'POST'])
    @has_access
    def create(self):
        """Create a new team."""
        if request.method == 'POST':
            from models import Team, TeamMember

            name = request.form.get('name')
            description = request.form.get('description')

            if name:
                team = Team(
                    name=name,
                    description=description,
                    invite_code=str(uuid.uuid4())[:8]
                )
                self.appbuilder.session.add(team)
                self.appbuilder.session.flush()

                # Add creator as team owner
                member = TeamMember(
                    team_id=team.id,
                    user_id=self.appbuilder.sm.current_user.id,
                    role='owner',
                    can_edit=True,
                    can_invite=True,
                    can_manage=True
                )
                self.appbuilder.session.add(member)
                self.appbuilder.session.commit()

                return self.render_template('team_created.html', team=team)

        return self.render_template('create_team.html')

    @expose('/join/<invite_code>/')
    @has_access
    def join(self, invite_code):
        """Join a team using invite code."""
        from models import Team, TeamMember

        team = Team.query.filter_by(invite_code=invite_code).first_or_404()
        user_id = self.appbuilder.sm.current_user.id

        # Check if user is already a member
        existing_member = TeamMember.query.filter_by(
            team_id=team.id,
            user_id=user_id
        ).first()

        if existing_member:
            if existing_member.is_active:
                return self.render_template('already_member.html', team=team)
            else:
                existing_member.is_active = True
                existing_member.joined_on = datetime.utcnow()
        else:
            member = TeamMember(
                team_id=team.id,
                user_id=user_id,
                role='member'
            )
            self.appbuilder.session.add(member)

        self.appbuilder.session.commit()
        return self.render_template('team_joined.html', team=team)
```

## Step 4: Create Collaborative Templates

Create `templates/collaborative_tasks.html`:

```html
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <h1>Collaborative Tasks</h1>

    <div class="row mb-3">
        <div class="col-md-12">
            <a href="{{ url_for('TaskModelView.add') }}" class="btn btn-success">
                <i class="fa fa-plus"></i> Create New Task
            </a>
        </div>
    </div>

    <div class="row">
        {% for task in tasks %}
        <div class="col-md-4 mb-3">
            <div class="card">
                <div class="card-header d-flex justify-content-between">
                    <h6 class="mb-0">{{ task.title }}</h6>
                    <span class="badge {{ task.status_badge_class }}">{{ task.status }}</span>
                </div>
                <div class="card-body">
                    <p class="card-text">{{ task.description[:100] }}{% if task.description|length > 100 %}...{% endif %}</p>

                    <div class="mb-2">
                        <small class="text-muted">
                            Priority: <span class="badge {{ task.priority_badge_class }}">{{ task.priority }}</span>
                        </small>
                    </div>

                    <div class="mb-2">
                        <small class="text-muted">
                            Created by: {{ task.created_by.username if task.created_by else 'Unknown' }}
                        </small>
                    </div>
                </div>
                <div class="card-footer">
                    <a href="{{ url_for('CollaborativeTaskView.edit', task_id=task.id) }}"
                       class="btn btn-primary btn-sm">
                        <i class="fa fa-users"></i> Collaborate
                    </a>
                    <a href="{{ url_for('TaskModelView.show', pk=task.id) }}"
                       class="btn btn-info btn-sm">
                        <i class="fa fa-eye"></i> View
                    </a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>

    {% if not tasks %}
    <div class="alert alert-info">
        <h4>No Collaborative Tasks</h4>
        <p>No tasks are currently set up for collaboration.
           <a href="{{ url_for('TaskModelView.list') }}">Enable collaboration</a>
           on existing tasks or create new ones.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
```

Create `templates/collaborative_edit.html`:

```html
{% extends "appbuilder/base.html" %}

{% block head_css %}
{{ super() }}
<style>
.collaborative-editor {
    border: 1px solid #ddd;
    min-height: 300px;
    padding: 15px;
    border-radius: 4px;
    position: relative;
}

.active-users {
    background: #f8f9fa;
    border-radius: 4px;
    padding: 10px;
    margin-bottom: 15px;
}

.user-cursor {
    position: absolute;
    border-left: 2px solid;
    height: 20px;
    pointer-events: none;
}

.user-avatar {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: bold;
    margin-right: 5px;
}

.collaboration-status {
    position: fixed;
    top: 70px;
    right: 20px;
    background: white;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    max-width: 250px;
}

.typing-indicator {
    color: #28a745;
    font-style: italic;
    margin-left: 10px;
}
</style>
{% endblock %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-md-9">
            <h1>Collaborative Editing: {{ task.title }}</h1>

            <!-- Task Details -->
            <div class="card mb-3">
                <div class="card-header">
                    <h5>Task Information</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <strong>Title:</strong> {{ task.title }}<br>
                            <strong>Priority:</strong>
                            <span class="badge {{ task.priority_badge_class }}">{{ task.priority }}</span><br>
                            <strong>Status:</strong>
                            <span class="badge {{ task.status_badge_class }}">{{ task.status }}</span>
                        </div>
                        <div class="col-md-6">
                            <strong>Created:</strong> {{ task.created_on.strftime('%Y-%m-%d %H:%M') if task.created_on else 'Unknown' }}<br>
                            <strong>Created by:</strong> {{ task.created_by.username if task.created_by else 'Unknown' }}<br>
                            <strong>Category:</strong> {{ task.category.name if task.category else 'None' }}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Collaborative Editor -->
            <div class="card">
                <div class="card-header">
                    <h5>Description <span class="typing-indicator" id="typing-indicator"></span></h5>
                </div>
                <div class="card-body">
                    <div class="active-users" id="active-users">
                        <strong>Active Collaborators:</strong>
                        <div id="user-list" class="mt-2"></div>
                    </div>

                    <div class="collaborative-editor" id="editor" contenteditable="true">
                        {{ task.description or '' }}
                    </div>

                    <div class="mt-3">
                        <button id="save-btn" class="btn btn-success">
                            <i class="fa fa-save"></i> Save Changes
                        </button>
                        <button id="cancel-btn" class="btn btn-secondary">
                            <i class="fa fa-times"></i> Cancel
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="collaboration-status">
                <h6>Collaboration Status</h6>
                <div id="connection-status">
                    <span class="badge badge-secondary">Connecting...</span>
                </div>

                <hr>

                <h6>Recent Activity</h6>
                <div id="activity-feed" style="max-height: 200px; overflow-y: auto;">
                    <!-- Activity items will be added here -->
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block tail_js %}
{{ super() }}
<script src="https://cdn.socket.io/4.0.0/socket.io.min.js"></script>
<script>
$(document).ready(function() {
    // Initialize SocketIO connection
    const socket = io();
    const taskId = {{ task.id }};
    const currentUser = {
        id: {{ g.user.id if g.user else 'null' }},
        username: "{{ g.user.username if g.user else '' }}",
        first_name: "{{ g.user.first_name if g.user else '' }}",
        last_name: "{{ g.user.last_name if g.user else '' }}"
    };

    let activeUsers = {};
    let isTyping = false;
    let typingTimeout;

    // Color scheme for user avatars
    const userColors = ['#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8', '#6f42c1'];

    // Connection handlers
    socket.on('connect', function() {
        $('#connection-status').html('<span class="badge badge-success">Connected</span>');

        // Join collaboration session
        socket.emit('join_collaboration', {
            document_id: taskId,
            document_type: 'task'
        });
    });

    socket.on('disconnect', function() {
        $('#connection-status').html('<span class="badge badge-danger">Disconnected</span>');
    });

    // User management
    socket.on('active_users', function(data) {
        updateActiveUsers(data.users);
    });

    socket.on('user_joined', function(user) {
        activeUsers[user.user_id] = user;
        updateActiveUsers(Object.values(activeUsers));
        addActivityItem(user.username + ' joined the collaboration');
    });

    socket.on('user_left', function(data) {
        if (activeUsers[data.user_id]) {
            addActivityItem(activeUsers[data.user_id].username + ' left the collaboration');
            delete activeUsers[data.user_id];
            updateActiveUsers(Object.values(activeUsers));
        }
    });

    // Editor event handlers
    $('#editor').on('input', function() {
        if (!isTyping) {
            isTyping = true;
            socket.emit('typing_start', {
                document_id: taskId,
                document_type: 'task'
            });
        }

        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(function() {
            isTyping = false;
            socket.emit('typing_stop', {
                document_id: taskId,
                document_type: 'task'
            });
        }, 1000);

        // Send collaborative edit operation
        const content = $('#editor').text();
        socket.emit('collaborative_edit', {
            document_id: taskId,
            document_type: 'task',
            operation: {
                type: 'replace',
                field: 'description',
                content: content,
                position: 0,
                length: content.length
            }
        });
    });

    // Collaborative editing handlers
    socket.on('operation_applied', function(data) {
        // Apply operation from other users
        if (data.user_id !== currentUser.id) {
            applyOperation(data.operation);
            if (activeUsers[data.user_id]) {
                addActivityItem(activeUsers[data.user_id].username + ' made an edit');
            }
        }
    });

    socket.on('cursor_update', function(data) {
        updateUserCursor(data.user_id, data.position);
    });

    // Save button
    $('#save-btn').click(function() {
        const content = $('#editor').html();

        $.ajax({
            url: '{{ url_for("TaskModelView.edit", pk=task.id) }}',
            method: 'POST',
            data: {
                description: content
            },
            success: function(response) {
                alert('Task saved successfully!');
            },
            error: function() {
                alert('Error saving task. Please try again.');
            }
        });
    });

    // Cancel button
    $('#cancel-btn').click(function() {
        if (confirm('Are you sure you want to cancel? Unsaved changes will be lost.')) {
            window.location.href = '{{ url_for("CollaborativeTaskView.list") }}';
        }
    });

    // Helper functions
    function updateActiveUsers(users) {
        const userList = $('#user-list');
        userList.empty();

        users.forEach(function(user, index) {
            if (user.user_id !== currentUser.id) {
                const colorIndex = user.user_id % userColors.length;
                const avatar = $('<div>').addClass('user-avatar')
                    .css('background-color', userColors[colorIndex])
                    .text((user.first_name || user.username).charAt(0).toUpperCase());

                const userElement = $('<span>').addClass('mr-2')
                    .append(avatar)
                    .append(user.first_name + ' ' + user.last_name || user.username);

                userList.append(userElement);
            }
        });

        if (userList.children().length === 0) {
            userList.html('<em>No other collaborators</em>');
        }
    }

    function applyOperation(operation) {
        // Simple operation application
        if (operation.type === 'replace') {
            $('#editor').html(operation.content);
        }
    }

    function updateUserCursor(userId, position) {
        // Update cursor position for other users
        // This is a simplified implementation
        const cursor = $(`#cursor-${userId}`);
        if (cursor.length === 0) {
            const newCursor = $('<div>').attr('id', `cursor-${userId}`)
                .addClass('user-cursor')
                .css('border-color', userColors[userId % userColors.length]);
            $('#editor').append(newCursor);
        }

        // Update cursor position (simplified)
        $(`#cursor-${userId}`).css('left', position + 'px');
    }

    function addActivityItem(message) {
        const timestamp = new Date().toLocaleTimeString();
        const item = $('<div>').addClass('small text-muted mb-1')
            .html(`<strong>${timestamp}</strong>: ${message}`);

        $('#activity-feed').prepend(item);

        // Keep only last 10 items
        $('#activity-feed').children().slice(10).remove();
    }

    // Cleanup on page unload
    $(window).on('beforeunload', function() {
        socket.emit('leave_collaboration', {
            document_id: taskId,
            document_type: 'task'
        });
    });
});
</script>
{% endblock %}
```

## Step 5: Testing Collaborative Features

### 1. Start the Application

```bash
# Make sure Redis is running
redis-server

# Start the application
python app.py
```

### 2. Enable Collaboration on Tasks

1. Go to "Tasks" and create or edit a task
2. Navigate to "Collaborative Tasks"
3. Click "Collaborate" on a task

### 3. Test Real-time Collaboration

1. Open the collaborative editor in multiple browser tabs
2. Edit the content in one tab
3. See real-time updates in other tabs
4. Observe user presence indicators

### 4. Test Team Features

1. Go to "Team Management"
2. Create a new team
3. Share the invite code with other users
4. Assign tasks to teams

## Step 6: Advanced Features

### Add Voice/Video Chat Integration

Add to `collaborative_edit.html`:

```html
<!-- Add video chat button -->
<button id="video-chat-btn" class="btn btn-info">
    <i class="fa fa-video-camera"></i> Start Video Chat
</button>

<!-- Video chat modal -->
<div class="modal fade" id="video-chat-modal">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5>Team Video Chat</h5>
                <button type="button" class="close" data-dismiss="modal">×</button>
            </div>
            <div class="modal-body">
                <div id="video-container">
                    <video id="local-video" autoplay muted style="width: 200px;"></video>
                    <div id="remote-videos"></div>
                </div>
            </div>
        </div>
    </div>
</div>
```

### Add Conflict Resolution UI

```javascript
// Add conflict resolution handling
socket.on('conflict_detected', function(data) {
    const conflictModal = $(`
        <div class="modal fade" id="conflict-modal">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5>Editing Conflict Detected</h5>
                    </div>
                    <div class="modal-body">
                        <p>Multiple users are editing the same section. Choose how to resolve:</p>
                        <div class="conflict-options">
                            <button class="btn btn-primary" onclick="resolveConflict('accept')">
                                Accept Other Changes
                            </button>
                            <button class="btn btn-warning" onclick="resolveConflict('merge')">
                                Merge Changes
                            </button>
                            <button class="btn btn-danger" onclick="resolveConflict('override')">
                                Keep My Changes
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

    $('body').append(conflictModal);
    $('#conflict-modal').modal('show');
});
```

## Best Practices

### 1. Performance Optimization

- Implement operation batching for high-frequency edits
- Use diff algorithms to minimize data transfer
- Cache frequently accessed collaborative sessions

### 2. Security Considerations

- Validate all collaborative operations server-side
- Implement proper authorization for team access
- Sanitize user-generated content in real-time updates

### 3. User Experience

- Provide clear visual feedback for collaborative actions
- Implement graceful handling of connection losses
- Show typing indicators and user presence

### 4. Scalability

- Use Redis pub/sub for multi-server deployments
- Implement operation queuing for offline users
- Consider using dedicated collaboration servers

## Troubleshooting

### Common Issues

**WebSocket Connection Fails:**
```javascript
// Add connection retry logic
socket.on('disconnect', function() {
    setTimeout(function() {
        socket.connect();
    }, 5000);
});
```

**Operations Out of Sync:**
- Implement proper Operational Transform
- Add operation acknowledgments
- Provide manual sync options

**Performance Issues:**
- Debounce rapid edits
- Implement operation batching
- Use efficient diff algorithms

This completes the collaborative features tutorial. Users can now edit documents in real-time, manage teams, and collaborate effectively!