"""
Testing Framework Configuration System

Comprehensive configuration management for test generation, execution, and reporting.
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Annotated
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict, HttpUrl


class TestDataVariety(Enum):
    """Test data variety levels."""
    LOW = "low"        # Basic test data
    MEDIUM = "medium"  # Moderate variety with some edge cases
    HIGH = "high"      # High variety with comprehensive edge cases


class ReportingFormat(Enum):
    """Test reporting format options."""
    HTML = "html"
    XML = "xml"
    JSON = "json"
    CONSOLE = "console"
    DASHBOARD = "dashboard"


class TestGenerationConfig(BaseModel):
    """
    Comprehensive configuration for test generation and execution with full validation.
    
    This configuration class controls all aspects of test generation including
    which test types to generate, coverage targets, data generation strategies,
    execution parameters, and reporting options.
    """
    
    model_config = ConfigDict(
        extra='forbid',
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=True,
        arbitrary_types_allowed=True
    )
    
    # ========== Test Type Configuration ==========
    generate_unit_tests: bool = Field(
        default=True,
        description="Generate unit tests for models and individual components"
    )
    generate_integration_tests: bool = Field(
        default=True,
        description="Generate integration tests for API endpoints and services"
    )
    generate_e2e_tests: bool = Field(
        default=True,
        description="Generate end-to-end browser automation tests"
    )
    generate_performance_tests: bool = Field(
        default=True,
        description="Generate performance and load tests"
    )
    generate_security_tests: bool = Field(
        default=True,
        description="Generate security vulnerability tests"
    )
    generate_accessibility_tests: bool = Field(
        default=True,
        description="Generate accessibility compliance tests"
    )
    
    # Master-detail specific testing
    generate_master_detail_tests: bool = Field(
        default=True,
        description="Generate tests for master-detail form relationships"
    )
    generate_inline_formset_tests: bool = Field(
        default=True,
        description="Generate tests for inline formset functionality"
    )
    generate_relationship_tests: bool = Field(
        default=True,
        description="Generate tests for foreign key relationships"
    )
    
    # ========== Test Coverage Configuration ==========
    target_coverage_percentage: Annotated[int, Field(
        default=95,
        ge=0,
        le=100,
        description="Target test coverage percentage (0-100)"
    )]
    include_edge_cases: bool = Field(
        default=True,
        description="Include edge case scenarios in test generation"
    )
    include_error_scenarios: bool = Field(
        default=True,
        description="Include error handling scenarios in test generation"
    )
    include_boundary_tests: bool = Field(
        default=True,
        description="Include boundary value testing"
    )
    include_regression_tests: bool = Field(
        default=True,
        description="Include regression testing scenarios"
    )
    
    # Coverage enforcement
    enforce_coverage_threshold: bool = Field(
        default=True,
        description="Enforce coverage threshold during test execution"
    )
    fail_on_coverage_below_threshold: bool = Field(
        default=False,
        description="Fail test suite if coverage is below threshold"
    )
    
    # ========== Test Data Configuration ==========
    realistic_test_data: bool = Field(
        default=True,
        description="Generate realistic test data with proper patterns"
    )
    test_data_variety: TestDataVariety = Field(
        default=TestDataVariety.HIGH,
        description="Level of variety in generated test data"
    )
    preserve_referential_integrity: bool = Field(
        default=True,
        description="Maintain referential integrity in test data"
    )
    include_performance_datasets: bool = Field(
        default=True,
        description="Generate large datasets for performance testing"
    )
    
    # Data generation specifics
    generate_large_datasets: bool = Field(
        default=True,
        description="Generate large datasets for scalability testing"
    )
    max_test_records_per_table: Annotated[int, Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum number of test records per table (1-100000)"
    )]
    include_unicode_test_data: bool = Field(
        default=True,
        description="Include Unicode characters in test data"
    )
    include_special_characters: bool = Field(
        default=True,
        description="Include special characters in test data"
    )
    
    # ========== Test Execution Configuration ==========
    parallel_execution: bool = Field(
        default=True,
        description="Execute tests in parallel for faster execution"
    )
    max_test_workers: Annotated[int, Field(
        default=4,
        ge=1,
        le=32,
        description="Maximum number of parallel test workers (1-32)"
    )]
    test_timeout_seconds: Annotated[int, Field(
        default=300,
        ge=30,
        le=3600,
        description="Test execution timeout in seconds (30-3600)"
    )]
    retry_failed_tests: bool = Field(
        default=True,
        description="Retry failed tests to reduce flakiness"
    )
    max_retry_attempts: Annotated[int, Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of retry attempts for failed tests (0-10)"
    )]
    
    # Test isolation
    use_test_database: bool = Field(
        default=True,
        description="Use isolated test database for testing"
    )
    cleanup_test_data: bool = Field(
        default=True,
        description="Clean up test data after execution"
    )
    reset_database_between_tests: bool = Field(
        default=False,
        description="Reset database state between test runs"
    )
    
    # ========== Performance Testing Configuration ==========
    load_test_duration_seconds: Annotated[int, Field(
        default=60,
        ge=10,
        le=3600,
        description="Load test duration in seconds (10-3600)"
    )]
    max_concurrent_users: Annotated[int, Field(
        default=100,
        ge=1,
        le=10000,
        description="Maximum concurrent users for load testing (1-10000)"
    )]
    performance_threshold_response_time_ms: Annotated[int, Field(
        default=1000,
        ge=1,
        le=60000,
        description="Performance threshold for response time in milliseconds (1-60000)"
    )]
    performance_threshold_throughput_rps: Annotated[int, Field(
        default=10,
        ge=1,
        le=10000,
        description="Performance threshold for throughput in requests per second (1-10000)"
    )]
    
    # Stress testing
    enable_stress_testing: bool = Field(
        default=True,
        description="Enable stress testing scenarios"
    )
    stress_test_multiplier: Annotated[float, Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Multiplier for stress test load (1.0-10.0)"
    )]
    memory_leak_detection: bool = Field(
        default=True,
        description="Enable memory leak detection during performance tests"
    )
    
    # ========== Security Testing Configuration ==========
    security_test_owasp_top10: bool = Field(
        default=True,
        description="Test for OWASP Top 10 vulnerabilities"
    )
    test_sql_injection: bool = Field(
        default=True,
        description="Test for SQL injection vulnerabilities"
    )
    test_xss_vulnerabilities: bool = Field(
        default=True,
        description="Test for Cross-Site Scripting (XSS) vulnerabilities"
    )
    test_authentication_bypass: bool = Field(
        default=True,
        description="Test for authentication bypass vulnerabilities"
    )
    test_authorization_flaws: bool = Field(
        default=True,
        description="Test for authorization and access control flaws"
    )
    test_sensitive_data_exposure: bool = Field(
        default=True,
        description="Test for sensitive data exposure vulnerabilities"
    )
    
    # ========== E2E Testing Configuration ==========
    browser_types: List[str] = Field(
        default=['chromium', 'firefox'],
        min_length=1,
        description="List of browser types for E2E testing"
    )
    headless_browser: bool = Field(
        default=True,
        description="Run browsers in headless mode"
    )
    viewport_width: Annotated[int, Field(
        default=1280,
        ge=320,
        le=4096,
        description="Browser viewport width in pixels (320-4096)"
    )]
    viewport_height: Annotated[int, Field(
        default=720,
        ge=240,
        le=2160,
        description="Browser viewport height in pixels (240-2160)"
    )]
    
    # E2E test scenarios
    test_user_workflows: bool = Field(
        default=True,
        description="Test complete user workflow scenarios"
    )
    test_master_detail_workflows: bool = Field(
        default=True,
        description="Test master-detail form workflows"
    )
    test_relationship_navigation: bool = Field(
        default=True,
        description="Test navigation through related records"
    )
    test_form_validation: bool = Field(
        default=True,
        description="Test client-side and server-side form validation"
    )
    
    # ========== Reporting Configuration ==========
    generate_html_reports: bool = Field(
        default=True,
        description="Generate HTML test reports"
    )
    generate_junit_xml: bool = Field(
        default=True,
        description="Generate JUnit XML reports for CI/CD integration"
    )
    generate_coverage_reports: bool = Field(
        default=True,
        description="Generate code coverage reports"
    )
    generate_performance_reports: bool = Field(
        default=True,
        description="Generate performance test reports"
    )
    generate_security_reports: bool = Field(
        default=True,
        description="Generate security test reports"
    )
    
    # Report formats
    report_formats: List[ReportingFormat] = Field(
        default=[ReportingFormat.HTML, ReportingFormat.XML],
        min_length=1,
        description="List of report formats to generate"
    )
    
    # Report destinations
    report_output_dir: Annotated[str, Field(
        default="./test_reports",
        min_length=1,
        description="Directory for test report output"
    )]
    archive_reports: bool = Field(
        default=True,
        description="Archive old test reports"
    )
    max_archived_reports: Annotated[int, Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of archived reports to keep (1-100)"
    )]
    
    # ========== Integration Configuration ==========
    ci_cd_integration: bool = Field(
        default=True,
        description="Enable CI/CD integration features"
    )
    webhook_notifications: bool = Field(
        default=False,
        description="Enable webhook notifications for test results"
    )
    slack_integration: bool = Field(
        default=False,
        description="Enable Slack integration for notifications"
    )
    email_notifications: bool = Field(
        default=False,
        description="Enable email notifications for test results"
    )
    
    # CI/CD specific
    junit_xml_path: Annotated[str, Field(
        default="./test-results.xml",
        min_length=1,
        description="Path for JUnit XML output file"
    )]
    coverage_xml_path: Annotated[str, Field(
        default="./coverage.xml",
        min_length=1,
        description="Path for coverage XML output file"
    )]
    fail_ci_on_test_failure: bool = Field(
        default=True,
        description="Fail CI/CD pipeline on test failures"
    )
    fail_ci_on_coverage_below_threshold: bool = Field(
        default=False,
        description="Fail CI/CD pipeline if coverage is below threshold"
    )
    
    # ========== Advanced Configuration ==========
    # Future enhancements
    ai_powered_test_generation: bool = Field(
        default=False,
        description="Enable AI-powered test case generation"
    )
    visual_regression_testing: bool = Field(
        default=False,
        description="Enable visual regression testing"
    )
    chaos_engineering_tests: bool = Field(
        default=False,
        description="Enable chaos engineering tests"
    )
    api_contract_testing: bool = Field(
        default=False,
        description="Enable API contract testing"
    )
    
    # Custom extensions
    custom_test_generators: List[str] = Field(
        default=[],
        description="List of custom test generator module names"
    )
    custom_test_runners: List[str] = Field(
        default=[],
        description="List of custom test runner module names"
    )
    custom_reporters: List[str] = Field(
        default=[],
        description="List of custom reporter module names"
    )
    
    # ========== Environment Configuration ==========
    test_environment: str = Field(
        default="test",
        min_length=1,
        description="Test environment name"
    )
    test_database_uri: Optional[str] = Field(
        default=None,
        description="Test database connection URI"
    )
    test_redis_uri: Optional[str] = Field(
        default=None,
        description="Test Redis connection URI"
    )
    test_elasticsearch_uri: Optional[str] = Field(
        default=None,
        description="Test Elasticsearch connection URI"
    )
    
    # Environment cleanup
    cleanup_test_environment: bool = Field(
        default=True,
        description="Clean up test environment after execution"
    )
    preserve_failed_test_artifacts: bool = Field(
        default=True,
        description="Preserve artifacts from failed tests for debugging"
    )
    
    @field_validator('browser_types')
    @classmethod
    def validate_browser_types(cls, v):
        """Validate browser types."""
        valid_browsers = {'chromium', 'firefox', 'webkit', 'chrome', 'safari', 'edge'}
        for browser in v:
            if browser not in valid_browsers:
                raise ValueError(f"Invalid browser type '{browser}'. Valid types: {', '.join(valid_browsers)}")
        return v
    
    @field_validator('report_output_dir', 'junit_xml_path', 'coverage_xml_path')
    @classmethod
    def validate_file_paths(cls, v):
        """Validate file and directory paths."""
        if not v or v.strip() == "":
            raise ValueError("File path cannot be empty")
        
        # Check for dangerous paths
        dangerous_paths = {'/', '/usr', '/etc', '/var', '/home', '/root'}
        abs_path = os.path.abspath(v)
        
        if abs_path in dangerous_paths:
            raise ValueError(f"Cannot use system directory: {abs_path}")
        
        return v
    
    @model_validator(mode='after')
    def validate_configuration_consistency(self):
        """Validate configuration consistency across related settings."""
        
        # Coverage validation
        if self.fail_on_coverage_below_threshold and not self.enforce_coverage_threshold:
            raise ValueError("Cannot fail on coverage below threshold without enforcing coverage threshold")
        
        # CI/CD validation
        if self.fail_ci_on_coverage_below_threshold and not self.generate_coverage_reports:
            raise ValueError("Cannot fail CI on coverage without generating coverage reports")
        
        # Performance testing validation
        if self.generate_performance_tests:
            if self.max_concurrent_users > 1000 and self.test_timeout_seconds < 600:
                raise ValueError("High concurrent users require longer timeout (>=600s)")
        
        # Parallel execution validation
        if self.parallel_execution and self.max_test_workers > 16:
            # Warn about excessive parallelism
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"High worker count ({self.max_test_workers}) may cause resource contention")
        
        # E2E testing validation
        if self.generate_e2e_tests and not self.browser_types:
            raise ValueError("E2E tests enabled but no browser types specified")
        
        # Security testing validation
        if (self.test_sql_injection or self.test_xss_vulnerabilities) and not self.generate_security_tests:
            raise ValueError("Specific security tests enabled but general security testing disabled")
        
        return self
    
    def model_post_init(self, __context: Any) -> None:
        """Post-initialization setup."""
        # Set environment-specific defaults
        self._set_environment_defaults()
        
        # Create output directories
        self._ensure_output_directories()
    
    def _set_environment_defaults(self):
        """Set environment-specific defaults."""
        # CI environment detection
        if os.getenv('CI'):
            object.__setattr__(self, 'headless_browser', True)
            object.__setattr__(self, 'cleanup_test_data', True)
            object.__setattr__(self, 'ci_cd_integration', True)
        
        # Development environment
        if os.getenv('FLASK_ENV') == 'development':
            object.__setattr__(self, 'preserve_failed_test_artifacts', True)
            object.__setattr__(self, 'fail_on_coverage_below_threshold', False)
        
        # Production environment (for staging tests)
        if os.getenv('FLASK_ENV') == 'production':
            object.__setattr__(self, 'cleanup_test_environment', True)
            object.__setattr__(self, 'fail_ci_on_test_failure', True)
    
    def _ensure_output_directories(self):
        """Ensure output directories exist."""
        directories = [
            self.report_output_dir,
            os.path.dirname(self.junit_xml_path) if self.junit_xml_path and os.path.dirname(self.junit_xml_path) else None,
            os.path.dirname(self.coverage_xml_path) if self.coverage_xml_path and os.path.dirname(self.coverage_xml_path) else None
        ]
        
        for directory in directories:
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
    
    @classmethod
    def from_file(cls, config_file: str) -> 'TestGenerationConfig':
        """
        Load configuration from file with validation.
        
        Args:
            config_file: Path to configuration file (JSON, YAML, or TOML)
            
        Returns:
            TestGenerationConfig instance
        """
        import json
        
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        try:
            with open(config_file, 'r') as f:
                if config_file.endswith('.json'):
                    config_data = json.load(f)
                elif config_file.endswith(('.yml', '.yaml')):
                    import yaml
                    config_data = yaml.safe_load(f)
                elif config_file.endswith('.toml'):
                    import toml
                    config_data = toml.load(f)
                else:
                    raise ValueError(f"Unsupported configuration file format: {config_file}")
            
            return cls.model_validate(config_data)
            
        except Exception as e:
            raise ValueError(f"Error loading configuration from {config_file}: {str(e)}")
    
    @classmethod
    def for_ci_cd(cls) -> 'TestGenerationConfig':
        """
        Create CI/CD optimized configuration.
        
        Returns:
            TestGenerationConfig optimized for CI/CD environments
        """
        return cls(
            parallel_execution=True,
            headless_browser=True,
            cleanup_test_data=True,
            ci_cd_integration=True,
            fail_ci_on_test_failure=True,
            fail_ci_on_coverage_below_threshold=True,
            generate_junit_xml=True,
            generate_coverage_reports=True,
            max_test_workers=2,  # Conservative for CI
            test_timeout_seconds=600,  # Longer timeout for CI
            report_formats=[ReportingFormat.XML, ReportingFormat.CONSOLE]
        )
    
    @classmethod
    def for_development(cls) -> 'TestGenerationConfig':
        """
        Create development optimized configuration.
        
        Returns:
            TestGenerationConfig optimized for development environments
        """
        return cls(
            parallel_execution=True,
            headless_browser=False,  # Show browser for debugging
            cleanup_test_data=False,  # Preserve data for inspection
            preserve_failed_test_artifacts=True,
            fail_on_coverage_below_threshold=False,
            generate_html_reports=True,
            generate_performance_reports=False,  # Skip for speed
            generate_security_tests=False,  # Skip for speed
            max_test_workers=4,
            test_timeout_seconds=120,
            report_formats=[ReportingFormat.HTML, ReportingFormat.CONSOLE]
        )
    
    @classmethod
    def for_production_validation(cls) -> 'TestGenerationConfig':
        """
        Create production validation configuration.
        
        Returns:
            TestGenerationConfig for production environment validation
        """
        return cls(
            # Enable all test types for comprehensive validation
            generate_unit_tests=True,
            generate_integration_tests=True,
            generate_e2e_tests=True,
            generate_performance_tests=True,
            generate_security_tests=True,
            generate_accessibility_tests=True,
            
            # High coverage requirements
            target_coverage_percentage=98,
            enforce_coverage_threshold=True,
            fail_on_coverage_below_threshold=True,
            
            # Comprehensive data testing
            test_data_variety=TestDataVariety.HIGH,
            include_edge_cases=True,
            include_error_scenarios=True,
            
            # Production-safe execution
            parallel_execution=True,
            cleanup_test_data=True,
            cleanup_test_environment=True,
            use_test_database=True,
            
            # Comprehensive reporting
            generate_html_reports=True,
            generate_junit_xml=True,
            generate_coverage_reports=True,
            generate_performance_reports=True,
            generate_security_reports=True,
            report_formats=[ReportingFormat.HTML, ReportingFormat.XML, ReportingFormat.JSON]
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        result = self.model_dump()
        
        # Convert enums to values
        for key, value in result.items():
            if isinstance(value, Enum):
                result[key] = value.value
            elif isinstance(value, list) and value and isinstance(value[0], Enum):
                result[key] = [item.value for item in value]
        
        return result
    
    def save_to_file(self, config_file: str):
        """
        Save configuration to file with validation.
        
        Args:
            config_file: Path to save configuration file
        """
        import json
        
        try:
            config_dict = self.to_dict()
            
            with open(config_file, 'w') as f:
                if config_file.endswith('.json'):
                    json.dump(config_dict, f, indent=2, default=str)
                elif config_file.endswith(('.yml', '.yaml')):
                    import yaml
                    yaml.dump(config_dict, f, default_flow_style=False)
                elif config_file.endswith('.toml'):
                    import toml
                    toml.dump(config_dict, f)
                else:
                    raise ValueError(f"Unsupported configuration file format: {config_file}")
            
        except Exception as e:
            raise ValueError(f"Error saving configuration to {config_file}: {str(e)}")


# Predefined configuration templates
QUICK_TEST_CONFIG = TestGenerationConfig(
    generate_unit_tests=True,
    generate_integration_tests=False,
    generate_e2e_tests=False,
    generate_performance_tests=False,
    generate_security_tests=False,
    target_coverage_percentage=80,
    test_data_variety=TestDataVariety.LOW,
    parallel_execution=True,
    max_test_workers=2
)

COMPREHENSIVE_TEST_CONFIG = TestGenerationConfig(
    # All test types enabled
    generate_unit_tests=True,
    generate_integration_tests=True,
    generate_e2e_tests=True,
    generate_performance_tests=True,
    generate_security_tests=True,
    generate_accessibility_tests=True,
    generate_master_detail_tests=True,
    
    # High coverage and quality
    target_coverage_percentage=95,
    enforce_coverage_threshold=True,
    test_data_variety=TestDataVariety.HIGH,
    include_edge_cases=True,
    include_error_scenarios=True,
    
    # Full reporting
    generate_html_reports=True,
    generate_junit_xml=True,
    generate_coverage_reports=True,
    generate_performance_reports=True,
    generate_security_reports=True,
    report_formats=[ReportingFormat.HTML, ReportingFormat.XML, ReportingFormat.JSON]
)