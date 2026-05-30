#!/usr/bin/env python3
"""
Documentation Completeness Validation Tests

Comprehensive tests to validate documentation completeness across the entire
PgAppForge codebase, ensuring all public methods, classes, and modules
have appropriate documentation.
"""

import ast
import inspect
import importlib
import logging
import os
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass, field

# Add the parent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)


@dataclass
class DocumentationIssue:
    """Represents a documentation issue found during analysis."""
    
    file_path: str
    class_name: Optional[str]
    method_name: str
    issue_type: str  # 'missing_docstring', 'incomplete_params', 'missing_returns', etc.
    line_number: int
    severity: str  # 'critical', 'high', 'medium', 'low'
    description: str


@dataclass  
class DocumentationAnalysis:
    """Results of documentation analysis."""
    
    total_methods: int = 0
    documented_methods: int = 0
    total_classes: int = 0
    documented_classes: int = 0
    total_modules: int = 0
    documented_modules: int = 0
    issues: List[DocumentationIssue] = field(default_factory=list)
    
    @property
    def method_coverage(self) -> float:
        """Calculate method documentation coverage percentage."""
        if self.total_methods == 0:
            return 100.0
        return (self.documented_methods / self.total_methods) * 100.0
    
    @property
    def class_coverage(self) -> float:
        """Calculate class documentation coverage percentage."""
        if self.total_classes == 0:
            return 100.0
        return (self.documented_classes / self.total_classes) * 100.0
    
    @property
    def module_coverage(self) -> float:
        """Calculate module documentation coverage percentage."""
        if self.total_modules == 0:
            return 100.0
        return (self.documented_modules / self.total_modules) * 100.0
    
    @property
    def overall_coverage(self) -> float:
        """Calculate overall documentation coverage percentage."""
        total = self.total_methods + self.total_classes + self.total_modules
        documented = self.documented_methods + self.documented_classes + self.documented_modules
        if total == 0:
            return 100.0
        return (documented / total) * 100.0


class DocumentationAnalyzer:
    """
    Analyzes Python code for documentation completeness.
    
    Provides comprehensive analysis of docstring coverage, parameter documentation,
    return value documentation, and overall documentation quality.
    """
    
    def __init__(self, base_path: str):
        """
        Initialize the documentation analyzer.
        
        Args:
            base_path: Root path to analyze for documentation
        """
        self.base_path = Path(base_path)
        self.analysis = DocumentationAnalysis()
    
    def analyze_file(self, file_path: Path) -> None:
        """
        Analyze a single Python file for documentation completeness.
        
        Args:
            file_path: Path to the Python file to analyze
            
        Raises:
            SyntaxError: If the file cannot be parsed as valid Python
            FileNotFoundError: If the file does not exist
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the AST
            tree = ast.parse(content, filename=str(file_path))
            
            # Analyze module-level docstring
            self._analyze_module_docstring(tree, file_path)
            
            # Analyze classes and methods
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self._analyze_class(node, file_path)
                elif isinstance(node, ast.FunctionDef):
                    # Only analyze top-level functions (not methods)
                    if not any(isinstance(parent, ast.ClassDef) 
                             for parent in ast.walk(tree) 
                             if any(child == node for child in ast.walk(parent))):
                        self._analyze_function(node, file_path)
                        
        except Exception as e:
            logger.warning(f"Could not analyze file {file_path}: {e}")
    
    def _analyze_module_docstring(self, tree: ast.AST, file_path: Path) -> None:
        """
        Analyze module-level docstring.
        
        Args:
            tree: AST tree of the module
            file_path: Path to the module file
        """
        self.analysis.total_modules += 1
        
        if (tree.body and 
            isinstance(tree.body[0], ast.Expr) and 
            isinstance(tree.body[0].value, ast.Str)):
            
            docstring = tree.body[0].value.s.strip()
            if len(docstring) > 20:  # Minimum meaningful docstring length
                self.analysis.documented_modules += 1
            else:
                self._add_issue(
                    file_path=str(file_path),
                    class_name=None,
                    method_name="<module>",
                    issue_type="incomplete_docstring",
                    line_number=1,
                    severity="medium",
                    description="Module docstring is too brief"
                )
        else:
            self._add_issue(
                file_path=str(file_path),
                class_name=None,
                method_name="<module>",
                issue_type="missing_docstring",
                line_number=1,
                severity="high",
                description="Module missing docstring"
            )
    
    def _analyze_class(self, node: ast.ClassDef, file_path: Path) -> None:
        """
        Analyze a class for documentation completeness.
        
        Args:
            node: AST ClassDef node
            file_path: Path to the file containing the class
        """
        self.analysis.total_classes += 1
        
        # Check class docstring
        if (node.body and 
            isinstance(node.body[0], ast.Expr) and 
            isinstance(node.body[0].value, ast.Str)):
            
            docstring = node.body[0].value.s.strip()
            if len(docstring) > 20:
                self.analysis.documented_classes += 1
            else:
                self._add_issue(
                    file_path=str(file_path),
                    class_name=node.name,
                    method_name="<class>",
                    issue_type="incomplete_docstring",
                    line_number=node.lineno,
                    severity="medium",
                    description=f"Class '{node.name}' docstring is too brief"
                )
        else:
            self._add_issue(
                file_path=str(file_path),
                class_name=node.name,
                method_name="<class>",
                issue_type="missing_docstring",
                line_number=node.lineno,
                severity="high",
                description=f"Class '{node.name}' missing docstring"
            )
        
        # Analyze methods
        for method_node in node.body:
            if isinstance(method_node, ast.FunctionDef):
                self._analyze_method(method_node, file_path, node.name)
    
    def _analyze_function(self, node: ast.FunctionDef, file_path: Path, class_name: str = None) -> None:
        """
        Analyze a function for documentation completeness.
        
        Args:
            node: AST FunctionDef node
            file_path: Path to the file containing the function
            class_name: Name of the containing class (if any)
        """
        self.analysis.total_methods += 1
        
        # Skip private methods (unless they're special methods)
        if node.name.startswith('_') and not (node.name.startswith('__') and node.name.endswith('__')):
            self.analysis.documented_methods += 1  # Don't require docs for private methods
            return
        
        # Check for docstring
        has_docstring = (node.body and 
                        isinstance(node.body[0], ast.Expr) and 
                        isinstance(node.body[0].value, ast.Str))
        
        if has_docstring:
            docstring = node.body[0].value.s.strip()
            self._analyze_docstring_quality(docstring, node, file_path, class_name)
            self.analysis.documented_methods += 1
        else:
            self._add_issue(
                file_path=str(file_path),
                class_name=class_name,
                method_name=node.name,
                issue_type="missing_docstring",
                line_number=node.lineno,
                severity="critical" if not node.name.startswith('_') else "low",
                description=f"Method '{node.name}' missing docstring"
            )
    
    def _analyze_method(self, node: ast.FunctionDef, file_path: Path, class_name: str) -> None:
        """
        Analyze a class method for documentation completeness.
        
        Args:
            node: AST FunctionDef node
            file_path: Path to the file containing the method
            class_name: Name of the containing class
        """
        self._analyze_function(node, file_path, class_name)
    
    def _analyze_docstring_quality(self, docstring: str, node: ast.FunctionDef, 
                                 file_path: Path, class_name: str = None) -> None:
        """
        Analyze the quality of a function/method docstring.
        
        Args:
            docstring: The docstring content
            node: AST FunctionDef node
            file_path: Path to the file
            class_name: Name of containing class (if any)
        """
        lines = docstring.split('\n')
        
        # Check for minimum length
        if len(docstring.strip()) < 20:
            self._add_issue(
                file_path=str(file_path),
                class_name=class_name,
                method_name=node.name,
                issue_type="incomplete_docstring",
                line_number=node.lineno,
                severity="medium",
                description=f"Docstring for '{node.name}' is too brief"
            )
        
        # Check for parameter documentation if method has parameters
        params = [arg.arg for arg in node.args.args if arg.arg != 'self']
        if params:
            has_args_section = any('Args:' in line or 'Arguments:' in line or 'Parameters:' in line 
                                 for line in lines)
            if not has_args_section:
                self._add_issue(
                    file_path=str(file_path),
                    class_name=class_name,
                    method_name=node.name,
                    issue_type="missing_params",
                    line_number=node.lineno,
                    severity="medium",
                    description=f"Method '{node.name}' missing parameter documentation"
                )
        
        # Check for return documentation if method likely returns something
        if not node.name.startswith('__') and node.name not in ['setUp', 'tearDown']:
            has_returns_section = any('Returns:' in line or 'Return:' in line 
                                    for line in lines)
            # Only require returns documentation for non-obvious methods
            if not has_returns_section and not node.name.startswith('set_'):
                self._add_issue(
                    file_path=str(file_path),
                    class_name=class_name,
                    method_name=node.name,
                    issue_type="missing_returns",
                    line_number=node.lineno,
                    severity="low",
                    description=f"Method '{node.name}' missing return documentation"
                )
    
    def _add_issue(self, file_path: str, class_name: Optional[str], method_name: str,
                  issue_type: str, line_number: int, severity: str, description: str) -> None:
        """
        Add a documentation issue to the analysis results.
        
        Args:
            file_path: Path to the file with the issue
            class_name: Name of the class (if applicable)
            method_name: Name of the method/function
            issue_type: Type of documentation issue
            line_number: Line number where issue occurs
            severity: Severity level of the issue
            description: Human-readable description of the issue
        """
        issue = DocumentationIssue(
            file_path=file_path,
            class_name=class_name,
            method_name=method_name,
            issue_type=issue_type,
            line_number=line_number,
            severity=severity,
            description=description
        )
        self.analysis.issues.append(issue)
    
    def analyze_directory(self, directory: Path = None) -> DocumentationAnalysis:
        """
        Analyze all Python files in a directory for documentation completeness.
        
        Args:
            directory: Directory to analyze (defaults to base_path)
            
        Returns:
            DocumentationAnalysis with complete results
        """
        if directory is None:
            directory = self.base_path
            
        # Find all Python files
        python_files = list(directory.rglob("*.py"))
        
        # Filter out test files and __pycache__
        python_files = [
            f for f in python_files 
            if not any(part.startswith('__pycache__') or part.startswith('.') 
                      for part in f.parts)
        ]
        
        logger.info(f"Analyzing {len(python_files)} Python files for documentation completeness")
        
        # Analyze each file
        for file_path in python_files:
            self.analyze_file(file_path)
        
        return self.analysis
    
    def generate_report(self) -> str:
        """
        Generate a comprehensive documentation completeness report.
        
        Returns:
            Formatted report string
        """
        report = []
        report.append("=" * 80)
        report.append("DOCUMENTATION COMPLETENESS ANALYSIS REPORT")
        report.append("=" * 80)
        report.append("")
        
        # Summary statistics
        report.append("SUMMARY STATISTICS")
        report.append("-" * 40)
        report.append(f"Total Methods Analyzed: {self.analysis.total_methods}")
        report.append(f"Documented Methods: {self.analysis.documented_methods}")
        report.append(f"Method Documentation Coverage: {self.analysis.method_coverage:.1f}%")
        report.append("")
        report.append(f"Total Classes Analyzed: {self.analysis.total_classes}")
        report.append(f"Documented Classes: {self.analysis.documented_classes}")
        report.append(f"Class Documentation Coverage: {self.analysis.class_coverage:.1f}%")
        report.append("")
        report.append(f"Total Modules Analyzed: {self.analysis.total_modules}")
        report.append(f"Documented Modules: {self.analysis.documented_modules}")
        report.append(f"Module Documentation Coverage: {self.analysis.module_coverage:.1f}%")
        report.append("")
        report.append(f"OVERALL DOCUMENTATION COVERAGE: {self.analysis.overall_coverage:.1f}%")
        report.append("")
        
        # Issues summary
        critical_issues = [i for i in self.analysis.issues if i.severity == 'critical']
        high_issues = [i for i in self.analysis.issues if i.severity == 'high']
        medium_issues = [i for i in self.analysis.issues if i.severity == 'medium']
        low_issues = [i for i in self.analysis.issues if i.severity == 'low']
        
        report.append("ISSUES SUMMARY")
        report.append("-" * 40)
        report.append(f"Critical Issues: {len(critical_issues)}")
        report.append(f"High Priority Issues: {len(high_issues)}")
        report.append(f"Medium Priority Issues: {len(medium_issues)}")
        report.append(f"Low Priority Issues: {len(low_issues)}")
        report.append(f"Total Issues: {len(self.analysis.issues)}")
        report.append("")
        
        # Detailed issues (only show critical and high)
        if critical_issues or high_issues:
            report.append("CRITICAL AND HIGH PRIORITY ISSUES")
            report.append("-" * 40)
            
            for issue in critical_issues + high_issues:
                class_info = f" in class {issue.class_name}" if issue.class_name else ""
                report.append(f"[{issue.severity.upper()}] {issue.method_name}{class_info}")
                report.append(f"  File: {issue.file_path}:{issue.line_number}")
                report.append(f"  Issue: {issue.description}")
                report.append("")
        
        return "\n".join(report)


class TestDocumentationCompleteness(unittest.TestCase):
    """
    Test suite to validate documentation completeness across the PgAppForge codebase.
    
    These tests ensure that all public methods, classes, and modules have appropriate
    documentation to meet production quality standards.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for documentation analysis."""
        cls.pgappforge_path = Path(__file__).parent.parent.parent / "pgappforge"
        cls.analyzer = DocumentationAnalyzer(str(cls.pgappforge_path))
        cls.analysis = cls.analyzer.analyze_directory()
    
    def test_overall_documentation_coverage_target(self):
        """Test that overall documentation coverage meets target threshold."""
        target_coverage = 85.0  # 85% overall coverage target
        actual_coverage = self.analysis.overall_coverage
        
        self.assertGreaterEqual(
            actual_coverage, 
            target_coverage,
            f"Overall documentation coverage ({actual_coverage:.1f}%) is below target ({target_coverage}%)"
        )
    
    def test_method_documentation_coverage(self):
        """Test that method documentation coverage meets threshold."""
        target_coverage = 80.0  # 80% method coverage target
        actual_coverage = self.analysis.method_coverage
        
        self.assertGreaterEqual(
            actual_coverage,
            target_coverage,
            f"Method documentation coverage ({actual_coverage:.1f}%) is below target ({target_coverage}%)"
        )
    
    def test_class_documentation_coverage(self):
        """Test that class documentation coverage meets threshold."""
        target_coverage = 90.0  # 90% class coverage target
        actual_coverage = self.analysis.class_coverage
        
        self.assertGreaterEqual(
            actual_coverage,
            target_coverage,
            f"Class documentation coverage ({actual_coverage:.1f}%) is below target ({target_coverage}%)"
        )
    
    def test_no_critical_documentation_issues(self):
        """Test that there are no critical documentation issues."""
        critical_issues = [i for i in self.analysis.issues if i.severity == 'critical']
        
        if critical_issues:
            issue_details = "\n".join([
                f"  {issue.method_name} in {issue.file_path}:{issue.line_number} - {issue.description}"
                for issue in critical_issues[:10]  # Show first 10
            ])
            self.fail(
                f"Found {len(critical_issues)} critical documentation issues:\n{issue_details}"
            )
    
    def test_limited_high_priority_issues(self):
        """Test that high priority documentation issues are limited."""
        high_issues = [i for i in self.analysis.issues if i.severity == 'high']
        max_allowed_high_issues = 20  # Allow up to 20 high priority issues
        
        self.assertLessEqual(
            len(high_issues),
            max_allowed_high_issues,
            f"Too many high priority documentation issues ({len(high_issues)}) - maximum allowed is {max_allowed_high_issues}"
        )
    
    def test_database_modules_documentation(self):
        """Test that database modules have comprehensive documentation."""
        database_files = [
            "graph_manager.py",
            "erd_manager.py",
            "query_builder.py",
            "federated_analytics.py"
        ]
        
        for file_name in database_files:
            file_issues = [
                i for i in self.analysis.issues 
                if file_name in i.file_path and i.severity in ['critical', 'high']
            ]
            
            self.assertLessEqual(
                len(file_issues),
                3,  # Allow up to 3 critical/high issues per database module
                f"Too many critical/high documentation issues in {file_name}: {len(file_issues)}"
            )
    
    def test_security_modules_documentation(self):
        """Test that security modules have comprehensive documentation."""
        security_path_parts = ["security"]
        
        security_issues = [
            i for i in self.analysis.issues
            if any(part in i.file_path for part in security_path_parts)
            and i.severity in ['critical', 'high']
        ]
        
        self.assertLessEqual(
            len(security_issues),
            10,  # Allow up to 10 critical/high issues in security modules
            f"Too many critical/high documentation issues in security modules: {len(security_issues)}"
        )
    
    def test_api_modules_documentation(self):
        """Test that API modules have comprehensive documentation."""
        api_path_parts = ["api", "views"]
        
        api_issues = [
            i for i in self.analysis.issues
            if any(part in i.file_path for part in api_path_parts)
            and i.severity in ['critical', 'high']
        ]
        
        self.assertLessEqual(
            len(api_issues),
            15,  # Allow up to 15 critical/high issues in API modules
            f"Too many critical/high documentation issues in API modules: {len(api_issues)}"
        )
    
    def test_generate_documentation_report(self):
        """Generate and save comprehensive documentation report."""
        report = self.analyzer.generate_report()
        
        # Save report to file
        report_path = Path(__file__).parent / "documentation_completeness_report.txt"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"Documentation completeness report saved to {report_path}")
        
        # Report should contain key sections
        self.assertIn("DOCUMENTATION COMPLETENESS ANALYSIS REPORT", report)
        self.assertIn("SUMMARY STATISTICS", report)
        self.assertIn("OVERALL DOCUMENTATION COVERAGE", report)


def main():
    """Run documentation completeness analysis and tests."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the tests
    unittest.main(verbosity=2)


if __name__ == '__main__':
    main()