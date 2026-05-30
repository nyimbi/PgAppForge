"""
Data Pattern Analyzer

Analyzes existing data to learn patterns, distributions, relationships, and constraints
that can be used to generate more realistic synthetic data.
"""

import logging
import json
import re
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
import statistics
import math

logger = logging.getLogger(__name__)


@dataclass
class FieldAnalysis:
    """Analysis results for a single field."""
    field_name: str
    data_type: str
    distinct_count: int
    null_count: int
    null_percentage: float
    
    # Numeric analysis
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std_dev: Optional[float] = None
    
    # String analysis
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    avg_length: Optional[float] = None
    common_patterns: List[str] = None
    
    # Categorical analysis
    value_distribution: Dict[Any, int] = None
    top_values: List[Tuple[Any, int]] = None
    
    # Temporal analysis
    date_range: Optional[Tuple[datetime, datetime]] = None
    temporal_patterns: Dict[str, Any] = None


@dataclass
class DatasetAnalysis:
    """Analysis results for entire dataset."""
    total_records: int
    total_fields: int
    field_analyses: Dict[str, FieldAnalysis]
    relationships: List[Dict[str, Any]]
    data_quality_score: float
    detected_patterns: List[Dict[str, Any]]
    suggested_constraints: List[Dict[str, Any]]


class DataPatternAnalyzer:
    """
    Analyzes existing datasets to extract patterns for synthetic data generation.
    
    Capabilities:
    - Statistical analysis of numeric fields
    - Pattern detection in string fields
    - Relationship analysis between fields
    - Temporal pattern detection
    - Data quality assessment
    - Constraint inference
    """
    
    def __init__(self):
        self.pattern_cache: Dict[str, Any] = {}
        
        # Regex patterns for common data types
        self.common_patterns = {
            'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
            'phone_us': r'^\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})$',
            'ssn': r'^\d{3}-?\d{2}-?\d{4}$',
            'credit_card': r'^\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}$',
            'zip_code': r'^\d{5}(-\d{4})?$',
            'url': r'^https?://[^\s/$.?#].[^\s]*$',
            'ip_address': r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$',
            'uuid': r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            'date_iso': r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?',
            'currency': r'^\$?\d+(\.\d{2})?$'
        }
    
    def analyze_patterns(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze a dataset and extract patterns.
        
        Args:
            data: List of records to analyze
            
        Returns:
            Comprehensive analysis results
        """
        if not data:
            return {'error': 'No data provided'}
        
        logger.info(f"Analyzing {len(data)} records")
        
        # Basic dataset info
        total_records = len(data)
        field_names = set()
        for record in data:
            field_names.update(record.keys())
        field_names = list(field_names)
        
        # Analyze each field
        field_analyses = {}
        for field_name in field_names:
            field_analysis = self._analyze_field(data, field_name)
            field_analyses[field_name] = field_analysis
        
        # Analyze relationships between fields
        relationships = self._analyze_relationships(data, field_names)
        
        # Detect higher-level patterns
        detected_patterns = self._detect_dataset_patterns(data, field_analyses)
        
        # Calculate data quality score
        quality_score = self._calculate_quality_score(data, field_analyses)
        
        # Suggest constraints
        constraints = self._suggest_constraints(field_analyses, relationships)
        
        analysis = DatasetAnalysis(
            total_records=total_records,
            total_fields=len(field_names),
            field_analyses=field_analyses,
            relationships=relationships,
            data_quality_score=quality_score,
            detected_patterns=detected_patterns,
            suggested_constraints=constraints
        )
        
        return self._analysis_to_dict(analysis)
    
    def _analyze_field(self, data: List[Dict[str, Any]], field_name: str) -> FieldAnalysis:
        """Analyze a single field across all records."""
        
        # Extract all values for this field
        values = []
        null_count = 0
        
        for record in data:
            value = record.get(field_name)
            if value is None or value == '':
                null_count += 1
            else:
                values.append(value)
        
        if not values:
            # All values are null
            return FieldAnalysis(
                field_name=field_name,
                data_type='null',
                distinct_count=0,
                null_count=null_count,
                null_percentage=100.0
            )
        
        # Basic stats
        distinct_count = len(set(str(v) for v in values))
        null_percentage = (null_count / len(data)) * 100
        
        # Detect data type
        data_type = self._detect_data_type(values)
        
        # Initialize analysis
        analysis = FieldAnalysis(
            field_name=field_name,
            data_type=data_type,
            distinct_count=distinct_count,
            null_count=null_count,
            null_percentage=null_percentage
        )
        
        # Type-specific analysis
        if data_type == 'numeric':
            self._analyze_numeric_field(values, analysis)
        elif data_type == 'string':
            self._analyze_string_field(values, analysis)
        elif data_type == 'datetime':
            self._analyze_datetime_field(values, analysis)
        elif data_type == 'boolean':
            self._analyze_boolean_field(values, analysis)
        
        # Categorical analysis (for any type with limited distinct values)
        if distinct_count <= min(50, len(values) * 0.1):
            self._analyze_categorical_field(values, analysis)
        
        return analysis
    
    def _detect_data_type(self, values: List[Any]) -> str:
        """Detect the most likely data type for field values."""
        
        if not values:
            return 'unknown'
        
        # Sample for type detection (use first 100 values for performance)
        sample = values[:100]
        
        # Count successful conversions for each type
        type_scores = {
            'numeric': 0,
            'datetime': 0,
            'boolean': 0,
            'string': 0
        }
        
        for value in sample:
            str_value = str(value).strip()
            
            # Numeric check
            try:
                float(str_value)
                type_scores['numeric'] += 1
            except (ValueError, TypeError):
                pass
            
            # Boolean check
            if str_value.lower() in ['true', 'false', '1', '0', 'yes', 'no', 't', 'f']:
                type_scores['boolean'] += 1
            
            # DateTime check
            if self._looks_like_datetime(str_value):
                type_scores['datetime'] += 1
            
            # String (always possible)
            type_scores['string'] += 1
        
        # Return type with highest score (excluding string)
        non_string_scores = {k: v for k, v in type_scores.items() if k != 'string'}
        if non_string_scores:
            best_type = max(non_string_scores.items(), key=lambda x: x[1])
            if best_type[1] >= len(sample) * 0.8:  # 80% confidence threshold
                return best_type[0]
        
        return 'string'
    
    def _looks_like_datetime(self, value: str) -> bool:
        """Check if string looks like a datetime."""
        
        # Common datetime patterns
        datetime_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
            r'\d{2}-\d{2}-\d{4}',  # MM-DD-YYYY
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{2}/\d{2}/\d{2}',  # MM/DD/YY
        ]
        
        for pattern in datetime_patterns:
            if re.search(pattern, value):
                return True
        
        # Try parsing with common formats
        common_formats = [
            '%Y-%m-%d',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y',
            '%m-%d-%Y',
            '%Y/%m/%d',
            '%d/%m/%Y',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
        ]
        
        for fmt in common_formats:
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
        
        return False
    
    def _analyze_numeric_field(self, values: List[Any], analysis: FieldAnalysis):
        """Analyze numeric field values."""
        
        # Convert to numeric
        numeric_values = []
        for value in values:
            try:
                numeric_values.append(float(value))
            except (ValueError, TypeError):
                continue
        
        if not numeric_values:
            return
        
        # Basic statistics
        analysis.min_value = min(numeric_values)
        analysis.max_value = max(numeric_values)
        analysis.mean = statistics.mean(numeric_values)
        analysis.median = statistics.median(numeric_values)
        
        if len(numeric_values) > 1:
            analysis.std_dev = statistics.stdev(numeric_values)
        else:
            analysis.std_dev = 0.0
    
    def _analyze_string_field(self, values: List[Any], analysis: FieldAnalysis):
        """Analyze string field values."""
        
        str_values = [str(v) for v in values]
        
        # Length analysis
        lengths = [len(s) for s in str_values]
        analysis.min_length = min(lengths)
        analysis.max_length = max(lengths)
        analysis.avg_length = sum(lengths) / len(lengths)
        
        # Pattern detection
        analysis.common_patterns = self._detect_string_patterns(str_values)
    
    def _analyze_datetime_field(self, values: List[Any], analysis: FieldAnalysis):
        """Analyze datetime field values."""
        
        # Parse datetime values
        datetime_values = []
        for value in values:
            dt = self._parse_datetime(str(value))
            if dt:
                datetime_values.append(dt)
        
        if not datetime_values:
            return
        
        # Date range
        min_date = min(datetime_values)
        max_date = max(datetime_values)
        analysis.date_range = (min_date, max_date)
        
        # Temporal patterns
        analysis.temporal_patterns = self._analyze_temporal_patterns(datetime_values)
    
    def _analyze_boolean_field(self, values: List[Any], analysis: FieldAnalysis):
        """Analyze boolean field values."""
        
        # Convert to boolean and count distribution
        bool_values = []
        for value in values:
            str_val = str(value).lower().strip()
            if str_val in ['true', '1', 'yes', 't', 'y']:
                bool_values.append(True)
            elif str_val in ['false', '0', 'no', 'f', 'n']:
                bool_values.append(False)
        
        if bool_values:
            true_count = sum(bool_values)
            false_count = len(bool_values) - true_count
            analysis.value_distribution = {True: true_count, False: false_count}
    
    def _analyze_categorical_field(self, values: List[Any], analysis: FieldAnalysis):
        """Analyze categorical (limited distinct values) field."""
        
        # Count value occurrences
        value_counts = Counter(str(v) for v in values)
        analysis.value_distribution = dict(value_counts)
        
        # Top values (up to 20)
        analysis.top_values = value_counts.most_common(20)
    
    def _detect_string_patterns(self, values: List[str]) -> List[str]:
        """Detect common patterns in string values."""
        
        detected = []
        
        # Check against known patterns
        for pattern_name, pattern_regex in self.common_patterns.items():
            compiled_pattern = re.compile(pattern_regex, re.IGNORECASE)
            matches = sum(1 for v in values if compiled_pattern.match(v))
            
            if matches >= len(values) * 0.8:  # 80% of values match
                detected.append(pattern_name)
        
        # Detect custom patterns
        # Simple approach: find common character patterns
        if not detected:
            # Analyze character types
            pattern_analysis = self._analyze_character_patterns(values)
            if pattern_analysis:
                detected.append(f"custom_{pattern_analysis}")
        
        return detected
    
    def _analyze_character_patterns(self, values: List[str]) -> Optional[str]:
        """Analyze character type patterns in strings."""
        
        if not values:
            return None
        
        # Sample some values for pattern analysis
        sample = values[:50]
        
        # Create pattern signatures
        signatures = []
        for value in sample:
            signature = ''
            for char in value:
                if char.isdigit():
                    signature += 'D'
                elif char.isalpha():
                    signature += 'A'
                elif char in '-_.,':
                    signature += 'S'  # Separator
                else:
                    signature += 'X'  # Other
            signatures.append(signature)
        
        # Find most common signature
        signature_counts = Counter(signatures)
        most_common = signature_counts.most_common(1)
        
        if most_common and most_common[0][1] >= len(sample) * 0.7:
            return most_common[0][0]
        
        return None
    
    def _parse_datetime(self, value: str) -> Optional[datetime]:
        """Parse datetime from string."""
        
        common_formats = [
            '%Y-%m-%d',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y',
            '%m-%d-%Y',
            '%Y/%m/%d',
            '%d/%m/%Y',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%f',
        ]
        
        for fmt in common_formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        
        return None
    
    def _analyze_temporal_patterns(self, datetime_values: List[datetime]) -> Dict[str, Any]:
        """Analyze temporal patterns in datetime values."""
        
        patterns = {}
        
        # Day of week distribution
        dow_counts = Counter(dt.weekday() for dt in datetime_values)
        patterns['day_of_week_distribution'] = dict(dow_counts)
        
        # Hour distribution (if time component exists)
        hours = [dt.hour for dt in datetime_values if dt.hour != 0 or dt.minute != 0 or dt.second != 0]
        if hours:
            hour_counts = Counter(hours)
            patterns['hour_distribution'] = dict(hour_counts)
        
        # Month distribution
        month_counts = Counter(dt.month for dt in datetime_values)
        patterns['month_distribution'] = dict(month_counts)
        
        # Time gaps analysis
        if len(datetime_values) > 1:
            sorted_times = sorted(datetime_values)
            gaps = []
            for i in range(1, len(sorted_times)):
                gap = sorted_times[i] - sorted_times[i-1]
                gaps.append(gap.total_seconds())
            
            if gaps:
                patterns['avg_time_gap_seconds'] = statistics.mean(gaps)
                patterns['median_time_gap_seconds'] = statistics.median(gaps)
        
        return patterns
    
    def _analyze_relationships(self, data: List[Dict[str, Any]], 
                             field_names: List[str]) -> List[Dict[str, Any]]:
        """Analyze relationships between fields."""
        
        relationships = []
        
        # Correlation analysis for numeric fields
        numeric_fields = []
        for field_name in field_names:
            values = [record.get(field_name) for record in data]
            if self._is_mostly_numeric(values):
                numeric_fields.append(field_name)
        
        # Calculate correlations between numeric fields
        if len(numeric_fields) >= 2:
            for i, field1 in enumerate(numeric_fields):
                for field2 in numeric_fields[i+1:]:
                    correlation = self._calculate_correlation(data, field1, field2)
                    if correlation and abs(correlation) >= 0.5:  # Significant correlation
                        relationships.append({
                            'type': 'correlation',
                            'field1': field1,
                            'field2': field2,
                            'strength': correlation,
                            'description': f'Numeric correlation between {field1} and {field2}'
                        })
        
        # Foreign key relationship detection
        fk_relationships = self._detect_foreign_key_relationships(data, field_names)
        relationships.extend(fk_relationships)
        
        # Hierarchical relationship detection
        hierarchical_relationships = self._detect_hierarchical_relationships(data, field_names)
        relationships.extend(hierarchical_relationships)
        
        return relationships
    
    def _is_mostly_numeric(self, values: List[Any]) -> bool:
        """Check if list of values is mostly numeric."""
        if not values:
            return False
        
        numeric_count = 0
        valid_count = 0
        
        for value in values:
            if value is not None and value != '':
                valid_count += 1
                try:
                    float(value)
                    numeric_count += 1
                except (ValueError, TypeError):
                    pass
        
        return valid_count > 0 and numeric_count / valid_count >= 0.8
    
    def _calculate_correlation(self, data: List[Dict[str, Any]], 
                             field1: str, field2: str) -> Optional[float]:
        """Calculate Pearson correlation between two numeric fields."""
        
        # Extract paired values
        pairs = []
        for record in data:
            val1 = record.get(field1)
            val2 = record.get(field2)
            
            try:
                num1 = float(val1)
                num2 = float(val2)
                pairs.append((num1, num2))
            except (ValueError, TypeError):
                continue
        
        if len(pairs) < 2:
            return None
        
        # Calculate Pearson correlation
        x_values = [p[0] for p in pairs]
        y_values = [p[1] for p in pairs]
        
        try:
            n = len(pairs)
            sum_x = sum(x_values)
            sum_y = sum(y_values)
            sum_x2 = sum(x * x for x in x_values)
            sum_y2 = sum(y * y for y in y_values)
            sum_xy = sum(x * y for x, y in pairs)
            
            numerator = n * sum_xy - sum_x * sum_y
            denominator = math.sqrt((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2))
            
            if denominator == 0:
                return None
            
            return numerator / denominator
            
        except (ValueError, ZeroDivisionError):
            return None
    
    def _detect_foreign_key_relationships(self, data: List[Dict[str, Any]], 
                                        field_names: List[str]) -> List[Dict[str, Any]]:
        """Detect potential foreign key relationships."""
        
        relationships = []
        
        # Look for fields ending with _id, _key, etc.
        potential_fks = [
            field for field in field_names 
            if field.endswith(('_id', '_key', 'Id', 'Key')) or field.lower() == 'id'
        ]
        
        for fk_field in potential_fks:
            # Get all values for this field
            fk_values = set()
            for record in data:
                value = record.get(fk_field)
                if value is not None:
                    fk_values.add(value)
            
            # Look for other fields that might be the referenced primary key
            for other_field in field_names:
                if other_field == fk_field:
                    continue
                
                other_values = set()
                for record in data:
                    value = record.get(other_field)
                    if value is not None:
                        other_values.add(value)
                
                # Check if FK values are subset of other field values
                if fk_values and fk_values.issubset(other_values):
                    overlap = len(fk_values & other_values) / len(fk_values)
                    if overlap >= 0.8:  # 80% overlap threshold
                        relationships.append({
                            'type': 'foreign_key',
                            'foreign_key': fk_field,
                            'referenced_key': other_field,
                            'overlap_percentage': overlap * 100,
                            'description': f'Potential FK relationship: {fk_field} -> {other_field}'
                        })
        
        return relationships
    
    def _detect_hierarchical_relationships(self, data: List[Dict[str, Any]], 
                                         field_names: List[str]) -> List[Dict[str, Any]]:
        """Detect hierarchical (parent-child) relationships within same table."""
        
        relationships = []
        
        # Look for self-referencing patterns
        for field in field_names:
            if 'parent' in field.lower() or 'manager' in field.lower():
                # Check if values reference other values in an ID-like field
                id_fields = [f for f in field_names if f.lower() == 'id' or f.endswith('_id')]
                
                for id_field in id_fields:
                    hierarchy_strength = self._check_hierarchical_strength(data, field, id_field)
                    if hierarchy_strength >= 0.3:  # 30% threshold
                        relationships.append({
                            'type': 'hierarchical',
                            'child_field': field,
                            'parent_field': id_field,
                            'strength': hierarchy_strength,
                            'description': f'Hierarchical relationship: {field} references {id_field}'
                        })
        
        return relationships
    
    def _check_hierarchical_strength(self, data: List[Dict[str, Any]], 
                                   parent_field: str, id_field: str) -> float:
        """Check strength of hierarchical relationship."""
        
        # Get all ID values and parent references
        id_values = set()
        parent_values = set()
        
        for record in data:
            id_val = record.get(id_field)
            parent_val = record.get(parent_field)
            
            if id_val is not None:
                id_values.add(id_val)
            if parent_val is not None:
                parent_values.add(parent_val)
        
        if not parent_values:
            return 0.0
        
        # Calculate how many parent references exist as IDs
        valid_references = len(parent_values & id_values)
        total_references = len(parent_values)
        
        return valid_references / total_references if total_references > 0 else 0.0
    
    def _detect_dataset_patterns(self, data: List[Dict[str, Any]], 
                               field_analyses: Dict[str, FieldAnalysis]) -> List[Dict[str, Any]]:
        """Detect higher-level patterns across the dataset."""
        
        patterns = []
        
        # Audit trail pattern detection
        if self._has_audit_trail_pattern(field_analyses):
            patterns.append({
                'type': 'audit_trail',
                'description': 'Dataset contains audit trail fields',
                'fields': self._get_audit_trail_fields(field_analyses),
                'confidence': 0.9
            })
        
        # Versioning pattern detection
        if self._has_versioning_pattern(field_analyses):
            patterns.append({
                'type': 'versioning',
                'description': 'Dataset contains version control fields',
                'fields': self._get_versioning_fields(field_analyses),
                'confidence': 0.8
            })
        
        # Status workflow pattern detection
        status_fields = self._find_status_fields(field_analyses)
        if status_fields:
            for field_name, analysis in status_fields.items():
                if analysis.value_distribution:
                    patterns.append({
                        'type': 'status_workflow',
                        'description': f'Status workflow detected in field {field_name}',
                        'field': field_name,
                        'states': list(analysis.value_distribution.keys()),
                        'confidence': 0.7
                    })
        
        # Time series pattern detection
        if self._has_time_series_pattern(field_analyses):
            patterns.append({
                'type': 'time_series',
                'description': 'Dataset appears to be time series data',
                'time_fields': self._get_time_fields(field_analyses),
                'confidence': 0.8
            })
        
        return patterns
    
    def _has_audit_trail_pattern(self, field_analyses: Dict[str, FieldAnalysis]) -> bool:
        """Check if dataset has audit trail pattern."""
        audit_indicators = ['created_at', 'updated_at', 'created_by', 'updated_by', 'modified_at']
        found_indicators = 0
        
        for field_name in field_analyses.keys():
            field_lower = field_name.lower()
            if any(indicator in field_lower for indicator in audit_indicators):
                found_indicators += 1
        
        return found_indicators >= 2
    
    def _get_audit_trail_fields(self, field_analyses: Dict[str, FieldAnalysis]) -> List[str]:
        """Get audit trail fields."""
        audit_indicators = ['created_at', 'updated_at', 'created_by', 'updated_by', 'modified_at']
        audit_fields = []
        
        for field_name in field_analyses.keys():
            field_lower = field_name.lower()
            if any(indicator in field_lower for indicator in audit_indicators):
                audit_fields.append(field_name)
        
        return audit_fields
    
    def _has_versioning_pattern(self, field_analyses: Dict[str, FieldAnalysis]) -> bool:
        """Check if dataset has versioning pattern."""
        version_indicators = ['version', 'revision', 'v_', '_v']
        
        for field_name in field_analyses.keys():
            field_lower = field_name.lower()
            if any(indicator in field_lower for indicator in version_indicators):
                return True
        
        return False
    
    def _get_versioning_fields(self, field_analyses: Dict[str, FieldAnalysis]) -> List[str]:
        """Get versioning fields."""
        version_indicators = ['version', 'revision', 'v_', '_v']
        version_fields = []
        
        for field_name in field_analyses.keys():
            field_lower = field_name.lower()
            if any(indicator in field_lower for indicator in version_indicators):
                version_fields.append(field_name)
        
        return version_fields
    
    def _find_status_fields(self, field_analyses: Dict[str, FieldAnalysis]) -> Dict[str, FieldAnalysis]:
        """Find fields that appear to represent status or state."""
        status_fields = {}
        status_indicators = ['status', 'state', 'phase', 'stage', 'condition']
        
        for field_name, analysis in field_analyses.items():
            field_lower = field_name.lower()
            
            # Check if field name indicates status
            if any(indicator in field_lower for indicator in status_indicators):
                # Check if it has limited distinct values (categorical)
                if (analysis.distinct_count <= 20 and 
                    analysis.distinct_count >= 2 and
                    analysis.value_distribution):
                    status_fields[field_name] = analysis
        
        return status_fields
    
    def _has_time_series_pattern(self, field_analyses: Dict[str, FieldAnalysis]) -> bool:
        """Check if dataset appears to be time series data."""
        
        # Look for datetime fields
        datetime_fields = 0
        for analysis in field_analyses.values():
            if analysis.data_type == 'datetime':
                datetime_fields += 1
        
        # Look for sequential patterns
        numeric_fields_with_sequences = 0
        for analysis in field_analyses.values():
            if (analysis.data_type == 'numeric' and 
                analysis.min_value is not None and 
                analysis.max_value is not None):
                # Check if values appear sequential
                value_range = analysis.max_value - analysis.min_value
                if value_range > 0 and analysis.distinct_count > value_range * 0.5:
                    numeric_fields_with_sequences += 1
        
        return datetime_fields >= 1 or numeric_fields_with_sequences >= 1
    
    def _get_time_fields(self, field_analyses: Dict[str, FieldAnalysis]) -> List[str]:
        """Get time-related fields."""
        time_fields = []
        
        for field_name, analysis in field_analyses.items():
            if analysis.data_type == 'datetime':
                time_fields.append(field_name)
            elif 'time' in field_name.lower() or 'date' in field_name.lower():
                time_fields.append(field_name)
        
        return time_fields
    
    def _calculate_quality_score(self, data: List[Dict[str, Any]], 
                               field_analyses: Dict[str, FieldAnalysis]) -> float:
        """Calculate overall data quality score."""
        
        if not data or not field_analyses:
            return 0.0
        
        scores = []
        
        # Completeness score (average non-null percentage)
        completeness_scores = []
        for analysis in field_analyses.values():
            completeness = 100 - analysis.null_percentage
            completeness_scores.append(completeness / 100)  # Normalize to 0-1
        
        if completeness_scores:
            scores.append(statistics.mean(completeness_scores))
        
        # Uniqueness score for ID fields
        id_fields = [name for name in field_analyses.keys() 
                    if name.lower() == 'id' or name.endswith('_id')]
        
        if id_fields:
            uniqueness_scores = []
            for id_field in id_fields:
                analysis = field_analyses[id_field]
                total_values = len(data) - analysis.null_count
                if total_values > 0:
                    uniqueness = analysis.distinct_count / total_values
                    uniqueness_scores.append(min(uniqueness, 1.0))
            
            if uniqueness_scores:
                scores.append(statistics.mean(uniqueness_scores))
        
        # Consistency score (based on pattern detection)
        consistency_score = 0.0
        pattern_fields = 0
        
        for analysis in field_analyses.values():
            if analysis.common_patterns:
                consistency_score += 1.0
                pattern_fields += 1
        
        if pattern_fields > 0:
            scores.append(consistency_score / pattern_fields)
        
        # Return average of all scores
        return statistics.mean(scores) if scores else 0.5
    
    def _suggest_constraints(self, field_analyses: Dict[str, FieldAnalysis], 
                           relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Suggest data constraints based on analysis."""
        
        constraints = []
        
        for field_name, analysis in field_analyses.items():
            # Numeric constraints
            if analysis.data_type == 'numeric' and analysis.min_value is not None:
                constraints.append({
                    'type': 'range',
                    'field': field_name,
                    'min_value': analysis.min_value,
                    'max_value': analysis.max_value,
                    'description': f'Value range for {field_name}'
                })
            
            # String length constraints
            if analysis.data_type == 'string' and analysis.min_length is not None:
                constraints.append({
                    'type': 'length',
                    'field': field_name,
                    'min_length': analysis.min_length,
                    'max_length': analysis.max_length,
                    'description': f'String length constraint for {field_name}'
                })
            
            # Pattern constraints
            if analysis.common_patterns:
                for pattern in analysis.common_patterns:
                    constraints.append({
                        'type': 'pattern',
                        'field': field_name,
                        'pattern': pattern,
                        'description': f'Pattern constraint for {field_name}: {pattern}'
                    })
            
            # Categorical constraints
            if (analysis.value_distribution and 
                analysis.distinct_count <= 50 and  # Reasonable number of categories
                analysis.distinct_count >= 2):
                
                constraints.append({
                    'type': 'categorical',
                    'field': field_name,
                    'allowed_values': list(analysis.value_distribution.keys()),
                    'description': f'Categorical constraint for {field_name}'
                })
            
            # Not null constraints (if low null percentage)
            if analysis.null_percentage <= 5.0:  # 5% or less nulls
                constraints.append({
                    'type': 'not_null',
                    'field': field_name,
                    'description': f'Not null constraint for {field_name}'
                })
        
        # Relationship constraints
        for relationship in relationships:
            if relationship['type'] == 'foreign_key':
                constraints.append({
                    'type': 'foreign_key',
                    'field': relationship['foreign_key'],
                    'references': relationship['referenced_key'],
                    'description': f"Foreign key constraint: {relationship['foreign_key']} references {relationship['referenced_key']}"
                })
        
        return constraints
    
    def _analysis_to_dict(self, analysis: DatasetAnalysis) -> Dict[str, Any]:
        """Convert DatasetAnalysis to dictionary for serialization."""
        
        field_analyses_dict = {}
        for field_name, field_analysis in analysis.field_analyses.items():
            field_analyses_dict[field_name] = {
                'field_name': field_analysis.field_name,
                'data_type': field_analysis.data_type,
                'distinct_count': field_analysis.distinct_count,
                'null_count': field_analysis.null_count,
                'null_percentage': field_analysis.null_percentage,
                'min_value': field_analysis.min_value,
                'max_value': field_analysis.max_value,
                'mean': field_analysis.mean,
                'median': field_analysis.median,
                'std_dev': field_analysis.std_dev,
                'min_length': field_analysis.min_length,
                'max_length': field_analysis.max_length,
                'avg_length': field_analysis.avg_length,
                'common_patterns': field_analysis.common_patterns,
                'value_distribution': field_analysis.value_distribution,
                'top_values': field_analysis.top_values,
                'date_range': [dt.isoformat() if dt else None 
                              for dt in field_analysis.date_range] if field_analysis.date_range else None,
                'temporal_patterns': field_analysis.temporal_patterns
            }
        
        return {
            'total_records': analysis.total_records,
            'total_fields': analysis.total_fields,
            'field_analyses': field_analyses_dict,
            'relationships': analysis.relationships,
            'data_quality_score': analysis.data_quality_score,
            'detected_patterns': analysis.detected_patterns,
            'suggested_constraints': analysis.suggested_constraints
        }
    
    # Utility methods for external use
    def suggest_generation_parameters(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """Suggest parameters for generating similar synthetic data."""
        
        suggestions = {
            'record_count': analysis_results['total_records'],
            'field_suggestions': {},
            'relationship_suggestions': [],
            'quality_targets': {}
        }
        
        # Field-level suggestions
        field_analyses = analysis_results.get('field_analyses', {})
        for field_name, field_data in field_analyses.items():
            field_suggestions = {}
            
            if field_data['data_type'] == 'numeric':
                field_suggestions.update({
                    'type': 'numeric',
                    'min_value': field_data.get('min_value'),
                    'max_value': field_data.get('max_value'),
                    'mean': field_data.get('mean'),
                    'std_dev': field_data.get('std_dev')
                })
            
            elif field_data['data_type'] == 'string':
                field_suggestions.update({
                    'type': 'string',
                    'min_length': field_data.get('min_length'),
                    'max_length': field_data.get('max_length'),
                    'patterns': field_data.get('common_patterns', [])
                })
            
            elif field_data['data_type'] == 'datetime':
                field_suggestions.update({
                    'type': 'datetime',
                    'date_range': field_data.get('date_range'),
                    'temporal_patterns': field_data.get('temporal_patterns', {})
                })
            
            # Categorical suggestions
            if field_data.get('value_distribution'):
                field_suggestions['categorical_distribution'] = field_data['value_distribution']
            
            # Null percentage
            field_suggestions['null_percentage'] = field_data.get('null_percentage', 0.0)
            
            suggestions['field_suggestions'][field_name] = field_suggestions
        
        # Relationship suggestions
        relationships = analysis_results.get('relationships', [])
        for relationship in relationships:
            suggestions['relationship_suggestions'].append({
                'type': relationship['type'],
                'description': relationship['description'],
                'fields': [relationship.get('field1', relationship.get('foreign_key')),
                          relationship.get('field2', relationship.get('referenced_key'))],
                'strength': relationship.get('strength', relationship.get('overlap_percentage', 100))
            })
        
        # Quality targets
        suggestions['quality_targets'] = {
            'data_quality_score': analysis_results.get('data_quality_score', 0.8),
            'completeness_target': 95.0,  # 95% non-null
            'consistency_target': 90.0    # 90% pattern compliance
        }
        
        return suggestions