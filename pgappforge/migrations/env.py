"""
Alembic environment script for PgAppForge Collaborative Features.

This script is used by Alembic to configure the migration environment,
set up database connections, and run migrations.
"""

from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys
from pathlib import Path

# Add the PgAppForge directory to the Python path
fab_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(fab_path))

# Import PgAppForge models
try:
    from pgappforge.models.sqla import Model
    from pgappforge.collaborative.core.team_manager import (
        Team, TeamInvitation, team_members, team_role_permissions
    )
    from pgappforge.collaborative.core.workspace_manager import (
        Workspace, WorkspaceResource, WorkspaceMember, ResourceVersion, 
        ResourcePermission, WorkspaceActivity
    )
    from pgappforge.collaborative.integration.version_control import (
        Repository, Branch, Commit, CommitChange, MergeRequest, MergeConflict
    )
    from pgappforge.collaborative.communication.notification_manager import (
        Notification, NotificationPreference, NotificationDelivery, NotificationDigest
    )
    from pgappforge.collaborative.communication.comment_manager import (
        CommentThread, Comment, CommentReaction
    )
    from pgappforge.collaborative.communication.chat_manager import (
        ChatChannel, ChatChannelMember, ChatMessage
    )
except ImportError as e:
    print(f"Warning: Could not import collaborative models: {e}")
    # Create a minimal Model class for basic migration support
    from sqlalchemy.ext.declarative import declarative_base
    Model = declarative_base()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata
target_metadata = Model.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url():
    """Get database URL from environment or config."""
    # Try to get URL from environment variable first
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    
    # Fall back to config file
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()