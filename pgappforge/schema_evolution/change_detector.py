"""
Change Detector for Real-Time Schema Evolution System

This module provides advanced schema change detection capabilities with
intelligent analysis, impact assessment, and change classification.
"""

import json
import hashlib
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
import difflib

from .schema_monitor import SchemaChange, ChangeType, SchemaSnapshot
from ..cli.generators.database_inspector import EnhancedDatabaseInspector, TableInfo, ColumnInfo


class ChangeImpact(Enum):
    """Change impact levels."""
    MINIMAL = "minimal"      # Index changes, comments
    LOW = "low"             # New optional columns, new tables
    MEDIUM = "medium"       # Column modifications, new constraints
    HIGH = "high"           # Column removals, type changes
    CRITICAL = "critical"   # Table removals, breaking changes


class ChangeCategory(Enum):
    """Change categories for better organization."""
    SCHEMA_STRUCTURE = "schema_structure"
    DATA_DEFINITION = "data_definition"
    CONSTRAINTS = "constraints"
    INDEXES = "indexes"
    RELATIONSHIPS = "relationships"
    METADATA = "metadata"


@dataclass
class ColumnChange:
    """Detailed column change information."""
    column_name: str
    change_type: str
    old_definition: Optional[Dict[str, Any]]
    new_definition: Optional[Dict[str, Any]]
    impact_level: ChangeImpact
    backward_compatible: bool
    migration_required: bool
    suggested_migration: Optional[str] = None


@dataclass
class TableChange:
    """Detailed table change information."""
    table_name: str
    change_type: str
    column_changes: List[ColumnChange]
    index_changes: List[Dict[str, Any]]
    constraint_changes: List[Dict[str, Any]]
    relationship_changes: List[Dict[str, Any]]
    overall_impact: ChangeImpact
    migration_strategy: str


@dataclass
class SchemaComparison:
    """Complete schema comparison result."""
    old_snapshot: SchemaSnapshot
    new_snapshot: SchemaSnapshot
    detected_changes: List[SchemaChange]
    table_changes: Dict[str, TableChange]
    impact_summary: Dict[ChangeImpact, int]
    breaking_changes: List[SchemaChange]
    migration_required: bool
    estimated_effort: str  # low, medium, high


class ChangeDetector:
    """
    Advanced schema change detector with intelligent analysis capabilities.

    Features:
    - Detailed change analysis with impact assessment
    - Breaking change detection
    - Migration strategy recommendations
    - Backward compatibility analysis
    - Performance impact evaluation
    - Change classification and prioritization
    """

    def __init__(self, inspector: EnhancedDatabaseInspector):
        self.inspector = inspector

    def compare_schemas(self, old_snapshot: SchemaSnapshot,
                       new_snapshot: SchemaSnapshot) -> SchemaComparison:
        """
        Compare two schema snapshots and provide detailed analysis.

        Args:
            old_snapshot: Previous schema snapshot
            new_snapshot: Current schema snapshot

        Returns:
            SchemaComparison with detailed change analysis
        """
        # Detect raw changes
        detected_changes = self._detect_raw_changes(old_snapshot, new_snapshot)

        # Analyze table-level changes
        table_changes = self._analyze_table_changes(old_snapshot, new_snapshot, detected_changes)

        # Assess impact and breaking changes
        impact_summary = self._assess_impact(detected_changes)
        breaking_changes = self._identify_breaking_changes(detected_changes)

        # Determine migration requirements
        migration_required = any(
            change.change_type in [
                ChangeType.TABLE_REMOVED,
                ChangeType.COLUMN_REMOVED,
                ChangeType.COLUMN_MODIFIED
            ]
            for change in detected_changes
        )

        # Estimate effort
        estimated_effort = self._estimate_effort(detected_changes, impact_summary)

        return SchemaComparison(
            old_snapshot=old_snapshot,
            new_snapshot=new_snapshot,
            detected_changes=detected_changes,
            table_changes=table_changes,
            impact_summary=impact_summary,
            breaking_changes=breaking_changes,
            migration_required=migration_required,
            estimated_effort=estimated_effort
        )

    def _detect_raw_changes(self, old_snapshot: SchemaSnapshot,
                          new_snapshot: SchemaSnapshot) -> List[SchemaChange]:
        """Detect raw schema changes between snapshots."""
        changes = []

        old_tables = set(old_snapshot.tables.keys())
        new_tables = set(new_snapshot.tables.keys())

        # Table-level changes
        added_tables = new_tables - old_tables
        removed_tables = old_tables - new_tables
        common_tables = old_tables & new_tables

        # Process added tables
        for table_name in added_tables:
            change = SchemaChange(
                change_type=ChangeType.TABLE_ADDED,
                table_name=table_name,
                change_details={
                    "table_definition": new_snapshot.tables[table_name],
                    "columns": len(new_snapshot.tables[table_name]["columns"]),
                    "indexes": len(new_snapshot.tables[table_name]["indexes"]),
                    "foreign_keys": len(new_snapshot.tables[table_name]["foreign_keys"])
                },
                timestamp=new_snapshot.timestamp,
                change_id="",
                priority=2
            )
            changes.append(change)

        # Process removed tables
        for table_name in removed_tables:
            change = SchemaChange(
                change_type=ChangeType.TABLE_REMOVED,
                table_name=table_name,
                change_details={
                    "table_definition": old_snapshot.tables[table_name],
                    "data_loss_risk": "high",
                    "dependent_tables": self._find_dependent_tables(table_name, old_snapshot)
                },
                timestamp=new_snapshot.timestamp,
                change_id="",
                priority=4
            )
            changes.append(change)

        # Process modified tables
        for table_name in common_tables:
            table_changes = self._detect_table_changes(
                table_name,
                old_snapshot.tables[table_name],
                new_snapshot.tables[table_name],
                new_snapshot.timestamp
            )
            changes.extend(table_changes)

        return changes

    def _detect_table_changes(self, table_name: str, old_table: Dict[str, Any],
                            new_table: Dict[str, Any], timestamp: datetime) -> List[SchemaChange]:
        """Detect changes within a specific table."""
        changes = []

        # Column changes
        old_columns = {col["name"]: col for col in old_table["columns"]}
        new_columns = {col["name"]: col for col in new_table["columns"]}

        column_changes = self._detect_column_changes(
            table_name, old_columns, new_columns, timestamp
        )
        changes.extend(column_changes)

        # Index changes
        index_changes = self._detect_index_changes(
            table_name, old_table["indexes"], new_table["indexes"], timestamp
        )
        changes.extend(index_changes)

        # Foreign key changes
        fk_changes = self._detect_foreign_key_changes(
            table_name, old_table["foreign_keys"], new_table["foreign_keys"], timestamp
        )
        changes.extend(fk_changes)

        return changes

    def _detect_column_changes(self, table_name: str, old_columns: Dict[str, Dict],
                             new_columns: Dict[str, Dict], timestamp: datetime) -> List[SchemaChange]:
        """Detect column-level changes."""
        changes = []

        added_columns = set(new_columns.keys()) - set(old_columns.keys())
        removed_columns = set(old_columns.keys()) - set(new_columns.keys())
        common_columns = set(old_columns.keys()) & set(new_columns.keys())

        # Added columns
        for col_name in added_columns:
            col_info = new_columns[col_name]
            priority = 3 if not col_info.get("nullable", True) else 2

            change = SchemaChange(
                change_type=ChangeType.COLUMN_ADDED,
                table_name=table_name,
                change_details={
                    "column_name": col_name,
                    "column_definition": col_info,
                    "nullable": col_info.get("nullable", True),
                    "has_default": col_info.get("default") is not None,
                    "migration_impact": "low" if col_info.get("nullable", True) or col_info.get("default") else "medium"
                },
                timestamp=timestamp,
                change_id="",
                priority=priority
            )
            changes.append(change)

        # Removed columns
        for col_name in removed_columns:
            col_info = old_columns[col_name]

            change = SchemaChange(
                change_type=ChangeType.COLUMN_REMOVED,
                table_name=table_name,
                change_details={
                    "column_name": col_name,
                    "column_definition": col_info,
                    "data_loss_risk": "high",
                    "breaking_change": True,
                    "dependent_constraints": self._find_column_constraints(table_name, col_name, col_info)
                },
                timestamp=timestamp,
                change_id="",
                priority=4
            )
            changes.append(change)

        # Modified columns
        for col_name in common_columns:
            old_col = old_columns[col_name]
            new_col = new_columns[col_name]

            if self._column_definition_changed(old_col, new_col):
                modification_details = self._analyze_column_modification(old_col, new_col)

                change = SchemaChange(
                    change_type=ChangeType.COLUMN_MODIFIED,
                    table_name=table_name,
                    change_details={
                        "column_name": col_name,
                        "old_definition": old_col,
                        "new_definition": new_col,
                        "modifications": modification_details,
                        "breaking_change": modification_details.get("breaking", False),
                        "data_conversion_required": modification_details.get("conversion_required", False)
                    },
                    timestamp=timestamp,
                    change_id="",
                    priority=3 if modification_details.get("breaking", False) else 2
                )
                changes.append(change)

        return changes

    def _detect_index_changes(self, table_name: str, old_indexes: List[Dict],
                            new_indexes: List[Dict], timestamp: datetime) -> List[SchemaChange]:
        """Detect index changes."""
        changes = []

        old_index_names = {idx["name"]: idx for idx in old_indexes if idx.get("name")}
        new_index_names = {idx["name"]: idx for idx in new_indexes if idx.get("name")}

        added_indexes = set(new_index_names.keys()) - set(old_index_names.keys())
        removed_indexes = set(old_index_names.keys()) - set(new_index_names.keys())

        # Added indexes
        for idx_name in added_indexes:
            change = SchemaChange(
                change_type=ChangeType.INDEX_ADDED,
                table_name=table_name,
                change_details={
                    "index_name": idx_name,
                    "index_definition": new_index_names[idx_name],
                    "performance_impact": "positive"
                },
                timestamp=timestamp,
                change_id="",
                priority=1
            )
            changes.append(change)

        # Removed indexes
        for idx_name in removed_indexes:
            change = SchemaChange(
                change_type=ChangeType.INDEX_REMOVED,
                table_name=table_name,
                change_details={
                    "index_name": idx_name,
                    "index_definition": old_index_names[idx_name],
                    "performance_impact": "negative"
                },
                timestamp=timestamp,
                change_id="",
                priority=2
            )
            changes.append(change)

        return changes

    def _detect_foreign_key_changes(self, table_name: str, old_fks: List[Dict],
                                  new_fks: List[Dict], timestamp: datetime) -> List[SchemaChange]:
        """Detect foreign key changes."""
        changes = []

        old_fk_names = {fk["name"]: fk for fk in old_fks if fk.get("name")}
        new_fk_names = {fk["name"]: fk for fk in new_fks if fk.get("name")}

        added_fks = set(new_fk_names.keys()) - set(old_fk_names.keys())
        removed_fks = set(old_fk_names.keys()) - set(new_fk_names.keys())

        # Added foreign keys
        for fk_name in added_fks:
            change = SchemaChange(
                change_type=ChangeType.FOREIGN_KEY_ADDED,
                table_name=table_name,
                change_details={
                    "foreign_key_name": fk_name,
                    "foreign_key_definition": new_fk_names[fk_name],
                    "referential_integrity": "enhanced"
                },
                timestamp=timestamp,
                change_id="",
                priority=2
            )
            changes.append(change)

        # Removed foreign keys
        for fk_name in removed_fks:
            change = SchemaChange(
                change_type=ChangeType.FOREIGN_KEY_REMOVED,
                table_name=table_name,
                change_details={
                    "foreign_key_name": fk_name,
                    "foreign_key_definition": old_fk_names[fk_name],
                    "referential_integrity": "reduced",
                    "data_consistency_risk": "medium"
                },
                timestamp=timestamp,
                change_id="",
                priority=3
            )
            changes.append(change)

        return changes

    def _analyze_table_changes(self, old_snapshot: SchemaSnapshot,
                             new_snapshot: SchemaSnapshot,
                             detected_changes: List[SchemaChange]) -> Dict[str, TableChange]:
        """Analyze changes at the table level."""
        table_changes = {}

        # Group changes by table
        changes_by_table = {}
        for change in detected_changes:
            if change.table_name not in changes_by_table:
                changes_by_table[change.table_name] = []
            changes_by_table[change.table_name].append(change)

        # Analyze each table
        for table_name, changes in changes_by_table.items():
            column_changes = []
            index_changes = []
            constraint_changes = []
            relationship_changes = []

            for change in changes:
                if change.change_type in [ChangeType.COLUMN_ADDED, ChangeType.COLUMN_REMOVED,
                                        ChangeType.COLUMN_MODIFIED]:
                    # Convert to ColumnChange
                    col_change = self._create_column_change(change)
                    column_changes.append(col_change)
                elif change.change_type in [ChangeType.INDEX_ADDED, ChangeType.INDEX_REMOVED]:
                    index_changes.append(change.change_details)
                elif change.change_type in [ChangeType.CONSTRAINT_ADDED, ChangeType.CONSTRAINT_REMOVED]:
                    constraint_changes.append(change.change_details)
                elif change.change_type in [ChangeType.FOREIGN_KEY_ADDED, ChangeType.FOREIGN_KEY_REMOVED]:
                    relationship_changes.append(change.change_details)

            # Assess overall impact
            overall_impact = self._assess_table_impact(changes)

            # Determine migration strategy
            migration_strategy = self._determine_migration_strategy(changes)

            table_change = TableChange(
                table_name=table_name,
                change_type=self._determine_table_change_type(changes),
                column_changes=column_changes,
                index_changes=index_changes,
                constraint_changes=constraint_changes,
                relationship_changes=relationship_changes,
                overall_impact=overall_impact,
                migration_strategy=migration_strategy
            )

            table_changes[table_name] = table_change

        return table_changes

    def _create_column_change(self, change: SchemaChange) -> ColumnChange:
        """Create ColumnChange from SchemaChange."""
        details = change.change_details

        # Determine impact level
        impact_level = ChangeImpact.LOW
        if change.change_type == ChangeType.COLUMN_REMOVED:
            impact_level = ChangeImpact.CRITICAL
        elif change.change_type == ChangeType.COLUMN_MODIFIED:
            if details.get("breaking_change", False):
                impact_level = ChangeImpact.HIGH
            else:
                impact_level = ChangeImpact.MEDIUM

        # Determine backward compatibility
        backward_compatible = True
        if change.change_type == ChangeType.COLUMN_REMOVED:
            backward_compatible = False
        elif change.change_type == ChangeType.COLUMN_MODIFIED:
            backward_compatible = not details.get("breaking_change", False)

        return ColumnChange(
            column_name=details.get("column_name", ""),
            change_type=change.change_type.value,
            old_definition=details.get("old_definition"),
            new_definition=details.get("new_definition", details.get("column_definition")),
            impact_level=impact_level,
            backward_compatible=backward_compatible,
            migration_required=details.get("data_conversion_required", False),
            suggested_migration=self._suggest_column_migration(change)
        )

    def _suggest_column_migration(self, change: SchemaChange) -> Optional[str]:
        """Suggest migration strategy for column change."""
        if change.change_type == ChangeType.COLUMN_ADDED:
            details = change.change_details
            if not details.get("nullable", True) and not details.get("has_default", False):
                return f"Add default value or make column nullable: ALTER TABLE {change.table_name} ALTER COLUMN {details['column_name']} SET DEFAULT <value>;"

        elif change.change_type == ChangeType.COLUMN_REMOVED:
            return f"Consider backup before removal: CREATE TABLE {change.table_name}_backup AS SELECT * FROM {change.table_name};"

        elif change.change_type == ChangeType.COLUMN_MODIFIED:
            details = change.change_details
            if details.get("data_conversion_required", False):
                return f"Data conversion required for column {details['column_name']} in table {change.table_name}"

        return None

    def _assess_table_impact(self, changes: List[SchemaChange]) -> ChangeImpact:
        """Assess overall impact of changes to a table."""
        max_impact = ChangeImpact.MINIMAL

        impact_mapping = {
            ChangeType.TABLE_REMOVED: ChangeImpact.CRITICAL,
            ChangeType.COLUMN_REMOVED: ChangeImpact.HIGH,
            ChangeType.COLUMN_MODIFIED: ChangeImpact.MEDIUM,
            ChangeType.FOREIGN_KEY_REMOVED: ChangeImpact.MEDIUM,
            ChangeType.COLUMN_ADDED: ChangeImpact.LOW,
            ChangeType.FOREIGN_KEY_ADDED: ChangeImpact.LOW,
            ChangeType.INDEX_ADDED: ChangeImpact.MINIMAL,
            ChangeType.INDEX_REMOVED: ChangeImpact.MINIMAL
        }

        for change in changes:
            change_impact = impact_mapping.get(change.change_type, ChangeImpact.MINIMAL)
            if change_impact.value > max_impact.value:
                max_impact = change_impact

        return max_impact

    def _determine_migration_strategy(self, changes: List[SchemaChange]) -> str:
        """Determine migration strategy for table changes."""
        has_breaking_changes = any(
            change.change_type in [ChangeType.TABLE_REMOVED, ChangeType.COLUMN_REMOVED]
            or change.change_details.get("breaking_change", False)
            for change in changes
        )

        has_data_changes = any(
            change.change_type in [ChangeType.COLUMN_MODIFIED, ChangeType.COLUMN_REMOVED]
            for change in changes
        )

        if has_breaking_changes:
            return "blue_green_deployment"  # Zero-downtime deployment strategy
        elif has_data_changes:
            return "rolling_migration"      # Gradual data migration
        else:
            return "direct_migration"       # Simple schema update

    def _determine_table_change_type(self, changes: List[SchemaChange]) -> str:
        """Determine the primary type of change for a table."""
        change_types = [change.change_type for change in changes]

        if ChangeType.TABLE_ADDED in change_types:
            return "table_creation"
        elif ChangeType.TABLE_REMOVED in change_types:
            return "table_removal"
        elif any(ct in change_types for ct in [ChangeType.COLUMN_ADDED, ChangeType.COLUMN_REMOVED, ChangeType.COLUMN_MODIFIED]):
            return "schema_modification"
        elif any(ct in change_types for ct in [ChangeType.INDEX_ADDED, ChangeType.INDEX_REMOVED]):
            return "index_optimization"
        else:
            return "constraint_modification"

    def _assess_impact(self, changes: List[SchemaChange]) -> Dict[ChangeImpact, int]:
        """Assess overall impact of all changes."""
        impact_counts = {impact: 0 for impact in ChangeImpact}

        impact_mapping = {
            ChangeType.TABLE_REMOVED: ChangeImpact.CRITICAL,
            ChangeType.COLUMN_REMOVED: ChangeImpact.HIGH,
            ChangeType.COLUMN_MODIFIED: ChangeImpact.MEDIUM,
            ChangeType.FOREIGN_KEY_REMOVED: ChangeImpact.MEDIUM,
            ChangeType.TABLE_ADDED: ChangeImpact.LOW,
            ChangeType.COLUMN_ADDED: ChangeImpact.LOW,
            ChangeType.FOREIGN_KEY_ADDED: ChangeImpact.LOW,
            ChangeType.INDEX_ADDED: ChangeImpact.MINIMAL,
            ChangeType.INDEX_REMOVED: ChangeImpact.MINIMAL
        }

        for change in changes:
            impact = impact_mapping.get(change.change_type, ChangeImpact.MINIMAL)

            # Adjust based on change details
            if change.change_details.get("breaking_change", False):
                impact = ChangeImpact.HIGH

            impact_counts[impact] += 1

        return impact_counts

    def _identify_breaking_changes(self, changes: List[SchemaChange]) -> List[SchemaChange]:
        """Identify changes that would break existing code."""
        breaking_changes = []

        breaking_change_types = {
            ChangeType.TABLE_REMOVED,
            ChangeType.COLUMN_REMOVED,
            ChangeType.FOREIGN_KEY_REMOVED
        }

        for change in changes:
            if (change.change_type in breaking_change_types or
                change.change_details.get("breaking_change", False)):
                breaking_changes.append(change)

        return breaking_changes

    def _estimate_effort(self, changes: List[SchemaChange],
                        impact_summary: Dict[ChangeImpact, int]) -> str:
        """Estimate the effort required to handle the changes."""
        total_changes = len(changes)

        if impact_summary[ChangeImpact.CRITICAL] > 0:
            return "high"
        elif impact_summary[ChangeImpact.HIGH] > 2 or total_changes > 20:
            return "high"
        elif impact_summary[ChangeImpact.MEDIUM] > 5 or total_changes > 10:
            return "medium"
        else:
            return "low"

    def _column_definition_changed(self, old_col: Dict[str, Any],
                                 new_col: Dict[str, Any]) -> bool:
        """Check if column definition has meaningful changes."""
        comparable_fields = ["type", "nullable", "default", "primary_key", "autoincrement"]

        for field in comparable_fields:
            if str(old_col.get(field, "")).lower() != str(new_col.get(field, "")).lower():
                return True

        return False

    def _analyze_column_modification(self, old_col: Dict[str, Any],
                                   new_col: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the specific modifications in a column."""
        modifications = {}

        # Type changes
        if old_col.get("type") != new_col.get("type"):
            modifications["type_changed"] = {
                "from": old_col.get("type"),
                "to": new_col.get("type")
            }
            modifications["conversion_required"] = True
            modifications["breaking"] = self._is_type_change_breaking(
                old_col.get("type"), new_col.get("type")
            )

        # Nullability changes
        if old_col.get("nullable") != new_col.get("nullable"):
            modifications["nullability_changed"] = {
                "from": old_col.get("nullable"),
                "to": new_col.get("nullable")
            }
            if old_col.get("nullable") and not new_col.get("nullable"):
                modifications["breaking"] = True

        # Default value changes
        if old_col.get("default") != new_col.get("default"):
            modifications["default_changed"] = {
                "from": old_col.get("default"),
                "to": new_col.get("default")
            }

        return modifications

    def _is_type_change_breaking(self, old_type: str, new_type: str) -> bool:
        """Determine if a type change is breaking."""
        if not old_type or not new_type:
            return False

        # Common breaking type changes
        breaking_changes = [
            ("VARCHAR", "INTEGER"),
            ("TEXT", "INTEGER"),
            ("INTEGER", "BOOLEAN"),
            ("DECIMAL", "INTEGER")
        ]

        old_type_upper = str(old_type).upper()
        new_type_upper = str(new_type).upper()

        return (old_type_upper, new_type_upper) in breaking_changes

    def _find_dependent_tables(self, table_name: str, snapshot: SchemaSnapshot) -> List[str]:
        """Find tables that depend on the given table."""
        dependent_tables = []

        for other_table_name, other_table_info in snapshot.tables.items():
            if other_table_name == table_name:
                continue

            # Check foreign keys
            for fk in other_table_info.get("foreign_keys", []):
                if fk.get("referred_table") == table_name:
                    dependent_tables.append(other_table_name)
                    break

        return dependent_tables

    def _find_column_constraints(self, table_name: str, column_name: str,
                               column_info: Dict[str, Any]) -> List[str]:
        """Find constraints that depend on a column."""
        constraints = []

        if column_info.get("primary_key"):
            constraints.append("PRIMARY KEY")

        if column_info.get("unique"):
            constraints.append("UNIQUE")

        # Would need to check foreign keys that reference this column
        # This is simplified - real implementation would query constraint information

        return constraints