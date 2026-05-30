"""
Apply All AI Model Migrations

This script applies all AI-related database migrations in the correct order.
Run this after setting up PgAppForge to create the necessary AI tables.
"""

import sys
import logging
from typing import List
from pgappforge.database.migration_manager import get_migration_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import migration modules
try:
    from . import ai_models_001_create_vector_embedding_table as migration_001
    from . import ai_models_002_create_chatbot_tables as migration_002  
    from . import ai_models_003_create_indexed_content_table as migration_003
except ImportError:
    # Handle relative import issues when run as script
    import ai_models_001_create_vector_embedding_table as migration_001
    import ai_models_002_create_chatbot_tables as migration_002
    import ai_models_003_create_indexed_content_table as migration_003

def apply_all_ai_migrations(executed_by: str = "system") -> List[str]:
    """
    Apply all AI model migrations in order.
    
    Args:
        executed_by: User executing the migrations
        
    Returns:
        List of migration IDs that were applied
    """
    logger.info("Starting AI model migrations...")
    
    try:
        # Get migration manager
        manager = get_migration_manager()
        if not manager:
            raise RuntimeError("Could not initialize migration manager")
            
        applied_migrations = []
        
        # Migration 001: VectorEmbedding table
        logger.info("Applying migration 001: VectorEmbedding table...")
        try:
            migration_id = migration_001.apply_migration(manager, executed_by)
            applied_migrations.append(migration_id)
            logger.info(f"✅ Migration 001 completed: {migration_id}")
        except Exception as e:
            logger.error(f"❌ Migration 001 failed: {e}")
            raise
            
        # Migration 002: Chatbot tables  
        logger.info("Applying migration 002: Chatbot tables...")
        try:
            migration_id = migration_002.apply_migration(manager, executed_by)
            applied_migrations.append(migration_id)
            logger.info(f"✅ Migration 002 completed: {migration_id}")
        except Exception as e:
            logger.error(f"❌ Migration 002 failed: {e}")
            raise
            
        # Migration 003: IndexedContent table
        logger.info("Applying migration 003: IndexedContent table...")
        try:
            migration_id = migration_003.apply_migration(manager, executed_by)
            applied_migrations.append(migration_id)
            logger.info(f"✅ Migration 003 completed: {migration_id}")
        except Exception as e:
            logger.error(f"❌ Migration 003 failed: {e}")
            raise
            
        logger.info(f"🎉 All AI model migrations completed successfully!")
        logger.info(f"Applied migrations: {applied_migrations}")
        
        return applied_migrations
        
    except Exception as e:
        logger.error(f"AI model migrations failed: {e}")
        raise

def rollback_all_ai_migrations(migration_ids: List[str], rolled_back_by: str = "system") -> bool:
    """
    Rollback all AI model migrations in reverse order.
    
    Args:
        migration_ids: List of migration IDs to rollback (in reverse order)
        rolled_back_by: User performing the rollback
        
    Returns:
        True if all rollbacks successful
    """
    logger.info("Starting AI model migration rollback...")
    
    try:
        manager = get_migration_manager()
        if not manager:
            raise RuntimeError("Could not initialize migration manager")
            
        # Rollback in reverse order
        for migration_id in reversed(migration_ids):
            logger.info(f"Rolling back migration: {migration_id}")
            
            if migration_id.endswith("003_create_indexed_content_table"):
                success = migration_003.rollback_migration(manager, migration_id, rolled_back_by)
            elif migration_id.endswith("002_create_chatbot_tables"):
                success = migration_002.rollback_migration(manager, migration_id, rolled_back_by)
            elif migration_id.endswith("001_create_vector_embedding_table"):
                success = migration_001.rollback_migration(manager, migration_id, rolled_back_by)
            else:
                logger.warning(f"Unknown migration ID: {migration_id}")
                success = False
                
            if success:
                logger.info(f"✅ Rolled back: {migration_id}")
            else:
                logger.error(f"❌ Failed to rollback: {migration_id}")
                return False
                
        logger.info("🎉 All AI model migrations rolled back successfully!")
        return True
        
    except Exception as e:
        logger.error(f"AI model migration rollback failed: {e}")
        return False

def check_migration_status():
    """Check the status of AI model migrations."""
    logger.info("Checking AI model migration status...")
    
    try:
        manager = get_migration_manager()
        if not manager:
            raise RuntimeError("Could not initialize migration manager")
            
        # List all migrations
        migrations = manager.list_migrations(limit=100)
        
        # Filter for AI model migrations
        ai_migrations = [
            m for m in migrations 
            if m.name.startswith('ai_models_')
        ]
        
        if not ai_migrations:
            logger.info("No AI model migrations found")
            return
            
        logger.info(f"Found {len(ai_migrations)} AI model migrations:")
        for migration in ai_migrations:
            status_icon = {
                'COMPLETED': '✅',
                'PENDING': '⏳',
                'RUNNING': '🔄',
                'FAILED': '❌',
                'ROLLED_BACK': '↩️'
            }.get(migration.status.value, '❓')
            
            logger.info(f"  {status_icon} {migration.name} - {migration.status.value}")
            if migration.executed_at:
                logger.info(f"    Executed: {migration.executed_at}")
            if migration.error_message:
                logger.error(f"    Error: {migration.error_message}")
                
    except Exception as e:
        logger.error(f"Failed to check migration status: {e}")

def main():
    """Main entry point for script execution."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python apply_ai_migrations.py apply [executed_by]")
        print("  python apply_ai_migrations.py status") 
        print("  python apply_ai_migrations.py rollback migration_id1,migration_id2,...")
        sys.exit(1)
        
    command = sys.argv[1].lower()
    
    if command == "apply":
        executed_by = sys.argv[2] if len(sys.argv) > 2 else "system"
        try:
            migration_ids = apply_all_ai_migrations(executed_by)
            print(f"Applied migrations: {migration_ids}")
            sys.exit(0)
        except Exception as e:
            print(f"Migration failed: {e}")
            sys.exit(1)
            
    elif command == "status":
        check_migration_status()
        sys.exit(0)
        
    elif command == "rollback":
        if len(sys.argv) < 3:
            print("Usage: python apply_ai_migrations.py rollback migration_id1,migration_id2,...")
            sys.exit(1)
            
        migration_ids = sys.argv[2].split(',')
        rolled_back_by = sys.argv[3] if len(sys.argv) > 3 else "system"
        
        try:
            success = rollback_all_ai_migrations(migration_ids, rolled_back_by)
            if success:
                print("Rollback completed successfully")
                sys.exit(0)
            else:
                print("Rollback failed")
                sys.exit(1)
        except Exception as e:
            print(f"Rollback failed: {e}")
            sys.exit(1)
            
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()