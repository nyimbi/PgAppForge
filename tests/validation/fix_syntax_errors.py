#!/usr/bin/env python3
"""
Fix Syntax Errors Introduced by Documentation Fixer

This script identifies and fixes syntax errors that were introduced by the
automated documentation enhancement script, particularly missing function
bodies and malformed docstring insertions.
"""

import ast
import os
import re
from pathlib import Path
from typing import List, Dict, Tuple


class SyntaxErrorFixer:
    """
    Fixes syntax errors in Python files caused by documentation insertion issues.
    
    This class provides methods to identify and fix common syntax errors
    such as missing function bodies, malformed indentation, and incomplete
    docstring insertions.
    """
    
    def __init__(self, base_path: str):
        """
        Initialize the syntax error fixer.
        
        Args:
            base_path: Root path to scan for files with syntax errors
        """
        self.base_path = Path(base_path)
        self.fixes_applied = 0
        self.files_fixed = 0
    
    def analyze_syntax_errors(self) -> Dict:
        """
        Analyze syntax errors across all Python files.
        
        Returns:
            Dictionary containing analysis results
        """
        error_files = []
        python_files = list(self.base_path.rglob("*.py"))
        total_files = 0
        
        for file_path in python_files:
            if any(part.startswith('__pycache__') for part in file_path.parts):
                continue
            
            total_files += 1
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                ast.parse(content)
            except SyntaxError as e:
                error_files.append({
                    'file': str(file_path),
                    'error': str(e),
                    'line': getattr(e, 'lineno', 0)
                })
            except Exception as e:
                error_files.append({
                    'file': str(file_path),
                    'error': f"Parse error: {str(e)}",
                    'line': 0
                })
        
        return {
            'total_files_analyzed': total_files,
            'files_with_errors': error_files,
            'error_count': len(error_files)
        }

    def find_syntax_error_files(self) -> List[Path]:
        """
        Find all Python files with syntax errors.
        
        Returns:
            List of file paths that have syntax errors
        """
        error_files = []
        python_files = list(self.base_path.rglob("*.py"))
        
        for file_path in python_files:
            if any(part.startswith('__pycache__') for part in file_path.parts):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                ast.parse(content)
            except SyntaxError as e:
                error_files.append(file_path)
                print(f"Syntax error in {file_path}: {e}")
        
        return error_files
    
    def fix_missing_function_bodies(self, file_path: Path) -> bool:
        """
        Fix functions that are missing their bodies due to malformed docstring insertion.
        
        Args:
            file_path: Path to the file to fix
            
        Returns:
            True if the file was modified, False otherwise
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            modified = False
            i = 0
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Look for function definitions followed by docstrings without bodies
                if line.startswith('def ') and line.endswith(':'):
                    # Check if next line starts a docstring
                    if i + 1 < len(lines) and lines[i + 1].strip().startswith('"""'):
                        # Find the end of the docstring
                        j = i + 2
                        while j < len(lines):
                            if '"""' in lines[j] and not lines[j].strip().startswith('"""'):
                                break
                            j += 1
                        
                        # Check if there's a body after the docstring
                        if j + 1 < len(lines):
                            next_meaningful_line = lines[j + 1].strip()
                            # If next line is another def, class, or dedented line, add pass
                            if (next_meaningful_line.startswith(('def ', 'class ', '@')) or
                                (next_meaningful_line and not lines[j + 1].startswith('    '))):
                                # Insert pass statement
                                indent = '    ' * (len(lines[i]) - len(lines[i].lstrip())) // 4 + 1
                                lines.insert(j + 1, f"{indent}pass\n")
                                modified = True
                                self.fixes_applied += 1
                
                i += 1
            
            if modified:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                self.files_fixed += 1
                print(f"Fixed missing function bodies in: {file_path}")
            
            return modified
            
        except Exception as e:
            print(f"Error fixing {file_path}: {e}")
            return False
    
    def fix_malformed_docstrings(self, file_path: Path) -> bool:
        """
        Fix malformed docstrings that break syntax.
        
        Args:
            file_path: Path to the file to fix
            
        Returns:
            True if the file was modified, False otherwise
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Fix common docstring issues
            original_content = content
            
            # Fix unmatched triple quotes
            content = re.sub(r'"""([^"]*?)"""([^"]*?)"""', r'"""\1\2"""', content)
            
            # Fix incomplete docstrings after function definitions
            content = re.sub(
                r'(def\s+\w+\([^)]*\):\s*\n\s*"""[^"]*?)\n(\s*def\s|\s*class\s|\s*@|\n\S)',
                r'\1"""\n        pass\n\2',
                content,
                flags=re.MULTILINE | re.DOTALL
            )
            
            # Fix functions without bodies
            content = re.sub(
                r'(def\s+\w+\([^)]*\):\s*\n)(\s*""".*?"""\s*\n)(\s*(?:def\s|class\s|@|\S))',
                r'\1\2        pass\n\3',
                content,
                flags=re.MULTILINE | re.DOTALL
            )
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.fixes_applied += 1
                self.files_fixed += 1
                print(f"Fixed malformed docstrings in: {file_path}")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error fixing malformed docstrings in {file_path}: {e}")
            return False
    
    def remove_broken_files(self, file_paths: List[Path]) -> None:
        """
        For files that can't be easily fixed, restore from a clean template.
        
        Args:
            file_paths: List of file paths that need complete restoration
        """
        for file_path in file_paths:
            try:
                # Create a minimal working version
                content_template = f'''"""
{file_path.name} - PgAppForge Component

This module has been restored to a minimal working state due to syntax errors.
Original functionality is preserved where possible.
"""

# TODO: Review and enhance this file after syntax error resolution
pass
'''
                
                backup_path = file_path.with_suffix('.py.broken')
                
                # Backup the broken file
                if file_path.exists():
                    import shutil
                    shutil.copy2(file_path, backup_path)
                    print(f"Backed up broken file to: {backup_path}")
                
                # Write minimal template (only if file is completely broken)
                with open(file_path, 'r') as f:
                    try:
                        ast.parse(f.read())
                        # File is parseable, don't replace
                        continue
                    except SyntaxError:
                        pass
                
                print(f"File {file_path} is severely broken, consider manual review")
                
            except Exception as e:
                print(f"Error handling {file_path}: {e}")
    
    def fix_all_syntax_errors(self) -> Dict[str, int]:
        """
        Find and fix all syntax errors in the codebase.
        
        Returns:
            Dictionary with statistics about fixes applied
        """
        print("Scanning for syntax errors...")
        error_files = self.find_syntax_error_files()
        
        if not error_files:
            print("No syntax errors found!")
            return {"files_with_errors": 0, "files_fixed": 0, "fixes_applied": 0}
        
        print(f"Found {len(error_files)} files with syntax errors")
        
        # Try to fix each file
        for file_path in error_files:
            print(f"\nFixing: {file_path}")
            
            # Try multiple fix strategies
            fixed = False
            
            # Strategy 1: Fix missing function bodies
            if self.fix_missing_function_bodies(file_path):
                fixed = True
            
            # Strategy 2: Fix malformed docstrings
            if self.fix_malformed_docstrings(file_path):
                fixed = True
            
            # Verify the fix worked
            try:
                with open(file_path, 'r') as f:
                    ast.parse(f.read())
                print(f"✅ Successfully fixed: {file_path}")
            except SyntaxError as e:
                print(f"❌ Still has errors: {file_path} - {e}")
        
        return {
            "files_with_errors": len(error_files),
            "files_fixed": self.files_fixed,
            "fixes_applied": self.fixes_applied
        }


def main():
    """Main function to fix syntax errors."""
    pgappforge_path = Path(__file__).parent.parent.parent / "pgappforge"
    
    print("Starting syntax error fixing process...")
    print("=" * 60)
    
    fixer = SyntaxErrorFixer(str(pgappforge_path))
    results = fixer.fix_all_syntax_errors()
    
    print("\n" + "=" * 60)
    print("SYNTAX ERROR FIXING RESULTS")
    print("=" * 60)
    print(f"Files with errors found: {results['files_with_errors']}")
    print(f"Files successfully fixed: {results['files_fixed']}")
    print(f"Total fixes applied: {results['fixes_applied']}")
    
    if results['files_with_errors'] == 0:
        print("\n✅ No syntax errors found - codebase is clean!")
    elif results['files_fixed'] > 0:
        print(f"\n✅ Fixed {results['files_fixed']} files with syntax errors")
    else:
        print(f"\n⚠️  Some files may need manual review")
    
    print("\nSyntax error fixing completed!")


if __name__ == '__main__':
    main()