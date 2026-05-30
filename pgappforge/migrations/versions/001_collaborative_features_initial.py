"""Collaborative Features Initial Migration

Revision ID: 001_collaborative_features
Revises: 
Create Date: 2025-01-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql, postgresql


# revision identifiers, used by Alembic.
revision = '001_collaborative_features'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all collaborative feature tables."""
    
    # ============================
    # Team Management Tables
    # ============================
    
    # Teams table
    op.create_table(
        'fab_teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('slug', sa.String(100), unique=True, nullable=False),
        sa.Column('is_public', sa.Boolean(), default=False),
        sa.Column('require_approval', sa.Boolean(), default=True),
        sa.Column('max_members', sa.Integer(), default=100),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Team members association table
    op.create_table(
        'fab_team_members',
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('fab_teams.id'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), primary_key=True),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('joined_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), default=True),
    )
    
    # Team role permissions table
    op.create_table(
        'fab_team_role_permissions',
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('fab_teams.id'), primary_key=True),
        sa.Column('role', sa.String(50), primary_key=True),
        sa.Column('permission', sa.String(100), primary_key=True),
    )
    
    # Team invitations table
    op.create_table(
        'fab_team_invitations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('fab_teams.id'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('token', sa.String(255), unique=True, nullable=False),
        sa.Column('message', sa.Text()),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime()),
        sa.Column('invited_user_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        
        sa.UniqueConstraint('team_id', 'email', name='unique_team_email_invitation'),
    )
    
    # ============================
    # Workspace Management Tables
    # ============================
    
    # Workspaces table
    op.create_table(
        'fab_workspaces',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('workspace_type', sa.String(50), nullable=False),
        sa.Column('is_public', sa.Boolean(), default=False),
        sa.Column('share_scope', sa.String(50), default='private'),
        sa.Column('require_approval', sa.Boolean(), default=False),
        sa.Column('config', sa.JSON()),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('fab_teams.id')),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Workspace resources table
    op.create_table(
        'fab_workspace_resources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('uuid', sa.String(36), unique=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('path', sa.String(500)),
        sa.Column('content', sa.Text()),
        sa.Column('content_hash', sa.String(64)),
        sa.Column('metadata', sa.JSON()),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id')),
        sa.Column('is_public', sa.Boolean(), default=False),
        sa.Column('is_locked', sa.Boolean(), default=False),
        sa.Column('locked_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('version', sa.Integer(), default=1),
        sa.Column('last_accessed', sa.DateTime(), default=sa.func.now()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Workspace members table
    op.create_table(
        'fab_workspace_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('access_level', sa.String(20), nullable=False),
        sa.Column('invited_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('joined_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('last_activity', sa.DateTime(), default=sa.func.now()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Resource versions table
    op.create_table(
        'fab_resource_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('resource_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text()),
        sa.Column('content_hash', sa.String(64)),
        sa.Column('metadata', sa.JSON()),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('change_summary', sa.String(500)),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Resource permissions table
    op.create_table(
        'fab_resource_permissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('resource_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('fab_teams.id')),
        sa.Column('permission_type', sa.String(50), nullable=False),
        sa.Column('granted_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('granted_by_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR (user_id IS NULL AND team_id IS NOT NULL)",
            name="check_permission_subject"
        ),
    )
    
    # Workspace activity table
    op.create_table(
        'fab_workspace_activity',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('activity_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id')),
        sa.Column('description', sa.Text()),
        sa.Column('metadata', sa.JSON()),
        sa.Column('activity_timestamp', sa.DateTime(), default=sa.func.now()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # ============================
    # Version Control Tables
    # ============================
    
    # Repositories table
    op.create_table(
        'fab_vc_repositories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('default_branch', sa.String(100), default='main'),
        sa.Column('allow_force_push', sa.Boolean(), default=False),
        sa.Column('require_review', sa.Boolean(), default=False),
        sa.Column('auto_merge', sa.Boolean(), default=True),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Branches table
    op.create_table(
        'fab_vc_branches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('fab_vc_repositories.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('head_commit_id', sa.Integer(), sa.ForeignKey('fab_vc_commits.id')),
        sa.Column('parent_branch_id', sa.Integer(), sa.ForeignKey('fab_vc_branches.id')),
        sa.Column('is_protected', sa.Boolean(), default=False),
        sa.Column('require_pull_request', sa.Boolean(), default=False),
        sa.Column('last_commit_at', sa.DateTime(), default=sa.func.now()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Commits table
    op.create_table(
        'fab_vc_commits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('fab_vc_repositories.id'), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('fab_vc_branches.id'), nullable=False),
        sa.Column('hash', sa.String(64), unique=True, nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('parent_commit_id', sa.Integer(), sa.ForeignKey('fab_vc_commits.id')),
        sa.Column('merge_commit_id', sa.Integer(), sa.ForeignKey('fab_vc_commits.id')),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('authored_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('committed_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('tags', sa.JSON()),
        sa.Column('statistics', sa.JSON()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Commit changes table
    op.create_table(
        'fab_vc_commit_changes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('commit_id', sa.Integer(), sa.ForeignKey('fab_vc_commits.id'), nullable=False),
        sa.Column('resource_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id'), nullable=False),
        sa.Column('change_type', sa.String(20), nullable=False),
        sa.Column('old_path', sa.String(500)),
        sa.Column('new_path', sa.String(500)),
        sa.Column('old_content', sa.Text()),
        sa.Column('new_content', sa.Text()),
        sa.Column('diff', sa.Text()),
        sa.Column('lines_added', sa.Integer(), default=0),
        sa.Column('lines_deleted', sa.Integer(), default=0),
        sa.Column('lines_modified', sa.Integer(), default=0),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Merge requests table
    op.create_table(
        'fab_vc_merge_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('fab_vc_repositories.id'), nullable=False),
        sa.Column('source_branch_id', sa.Integer(), sa.ForeignKey('fab_vc_branches.id'), nullable=False),
        sa.Column('target_branch_id', sa.Integer(), sa.ForeignKey('fab_vc_branches.id'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('status', sa.String(20), default='open'),
        sa.Column('require_approval', sa.Boolean(), default=True),
        sa.Column('auto_merge', sa.Boolean(), default=False),
        sa.Column('merge_strategy', sa.String(20)),
        sa.Column('merged_at', sa.DateTime()),
        sa.Column('merged_commit_id', sa.Integer(), sa.ForeignKey('fab_vc_commits.id')),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Merge conflicts table
    op.create_table(
        'fab_vc_merge_conflicts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('merge_request_id', sa.Integer(), sa.ForeignKey('fab_vc_merge_requests.id'), nullable=False),
        sa.Column('resource_id', sa.Integer(), sa.ForeignKey('fab_workspace_resources.id'), nullable=False),
        sa.Column('conflict_type', sa.String(50), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('line_number', sa.Integer()),
        sa.Column('base_content', sa.Text()),
        sa.Column('source_content', sa.Text()),
        sa.Column('target_content', sa.Text()),
        sa.Column('resolved_content', sa.Text()),
        sa.Column('is_resolved', sa.Boolean(), default=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # ============================
    # Communication Tables
    # ============================
    
    # Chat channels table
    op.create_table(
        'fab_chat_channels',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('is_private', sa.Boolean(), default=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Chat channel members table
    op.create_table(
        'fab_chat_channel_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('channel_id', sa.Integer(), sa.ForeignKey('fab_chat_channels.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('joined_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('is_admin', sa.Boolean(), default=False),
        sa.Column('last_read_message_id', sa.Integer(), sa.ForeignKey('fab_chat_messages.id')),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Chat messages table
    op.create_table(
        'fab_chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('channel_id', sa.Integer(), sa.ForeignKey('fab_chat_channels.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(20), default='text'),
        sa.Column('is_edited', sa.Boolean(), default=False),
        sa.Column('is_deleted', sa.Boolean(), default=False),
        sa.Column('reply_to_id', sa.Integer(), sa.ForeignKey('fab_chat_messages.id')),
        sa.Column('metadata', sa.JSON()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Comment threads table
    op.create_table(
        'fab_comment_threads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id'), nullable=False),
        sa.Column('commentable_type', sa.String(50), nullable=False),
        sa.Column('commentable_id', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255)),
        sa.Column('line_number', sa.Integer()),
        sa.Column('character_position', sa.Integer()),
        sa.Column('x_coordinate', sa.Float()),
        sa.Column('y_coordinate', sa.Float()),
        sa.Column('selection_text', sa.Text()),
        sa.Column('status', sa.String(20), default='open'),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('context_data', sa.Text()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Comments table
    op.create_table(
        'fab_comments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('thread_id', sa.Integer(), sa.ForeignKey('fab_comment_threads.id'), nullable=False),
        sa.Column('parent_comment_id', sa.Integer(), sa.ForeignKey('fab_comments.id')),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_format', sa.String(20), default='markdown'),
        sa.Column('is_deleted', sa.Boolean(), default=False),
        sa.Column('reactions', sa.Text()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Comment reactions table
    op.create_table(
        'fab_comment_reactions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('comment_id', sa.Integer(), sa.ForeignKey('fab_comments.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('reaction_type', sa.String(20), nullable=False),
        sa.Column('reaction_timestamp', sa.DateTime(), default=sa.func.now()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        
        sa.UniqueConstraint('comment_id', 'user_id', 'reaction_type', name='unique_comment_user_reaction'),
    )
    
    # Notifications table
    op.create_table(
        'fab_notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id')),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('priority', sa.String(20), default='normal'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('related_entity_type', sa.String(50)),
        sa.Column('related_entity_id', sa.String(255)),
        sa.Column('metadata', sa.JSON()),
        sa.Column('action_url', sa.String(500)),
        sa.Column('scheduled_for', sa.DateTime()),
        sa.Column('delivered_at', sa.DateTime()),
        sa.Column('read_at', sa.DateTime()),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('is_delivered', sa.Boolean(), default=False),
        sa.Column('delivery_attempts', sa.Integer(), default=0),
        sa.Column('max_delivery_attempts', sa.Integer(), default=3),
        sa.Column('digest_group', sa.String(100)),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Notification preferences table
    op.create_table(
        'fab_notification_preferences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('fab_workspaces.id')),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('delivery_channels', sa.JSON(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), default=True),
        sa.Column('immediate_delivery', sa.Boolean(), default=True),
        sa.Column('digest_frequency', sa.String(20), default='daily'),
        sa.Column('quiet_hours_start', sa.Integer()),
        sa.Column('quiet_hours_end', sa.Integer()),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Notification deliveries table
    op.create_table(
        'fab_notification_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('fab_notifications.id'), nullable=False),
        sa.Column('delivery_channel', sa.String(20), nullable=False),
        sa.Column('delivery_status', sa.String(20), nullable=False),
        sa.Column('attempted_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('delivered_at', sa.DateTime()),
        sa.Column('error_message', sa.Text()),
        sa.Column('external_id', sa.String(255)),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # Notification digests table
    op.create_table(
        'fab_notification_digests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('ab_user.id'), nullable=False),
        sa.Column('digest_type', sa.String(20), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=False),
        sa.Column('period_end', sa.DateTime(), nullable=False),
        sa.Column('notifications_count', sa.Integer(), default=0),
        sa.Column('digest_content', sa.Text()),
        sa.Column('sent_at', sa.DateTime()),
        sa.Column('is_sent', sa.Boolean(), default=False),
        
        # AuditMixin fields
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('changed_on', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('ab_user.id')),
    )
    
    # ============================
    # Create Indexes
    # ============================
    
    # Team indexes
    op.create_index('ix_team_slug', 'fab_teams', ['slug'])
    op.create_index('ix_team_public', 'fab_teams', ['is_public'])
    
    # Workspace indexes  
    op.create_index('ix_workspace_team', 'fab_workspaces', ['team_id'])
    op.create_index('ix_workspace_type', 'fab_workspaces', ['workspace_type'])
    op.create_index('ix_workspace_public', 'fab_workspaces', ['is_public'])
    op.create_index('ix_workspace_slug', 'fab_workspaces', ['slug'], unique=True)
    
    # Resource indexes
    op.create_index('ix_resource_workspace', 'fab_workspace_resources', ['workspace_id'])
    op.create_index('ix_resource_type', 'fab_workspace_resources', ['resource_type'])
    op.create_index('ix_resource_parent', 'fab_workspace_resources', ['parent_id'])
    op.create_index('ix_resource_path', 'fab_workspace_resources', ['workspace_id', 'path'])
    
    # Workspace member indexes
    op.create_index('ix_workspace_member', 'fab_workspace_members', ['workspace_id', 'user_id'], unique=True)
    
    # Version control indexes
    op.create_index('ix_repo_workspace', 'fab_vc_repositories', ['workspace_id'])
    op.create_index('ix_branch_repo', 'fab_vc_branches', ['repository_id', 'name'], unique=True)
    op.create_index('ix_commit_repo', 'fab_vc_commits', ['repository_id'])
    op.create_index('ix_commit_branch', 'fab_vc_commits', ['branch_id'])
    op.create_index('ix_commit_hash', 'fab_vc_commits', ['hash'])
    
    # Version indexes
    op.create_index('ix_version_resource', 'fab_resource_versions', ['resource_id'])
    op.create_index('ix_version_number', 'fab_resource_versions', ['resource_id', 'version_number'], unique=True)
    
    # Permission indexes
    op.create_index('ix_resource_permission_user', 'fab_resource_permissions', ['resource_id', 'user_id'])
    op.create_index('ix_resource_permission_team', 'fab_resource_permissions', ['resource_id', 'team_id'])
    
    # Merge request indexes
    op.create_index('ix_merge_request_repo', 'fab_vc_merge_requests', ['repository_id'])
    op.create_index('ix_merge_request_source', 'fab_vc_merge_requests', ['source_branch_id'])
    op.create_index('ix_merge_request_target', 'fab_vc_merge_requests', ['target_branch_id'])
    
    # Conflict indexes
    op.create_index('ix_conflict_merge_request', 'fab_vc_merge_conflicts', ['merge_request_id'])
    op.create_index('ix_conflict_resource', 'fab_vc_merge_conflicts', ['resource_id'])
    
    # Notification indexes
    op.create_index('ix_notification_user', 'fab_notifications', ['user_id'])
    op.create_index('ix_notification_workspace', 'fab_notifications', ['workspace_id'])
    op.create_index('ix_notification_type', 'fab_notifications', ['notification_type'])
    op.create_index('ix_notification_read', 'fab_notifications', ['user_id', 'is_read'])
    op.create_index('ix_notification_delivered', 'fab_notifications', ['is_delivered'])


def downgrade():
    """Drop all collaborative feature tables."""
    
    # Drop tables in reverse order to handle foreign key constraints
    table_names = [
        'fab_notification_digests',
        'fab_notification_deliveries', 
        'fab_notification_preferences',
        'fab_notifications',
        'fab_comment_reactions',
        'fab_comments',
        'fab_comment_threads',
        'fab_chat_messages',
        'fab_chat_channel_members',
        'fab_chat_channels',
        'fab_vc_merge_conflicts',
        'fab_vc_merge_requests',
        'fab_vc_commit_changes',
        'fab_vc_commits',
        'fab_vc_branches',
        'fab_vc_repositories',
        'fab_workspace_activity',
        'fab_resource_permissions',
        'fab_resource_versions',
        'fab_workspace_members',
        'fab_workspace_resources',
        'fab_workspaces',
        'fab_team_invitations',
        'fab_team_role_permissions',
        'fab_team_members',
        'fab_teams',
    ]
    
    for table_name in table_names:
        op.drop_table(table_name)