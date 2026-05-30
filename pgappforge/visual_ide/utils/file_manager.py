"""
File Manager for Visual IDE.

Handles file operations, versioning, backups, and project file management
for the visual development environment.
"""

import os
import json
import shutil
import hashlib
import logging
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
import zipfile
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class FileVersion:
    """Represents a version of a file."""
    version: str
    timestamp: datetime
    file_hash: str
    file_size: int
    description: str = ""
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class BackupInfo:
    """Information about a project backup."""
    backup_id: str
    timestamp: datetime
    description: str
    files_count: int
    backup_size: int
    backup_path: str
    project_version: str


class IDEFileManager:
    """
    File management system for the Visual IDE.
    
    Provides comprehensive file operations including:
    - Project file management
    - Version control and history
    - Backup and restore operations
    - Template management
    - File watching and synchronization
    """
    
    def __init__(self, project_path: Path, backup_path: Path):
        self.project_path = Path(project_path)
        self.backup_path = Path(backup_path)
        
        # Create directories
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)
        
        # Version tracking
        self.versions_path = self.project_path / '.versions'
        self.versions_path.mkdir(exist_ok=True)
        
        # File versions registry
        self.file_versions: Dict[str, List[FileVersion]] = {}
        self._load_version_registry()
        
        # File watching
        self.watched_files: Dict[str, float] = {}  # file_path -> last_modified
        
        logger.info(f"File manager initialized for project: {project_path}")
    
    def _load_version_registry(self):
        """Load file version registry from disk."""
        registry_file = self.versions_path / 'registry.json'
        
        if registry_file.exists():
            try:
                with open(registry_file, 'r') as f:
                    data = json.load(f)
                
                for file_path, versions_data in data.items():
                    versions = []
                    for version_data in versions_data:
                        version = FileVersion(
                            version=version_data['version'],
                            timestamp=datetime.fromisoformat(version_data['timestamp']),
                            file_hash=version_data['file_hash'],
                            file_size=version_data['file_size'],
                            description=version_data.get('description', ''),
                            tags=version_data.get('tags', [])
                        )
                        versions.append(version)
                    
                    self.file_versions[file_path] = versions
                
                logger.info(f"Loaded version registry with {len(self.file_versions)} files")
                
            except Exception as e:
                logger.error(f"Failed to load version registry: {e}")
                self.file_versions = {}
    
    def _save_version_registry(self):
        """Save file version registry to disk."""
        registry_file = self.versions_path / 'registry.json'
        
        try:
            data = {}
            for file_path, versions in self.file_versions.items():
                versions_data = []
                for version in versions:
                    version_data = {
                        'version': version.version,
                        'timestamp': version.timestamp.isoformat(),
                        'file_hash': version.file_hash,
                        'file_size': version.file_size,
                        'description': version.description,
                        'tags': version.tags
                    }
                    versions_data.append(version_data)
                
                data[file_path] = versions_data
            
            with open(registry_file, 'w') as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            logger.error(f"Failed to save version registry: {e}")
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file."""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return ""
    
    def _generate_version_string(self, file_path: str) -> str:
        """Generate version string for a file."""
        versions = self.file_versions.get(file_path, [])
        version_number = len(versions) + 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"v{version_number}_{timestamp}"
    
    # File Operations
    def save_file(self, relative_path: str, content: str, description: str = "") -> bool:
        """
        Save a file with version tracking.
        
        Args:
            relative_path: Relative path from project root
            content: File content to save
            description: Version description
            
        Returns:
            True if file was saved successfully
        """
        try:
            file_path = self.project_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file content has changed
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_content = f.read()
                
                if existing_content == content:
                    logger.info(f"File {relative_path} unchanged, skipping save")
                    return True
            
            # Write file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Create version
            self._create_file_version(relative_path, description)
            
            logger.info(f"Saved file: {relative_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save file {relative_path}: {e}")
            return False
    
    def _create_file_version(self, relative_path: str, description: str = ""):
        """Create a version entry for a file."""
        try:
            file_path = self.project_path / relative_path
            
            if not file_path.exists():
                return
            
            # Calculate file properties
            file_hash = self._calculate_file_hash(file_path)
            file_size = file_path.stat().st_size
            version = self._generate_version_string(relative_path)
            
            # Create version entry
            file_version = FileVersion(
                version=version,
                timestamp=datetime.now(),
                file_hash=file_hash,
                file_size=file_size,
                description=description
            )
            
            # Add to versions
            if relative_path not in self.file_versions:
                self.file_versions[relative_path] = []
            
            self.file_versions[relative_path].append(file_version)
            
            # Copy file to versions directory
            version_file_path = self.versions_path / relative_path.replace('/', '_') / version
            version_file_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, version_file_path)
            
            # Save registry
            self._save_version_registry()
            
            logger.info(f"Created version {version} for {relative_path}")
            
        except Exception as e:
            logger.error(f"Failed to create version for {relative_path}: {e}")
    
    def read_file(self, relative_path: str, version: Optional[str] = None) -> Optional[str]:
        """
        Read a file, optionally a specific version.
        
        Args:
            relative_path: Relative path from project root
            version: Specific version to read (latest if None)
            
        Returns:
            File content or None if not found
        """
        try:
            if version:
                # Read specific version
                version_file_path = self.versions_path / relative_path.replace('/', '_') / version
                if version_file_path.exists():
                    with open(version_file_path, 'r', encoding='utf-8') as f:
                        return f.read()
                else:
                    logger.error(f"Version {version} not found for {relative_path}")
                    return None
            else:
                # Read current version
                file_path = self.project_path / relative_path
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return f.read()
                else:
                    logger.error(f"File not found: {relative_path}")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to read file {relative_path}: {e}")
            return None
    
    def delete_file(self, relative_path: str, keep_versions: bool = True) -> bool:
        """
        Delete a file.
        
        Args:
            relative_path: Relative path from project root
            keep_versions: Whether to keep version history
            
        Returns:
            True if file was deleted successfully
        """
        try:
            file_path = self.project_path / relative_path
            
            if file_path.exists():
                file_path.unlink()
            
            if not keep_versions:
                # Remove versions
                if relative_path in self.file_versions:
                    del self.file_versions[relative_path]
                
                # Remove version files
                version_dir = self.versions_path / relative_path.replace('/', '_')
                if version_dir.exists():
                    shutil.rmtree(version_dir)
                
                self._save_version_registry()
            
            logger.info(f"Deleted file: {relative_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete file {relative_path}: {e}")
            return False
    
    def copy_file(self, source_path: str, dest_path: str) -> bool:
        """
        Copy a file within the project.
        
        Args:
            source_path: Source relative path
            dest_path: Destination relative path
            
        Returns:
            True if file was copied successfully
        """
        try:
            source = self.project_path / source_path
            dest = self.project_path / dest_path
            
            if not source.exists():
                logger.error(f"Source file not found: {source_path}")
                return False
            
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            
            # Create version for destination
            self._create_file_version(dest_path, f"Copied from {source_path}")
            
            logger.info(f"Copied file: {source_path} -> {dest_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy file {source_path}: {e}")
            return False
    
    def move_file(self, source_path: str, dest_path: str) -> bool:
        """
        Move/rename a file within the project.
        
        Args:
            source_path: Source relative path
            dest_path: Destination relative path
            
        Returns:
            True if file was moved successfully
        """
        try:
            source = self.project_path / source_path
            dest = self.project_path / dest_path
            
            if not source.exists():
                logger.error(f"Source file not found: {source_path}")
                return False
            
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            
            # Update versions registry
            if source_path in self.file_versions:
                self.file_versions[dest_path] = self.file_versions.pop(source_path)
                self._save_version_registry()
            
            # Create version for moved file
            self._create_file_version(dest_path, f"Moved from {source_path}")
            
            logger.info(f"Moved file: {source_path} -> {dest_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to move file {source_path}: {e}")
            return False
    
    # Directory Operations
    def create_directory(self, relative_path: str) -> bool:
        """
        Create a directory.
        
        Args:
            relative_path: Relative path from project root
            
        Returns:
            True if directory was created successfully
        """
        try:
            dir_path = self.project_path / relative_path
            dir_path.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Created directory: {relative_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create directory {relative_path}: {e}")
            return False
    
    def list_directory(self, relative_path: str = "") -> List[Dict[str, Any]]:
        """
        List contents of a directory.
        
        Args:
            relative_path: Relative path from project root
            
        Returns:
            List of file/directory information
        """
        try:
            dir_path = self.project_path / relative_path
            
            if not dir_path.exists():
                return []
            
            contents = []
            
            for item in dir_path.iterdir():
                if item.name.startswith('.'):
                    continue  # Skip hidden files
                
                item_info = {
                    'name': item.name,
                    'path': str(item.relative_to(self.project_path)),
                    'is_directory': item.is_dir(),
                    'size': item.stat().st_size if item.is_file() else 0,
                    'modified': datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                    'has_versions': str(item.relative_to(self.project_path)) in self.file_versions
                }
                
                contents.append(item_info)
            
            # Sort: directories first, then files
            contents.sort(key=lambda x: (not x['is_directory'], x['name'].lower()))
            
            return contents
            
        except Exception as e:
            logger.error(f"Failed to list directory {relative_path}: {e}")
            return []
    
    def delete_directory(self, relative_path: str, recursive: bool = False) -> bool:
        """
        Delete a directory.
        
        Args:
            relative_path: Relative path from project root
            recursive: Whether to delete recursively
            
        Returns:
            True if directory was deleted successfully
        """
        try:
            dir_path = self.project_path / relative_path
            
            if not dir_path.exists():
                return True
            
            if recursive:
                shutil.rmtree(dir_path)
            else:
                dir_path.rmdir()  # Only works if empty
            
            logger.info(f"Deleted directory: {relative_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete directory {relative_path}: {e}")
            return False
    
    # Version Management
    def get_file_versions(self, relative_path: str) -> List[FileVersion]:
        """Get all versions of a file."""
        return self.file_versions.get(relative_path, [])
    
    def get_latest_version(self, relative_path: str) -> Optional[FileVersion]:
        """Get the latest version of a file."""
        versions = self.get_file_versions(relative_path)
        return versions[-1] if versions else None
    
    def revert_file_to_version(self, relative_path: str, version: str) -> bool:
        """
        Revert a file to a specific version.
        
        Args:
            relative_path: File to revert
            version: Version to revert to
            
        Returns:
            True if reversion was successful
        """
        try:
            # Read version content
            version_content = self.read_file(relative_path, version)
            if version_content is None:
                return False
            
            # Save as current file
            return self.save_file(relative_path, version_content, f"Reverted to {version}")
            
        except Exception as e:
            logger.error(f"Failed to revert {relative_path} to {version}: {e}")
            return False
    
    def compare_versions(self, relative_path: str, version1: str, version2: str) -> Dict[str, Any]:
        """
        Compare two versions of a file.
        
        Args:
            relative_path: File to compare
            version1: First version
            version2: Second version
            
        Returns:
            Comparison information
        """
        try:
            content1 = self.read_file(relative_path, version1)
            content2 = self.read_file(relative_path, version2)
            
            if content1 is None or content2 is None:
                return {'error': 'One or both versions not found'}
            
            # Simple line-by-line comparison
            lines1 = content1.splitlines()
            lines2 = content2.splitlines()
            
            differences = []
            max_lines = max(len(lines1), len(lines2))
            
            for i in range(max_lines):
                line1 = lines1[i] if i < len(lines1) else None
                line2 = lines2[i] if i < len(lines2) else None
                
                if line1 != line2:
                    differences.append({
                        'line': i + 1,
                        'version1': line1,
                        'version2': line2
                    })
            
            return {
                'differences': differences,
                'total_differences': len(differences),
                'version1_lines': len(lines1),
                'version2_lines': len(lines2)
            }
            
        except Exception as e:
            logger.error(f"Failed to compare versions: {e}")
            return {'error': str(e)}
    
    # Backup Operations
    def create_backup(self, description: str = "") -> Optional[BackupInfo]:
        """
        Create a backup of the entire project.
        
        Args:
            description: Backup description
            
        Returns:
            BackupInfo if successful, None otherwise
        """
        try:
            timestamp = datetime.now()
            backup_id = timestamp.strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{backup_id}.zip"
            backup_file_path = self.backup_path / backup_filename
            
            files_count = 0
            
            with zipfile.ZipFile(backup_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add all project files
                for file_path in self.project_path.rglob('*'):
                    if file_path.is_file() and not file_path.name.startswith('.'):
                        relative_path = file_path.relative_to(self.project_path)
                        zipf.write(file_path, relative_path)
                        files_count += 1
                
                # Add version registry
                registry_file = self.versions_path / 'registry.json'
                if registry_file.exists():
                    zipf.write(registry_file, '.versions/registry.json')
                    files_count += 1
            
            backup_size = backup_file_path.stat().st_size
            
            backup_info = BackupInfo(
                backup_id=backup_id,
                timestamp=timestamp,
                description=description,
                files_count=files_count,
                backup_size=backup_size,
                backup_path=str(backup_file_path),
                project_version="1.0"  # TODO: Get from project
            )
            
            # Save backup info
            self._save_backup_info(backup_info)
            
            logger.info(f"Created backup: {backup_id} with {files_count} files")
            return backup_info
            
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return None
    
    def _save_backup_info(self, backup_info: BackupInfo):
        """Save backup information to registry."""
        try:
            backups_file = self.backup_path / 'backups.json'
            
            backups = []
            if backups_file.exists():
                with open(backups_file, 'r') as f:
                    backups = json.load(f)
            
            backup_data = asdict(backup_info)
            backup_data['timestamp'] = backup_info.timestamp.isoformat()
            
            backups.append(backup_data)
            
            with open(backups_file, 'w') as f:
                json.dump(backups, f, indent=2)
            
        except Exception as e:
            logger.error(f"Failed to save backup info: {e}")
    
    def list_backups(self) -> List[BackupInfo]:
        """List all available backups."""
        try:
            backups_file = self.backup_path / 'backups.json'
            
            if not backups_file.exists():
                return []
            
            with open(backups_file, 'r') as f:
                backups_data = json.load(f)
            
            backups = []
            for backup_data in backups_data:
                backup_info = BackupInfo(
                    backup_id=backup_data['backup_id'],
                    timestamp=datetime.fromisoformat(backup_data['timestamp']),
                    description=backup_data['description'],
                    files_count=backup_data['files_count'],
                    backup_size=backup_data['backup_size'],
                    backup_path=backup_data['backup_path'],
                    project_version=backup_data['project_version']
                )
                backups.append(backup_info)
            
            # Sort by timestamp (newest first)
            backups.sort(key=lambda x: x.timestamp, reverse=True)
            
            return backups
            
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []
    
    def restore_backup(self, backup_id: str) -> bool:
        """
        Restore from a backup.
        
        Args:
            backup_id: Backup ID to restore from
            
        Returns:
            True if restore was successful
        """
        try:
            # Find backup
            backups = self.list_backups()
            backup_info = next((b for b in backups if b.backup_id == backup_id), None)
            
            if not backup_info:
                logger.error(f"Backup {backup_id} not found")
                return False
            
            backup_file_path = Path(backup_info.backup_path)
            
            if not backup_file_path.exists():
                logger.error(f"Backup file not found: {backup_file_path}")
                return False
            
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Extract backup
                with zipfile.ZipFile(backup_file_path, 'r') as zipf:
                    zipf.extractall(temp_path)
                
                # Replace current project files
                if self.project_path.exists():
                    shutil.rmtree(self.project_path)
                
                self.project_path.mkdir(parents=True, exist_ok=True)
                
                # Copy extracted files
                for item in temp_path.rglob('*'):
                    if item.is_file():
                        relative_path = item.relative_to(temp_path)
                        dest_path = self.project_path / relative_path
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_path)
            
            # Reload version registry
            self._load_version_registry()
            
            logger.info(f"Restored backup: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore backup {backup_id}: {e}")
            return False
    
    def delete_backup(self, backup_id: str) -> bool:
        """
        Delete a backup.
        
        Args:
            backup_id: Backup ID to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            backups = self.list_backups()
            backup_info = next((b for b in backups if b.backup_id == backup_id), None)
            
            if not backup_info:
                logger.error(f"Backup {backup_id} not found")
                return False
            
            backup_file_path = Path(backup_info.backup_path)
            
            if backup_file_path.exists():
                backup_file_path.unlink()
            
            # Remove from registry
            backups_file = self.backup_path / 'backups.json'
            if backups_file.exists():
                with open(backups_file, 'r') as f:
                    backups_data = json.load(f)
                
                backups_data = [b for b in backups_data if b['backup_id'] != backup_id]
                
                with open(backups_file, 'w') as f:
                    json.dump(backups_data, f, indent=2)
            
            logger.info(f"Deleted backup: {backup_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False
    
    # View-specific Operations
    def delete_view_files(self, view_name: str) -> bool:
        """
        Delete all files related to a view.
        
        Args:
            view_name: Name of the view to delete files for
            
        Returns:
            True if deletion was successful
        """
        try:
            view_files = [
                f"views/{view_name.lower()}_view.py",
                f"templates/{view_name.lower()}.html",
                f"static/css/{view_name.lower()}.css",
                f"static/js/{view_name.lower()}.js"
            ]
            
            deleted_count = 0
            
            for file_path in view_files:
                if self.delete_file(file_path, keep_versions=False):
                    deleted_count += 1
            
            logger.info(f"Deleted {deleted_count} files for view: {view_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete view files for {view_name}: {e}")
            return False
    
    # Utility Methods
    def get_project_statistics(self) -> Dict[str, Any]:
        """Get project file statistics."""
        try:
            total_files = 0
            total_size = 0
            file_types = {}
            
            for file_path in self.project_path.rglob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    total_files += 1
                    total_size += file_path.stat().st_size
                    
                    extension = file_path.suffix.lower()
                    if extension:
                        file_types[extension] = file_types.get(extension, 0) + 1
                    else:
                        file_types['no_extension'] = file_types.get('no_extension', 0) + 1
            
            return {
                'total_files': total_files,
                'total_size': total_size,
                'file_types': file_types,
                'versioned_files': len(self.file_versions),
                'total_versions': sum(len(versions) for versions in self.file_versions.values()),
                'project_path': str(self.project_path),
                'backup_path': str(self.backup_path)
            }
            
        except Exception as e:
            logger.error(f"Failed to get project statistics: {e}")
            return {}
    
    def cleanup_old_versions(self, keep_count: int = 10) -> int:
        """
        Clean up old versions, keeping only the most recent ones.
        
        Args:
            keep_count: Number of versions to keep per file
            
        Returns:
            Number of versions deleted
        """
        try:
            deleted_count = 0
            
            for file_path, versions in self.file_versions.items():
                if len(versions) > keep_count:
                    # Sort by timestamp and keep only the most recent
                    versions.sort(key=lambda v: v.timestamp)
                    versions_to_delete = versions[:-keep_count]
                    
                    for version in versions_to_delete:
                        # Delete version file
                        version_file_path = self.versions_path / file_path.replace('/', '_') / version.version
                        if version_file_path.exists():
                            version_file_path.unlink()
                            deleted_count += 1
                    
                    # Update versions list
                    self.file_versions[file_path] = versions[-keep_count:]
            
            # Save updated registry
            self._save_version_registry()
            
            logger.info(f"Cleaned up {deleted_count} old versions")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old versions: {e}")
            return 0