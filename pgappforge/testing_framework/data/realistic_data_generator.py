"""
Realistic Test Data Generator

Generates realistic, coherent test data for PgForge applications.
Uses intelligent patterns, relationships, and domain knowledge to create
meaningful test datasets that preserve referential integrity.
"""

import logging
import random
import string
from datetime import datetime, timedelta, date
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
import json

logger = logging.getLogger(__name__)


class DataPatternType(Enum):
    """Types of data patterns for intelligent generation."""
    PERSONAL_NAME = "personal_name"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    COMPANY = "company"
    PRODUCT = "product"
    FINANCIAL = "financial"
    GEOGRAPHIC = "geographic"
    TEMPORAL = "temporal"
    TECHNICAL = "technical"
    GENERIC = "generic"


@dataclass
class DataPattern:
    """Pattern definition for data generation."""
    pattern_type: DataPatternType
    field_names: List[str]
    generators: List[str]
    relationships: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedDataset:
    """Container for generated test data."""
    table_name: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    relationships: Dict[str, List[int]] = field(default_factory=dict)
    total_records: int = 0
    
    def __post_init__(self):
        """Initialize computed fields."""
        self.total_records = len(self.records)


class RealisticDataGenerator:
    """
    Advanced test data generator that creates realistic, coherent datasets.
    
    Features:
    - Domain-aware data generation (names, emails, addresses, etc.)
    - Relationship preservation and referential integrity
    - Configurable data variety and edge cases
    - Temporal consistency for date/time fields
    - Geographic consistency for location data
    - Business logic awareness for domain-specific fields
    - Memory management and leak prevention
    """
    
    def __init__(self, config):
        """
        Initialize the realistic data generator.
        
        Args:
            config: Test generation configuration
        """
        self.config = config
        
        # Data pattern definitions
        self.patterns = self._initialize_data_patterns()
        
        # Sample data pools (optimize memory usage)
        self.data_pools = self._initialize_data_pools()
        
        # Relationship tracking with memory management
        self.generated_datasets: Dict[str, GeneratedDataset] = {}
        self.foreign_key_map: Dict[str, Dict[str, List[Any]]] = {}
        
        # Memory management
        self._memory_threshold_mb = 500  # Maximum memory usage in MB
        self._cleanup_interval = 10  # Cleanup every N table generations
        self._generation_count = 0
        
        # Generation state
        self.random_seed = random.randint(1, 10000)
        random.seed(self.random_seed)
        
        logger.info(f"RealisticDataGenerator initialized with seed {self.random_seed}")
        logger.info(f"Memory management enabled: threshold={self._memory_threshold_mb}MB")
    
    def _initialize_data_patterns(self) -> Dict[str, DataPattern]:
        """Initialize data generation patterns."""
        patterns = {}
        
        # Personal information patterns
        patterns['personal_name'] = DataPattern(
            pattern_type=DataPatternType.PERSONAL_NAME,
            field_names=['name', 'first_name', 'last_name', 'full_name', 'username'],
            generators=['generate_person_name', 'generate_username']
        )
        
        patterns['email'] = DataPattern(
            pattern_type=DataPatternType.EMAIL,
            field_names=['email', 'email_address', 'contact_email'],
            generators=['generate_email']
        )
        
        patterns['phone'] = DataPattern(
            pattern_type=DataPatternType.PHONE,
            field_names=['phone', 'phone_number', 'mobile', 'contact_number'],
            generators=['generate_phone_number']
        )
        
        patterns['address'] = DataPattern(
            pattern_type=DataPatternType.ADDRESS,
            field_names=['address', 'street', 'city', 'state', 'zip', 'postal_code', 'country'],
            generators=['generate_address_component']
        )
        
        # Business patterns
        patterns['company'] = DataPattern(
            pattern_type=DataPatternType.COMPANY,
            field_names=['company', 'company_name', 'organization', 'employer'],
            generators=['generate_company_name']
        )
        
        patterns['product'] = DataPattern(
            pattern_type=DataPatternType.PRODUCT,
            field_names=['product', 'product_name', 'item', 'title', 'name'],
            generators=['generate_product_name']
        )
        
        # Financial patterns
        patterns['financial'] = DataPattern(
            pattern_type=DataPatternType.FINANCIAL,
            field_names=['price', 'amount', 'cost', 'salary', 'fee', 'total', 'balance'],
            generators=['generate_financial_amount']
        )
        
        # Geographic patterns
        patterns['geographic'] = DataPattern(
            pattern_type=DataPatternType.GEOGRAPHIC,
            field_names=['latitude', 'longitude', 'coords', 'location'],
            generators=['generate_geographic_data']
        )
        
        # Temporal patterns
        patterns['temporal'] = DataPattern(
            pattern_type=DataPatternType.TEMPORAL,
            field_names=['date', 'time', 'created_at', 'updated_at', 'timestamp', 'due_date'],
            generators=['generate_temporal_data']
        )
        
        return patterns
    
    def _initialize_data_pools(self) -> Dict[str, List[str]]:
        """Initialize pools of realistic sample data with memory optimization."""
        # Use smaller, representative samples to reduce memory usage
        return {
            'first_names': [
                'James', 'Mary', 'John', 'Patricia', 'Robert', 'Jennifer', 'Michael', 'Linda',
                'William', 'Elizabeth', 'David', 'Barbara', 'Richard', 'Susan', 'Joseph', 'Jessica',
                'Thomas', 'Sarah', 'Christopher', 'Karen', 'Daniel', 'Nancy', 'Matthew', 'Lisa',
                'Anthony', 'Betty', 'Mark', 'Helen', 'Donald', 'Sandra', 'Steven', 'Donna'
            ],
            
            'last_names': [
                'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis',
                'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson',
                'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson',
                'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez', 'Lewis', 'Robinson', 'Walker'
            ],
            
            'company_names': [
                'TechCorp', 'Global Solutions', 'InnovateCo', 'DataSystems', 'CloudWorks',
                'NextGen Industries', 'Digital Dynamics', 'Smart Technologies', 'FutureTech',
                'Alpha Enterprises', 'Beta Corporation', 'Gamma Industries', 'Delta Systems',
                'Epsilon Solutions', 'Zeta Technologies', 'Eta Innovations', 'Theta Corp'
            ],
            
            'product_names': [
                'Pro Widget', 'Super Tool', 'Ultra Device', 'Smart Gadget', 'Premium Service',
                'Advanced System', 'Professional Suite', 'Enterprise Solution', 'Standard Kit',
                'Basic Package', 'Deluxe Edition', 'Premium Plus', 'Executive Bundle'
            ],
            
            'cities': [
                'New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia',
                'San Antonio', 'San Diego', 'Dallas', 'San Jose', 'Austin', 'Jacksonville',
                'Fort Worth', 'Columbus', 'Charlotte', 'San Francisco', 'Indianapolis', 'Seattle'
            ],
            
            'states': [
                'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado',
                'Connecticut', 'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho',
                'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana'
            ],
            
            'countries': [
                'United States', 'Canada', 'United Kingdom', 'Germany', 'France',
                'Italy', 'Spain', 'Australia', 'Japan', 'China', 'Brazil', 'India'
            ],
            
            'street_types': [
                'Street', 'Avenue', 'Boulevard', 'Drive', 'Lane', 'Road', 'Circle',
                'Court', 'Place', 'Way', 'Trail', 'Path', 'Parkway', 'Highway'
            ],
            
            'domains': [
                'example.com', 'test.org', 'sample.net', 'demo.com', 'trial.org',
                'mock.net', 'placeholder.com', 'dummy.org', 'testing.net'
            ]
        }
    
    def generate_comprehensive_test_data(self, schema) -> Dict[str, Any]:
        """
        Generate comprehensive test data for all tables in schema.
        
        Args:
            schema: Database schema information
            
        Returns:
            Dictionary containing generated data and fixtures
        """
        logger.info("Generating comprehensive test data for schema")
        
        # Monitor memory usage at start
        start_memory = self._get_memory_usage_mb()
        logger.info(f"Starting memory usage: {start_memory:.2f}MB")
        
        try:
            # Get tables and analyze dependencies
            tables = self._get_tables_from_schema(schema)
            dependency_order = self._analyze_table_dependencies(tables)
            
            # Generate data in dependency order
            all_data = {}
            fixtures = {}
            
            for table_info in dependency_order:
                logger.debug(f"Generating data for table: {table_info.name}")
                
                # Check memory before generating each table
                current_memory = self._get_memory_usage_mb()
                if current_memory > self._memory_threshold_mb:
                    logger.warning(f"Memory usage ({current_memory:.2f}MB) exceeds threshold ({self._memory_threshold_mb}MB)")
                    self._perform_memory_cleanup()
                
                # Determine record count based on table characteristics
                record_count = self._determine_record_count(table_info)
                
                # Generate dataset
                dataset = self.generate_table_data(table_info, record_count)
                
                # Store generated data (with memory management)
                all_data[table_info.name] = dataset.records
                self.generated_datasets[table_info.name] = dataset
                
                # Create fixtures for this table
                fixtures[table_info.name] = self._create_fixtures_for_table(table_info, dataset)
                
                # Periodic cleanup
                self._generation_count += 1
                if self._generation_count % self._cleanup_interval == 0:
                    self._perform_periodic_cleanup()
            
            # Final memory check
            end_memory = self._get_memory_usage_mb()
            logger.info(f"Generated test data for {len(all_data)} tables")
            logger.info(f"Final memory usage: {end_memory:.2f}MB (delta: +{end_memory - start_memory:.2f}MB)")
            
            return {
                'data': all_data,
                'fixtures': fixtures,
                'metadata': {
                    'generation_seed': self.random_seed,
                    'total_tables': len(all_data),
                    'total_records': sum(len(records) for records in all_data.values()),
                    'generated_at': datetime.now().isoformat(),
                    'memory_usage_mb': end_memory,
                    'config': {
                        'data_variety': self.config.test_data_variety.value,
                        'preserve_integrity': self.config.preserve_referential_integrity,
                        'realistic_data': self.config.realistic_test_data
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"Test data generation failed: {str(e)}")
            # Clean up on error
            self.cleanup_all_data()
            raise
    
    def generate_table_data(self, table_info, record_count: int) -> GeneratedDataset:
        """
        Generate realistic data for a specific table.
        
        Args:
            table_info: Table information
            record_count: Number of records to generate
            
        Returns:
            GeneratedDataset with generated records
        """
        records = []
        table_name = table_info.name
        columns = getattr(table_info, 'columns', [])
        
        # Analyze column patterns
        column_patterns = self._analyze_column_patterns(columns)
        
        # Generate records in batches to manage memory
        batch_size = min(100, record_count)  # Process in batches
        
        for batch_start in range(0, record_count, batch_size):
            batch_end = min(batch_start + batch_size, record_count)
            batch_records = []
            
            for i in range(batch_start, batch_end):
                record = self._generate_single_record(table_info, column_patterns, i)
                batch_records.append(record)
            
            records.extend(batch_records)
            
            # Clear batch from memory
            del batch_records
        
        # Apply variety and edge cases
        if self.config.include_edge_cases:
            edge_case_records = self._generate_edge_case_records(table_info, column_patterns)
            records.extend(edge_case_records)
        
        return GeneratedDataset(
            table_name=table_name,
            records=records,
            metadata={
                'column_patterns': {col: pattern.pattern_type.value for col, pattern in column_patterns.items()},
                'record_count': len(records),
                'generation_strategy': 'realistic_patterns'
            }
        )
    
    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            # Fallback: estimate based on data structures
            return self._estimate_memory_usage()
    
    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage based on stored data structures."""
        import sys
        
        total_size = 0
        
        # Estimate size of generated datasets
        for dataset in self.generated_datasets.values():
            total_size += sys.getsizeof(dataset.records)
            total_size += sum(sys.getsizeof(record) for record in dataset.records[:10])  # Sample
        
        # Estimate size of foreign key map
        total_size += sys.getsizeof(self.foreign_key_map)
        
        # Estimate size of data pools
        total_size += sys.getsizeof(self.data_pools)
        
        return total_size / 1024 / 1024  # Convert to MB
    
    def _perform_memory_cleanup(self):
        """Perform aggressive memory cleanup."""
        logger.info("Performing memory cleanup due to high usage")
        
        # Clear old datasets (keep only recent ones for foreign key references)
        if len(self.generated_datasets) > 5:
            # Keep only the 5 most recently generated datasets
            dataset_items = list(self.generated_datasets.items())
            datasets_to_remove = dataset_items[:-5]
            
            for table_name, dataset in datasets_to_remove:
                logger.debug(f"Removing dataset for table {table_name} from memory")
                del self.generated_datasets[table_name]
                
                # Also clean up foreign key mappings
                if table_name in self.foreign_key_map:
                    del self.foreign_key_map[table_name]
        
        # Force garbage collection
        import gc
        collected = gc.collect()
        logger.info(f"Garbage collection freed {collected} objects")
    
    def _perform_periodic_cleanup(self):
        """Perform periodic cleanup to prevent memory accumulation."""
        logger.debug(f"Performing periodic cleanup (generation #{self._generation_count})")
        
        # Clear unused foreign key mappings
        active_tables = set(self.generated_datasets.keys())
        fk_tables = set(self.foreign_key_map.keys())
        unused_fk_tables = fk_tables - active_tables
        
        for table_name in unused_fk_tables:
            del self.foreign_key_map[table_name]
        
        # Compact data structures
        for dataset in self.generated_datasets.values():
            if hasattr(dataset, 'records') and len(dataset.records) > 1000:
                # Keep only a sample of large datasets
                logger.debug(f"Compacting large dataset: {dataset.table_name}")
                dataset.records = dataset.records[:500]  # Keep first 500 records
    
    def cleanup_all_data(self):
        """Clean up all generated data to free memory."""
        logger.info("Cleaning up all generated test data")
        
        # Clear all data structures
        self.generated_datasets.clear()
        self.foreign_key_map.clear()
        
        # Reset generation counter
        self._generation_count = 0
        
        # Force garbage collection
        import gc
        collected = gc.collect()
        logger.info(f"Cleanup complete. Garbage collection freed {collected} objects")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get current memory usage statistics."""
        return {
            'current_memory_mb': self._get_memory_usage_mb(),
            'memory_threshold_mb': self._memory_threshold_mb,
            'datasets_count': len(self.generated_datasets),
            'fk_mappings_count': len(self.foreign_key_map),
            'generation_count': self._generation_count,
            'total_records': sum(len(dataset.records) for dataset in self.generated_datasets.values())
        }
    
    def __del__(self):
        """Cleanup when object is destroyed."""
        try:
            self.cleanup_all_data()
        except Exception:
            pass  # Ignore cleanup errors during destruction
    
    # ... [Rest of the methods remain unchanged - continuing with original implementations]
    
    def _get_tables_from_schema(self, schema) -> List[Any]:
        """Extract table information from schema."""
        tables = []
        
        if hasattr(schema, 'tables'):
            tables = schema.tables
        elif hasattr(schema, 'get_all_tables') and hasattr(schema, 'analyze_table'):
            # Use inspector interface
            table_names = schema.get_all_tables()
            for table_name in table_names:
                table_info = schema.analyze_table(table_name)
                tables.append(table_info)
        
        return tables
    
    def _analyze_table_dependencies(self, tables: List[Any]) -> List[Any]:
        """
        Analyze foreign key dependencies and return tables in dependency order.
        
        Args:
            tables: List of table information objects
            
        Returns:
            List of tables ordered by dependencies (parents first)
        """
        # Build dependency graph
        dependencies = {}
        table_map = {table.name: table for table in tables}
        
        for table in tables:
            deps = set()
            columns = getattr(table, 'columns', [])
            
            for column in columns:
                if hasattr(column, 'foreign_key') and column.foreign_key:
                    # Extract referenced table name
                    if hasattr(column, 'foreign_key_table'):
                        deps.add(column.foreign_key_table)
                    elif hasattr(column, 'foreign_keys') and column.foreign_keys:
                        for fk in column.foreign_keys:
                            if hasattr(fk, 'column') and hasattr(fk.column, 'table'):
                                deps.add(fk.column.table.name)
            
            dependencies[table.name] = deps
        
        # Topological sort
        ordered = []
        visited = set()
        visiting = set()
        
        def visit(table_name):
            if table_name in visiting:
                # Circular dependency detected, add to end
                return
            if table_name in visited:
                return
            
            visiting.add(table_name)
            
            for dep in dependencies.get(table_name, []):
                if dep in table_map:  # Only process if we have this table
                    visit(dep)
            
            visiting.remove(table_name)
            visited.add(table_name)
            
            if table_name in table_map:
                ordered.append(table_map[table_name])
        
        for table in tables:
            visit(table.name)
        
        return ordered
    
    def _determine_record_count(self, table_info) -> int:
        """Determine appropriate record count for a table."""
        base_count = {
            'high': 50,
            'medium': 20,
            'low': 5
        }
        
        count = base_count.get(self.config.test_data_variety.value, 20)
        
        # Adjust based on table characteristics
        table_name_lower = table_info.name.lower()
        
        # Lookup/reference tables get fewer records
        if any(word in table_name_lower for word in ['type', 'status', 'category', 'lookup']):
            count = max(5, count // 4)
        
        # Association tables get more records
        elif getattr(table_info, 'is_association_table', False):
            count = count * 2
        
        # Main entity tables
        elif any(word in table_name_lower for word in ['user', 'customer', 'product', 'order']):
            count = count
        
        return min(count, self.config.max_test_records_per_table)
    
    def _analyze_column_patterns(self, columns) -> Dict[str, DataPattern]:
        """Analyze columns to identify data generation patterns."""
        column_patterns = {}
        
        for column in columns:
            if column.primary_key:
                continue  # Skip primary keys, they're auto-generated
            
            pattern = self._identify_column_pattern(column)
            column_patterns[column.name] = pattern
        
        return column_patterns
    
    def _identify_column_pattern(self, column) -> DataPattern:
        """Identify the appropriate data pattern for a column."""
        column_name_lower = column.name.lower()
        
        # Check each pattern for field name matches
        for pattern in self.patterns.values():
            if any(field_name in column_name_lower for field_name in pattern.field_names):
                return pattern
        
        # Default to generic pattern
        return DataPattern(
            pattern_type=DataPatternType.GENERIC,
            field_names=[column.name],
            generators=['generate_generic_value']
        )
    
    def _generate_single_record(self, table_info, column_patterns: Dict[str, DataPattern], 
                               record_index: int) -> Dict[str, Any]:
        """Generate a single realistic record."""
        record = {}
        columns = getattr(table_info, 'columns', [])
        
        # Generate values for each column
        for column in columns:
            if column.primary_key:
                continue  # Skip primary keys
            
            column_name = column.name
            pattern = column_patterns.get(column_name)
            
            if pattern:
                value = self._generate_value_for_pattern(column, pattern, record_index)
            else:
                value = self._generate_fallback_value(column, record_index)
            
            record[column_name] = value
        
        # Handle foreign keys with referential integrity
        if self.config.preserve_referential_integrity:
            record = self._apply_foreign_key_constraints(table_info, record)
        
        return record
    
    def _generate_value_for_pattern(self, column, pattern: DataPattern, record_index: int) -> Any:
        """Generate value based on identified pattern."""
        pattern_type = pattern.pattern_type
        
        if pattern_type == DataPatternType.PERSONAL_NAME:
            return self._generate_person_name(column, record_index)
        elif pattern_type == DataPatternType.EMAIL:
            return self._generate_email(column, record_index)
        elif pattern_type == DataPatternType.PHONE:
            return self._generate_phone_number(column, record_index)
        elif pattern_type == DataPatternType.ADDRESS:
            return self._generate_address_component(column, record_index)
        elif pattern_type == DataPatternType.COMPANY:
            return self._generate_company_name(column, record_index)
        elif pattern_type == DataPatternType.PRODUCT:
            return self._generate_product_name(column, record_index)
        elif pattern_type == DataPatternType.FINANCIAL:
            return self._generate_financial_amount(column, record_index)
        elif pattern_type == DataPatternType.GEOGRAPHIC:
            return self._generate_geographic_data(column, record_index)
        elif pattern_type == DataPatternType.TEMPORAL:
            return self._generate_temporal_data(column, record_index)
        else:
            return self._generate_generic_value(column, record_index)
    
    def _generate_person_name(self, column, record_index: int) -> str:
        """Generate realistic person names."""
        column_name_lower = column.name.lower()
        
        if 'first' in column_name_lower:
            return random.choice(self.data_pools['first_names'])
        elif 'last' in column_name_lower:
            return random.choice(self.data_pools['last_names'])
        elif 'username' in column_name_lower:
            first = random.choice(self.data_pools['first_names']).lower()
            last = random.choice(self.data_pools['last_names']).lower()
            return f"{first}.{last}{random.randint(1, 999)}"
        else:  # full name
            first = random.choice(self.data_pools['first_names'])
            last = random.choice(self.data_pools['last_names'])
            return f"{first} {last}"
    
    def _generate_email(self, column, record_index: int) -> str:
        """Generate realistic email addresses."""
        first = random.choice(self.data_pools['first_names']).lower()
        last = random.choice(self.data_pools['last_names']).lower()
        domain = random.choice(self.data_pools['domains'])
        
        separators = ['.', '_', '']
        separator = random.choice(separators)
        
        return f"{first}{separator}{last}{random.randint(1, 999)}@{domain}"
    
    def _generate_phone_number(self, column, record_index: int) -> str:
        """Generate realistic phone numbers."""
        formats = [
            lambda: f"({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}",
            lambda: f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}",
            lambda: f"{random.randint(200, 999)}.{random.randint(200, 999)}.{random.randint(1000, 9999)}",
            lambda: f"{random.randint(200, 999)}{random.randint(200, 999)}{random.randint(1000, 9999)}"
        ]
        
        return random.choice(formats)()
    
    def _generate_address_component(self, column, record_index: int) -> str:
        """Generate realistic address components."""
        column_name_lower = column.name.lower()
        
        if 'street' in column_name_lower or 'address' in column_name_lower:
            number = random.randint(1, 9999)
            street_name = random.choice(self.data_pools['last_names'])  # Use last names as street names
            street_type = random.choice(self.data_pools['street_types'])
            return f"{number} {street_name} {street_type}"
        elif 'city' in column_name_lower:
            return random.choice(self.data_pools['cities'])
        elif 'state' in column_name_lower:
            return random.choice(self.data_pools['states'])
        elif 'zip' in column_name_lower or 'postal' in column_name_lower:
            return f"{random.randint(10000, 99999)}"
        elif 'country' in column_name_lower:
            return random.choice(self.data_pools['countries'])
        else:
            return f"{random.randint(1, 999)} Main Street"
    
    def _generate_company_name(self, column, record_index: int) -> str:
        """Generate realistic company names."""
        return random.choice(self.data_pools['company_names'])
    
    def _generate_product_name(self, column, record_index: int) -> str:
        """Generate realistic product names."""
        base_name = random.choice(self.data_pools['product_names'])
        
        # Add version or variant sometimes
        if random.random() < 0.3:
            variants = ['v2.0', 'Pro', 'Lite', 'Plus', 'Max', 'Mini']
            base_name += f" {random.choice(variants)}"
        
        return base_name
    
    def _generate_financial_amount(self, column, record_index: int) -> float:
        """Generate realistic financial amounts."""
        column_name_lower = column.name.lower()
        
        if 'salary' in column_name_lower:
            return round(random.uniform(30000, 150000), 2)
        elif 'price' in column_name_lower or 'cost' in column_name_lower:
            return round(random.uniform(9.99, 999.99), 2)
        elif 'fee' in column_name_lower:
            return round(random.uniform(5.0, 50.0), 2)
        elif 'balance' in column_name_lower:
            return round(random.uniform(-1000.0, 10000.0), 2)
        else:
            return round(random.uniform(1.0, 1000.0), 2)
    
    def _generate_geographic_data(self, column, record_index: int) -> float:
        """Generate realistic geographic coordinates."""
        column_name_lower = column.name.lower()
        
        if 'latitude' in column_name_lower:
            return round(random.uniform(-90.0, 90.0), 6)
        elif 'longitude' in column_name_lower:
            return round(random.uniform(-180.0, 180.0), 6)
        else:
            # Default to coordinates within continental US
            return round(random.uniform(25.0, 49.0), 6)
    
    def _generate_temporal_data(self, column, record_index: int) -> datetime:
        """Generate realistic temporal data."""
        column_name_lower = column.name.lower()
        
        if 'created' in column_name_lower:
            # Created dates in the past year
            days_ago = random.randint(1, 365)
            return datetime.now() - timedelta(days=days_ago)
        elif 'updated' in column_name_lower:
            # Updated dates more recent than created
            days_ago = random.randint(1, 90)
            return datetime.now() - timedelta(days=days_ago)
        elif 'due' in column_name_lower:
            # Due dates in the future
            days_ahead = random.randint(1, 180)
            return datetime.now() + timedelta(days=days_ahead)
        else:
            # Random date within past 2 years
            days_ago = random.randint(1, 730)
            return datetime.now() - timedelta(days=days_ago)
    
    def _generate_generic_value(self, column, record_index: int) -> Any:
        """Generate generic value based on column type."""
        if hasattr(column, 'type'):
            column_type = str(column.type).lower()
            
            if 'string' in column_type or 'text' in column_type or 'varchar' in column_type:
                return f"test_{column.name}_{record_index}"
            elif 'int' in column_type:
                return random.randint(1, 1000)
            elif 'float' in column_type or 'numeric' in column_type or 'decimal' in column_type:
                return round(random.uniform(1.0, 1000.0), 2)
            elif 'bool' in column_type:
                return random.choice([True, False])
            elif 'date' in column_type:
                return date.today() - timedelta(days=random.randint(1, 365))
            elif 'time' in column_type:
                return datetime.now() - timedelta(days=random.randint(1, 365))
            elif 'json' in column_type:
                return {"key": f"value_{record_index}", "data": random.randint(1, 100)}
        
        # Fallback
        return f"test_value_{record_index}"
    
    def _generate_fallback_value(self, column, record_index: int) -> Any:
        """Generate fallback value when no pattern is identified."""
        return self._generate_generic_value(column, record_index)
    
    def _apply_foreign_key_constraints(self, table_info, record: Dict[str, Any]) -> Dict[str, Any]:
        """Apply foreign key constraints to maintain referential integrity."""
        columns = getattr(table_info, 'columns', [])
        
        for column in columns:
            if hasattr(column, 'foreign_key') and column.foreign_key:
                # Find referenced table and get available IDs
                referenced_table = self._get_referenced_table_name(column)
                
                if referenced_table and referenced_table in self.generated_datasets:
                    # Get available primary key values from referenced table
                    referenced_dataset = self.generated_datasets[referenced_table]
                    available_ids = []
                    
                    for ref_record in referenced_dataset.records:
                        # Assume primary key is 'id' or similar
                        pk_value = ref_record.get('id', 1)
                        available_ids.append(pk_value)
                    
                    if available_ids:
                        record[column.name] = random.choice(available_ids)
                    else:
                        record[column.name] = 1  # Default fallback
        
        return record
    
    def _get_referenced_table_name(self, column) -> Optional[str]:
        """Extract referenced table name from foreign key column."""
        # This is a simplified implementation
        # In practice, this would extract the table name from the foreign key constraint
        if hasattr(column, 'foreign_key_table'):
            return column.foreign_key_table
        
        # Try to infer from column name (common convention)
        column_name = column.name.lower()
        if column_name.endswith('_id'):
            return column_name[:-3] + 's'  # user_id -> users
        
        return None
    
    def _generate_edge_case_records(self, table_info, column_patterns: Dict[str, DataPattern]) -> List[Dict[str, Any]]:
        """Generate edge case records for boundary testing."""
        edge_cases = []
        columns = getattr(table_info, 'columns', [])
        
        # Generate records with edge case values
        for edge_type in ['min_values', 'max_values', 'empty_values', 'special_chars']:
            record = {}
            
            for column in columns:
                if column.primary_key:
                    continue
                
                value = self._generate_edge_case_value(column, edge_type)
                record[column.name] = value
            
            edge_cases.append(record)
        
        return edge_cases
    
    def _generate_edge_case_value(self, column, edge_type: str) -> Any:
        """Generate edge case value for a column."""
        if hasattr(column, 'type'):
            column_type = str(column.type).lower()
            
            if edge_type == 'min_values':
                if 'string' in column_type or 'text' in column_type:
                    return ""  # Empty string
                elif 'int' in column_type:
                    return 0
                elif 'float' in column_type or 'numeric' in column_type:
                    return 0.0
                elif 'bool' in column_type:
                    return False
            
            elif edge_type == 'max_values':
                if 'string' in column_type or 'text' in column_type:
                    # Generate long string
                    max_length = getattr(column.type, 'length', 255) if hasattr(column, 'type') else 255
                    return 'x' * min(max_length, 1000)
                elif 'int' in column_type:
                    return 2147483647  # Max int32
                elif 'float' in column_type or 'numeric' in column_type:
                    return 999999.99
                elif 'bool' in column_type:
                    return True
            
            elif edge_type == 'empty_values':
                if column.nullable or getattr(column, 'nullable', True):
                    return None
                else:
                    return self._generate_generic_value(column, 0)
            
            elif edge_type == 'special_chars':
                if 'string' in column_type or 'text' in column_type:
                    return "Special chars: àáâãäåæçèéêë!@#$%^&*()[]{}|;':\",./<>?"
                else:
                    return self._generate_generic_value(column, 0)
        
        return self._generate_generic_value(column, 0)
    
    def _create_fixtures_for_table(self, table_info, dataset: GeneratedDataset) -> Dict[str, Any]:
        """Create pytest fixtures for a table's test data."""
        fixture_code = f'''
@pytest.fixture
def {table_info.name}_test_data():
    """Test data fixture for {table_info.name} table."""
    return {json.dumps(dataset.records[:5], indent=2, default=str)}

@pytest.fixture
def sample_{table_info.name}():
    """Single sample record for {table_info.name} table."""
    return {json.dumps(dataset.records[0] if dataset.records else {}, indent=2, default=str)}

@pytest.fixture
def {table_info.name}_factory():
    """Factory function for creating {table_info.name} test records."""
    def _create_record(**overrides):
        base_data = {json.dumps(dataset.records[0] if dataset.records else {}, default=str)}
        base_data.update(overrides)
        return base_data
    return _create_record
'''
        
        return {
            'fixture_code': fixture_code,
            'sample_records': dataset.records[:5],
            'total_records': len(dataset.records)
        }