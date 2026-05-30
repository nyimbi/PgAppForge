"""
Create IndexedContent table for AI knowledge base system

Migration: ai_models_003_create_indexed_content_table
Description: Creates the fab_indexed_content table to track processed content
             for the AI knowledge base and RAG system
"""

from datetime import datetime
from pgappforge.database.migration_manager import DatabaseMigrationManager, MigrationType

# Migration metadata
MIGRATION_NAME = "ai_models_003_create_indexed_content_table"
MIGRATION_DESCRIPTION = "Create IndexedContent table for AI knowledge base system"
MIGRATION_TYPE = MigrationType.SCHEMA_CHANGE
CREATED_BY = "system"
DEPENDENCIES = ["ai_models_002_create_chatbot_tables"]

# Up script - Create the table
UP_SCRIPT = """
-- Create IndexedContent table for AI knowledge base system
CREATE TABLE fab_indexed_content (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    
    -- Content identification
    content_id VARCHAR(255) NOT NULL,
    content_source VARCHAR(50) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    
    -- Workspace context
    workspace_id INTEGER,
    team_id INTEGER,
    
    -- Indexing status
    status VARCHAR(20) DEFAULT 'pending',
    indexed_at TIMESTAMP NULL,
    chunks_created INTEGER DEFAULT 0,
    
    -- Content metadata
    content_length INTEGER,
    language VARCHAR(10) DEFAULT 'en',
    last_modified TIMESTAMP NULL,
    
    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    -- Audit fields (PgAppForge AuditMixin compatibility)
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by_fk INTEGER,
    changed_by_fk INTEGER,
    
    -- Indexes for efficient querying
    INDEX ix_content_id (content_id),
    INDEX ix_content_hash (content_hash),
    INDEX ix_content_workspace_source (workspace_id, content_source),
    INDEX ix_content_status (status),
    INDEX ix_content_hash_workspace (content_hash, workspace_id),
    
    -- Foreign key constraints
    FOREIGN KEY (workspace_id) REFERENCES fab_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES fab_teams(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL,
    FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL
);

-- Add comments for documentation
ALTER TABLE fab_indexed_content COMMENT = 'Tracks indexed content to avoid duplicate processing in AI knowledge base';
"""

# Down script - Drop the table  
DOWN_SCRIPT = """
-- Remove IndexedContent table
DROP TABLE IF EXISTS fab_indexed_content;
"""

def apply_migration(migration_manager: DatabaseMigrationManager, executed_by: str = "system") -> str:
    """
    Apply this migration using the migration manager.
    
    Args:
        migration_manager: DatabaseMigrationManager instance
        executed_by: User executing the migration
        
    Returns:
        Migration ID
    """
    migration_id = migration_manager.create_migration(
        name=MIGRATION_NAME,
        description=MIGRATION_DESCRIPTION, 
        migration_type=MIGRATION_TYPE,
        up_script=UP_SCRIPT,
        down_script=DOWN_SCRIPT,
        created_by=CREATED_BY,
        dependencies=DEPENDENCIES
    )
    
    # Execute the migration
    migration_manager.execute_migration(migration_id, executed_by)
    
    return migration_id

def rollback_migration(migration_manager: DatabaseMigrationManager, migration_id: str, rolled_back_by: str = "system") -> bool:
    """
    Rollback this migration using the migration manager.
    
    Args:
        migration_manager: DatabaseMigrationManager instance
        migration_id: ID of the migration to rollback
        rolled_back_by: User performing the rollback
        
    Returns:
        True if successful
    """
    return migration_manager.rollback_migration(migration_id, rolled_back_by)

if __name__ == "__main__":
    # For direct execution - create and apply migration
    from pgappforge.database.migration_manager import get_migration_manager
    
    manager = get_migration_manager()
    migration_id = apply_migration(manager)
    print(f"Applied migration: {migration_id}")