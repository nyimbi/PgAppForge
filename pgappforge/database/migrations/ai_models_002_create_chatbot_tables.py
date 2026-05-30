"""
Create Chatbot tables for AI-powered conversational system

Migration: ai_models_002_create_chatbot_tables
Description: Creates tables for ChatbotConversation and ChatbotMessage
             for the AI chatbot system
"""

from datetime import datetime
from pgappforge.database.migration_manager import DatabaseMigrationManager, MigrationType

# Migration metadata
MIGRATION_NAME = "ai_models_002_create_chatbot_tables"
MIGRATION_DESCRIPTION = "Create Chatbot tables for AI-powered conversational system"
MIGRATION_TYPE = MigrationType.SCHEMA_CHANGE
CREATED_BY = "system"
DEPENDENCIES = ["ai_models_001_create_vector_embedding_table"]

# Up script - Create the tables
UP_SCRIPT = """
-- Create ChatbotConversation table
CREATE TABLE fab_chatbot_conversations (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    
    -- Conversation identification
    conversation_id VARCHAR(255) NOT NULL UNIQUE,
    title VARCHAR(500),
    
    -- Context and settings
    workspace_id INTEGER,
    user_id INTEGER NOT NULL,
    context_type VARCHAR(50),  -- 'workspace', 'document', 'general'
    context_id VARCHAR(255),   -- ID of the contextual resource
    
    -- Conversation state
    status VARCHAR(20) DEFAULT 'active',  -- active, archived, deleted
    is_public BOOLEAN DEFAULT FALSE,
    
    -- AI configuration
    model_config TEXT,  -- JSON string for model settings
    system_prompt TEXT,
    
    -- Statistics
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    last_activity TIMESTAMP,
    
    -- Audit fields (PgAppForge AuditMixin compatibility)
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by_fk INTEGER,
    changed_by_fk INTEGER,
    
    -- Indexes
    INDEX ix_conversation_user (user_id),
    INDEX ix_conversation_workspace (workspace_id),
    INDEX ix_conversation_context (context_type, context_id),
    INDEX ix_conversation_status (status),
    INDEX ix_conversation_activity (last_activity),
    
    -- Foreign key constraints
    FOREIGN KEY (workspace_id) REFERENCES fab_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES ab_user(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL,
    FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL
);

-- Create ChatbotMessage table
CREATE TABLE fab_chatbot_messages (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    
    -- Message identification
    conversation_id INTEGER NOT NULL,
    message_id VARCHAR(255) NOT NULL,
    sequence_number INTEGER NOT NULL,
    
    -- Message content
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system', 'function'
    content TEXT NOT NULL,
    content_type VARCHAR(20) DEFAULT 'text',  -- text, markdown, html
    
    -- Message metadata
    token_count INTEGER,
    model_used VARCHAR(100),
    processing_time_ms INTEGER,
    
    -- Function calling (for AI tools)
    function_name VARCHAR(100),
    function_arguments TEXT,  -- JSON string
    function_result TEXT,     -- JSON string
    
    -- Message state
    is_edited BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    parent_message_id INTEGER,  -- For message editing/threading
    
    -- Context and attachments
    attachments TEXT,  -- JSON array of attachment metadata
    citations TEXT,    -- JSON array of source citations
    
    -- Audit fields (PgAppForge AuditMixin compatibility)
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by_fk INTEGER,
    changed_by_fk INTEGER,
    
    -- Indexes
    INDEX ix_message_conversation (conversation_id),
    INDEX ix_message_sequence (conversation_id, sequence_number),
    INDEX ix_message_role (role),
    INDEX ix_message_created (created_on),
    INDEX ix_message_parent (parent_message_id),
    
    -- Foreign key constraints
    FOREIGN KEY (conversation_id) REFERENCES fab_chatbot_conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_message_id) REFERENCES fab_chatbot_messages(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL,
    FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id) ON DELETE SET NULL,
    
    -- Unique constraint for conversation ordering
    UNIQUE KEY uk_conversation_sequence (conversation_id, sequence_number)
);

-- Add table comments
ALTER TABLE fab_chatbot_conversations COMMENT = 'AI chatbot conversations with context and configuration';
ALTER TABLE fab_chatbot_messages COMMENT = 'Individual messages within chatbot conversations';

-- Create trigger to update message count and last activity
DELIMITER //
CREATE TRIGGER update_conversation_stats 
AFTER INSERT ON fab_chatbot_messages
FOR EACH ROW
BEGIN
    UPDATE fab_chatbot_conversations 
    SET 
        message_count = (
            SELECT COUNT(*) 
            FROM fab_chatbot_messages 
            WHERE conversation_id = NEW.conversation_id 
            AND is_deleted = FALSE
        ),
        last_activity = NEW.created_on,
        total_tokens = COALESCE(total_tokens, 0) + COALESCE(NEW.token_count, 0)
    WHERE id = NEW.conversation_id;
END//
DELIMITER ;
"""

# Down script - Drop the tables
DOWN_SCRIPT = """
-- Drop trigger first
DROP TRIGGER IF EXISTS update_conversation_stats;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS fab_chatbot_messages;
DROP TABLE IF EXISTS fab_chatbot_conversations;
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