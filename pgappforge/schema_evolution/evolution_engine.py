"""
Evolution Engine for Real-Time Schema Evolution System

This module provides the core orchestration engine for automatic code generation,
testing, and deployment in response to database schema changes.
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Callable, Set, Tuple, Annotated
from dataclasses import dataclass, asdict
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, HttpUrl, ConfigDict
from pathlib import Path
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading

from .schema_monitor import SchemaMonitor, SchemaChange, ChangeType
from ..cli.generators.database_inspector import EnhancedDatabaseInspector
from ..cli.generators.model_generator import EnhancedModelGenerator
from ..cli.generators.view_generator import BeautifulViewGenerator
from ..testing_framework.core.test_generator import TestGenerator
from ..testing_framework.runner.test_runner import TestRunner, TestRunConfiguration


class EvolutionPhase(Enum):
    """Evolution process phases."""
    DETECTION = "detection"
    ANALYSIS = "analysis"
    GENERATION = "generation"
    TESTING = "testing"
    VALIDATION = "validation"
    DEPLOYMENT = "deployment"


class EvolutionStatus(Enum):
    """Evolution process status."""
    IDLE = "idle"
    PROCESSING = "processing"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK = "rollback"


class EvolutionConfig(BaseModel):
    """Configuration for schema evolution engine with comprehensive validation."""
    
    model_config = ConfigDict(
        extra='forbid',
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=True
    )
    
    # Monitoring settings
    monitor_interval: Annotated[int, Field(
        default=30,
        ge=5,
        le=3600,
        description="Monitoring interval in seconds (5-3600)"
    )]
    
    auto_evolution: bool = Field(
        default=True,
        description="Enable automatic schema evolution"
    )
    
    require_approval: bool = Field(
        default=False,
        description="Require manual approval for changes"
    )

    # Code generation settings
    generate_models: bool = Field(
        default=True,
        description="Generate model classes from schema"
    )
    
    generate_views: bool = Field(
        default=True,
        description="Generate view classes from schema"
    )
    
    generate_api: bool = Field(
        default=True,
        description="Generate REST API endpoints"
    )
    
    generate_tests: bool = Field(
        default=True,
        description="Generate comprehensive test suites"
    )

    # Testing settings
    run_tests_before_deployment: bool = Field(
        default=True,
        description="Run full test suite before deploying changes"
    )
    
    test_timeout: Annotated[int, Field(
        default=300,
        ge=60,
        le=3600,
        description="Test execution timeout in seconds (60-3600)"
    )]
    
    min_test_coverage: Annotated[float, Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Minimum required test coverage percentage (0-100)"
    )]

    # Safety settings
    enable_rollback: bool = Field(
        default=True,
        description="Enable automatic rollback on failures"
    )
    
    max_concurrent_evolutions: Annotated[int, Field(
        default=1,
        ge=1,
        le=5,
        description="Maximum number of concurrent evolution processes (1-5)"
    )]
    
    backup_before_changes: bool = Field(
        default=True,
        description="Create backup before applying changes"
    )

    # Output settings
    output_directory: Annotated[str, Field(
        default="./generated",
        min_length=1,
        description="Directory for generated code"
    )]
    
    preserve_custom_code: bool = Field(
        default=True,
        description="Preserve custom code during regeneration"
    )
    
    code_style: Annotated[str, Field(
        default="pep8",
        description="Code formatting style"
    )]

    # Notification settings
    notify_on_changes: bool = Field(
        default=True,
        description="Send notifications when changes are detected"
    )
    
    notify_on_errors: bool = Field(
        default=True,
        description="Send notifications when errors occur"
    )
    
    webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="Webhook URL for notifications"
    )
    
    @field_validator('code_style')
    @classmethod
    def validate_code_style(cls, v):
        """Validate code style option."""
        valid_styles = {'pep8', 'black', 'google', 'numpy'}
        if v not in valid_styles:
            raise ValueError(f"Code style must be one of: {', '.join(valid_styles)}")
        return v
    
    @field_validator('output_directory')
    @classmethod
    def validate_output_directory(cls, v):
        """Validate output directory path."""
        import os
        
        # Ensure directory is relative or absolute path
        if not v or v.strip() == "":
            raise ValueError("Output directory cannot be empty")
        
        # Check for dangerous paths
        dangerous_paths = {'/', '/usr', '/etc', '/var', '/home', '/root'}
        abs_path = os.path.abspath(v)
        
        if abs_path in dangerous_paths:
            raise ValueError(f"Cannot use system directory as output: {abs_path}")
        
        return v
    
    @model_validator(mode='after')
    def validate_configuration_consistency(self):
        """Validate configuration consistency across related settings."""
        
        # If auto_evolution is disabled, approval should be required
        if not self.auto_evolution and not self.require_approval:
            logger.warning("Auto-evolution disabled but approval not required - manual intervention may be needed")
        
        # If tests are generated but not run, warn about potential issues
        if self.generate_tests and not self.run_tests_before_deployment:
            logger.warning("Tests are generated but not executed before deployment - consider enabling test execution")
        
        # If rollback is disabled and backup is also disabled, warn about risk
        if not self.enable_rollback and not self.backup_before_changes:
            logger.warning("Both rollback and backup are disabled - this increases risk of data loss")
        
        # If concurrent evolutions > 1, ensure adequate testing timeout
        if self.max_concurrent_evolutions > 1 and self.test_timeout < 180:
            logger.warning(f"Concurrent evolutions ({self.max_concurrent_evolutions}) with short timeout ({self.test_timeout}s) may cause failures")
        
        return self
    
    @classmethod
    def for_development(cls) -> 'EvolutionConfig':
        """Create development-optimized configuration."""
        return cls(
            monitor_interval=10,  # More frequent monitoring
            auto_evolution=True,
            require_approval=False,  # Fast iteration
            generate_tests=True,
            run_tests_before_deployment=True,
            test_timeout=120,  # Shorter timeout for dev
            min_test_coverage=70.0,  # Lower coverage for dev speed
            enable_rollback=True,
            max_concurrent_evolutions=1,  # Safe for development
            backup_before_changes=True,
            preserve_custom_code=True,
            notify_on_changes=False,  # Reduce noise
            notify_on_errors=True
        )
    
    @classmethod
    def for_production(cls) -> 'EvolutionConfig':
        """Create production-optimized configuration."""
        return cls(
            monitor_interval=60,  # Less frequent monitoring
            auto_evolution=False,  # Manual control in production
            require_approval=True,  # Safety first
            generate_tests=True,
            run_tests_before_deployment=True,
            test_timeout=600,  # Longer timeout for comprehensive testing
            min_test_coverage=95.0,  # High coverage requirement
            enable_rollback=True,
            max_concurrent_evolutions=1,  # Conservative approach
            backup_before_changes=True,
            preserve_custom_code=True,
            notify_on_changes=True,
            notify_on_errors=True
        )
    
    @classmethod
    def for_ci_cd(cls) -> 'EvolutionConfig':
        """Create CI/CD pipeline optimized configuration."""
        return cls(
            monitor_interval=30,
            auto_evolution=True,  # Automated pipeline
            require_approval=False,  # Automated approval via tests
            generate_tests=True,
            run_tests_before_deployment=True,
            test_timeout=300,
            min_test_coverage=85.0,  # Balanced coverage
            enable_rollback=True,
            max_concurrent_evolutions=2,  # Parallel processing
            backup_before_changes=True,
            preserve_custom_code=True,
            notify_on_changes=True,
            notify_on_errors=True
        )


@dataclass
class EvolutionTask:
    """Represents a single evolution task."""
    task_id: str
    changes: List[SchemaChange]
    phase: EvolutionPhase
    status: EvolutionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    generated_files: List[str] = None
    test_results: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.generated_files is None:
            self.generated_files = []


@dataclass
class CodeGenerationPipeline:
    """Configuration for code generation pipeline."""
    generators: List[str]
    output_paths: Dict[str, str]
    templates: Dict[str, str]
    post_generation_hooks: List[Callable]


class EvolutionEngine:
    """
    Core evolution engine for orchestrating automatic code generation and testing.

    Features:
    - Real-time schema change detection and response
    - Intelligent change analysis and impact assessment
    - Automatic code generation with multiple generators
    - Comprehensive testing before deployment
    - Rollback capabilities for failed evolutions
    - Concurrent processing with proper synchronization
    - Extensible pipeline architecture
    - Integration with CI/CD workflows
    """

    def __init__(self, database_url: str, config: EvolutionConfig):
        self.database_url = database_url
        self.config = config
        self.inspector = EnhancedDatabaseInspector(database_url)

        # Setup paths
        self.output_dir = Path(config.output_directory)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.output_dir / "evolution_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.schema_monitor = SchemaMonitor(database_url, {
            "monitor_interval": config.monitor_interval,
            "storage_path": str(self.data_dir / "schema_monitor")
        })

        # Setup generators
        self.model_generator = EnhancedModelGenerator(self.inspector)
        self.view_generator = BeautifulViewGenerator(self.inspector)

        # State management
        self._active_tasks: Dict[str, EvolutionTask] = {}
        self._task_lock = threading.Lock()
        self._is_running = False
        self._executor = ThreadPoolExecutor(max_workers=config.max_concurrent_evolutions)

        # Setup logging
        self.logger = self._setup_logger()

        # Setup change handlers
        self.schema_monitor.add_batch_change_handler(self._handle_schema_changes)

        # Load previous state
        self._load_state()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging for evolution engine."""
        logger = logging.getLogger("EvolutionEngine")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            # Also log to file
            file_handler = logging.FileHandler(self.data_dir / "evolution.log")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger

    def start_engine(self):
        """Start the evolution engine."""
        if self._is_running:
            self.logger.warning("Evolution engine is already running")
            return

        self.logger.info("Starting PgAppForge Evolution Engine")
        self._is_running = True

        # Start schema monitoring
        self.schema_monitor.start_monitoring()

        # Run initial check
        if self.config.auto_evolution:
            initial_changes = self.schema_monitor.force_check()
            if initial_changes:
                self.logger.info(f"Found {len(initial_changes)} changes on startup")
                self._handle_schema_changes(initial_changes)

        self.logger.info("Evolution engine started successfully")

    def stop_engine(self):
        """Stop the evolution engine."""
        if not self._is_running:
            return

        self.logger.info("Stopping evolution engine")
        self._is_running = False

        # Stop schema monitoring
        self.schema_monitor.stop_monitoring()

        # Wait for active tasks to complete
        self._wait_for_active_tasks()

        # Shutdown executor
        self._executor.shutdown(wait=True)

        # Save state
        self._save_state()

        self.logger.info("Evolution engine stopped")

    def force_evolution(self, changes: Optional[List[SchemaChange]] = None) -> EvolutionTask:
        """Force an evolution process manually."""
        if changes is None:
            changes = self.schema_monitor.force_check()

        if not changes:
            self.logger.info("No changes detected for forced evolution")
            return None

        self.logger.info(f"Starting forced evolution with {len(changes)} changes")
        return self._create_evolution_task(changes)

    def get_active_tasks(self) -> List[EvolutionTask]:
        """Get list of currently active evolution tasks."""
        with self._task_lock:
            return list(self._active_tasks.values())

    def get_task_status(self, task_id: str) -> Optional[EvolutionTask]:
        """Get status of a specific evolution task."""
        with self._task_lock:
            return self._active_tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running evolution task."""
        with self._task_lock:
            task = self._active_tasks.get(task_id)
            if task and task.status == EvolutionStatus.PROCESSING:
                task.status = EvolutionStatus.FAILED
                task.error_message = "Task cancelled by user"
                task.completed_at = datetime.now()
                self.logger.info(f"Cancelled evolution task {task_id}")
                return True
            return False

    def _handle_schema_changes(self, changes: List[SchemaChange]):
        """Handle detected schema changes."""
        if not self._is_running:
            return

        self.logger.info(f"Processing {len(changes)} schema changes")

        # Filter changes based on priority and configuration
        filtered_changes = self._filter_changes(changes)

        if not filtered_changes:
            self.logger.info("No changes require evolution after filtering")
            return

        # Check if we should proceed with auto-evolution
        if self.config.require_approval:
            self.logger.info("Evolution requires approval - task created but not started")
            task = self._create_evolution_task(filtered_changes, auto_start=False)
            self._notify_approval_required(task)
            return

        # Create and start evolution task
        task = self._create_evolution_task(filtered_changes)

    def _filter_changes(self, changes: List[SchemaChange]) -> List[SchemaChange]:
        """Filter changes based on configuration and business rules."""
        filtered = []

        for change in changes:
            # Skip low priority changes if configured
            if change.priority < 2 and not self.config.auto_evolution:
                continue

            # Skip certain change types based on configuration
            if change.change_type == ChangeType.INDEX_ADDED and not self.config.generate_models:
                continue

            # Include change
            filtered.append(change)

        return filtered

    def _create_evolution_task(self, changes: List[SchemaChange], auto_start: bool = True) -> EvolutionTask:
        """Create a new evolution task."""
        task_id = self._generate_task_id()

        task = EvolutionTask(
            task_id=task_id,
            changes=changes,
            phase=EvolutionPhase.DETECTION,
            status=EvolutionStatus.IDLE,
            created_at=datetime.now()
        )

        with self._task_lock:
            self._active_tasks[task_id] = task

        if auto_start:
            self._start_evolution_task(task)

        return task

    def _start_evolution_task(self, task: EvolutionTask):
        """Start executing an evolution task."""
        if not self._is_running:
            return

        self.logger.info(f"Starting evolution task {task.task_id}")

        task.status = EvolutionStatus.PROCESSING
        task.started_at = datetime.now()

        # Submit to executor
        future = self._executor.submit(self._execute_evolution_task, task)

        # Handle completion
        def task_completed(fut):
            try:
                fut.result()
            except Exception as e:
                self.logger.error(f"Evolution task {task.task_id} failed: {e}")
                task.status = EvolutionStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.now()

        future.add_done_callback(task_completed)

    def _execute_evolution_task(self, task: EvolutionTask):
        """Execute the complete evolution pipeline for a task."""
        try:
            self.logger.info(f"Executing evolution task {task.task_id}")

            # Phase 1: Analysis
            task.phase = EvolutionPhase.ANALYSIS
            self._analyze_changes(task)

            # Phase 2: Code Generation
            task.phase = EvolutionPhase.GENERATION
            self._generate_code(task)

            # Phase 3: Testing
            if self.config.run_tests_before_deployment:
                task.phase = EvolutionPhase.TESTING
                self._run_tests(task)

            # Phase 4: Validation
            task.phase = EvolutionPhase.VALIDATION
            self._validate_changes(task)

            # Phase 5: Deployment
            task.phase = EvolutionPhase.DEPLOYMENT
            self._deploy_changes(task)

            # Mark as completed
            task.status = EvolutionStatus.COMPLETED
            task.completed_at = datetime.now()

            self.logger.info(f"Evolution task {task.task_id} completed successfully")

            # Notify completion
            self._notify_completion(task)

        except Exception as e:
            self.logger.error(f"Evolution task {task.task_id} failed: {e}")
            task.status = EvolutionStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now()

            # Attempt rollback if enabled
            if self.config.enable_rollback:
                self._rollback_changes(task)

            # Notify error
            self._notify_error(task, e)

        finally:
            # Clean up task from active list
            with self._task_lock:
                if task.task_id in self._active_tasks:
                    del self._active_tasks[task.task_id]

    def _analyze_changes(self, task: EvolutionTask):
        """Analyze schema changes and determine impact."""
        self.logger.info(f"Analyzing changes for task {task.task_id}")

        # Categorize changes by type
        change_categories = {
            "structural": [],
            "data": [],
            "constraint": [],
            "index": []
        }

        for change in task.changes:
            if change.change_type in [ChangeType.TABLE_ADDED, ChangeType.TABLE_REMOVED,
                                    ChangeType.COLUMN_ADDED, ChangeType.COLUMN_REMOVED]:
                change_categories["structural"].append(change)
            elif change.change_type in [ChangeType.COLUMN_MODIFIED]:
                change_categories["data"].append(change)
            elif change.change_type in [ChangeType.FOREIGN_KEY_ADDED, ChangeType.FOREIGN_KEY_REMOVED,
                                      ChangeType.CONSTRAINT_ADDED, ChangeType.CONSTRAINT_REMOVED]:
                change_categories["constraint"].append(change)
            elif change.change_type in [ChangeType.INDEX_ADDED, ChangeType.INDEX_REMOVED]:
                change_categories["index"].append(change)

        # Store analysis results
        task.analysis_results = change_categories

        self.logger.info(f"Analysis completed: {sum(len(v) for v in change_categories.values())} changes categorized")

    def _generate_code(self, task: EvolutionTask):
        """Generate code based on schema changes."""
        self.logger.info(f"Generating code for task {task.task_id}")

        generated_files = []

        # Generate models if requested
        if self.config.generate_models:
            model_files = self._generate_models(task)
            generated_files.extend(model_files)

        # Generate views if requested
        if self.config.generate_views:
            view_files = self._generate_views(task)
            generated_files.extend(view_files)

        # Generate API if requested
        if self.config.generate_api:
            api_files = self._generate_api(task)
            generated_files.extend(api_files)

        # Generate tests if requested
        if self.config.generate_tests:
            test_files = self._generate_tests(task)
            generated_files.extend(test_files)

        task.generated_files = generated_files

        self.logger.info(f"Code generation completed: {len(generated_files)} files generated")

    def _generate_models(self, task: EvolutionTask) -> List[str]:
        """Generate model files based on changes."""
        model_files = []

        # Get affected tables
        affected_tables = set()
        for change in task.changes:
            affected_tables.add(change.table_name)

        # Generate models for affected tables
        for table_name in affected_tables:
            try:
                table_info = None
                for table in self.inspector.get_all_tables():
                    if table.name == table_name:
                        table_info = table
                        break

                if table_info:
                    # Generate model code
                    model_code = self.model_generator.generate_model_class(table_info)

                    # Write to file
                    model_file = self.output_dir / "models" / f"{table_name}_model.py"
                    model_file.parent.mkdir(parents=True, exist_ok=True)

                    with open(model_file, 'w') as f:
                        f.write(model_code)

                    model_files.append(str(model_file))

            except Exception as e:
                self.logger.error(f"Failed to generate model for {table_name}: {e}")

        return model_files

    def _generate_views(self, task: EvolutionTask) -> List[str]:
        """Generate view files based on changes."""
        view_files = []

        # Get affected tables
        affected_tables = set()
        for change in task.changes:
            affected_tables.add(change.table_name)

        # Generate views for affected tables
        for table_name in affected_tables:
            try:
                table_info = None
                for table in self.inspector.get_all_tables():
                    if table.name == table_name:
                        table_info = table
                        break

                if table_info:
                    # Generate different view types
                    view_types = [
                        ("list", self.view_generator.generate_list_view),
                        ("detail", self.view_generator.generate_detail_view),
                        ("edit", self.view_generator.generate_edit_view)
                    ]

                    for view_type, generator_method in view_types:
                        try:
                            view_code = generator_method(table_info)

                            # Write to file
                            view_file = self.output_dir / "views" / f"{table_name}_{view_type}_view.py"
                            view_file.parent.mkdir(parents=True, exist_ok=True)

                            with open(view_file, 'w') as f:
                                f.write(view_code)

                            view_files.append(str(view_file))

                        except Exception as e:
                            self.logger.error(f"Failed to generate {view_type} view for {table_name}: {e}")

            except Exception as e:
                self.logger.error(f"Failed to generate views for {table_name}: {e}")

        return view_files

    def _generate_api(self, task: EvolutionTask) -> List[str]:
        """Generate API files based on changes."""
        api_files = []

        try:
            # Get affected tables
            affected_tables = set()
            for change in task.changes:
                affected_tables.add(change.table_name)

            # Generate API for affected tables
            for table_name in affected_tables:
                try:
                    table_info = None
                    for table in self.inspector.get_all_tables():
                        if table.name == table_name:
                            table_info = table
                            break

                    if table_info:
                        # Generate REST API code
                        api_code = self._generate_rest_api_code(table_info)

                        # Write to file
                        api_file = self.output_dir / "api" / f"{table_name}_api.py"
                        api_file.parent.mkdir(parents=True, exist_ok=True)

                        with open(api_file, 'w') as f:
                            f.write(api_code)

                        api_files.append(str(api_file))

                        self.logger.info(f"Generated API for table: {table_name}")

                except Exception as e:
                    self.logger.error(f"Failed to generate API for {table_name}: {e}")

        except Exception as e:
            self.logger.error(f"API generation failed: {e}")

        return api_files

    def _generate_rest_api_code(self, table_info) -> str:
        """Generate REST API code for a table."""
        model_name = inflection.camelize(table_info.name)
        api_class_name = f"{model_name}Api"

        # Generate field list for serialization
        fields = []
        for column in table_info.columns:
            fields.append(f"'{column.name}'")

        fields_str = ", ".join(fields)

        api_code = f'''"""
REST API for {model_name} model.

This file was automatically generated by the PgAppForge Evolution Engine.
"""

from pgappforge import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.api import BaseApi, expose
from flask import request

from ..models import {model_name}


class {api_class_name}(ModelRestApi):
    """
    REST API for {model_name} model.

    Provides full CRUD operations with automatic serialization,
    filtering, sorting, and pagination.
    """

    datamodel = SQLAInterface({model_name})

    # API configuration
    resource_name = '{table_info.name}'
    allow_browser_login = True

    # Define serialization fields
    list_columns = [{fields_str}]
    show_columns = [{fields_str}]
    add_columns = [{', '.join([f"'{col.name}'" for col in table_info.columns if col.name != 'id' and not col.name.endswith('_at')])}]
    edit_columns = [{', '.join([f"'{col.name}'" for col in table_info.columns if col.name != 'id' and not col.name.endswith('_at')])}]

    # Define search and filter columns
    search_columns = [{', '.join([f"'{col.name}'" for col in table_info.columns if col.type.lower() in ['varchar', 'text', 'string']])}]

    # Define ordering
    order_columns = [{', '.join([f"'{col.name}'" for col in table_info.columns if col.name in ['id', 'name', 'created_at']])}]
    base_order = ('id', 'desc')

    # Security - require authentication
    decorators = [BaseApi.auth_required]

    # Custom endpoints
    @expose('/stats', methods=['GET'])
    def stats(self):
        """Get statistics for {model_name} records."""
        total_count = self.datamodel.get_count()

        result = {{
            'total_records': total_count,
            'model_name': '{model_name}',
            'table_name': '{table_info.name}',
            'api_version': '1.0'
        }}

        return self.response(200, **result)

    @expose('/search', methods=['POST'])
    def advanced_search(self):
        """Advanced search endpoint with custom filters."""
        try:
            search_data = request.get_json()

            if not search_data:
                return self.response_400("Search data required")

            # Build query with filters
            query = self.datamodel.get_query()

            # Apply custom search filters
            for field, value in search_data.items():
                if hasattr({model_name}, field):
                    column = getattr({model_name}, field)
                    if isinstance(value, str):
                        query = query.filter(column.ilike(f'%{{value}}%'))
                    else:
                        query = query.filter(column == value)

            # Execute query with pagination
            page = search_data.get('page', 1)
            page_size = min(search_data.get('page_size', 20), 100)  # Max 100 records

            results = query.paginate(
                page=page,
                per_page=page_size,
                error_out=False
            )

            return self.response(200, **{{
                'results': [self.datamodel.obj_to_dict(item) for item in results.items],
                'total': results.total,
                'pages': results.pages,
                'current_page': results.page
            }})

        except Exception as e:
            self.logger.error(f"Advanced search error: {{e}}")
            return self.response_500()

    def pre_add(self, item):
        """Pre-processing before adding new record."""
        # Add any custom logic here
        pass

    def post_add(self, item):
        """Post-processing after adding new record."""
        self.logger.info(f"New {{self.resource_name}} created: {{item.id}}")

    def pre_update(self, item):
        """Pre-processing before updating record."""
        # Add any custom logic here
        pass

    def post_update(self, item):
        """Post-processing after updating record."""
        self.logger.info(f"{{self.resource_name}} updated: {{item.id}}")

    def pre_delete(self, item):
        """Pre-processing before deleting record."""
        # Add any custom logic here - e.g., check dependencies
        pass

    def post_delete(self, item):
        """Post-processing after deleting record."""
        self.logger.info(f"{{self.resource_name}} deleted: {{item.id}}")
'''

        return api_code

    def _generate_tests(self, task: EvolutionTask) -> List[str]:
        """Generate test files based on changes."""
        test_files = []

        try:
            from ..testing_framework.core.config import TestGenerationConfig
            from ..testing_framework.core.test_generator import TestGenerator

            # Create test configuration
            test_config = TestGenerationConfig()

            # Create test generator
            test_generator = TestGenerator(test_config, self.inspector)

            # Generate tests for affected tables
            affected_tables = set()
            for change in task.changes:
                affected_tables.add(change.table_name)

            for table_name in affected_tables:
                try:
                    table_info = None
                    for table in self.inspector.get_all_tables():
                        if table.name == table_name:
                            table_info = table
                            break

                    if table_info:
                        # Generate test suite
                        test_suite = test_generator.generate_complete_test_suite(table_info)

                        # Write test files
                        test_dir = self.output_dir / "tests"
                        test_dir.mkdir(parents=True, exist_ok=True)

                        # Write different test types
                        test_types = [
                            ("unit", test_suite.unit_tests),
                            ("integration", test_suite.integration_tests),
                        ]

                        for test_type, test_code in test_types:
                            if test_code:
                                test_file = test_dir / f"test_{table_name}_{test_type}.py"
                                with open(test_file, 'w') as f:
                                    f.write(test_code)
                                test_files.append(str(test_file))

                except Exception as e:
                    self.logger.error(f"Failed to generate tests for {table_name}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to initialize test generation: {e}")

        return test_files

    def _run_tests(self, task: EvolutionTask):
        """Run tests to validate generated code."""
        self.logger.info(f"Running tests for task {task.task_id}")

        try:
            from ..testing_framework.runner.test_runner import TestRunner, TestRunConfiguration, TestType

            # Create test configuration
            test_config = TestRunConfiguration(
                test_types=[TestType.UNIT, TestType.INTEGRATION],
                parallel_execution=True,
                max_workers=2,
                timeout_seconds=self.config.test_timeout,
                coverage_enabled=True,
                fail_fast=True
            )

            # Create test runner
            test_runner = TestRunner(
                config=None,  # Would need proper test config
                test_directory=str(self.output_dir / "tests")
            )

            # Run tests
            results = test_runner.run_all_tests(test_config)

            # Check if tests passed
            total_failed = sum(suite.failed_tests + suite.error_tests for suite in results.values())
            total_tests = sum(suite.total_tests for suite in results.values())

            if total_failed > 0:
                raise Exception(f"{total_failed} out of {total_tests} tests failed")

            # Check coverage requirement
            avg_coverage = sum(suite.coverage_percentage for suite in results.values()) / len(results) if results else 0
            if avg_coverage < self.config.min_test_coverage:
                raise Exception(f"Test coverage {avg_coverage:.1f}% below minimum {self.config.min_test_coverage}%")

            task.test_results = {
                "total_tests": total_tests,
                "passed_tests": sum(suite.passed_tests for suite in results.values()),
                "failed_tests": total_failed,
                "coverage": avg_coverage,
                "status": "passed"
            }

            self.logger.info(f"All tests passed: {total_tests} tests, {avg_coverage:.1f}% coverage")

        except Exception as e:
            task.test_results = {
                "status": "failed",
                "error": str(e)
            }
            raise Exception(f"Test execution failed: {e}")

    def _validate_changes(self, task: EvolutionTask):
        """Validate the generated changes."""
        self.logger.info(f"Validating changes for task {task.task_id}")

        # Basic validation checks
        validation_errors = []

        # Check that all generated files exist and are valid
        for file_path in task.generated_files:
            if not Path(file_path).exists():
                validation_errors.append(f"Generated file not found: {file_path}")
                continue

            # Basic syntax validation for Python files
            if file_path.endswith('.py'):
                try:
                    with open(file_path, 'r') as f:
                        code = f.read()
                    compile(code, file_path, 'exec')
                except SyntaxError as e:
                    validation_errors.append(f"Syntax error in {file_path}: {e}")

        if validation_errors:
            raise Exception(f"Validation failed: {'; '.join(validation_errors)}")

        self.logger.info("Validation completed successfully")

    def _deploy_changes(self, task: EvolutionTask):
        """Deploy the validated changes."""
        self.logger.info(f"Deploying changes for task {task.task_id}")

        # For now, files are already written to output directory
        # In a full implementation, this would handle:
        # - Moving files to proper locations
        # - Updating imports and dependencies
        # - Restarting services if needed
        # - Database migrations if required

        self.logger.info("Deployment completed successfully")

    def _rollback_changes(self, task: EvolutionTask):
        """Rollback changes if evolution failed."""
        self.logger.info(f"Rolling back changes for task {task.task_id}")

        task.status = EvolutionStatus.ROLLBACK

        try:
            # Remove generated files
            for file_path in task.generated_files:
                file_obj = Path(file_path)
                if file_obj.exists():
                    file_obj.unlink()
                    self.logger.info(f"Removed generated file: {file_path}")

            self.logger.info("Rollback completed successfully")

        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")

    def _notify_completion(self, task: EvolutionTask):
        """Notify about successful completion."""
        if self.config.notify_on_changes:
            message = f"Evolution task {task.task_id} completed successfully"
            self._send_notification(message, task)

    def _notify_error(self, task: EvolutionTask, error: Exception):
        """Notify about errors."""
        if self.config.notify_on_errors:
            message = f"Evolution task {task.task_id} failed: {str(error)}"
            self._send_notification(message, task)

    def _notify_approval_required(self, task: EvolutionTask):
        """Notify that approval is required."""
        message = f"Evolution task {task.task_id} requires approval"
        self._send_notification(message, task)

    def _send_notification(self, message: str, task: EvolutionTask):
        """Send notification via configured channels."""
        self.logger.info(f"Notification: {message}")

        # Send webhook if configured
        if self.config.webhook_url:
            try:
                import requests

                payload = {
                    "message": message,
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "changes": len(task.changes),
                    "timestamp": datetime.now().isoformat()
                }

                requests.post(self.config.webhook_url, json=payload, timeout=10)

            except Exception as e:
                self.logger.error(f"Failed to send webhook notification: {e}")

    def _generate_task_id(self) -> str:
        """Generate unique task ID."""
        import uuid
        return f"evo_{int(time.time())}_{str(uuid.uuid4())[:8]}"

    def _wait_for_active_tasks(self):
        """Wait for all active tasks to complete."""
        while True:
            with self._task_lock:
                if not self._active_tasks:
                    break

            self.logger.info(f"Waiting for {len(self._active_tasks)} active tasks to complete")
            time.sleep(1)

    def _save_state(self):
        """Save engine state to disk."""
        state_file = self.data_dir / "engine_state.json"

        state_data = {
            "last_run": datetime.now().isoformat(),
            "config": asdict(self.config),
            "statistics": self.get_statistics()
        }

        with open(state_file, 'w') as f:
            json.dump(state_data, f, indent=2)

    def _load_state(self):
        """Load previous engine state."""
        state_file = self.data_dir / "engine_state.json"

        if not state_file.exists():
            return

        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)

            self.logger.info(f"Loaded previous state from {state_data.get('last_run')}")

        except Exception as e:
            self.logger.warning(f"Could not load previous state: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "is_running": self._is_running,
            "active_tasks": len(self._active_tasks),
            "config": asdict(self.config),
            "monitoring_stats": self.schema_monitor.get_statistics() if hasattr(self.schema_monitor, 'get_statistics') else {}
        }

    def __enter__(self):
        """Context manager entry."""
        self.start_engine()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop_engine()


# Utility functions
def create_default_evolution_config(**overrides) -> EvolutionConfig:
    """Create default evolution configuration with optional overrides."""
    config = EvolutionConfig()

    for key, value in overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)

    return config