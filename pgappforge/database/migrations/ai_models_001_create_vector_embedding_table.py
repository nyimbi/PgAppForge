"""
Create VectorEmbedding table for AI-powered RAG system

Migration: ai_models_001_create_vector_embedding_table
Description: Creates the fab_vector_embeddings table to store document embeddings
             for the RAG (Retrieval-Augmented Generation) system
"""

from datetime import datetime
from pgappforge.database.migration_manager import DatabaseMigrationManager, MigrationType

# Migration metadata
MIGRATION_NAME = "ai_models_001_create_vector_embedding_table"
MIGRATION_DESCRIPTION = "Create VectorEmbedding table for AI-powered RAG system"
MIGRATION_TYPE = MigrationType.SCHEMA_CHANGE
CREATED_BY = "system"
DEPENDENCIES = []

# Up script - Create the table
UP_SCRIPT = """
-- Create VectorEmbedding table for AI-powered RAG system
CREATE TABLE fab_vector_embeddings (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    
    -- Document identification
    document_id VARCHAR(255) NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    content_hash VARCHAR(64) NOT NULL,
    
    -- Content and metadata
    content TEXT NOT NULL,
    meta_data TEXT,  -- JSON string for metadata
    
    -- Embeddings (stored as JSON for flexibility)  
    embedding_vector TEXT NOT NULL,  -- JSON array of floats
    embedding_model VARCHAR(100) NOT NULL,
    
    -- Workspace/access control
    workspace_id INTEGER,
    team_id INTEGER,  
    user_id INTEGER,
    
    -- Performance optimization
    content_length INTEGER,
    language VARCHAR(10) DEFAULT 'en',
    
    -- Audit fields (PgAppForge AuditMixin compatibility)
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by_id INTEGER,
    changed_by_id INTEGER,
    
    -- Indexes for efficient querying
    INDEX ix_embedding_document_id (document_id),
    INDEX ix_embedding_content_hash (content_hash),
    INDEX ix_embedding_workspace (workspace_id),
    INDEX ix_embedding_team (team_id),
    INDEX ix_embedding_type (document_type),
    INDEX ix_embedding_composite (workspace_id, document_type),
    
    -- Foreign key constraints
    FOREIGN KEY (workspace_id) REFERENCES fab_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES fab_teams(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES ab_user(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_id) REFERENCES ab_user(id) ON DELETE SET NULL,
    FOREIGN KEY (changed_by_id) REFERENCES ab_user(id) ON DELETE SET NULL
);

-- Add comments for documentation
ALTER TABLE fab_vector_embeddings COMMENT = 'Vector embeddings for AI-powered document retrieval and RAG system';
"""

# Down script - Drop the table  
DOWN_SCRIPT = """
-- Remove VectorEmbedding table
DROP TABLE IF EXISTS fab_vector_embeddings;
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