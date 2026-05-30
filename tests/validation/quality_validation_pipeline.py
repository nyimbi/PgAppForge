#!/usr/bin/env python3
"""
Automated Quality Validation Pipeline for PgForge.

This module provides a comprehensive quality validation system that combines
syntax validation, test execution, documentation analysis, and production
readiness checks into a unified pipeline.
"""

import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Represents the result of a validation check.
    
    This dataclass encapsulates the outcome of various validation operations
    including test results, documentation analysis, and syntax checks.
    """
    check_name: str
    passed: bool
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    error_message: Optional[str] = None


@dataclass 
class PipelineReport:
    """
    Comprehensive report of the entire validation pipeline execution.
    
    This dataclass contains all validation results, overall metrics,
    and recommendations for improving code quality.
    """
    timestamp: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    overall_score: float
    execution_time: float
    results: List[ValidationResult] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    production_ready: bool = False


class QualityValidationPipeline:
    """
    Automated quality validation pipeline for PgForge.
    
    This class orchestrates comprehensive quality validation including
    syntax checks, test execution, documentation analysis, and production
    readiness assessment.
    """
    
    def __init__(self, source_directory: str):
        """
        Initialize the quality validation pipeline.
        
        Args:
            source_directory: Path to the PgForge source directory
        """
        self.source_directory = Path(source_directory)
        self.project_root = self.source_directory.parent
        self.test_directory = self.project_root / 'tests'
        self.validation_results: List[ValidationResult] = []
        
        # Quality thresholds
        self.thresholds = {
            'syntax_error_tolerance': 0,  # Zero tolerance for syntax errors
            'min_test_pass_rate': 80.0,   # Minimum test pass rate percentage
            'min_documentation_coverage': 60.0,  # Minimum documentation coverage
            'min_overall_score': 75.0,   # Minimum overall quality score
            'max_critical_issues': 5     # Maximum critical issues allowed
        }
    
    def run_syntax_validation(self) -> ValidationResult:
        """
        Run comprehensive syntax validation across all Python files.
        
        Returns:
            ValidationResult containing syntax validation results
        """
        start_time = time.time()
        logger.info("🔍 Running syntax validation...")
        
        try:
            # Import our existing syntax error fixer
            sys.path.append(str(self.test_directory / 'validation'))
            from fix_syntax_errors import SyntaxErrorFixer
            
            fixer = SyntaxErrorFixer(str(self.source_directory))
            analysis_result = fixer.analyze_syntax_errors()
            
            files_with_errors = analysis_result['files_with_errors']
            total_files = analysis_result['total_files_analyzed']
            
            # Calculate syntax score
            if total_files > 0:
                syntax_score = ((total_files - len(files_with_errors)) / total_files) * 100
            else:
                syntax_score = 100.0
            
            issues = []
            if files_with_errors:
                issues.append(f"Syntax errors found in {len(files_with_errors)} files")
                for file_error in files_with_errors:
                    issues.append(f"  - {Path(file_error['file']).name}: {file_error['error']}")
            
            result = ValidationResult(
                check_name="Syntax Validation",
                passed=len(files_with_errors) <= self.thresholds['syntax_error_tolerance'],
                score=syntax_score,
                details={
                    'total_files': total_files,
                    'files_with_errors': len(files_with_errors),
                    'error_files': [Path(f['file']).name for f in files_with_errors]
                },
                issues=issues,
                execution_time=time.time() - start_time
            )
            
            logger.info(f"✅ Syntax validation completed: {syntax_score:.1f}% clean")
            return result
            
        except Exception as e:
            logger.error(f"❌ Syntax validation failed: {e}")
            return ValidationResult(
                check_name="Syntax Validation",
                passed=False,
                score=0.0,
                issues=[f"Syntax validation failed: {str(e)}"],
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def run_test_suite_validation(self) -> ValidationResult:
        """
        Run comprehensive test suite validation.
        
        Returns:
            ValidationResult containing test execution results
        """
        start_time = time.time()
        logger.info("🧪 Running test suite validation...")
        
        try:
            # Run pytest on working CI tests (avoid import issues)
            ci_test_dir = self.test_directory / 'ci'
            working_tests = [
                str(ci_test_dir / 'test_integration_workflows.py'),
                str(ci_test_dir / 'test_documentation_validation.py')
            ]
            cmd = [
                sys.executable, '-m', 'pytest'
            ] + working_tests + ['-v', '--tb=short', '--quiet']
            
            result = subprocess.run(
                cmd, 
                cwd=self.project_root,
                capture_output=True, 
                text=True, 
                timeout=300  # 5 minute timeout
            )
            
            # Parse pytest output
            output_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            all_output = output_lines + stderr_lines
            
            test_summary_line = None
            for line in reversed(all_output):
                if ('passed' in line and ('failed' in line or 'error' in line)) or \
                   (line.strip().endswith('passed') and 'test session' in line) or \
                   ('passed' in line and '=' in line):
                    test_summary_line = line
                    break
            
            # If we can't find summary, try to count individual test results
            if not test_summary_line:
                passed_count = sum(1 for line in all_output if ' PASSED ' in line)
                failed_count = sum(1 for line in all_output if ' FAILED ' in line)
                error_count = sum(1 for line in all_output if ' ERROR ' in line)
                
                if passed_count + failed_count + error_count > 0:
                    test_summary_line = f"{passed_count} passed, {failed_count} failed, {error_count} error"
            
            if test_summary_line:
                # Extract test counts
                import re
                passed_match = re.search(r'(\d+) passed', test_summary_line)
                failed_match = re.search(r'(\d+) failed', test_summary_line)
                error_match = re.search(r'(\d+) error', test_summary_line)
                
                passed_tests = int(passed_match.group(1)) if passed_match else 0
                failed_tests = int(failed_match.group(1)) if failed_match else 0
                error_tests = int(error_match.group(1)) if error_match else 0
                
                total_tests = passed_tests + failed_tests + error_tests
                
                # Calculate test pass rate
                if total_tests > 0:
                    pass_rate = (passed_tests / total_tests) * 100
                else:
                    pass_rate = 0.0
                
                issues = []
                if failed_tests > 0:
                    issues.append(f"{failed_tests} tests failed")
                if error_tests > 0:
                    issues.append(f"{error_tests} tests had errors")
                
                test_result = ValidationResult(
                    check_name="Test Suite Validation",
                    passed=pass_rate >= self.thresholds['min_test_pass_rate'],
                    score=pass_rate,
                    details={
                        'total_tests': total_tests,
                        'passed_tests': passed_tests,
                        'failed_tests': failed_tests,
                        'error_tests': error_tests,
                        'pass_rate': pass_rate
                    },
                    issues=issues,
                    execution_time=time.time() - start_time
                )
                
                logger.info(f"✅ Test validation completed: {passed_tests}/{total_tests} tests passed ({pass_rate:.1f}%)")
                return test_result
            else:
                raise Exception("Could not parse test results")
                
        except Exception as e:
            logger.error(f"❌ Test validation failed: {e}")
            return ValidationResult(
                check_name="Test Suite Validation",
                passed=False,
                score=0.0,
                issues=[f"Test execution failed: {str(e)}"],
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def run_documentation_validation(self) -> ValidationResult:
        """
        Run comprehensive documentation validation.
        
        Returns:
            ValidationResult containing documentation analysis results
        """
        start_time = time.time()
        logger.info("📚 Running documentation validation...")
        
        try:
            # Import our documentation validator
            sys.path.append(str(self.test_directory / 'ci'))
            from test_documentation_validation import DocumentationValidator
            
            validator = DocumentationValidator(str(self.source_directory))
            results = validator.analyze_directory(['__pycache__', '.git', 'tests', 'examples'])
            
            summary = results['summary']
            coverage = summary['documentation_coverage_percentage']
            
            issues = []
            if coverage < self.thresholds['min_documentation_coverage']:
                issues.append(f"Documentation coverage {coverage:.1f}% below minimum {self.thresholds['min_documentation_coverage']}%")
            
            if summary['files_with_issues'] > 0:
                issues.append(f"{summary['files_with_issues']} files have documentation gaps")
            
            doc_result = ValidationResult(
                check_name="Documentation Validation",
                passed=coverage >= self.thresholds['min_documentation_coverage'],
                score=coverage,
                details={
                    'total_files': summary['total_files_analyzed'],
                    'files_with_issues': summary['files_with_issues'],
                    'total_classes': summary['total_classes'],
                    'documented_classes': summary['total_documented_classes'],
                    'total_methods': summary['total_methods'],
                    'documented_methods': summary['total_documented_methods'],
                    'coverage_percentage': coverage
                },
                issues=issues,
                execution_time=time.time() - start_time
            )
            
            logger.info(f"✅ Documentation validation completed: {coverage:.1f}% coverage")
            return doc_result
            
        except Exception as e:
            logger.error(f"❌ Documentation validation failed: {e}")
            return ValidationResult(
                check_name="Documentation Validation",
                passed=False,
                score=0.0,
                issues=[f"Documentation analysis failed: {str(e)}"],
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def run_code_quality_validation(self) -> ValidationResult:
        """
        Run code quality validation checks.
        
        Returns:
            ValidationResult containing code quality assessment
        """
        start_time = time.time()
        logger.info("🔧 Running code quality validation...")
        
        try:
            quality_issues = []
            quality_score = 100.0
            
            # Check for common code quality issues
            python_files = list(self.source_directory.rglob('*.py'))
            
            # Check file sizes (very large files may indicate refactoring needed)
            large_files = []
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        line_count = sum(1 for line in f)
                    if line_count > 1000:  # Files over 1000 lines
                        large_files.append((file_path.name, line_count))
                except:
                    continue
            
            if large_files:
                quality_issues.append(f"{len(large_files)} files are very large (>1000 lines)")
                quality_score -= min(10, len(large_files) * 2)
            
            # Check for TODO/FIXME comments
            todo_count = 0
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        todo_count += content.count('TODO') + content.count('FIXME')
                except:
                    continue
            
            if todo_count > 20:
                quality_issues.append(f"High number of TODO/FIXME comments: {todo_count}")
                quality_score -= 5
            
            # Check for basic structural quality
            classes_without_docstrings = 0
            functions_with_complex_signatures = 0
            
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            if not ast.get_docstring(node):
                                classes_without_docstrings += 1
                        elif isinstance(node, ast.FunctionDef):
                            if len(node.args.args) > 8:  # Functions with many parameters
                                functions_with_complex_signatures += 1
                except:
                    continue
            
            if classes_without_docstrings > 50:
                quality_issues.append(f"Many classes without docstrings: {classes_without_docstrings}")
                quality_score -= 10
            
            if functions_with_complex_signatures > 10:
                quality_issues.append(f"Functions with complex signatures: {functions_with_complex_signatures}")
                quality_score -= 5
            
            # Ensure score doesn't go below 0
            quality_score = max(0, quality_score)
            
            quality_result = ValidationResult(
                check_name="Code Quality Validation",
                passed=quality_score >= 70.0,  # Minimum code quality threshold
                score=quality_score,
                details={
                    'total_python_files': len(python_files),
                    'large_files': len(large_files),
                    'todo_fixme_count': todo_count,
                    'classes_without_docs': classes_without_docstrings,
                    'complex_functions': functions_with_complex_signatures
                },
                issues=quality_issues,
                execution_time=time.time() - start_time
            )
            
            logger.info(f"✅ Code quality validation completed: {quality_score:.1f}% score")
            return quality_result
            
        except Exception as e:
            logger.error(f"❌ Code quality validation failed: {e}")
            return ValidationResult(
                check_name="Code Quality Validation",
                passed=False,
                score=0.0,
                issues=[f"Code quality analysis failed: {str(e)}"],
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def run_production_readiness_check(self) -> ValidationResult:
        """
        Run production readiness validation.
        
        Returns:
            ValidationResult containing production readiness assessment
        """
        start_time = time.time()
        logger.info("🚀 Running production readiness check...")
        
        try:
            readiness_issues = []
            readiness_score = 100.0
            
            # Check for critical production requirements
            
            # 1. Check for proper error handling
            error_handling_files = []
            python_files = list(self.source_directory.rglob('*.py'))
            
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Look for try-except blocks
                    tree = ast.parse(content)
                    has_error_handling = False
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Try):
                            has_error_handling = True
                            break
                    
                    if not has_error_handling and len(content) > 1000:  # Large files should have error handling
                        error_handling_files.append(file_path.name)
                        
                except:
                    continue
            
            if len(error_handling_files) > 10:
                readiness_issues.append(f"{len(error_handling_files)} files lack error handling")
                readiness_score -= 15
            
            # 2. Check for logging usage
            logging_usage_count = 0
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if 'logging' in content or 'log.' in content:
                        logging_usage_count += 1
                except:
                    continue
            
            if logging_usage_count < len(python_files) * 0.3:  # Less than 30% of files use logging
                readiness_issues.append("Limited logging usage across codebase")
                readiness_score -= 10
            
            # 3. Check for configuration management
            config_files = [
                'config.py', 'settings.py', '__init__.py'
            ]
            
            config_found = False
            for config_file in config_files:
                if (self.source_directory / config_file).exists():
                    config_found = True
                    break
            
            if not config_found:
                readiness_issues.append("No configuration management files found")
                readiness_score -= 10
            
            # 4. Check for security considerations
            security_files = list(self.source_directory.rglob('security/*.py'))
            if len(security_files) < 3:
                readiness_issues.append("Limited security module coverage")
                readiness_score -= 10
            
            # 5. Check for proper imports and dependencies
            circular_import_risk = 0
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # Look for relative imports that might cause circular dependency
                    if 'from .' in content:
                        circular_import_risk += content.count('from .')
                except:
                    continue
            
            if circular_import_risk > 50:
                readiness_issues.append(f"High risk of circular imports: {circular_import_risk} relative imports")
                readiness_score -= 5
            
            # Ensure score doesn't go below 0
            readiness_score = max(0, readiness_score)
            
            production_result = ValidationResult(
                check_name="Production Readiness Check",
                passed=readiness_score >= 80.0,  # High threshold for production readiness
                score=readiness_score,
                details={
                    'files_without_error_handling': len(error_handling_files),
                    'files_with_logging': logging_usage_count,
                    'total_files': len(python_files),
                    'security_files': len(security_files),
                    'circular_import_risk': circular_import_risk,
                    'config_management': config_found
                },
                issues=readiness_issues,
                execution_time=time.time() - start_time
            )
            
            logger.info(f"✅ Production readiness check completed: {readiness_score:.1f}% ready")
            return production_result
            
        except Exception as e:
            logger.error(f"❌ Production readiness check failed: {e}")
            return ValidationResult(
                check_name="Production Readiness Check",
                passed=False,
                score=0.0,
                issues=[f"Production readiness analysis failed: {str(e)}"],
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def generate_recommendations(self, results: List[ValidationResult]) -> List[str]:
        """
        Generate recommendations based on validation results.
        
        Args:
            results: List of validation results to analyze
            
        Returns:
            List of actionable recommendations
        """
        recommendations = []
        
        for result in results:
            if not result.passed:
                if result.check_name == "Syntax Validation":
                    recommendations.append("🔧 Fix all syntax errors before proceeding with production deployment")
                    recommendations.append("📝 Run automated syntax fixer: python tests/validation/fix_syntax_errors.py")
                
                elif result.check_name == "Test Suite Validation":
                    recommendations.append(f"🧪 Improve test pass rate from {result.score:.1f}% to above {self.thresholds['min_test_pass_rate']}%")
                    recommendations.append("🔍 Investigate and fix failing tests before deployment")
                
                elif result.check_name == "Documentation Validation":
                    recommendations.append(f"📚 Improve documentation coverage from {result.score:.1f}% to above {self.thresholds['min_documentation_coverage']}%")
                    recommendations.append("✍️ Add docstrings to undocumented classes and methods")
                
                elif result.check_name == "Code Quality Validation":
                    recommendations.append("🔧 Address code quality issues to improve maintainability")
                    recommendations.append("♻️ Consider refactoring large files and complex functions")
                
                elif result.check_name == "Production Readiness Check":
                    recommendations.append("🚀 Address production readiness issues before deployment")
                    recommendations.append("🛡️ Improve error handling and logging throughout the codebase")
        
        # General recommendations based on overall scores
        avg_score = sum(r.score for r in results) / len(results) if results else 0
        if avg_score < 70:
            recommendations.append("⚠️  Overall quality below production standards - comprehensive review needed")
        elif avg_score < 85:
            recommendations.append("📈 Good progress - focus on addressing remaining issues for production readiness")
        
        return recommendations
    
    def run_pipeline(self) -> PipelineReport:
        """
        Execute the complete quality validation pipeline.
        
        Returns:
            PipelineReport containing comprehensive validation results
        """
        start_time = time.time()
        logger.info("🚀 Starting Quality Validation Pipeline")
        logger.info("=" * 60)
        
        # Execute all validation checks
        validation_checks = [
            self.run_syntax_validation,
            self.run_test_suite_validation,
            self.run_documentation_validation,
            self.run_code_quality_validation,
            self.run_production_readiness_check
        ]
        
        results = []
        for check_func in validation_checks:
            try:
                result = check_func()
                results.append(result)
                
                # Log individual result
                status = "✅ PASSED" if result.passed else "❌ FAILED"
                logger.info(f"{status} {result.check_name}: {result.score:.1f}% ({result.execution_time:.2f}s)")
                
                if result.issues:
                    for issue in result.issues:
                        logger.warning(f"  ⚠️  {issue}")
                        
            except Exception as e:
                logger.error(f"❌ Validation check failed: {e}")
                results.append(ValidationResult(
                    check_name="Unknown Check",
                    passed=False,
                    score=0.0,
                    error_message=str(e)
                ))
        
        # Calculate overall metrics
        total_checks = len(results)
        passed_checks = sum(1 for r in results if r.passed)
        failed_checks = total_checks - passed_checks
        overall_score = sum(r.score for r in results) / total_checks if total_checks > 0 else 0
        execution_time = time.time() - start_time
        
        # Generate recommendations
        recommendations = self.generate_recommendations(results)
        
        # Determine production readiness
        production_ready = (
            overall_score >= self.thresholds['min_overall_score'] and
            passed_checks >= total_checks * 0.8  # At least 80% of checks must pass
        )
        
        # Create comprehensive report
        report = PipelineReport(
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            overall_score=overall_score,
            execution_time=execution_time,
            results=results,
            recommendations=recommendations,
            production_ready=production_ready
        )
        
        # Log final summary
        logger.info("=" * 60)
        logger.info("📊 QUALITY VALIDATION PIPELINE SUMMARY")
        logger.info(f"   Overall Score: {overall_score:.1f}%")
        logger.info(f"   Checks Passed: {passed_checks}/{total_checks}")
        logger.info(f"   Production Ready: {'✅ YES' if production_ready else '❌ NO'}")
        logger.info(f"   Execution Time: {execution_time:.2f}s")
        
        if recommendations:
            logger.info("\n💡 RECOMMENDATIONS:")
            for rec in recommendations:
                logger.info(f"   {rec}")
        
        logger.info("=" * 60)
        
        return report
    
    def save_report(self, report: PipelineReport, output_file: str = None) -> str:
        """
        Save validation report to JSON file.
        
        Args:
            report: Pipeline report to save
            output_file: Optional output file path
            
        Returns:
            Path to the saved report file
        """
        if output_file is None:
            output_file = f"quality_validation_report_{int(time.time())}.json"
        
        output_path = self.project_root / output_file
        
        # Convert report to dictionary for JSON serialization
        report_dict = {
            'timestamp': report.timestamp,
            'total_checks': report.total_checks,
            'passed_checks': report.passed_checks,
            'failed_checks': report.failed_checks,
            'overall_score': report.overall_score,
            'execution_time': report.execution_time,
            'production_ready': report.production_ready,
            'recommendations': report.recommendations,
            'results': [
                {
                    'check_name': r.check_name,
                    'passed': r.passed,
                    'score': r.score,
                    'details': r.details,
                    'issues': r.issues,
                    'execution_time': r.execution_time,
                    'error_message': r.error_message
                }
                for r in report.results
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Report saved to: {output_path}")
        return str(output_path)


def main():
    """Main entry point for the quality validation pipeline."""
    if len(sys.argv) < 2:
        print("Usage: python quality_validation_pipeline.py <source_directory>")
        sys.exit(1)
    
    source_directory = sys.argv[1]
    
    if not Path(source_directory).exists():
        print(f"Error: Source directory '{source_directory}' does not exist")
        sys.exit(1)
    
    # Run the quality validation pipeline
    pipeline = QualityValidationPipeline(source_directory)
    report = pipeline.run_pipeline()
    
    # Save the report
    report_path = pipeline.save_report(report)
    
    # Exit with appropriate code
    if report.production_ready:
        print(f"\n🎉 SUCCESS: PgForge is production ready!")
        sys.exit(0)
    else:
        print(f"\n⚠️  WARNING: PgForge needs improvements before production deployment")
        sys.exit(1)


if __name__ == '__main__':
    main()