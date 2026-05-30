# Enhanced View Generation Guide

PgForge's enhanced view generation system provides sophisticated master-detail views, inline formsets, and relationship-specific views that dramatically improve the user experience for complex data relationships.

## Table of Contents

1. [Overview](#overview)
2. [Master-Detail Views](#master-detail-views)
3. [Inline Formsets](#inline-formsets)
4. [Relationship Views](#relationship-views)
5. [CLI Usage](#cli-usage)
6. [Configuration](#configuration)
7. [Examples](#examples)
8. [Best Practices](#best-practices)

## Overview

The enhanced view generation system automatically detects relationship patterns in your database and generates appropriate view types:

### New View Types

- **Master-Detail Views**: Parent records with inline child record editing
- **Lookup Views**: Advanced filtering for tables with multiple foreign keys
- **Reference Views**: Grouped views showing records organized by relationships
- **Relationship Navigation Views**: Dashboard views for exploring complex relationships

### Key Features

- **Intelligent Pattern Detection**: Automatically identifies suitable master-detail patterns
- **Multiple Layout Options**: Stacked, tabular, and accordion layouts for inline forms
- **Transaction-Safe Operations**: Proper error handling and rollback support
- **Responsive Design**: Mobile-friendly layouts with modern UI components
- **Bulk Operations**: Support for bulk editing and deletion of child records

## Master-Detail Views

Master-detail views allow users to edit parent records along with their related child records in a single, integrated interface.

### Pattern Detection

The system automatically detects suitable master-detail patterns based on:

- **Relationship Type**: One-to-many relationships
- **Child Table Complexity**: 2-15 non-system columns
- **Foreign Key Count**: Not more than 3 foreign keys in child table
- **Parent Display Fields**: Parent has identifiable display fields (name, title, etc.)

### Example: Customer-Orders Master-Detail

```python
# Generated master-detail view for Customer with Orders
class CustomerOrdersMasterDetailView(ModelView):
    datamodel = SQLAInterface(Customer)
    
    # Inline configuration
    inline_models = [Order]
    inline_formset_config = {
        'default_count': 3,
        'min_forms': 1,
        'max_forms': 10,
        'layout': 'stacked',
        'enable_sorting': True,
        'enable_deletion': True
    }
    
    @expose('/edit/<pk>', methods=['GET', 'POST'])  
    def edit(self, pk):
        # Handle master record with inline child forms
        # Transaction-safe updates with validation
        pass
```

### UI Layouts

#### Stacked Layout
- Each child record in a separate card
- Best for complex child forms (5+ fields)
- Expandable/collapsible sections

#### Tabular Layout  
- Child records in a table format
- Best for simple child forms (2-4 fields)
- Bulk editing capabilities

#### Accordion Layout
- Child records in accordion panels
- Best for moderate complexity (4-8 fields)
- Space-efficient display

## Inline Formsets

Inline formsets provide dynamic form management for child records.

### Features

- **Dynamic Addition**: Add new child forms without page refresh
- **Soft Deletion**: Mark records for deletion without losing data
- **Validation**: Client-side and server-side validation
- **Reordering**: Drag-and-drop reordering (when enabled)
- **Bulk Operations**: Select and modify multiple records

### JavaScript Integration

```javascript
// Automatic form management
document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('inline-forms');
    const addBtn = document.querySelector('.add-form-btn');
    let formCount = 3; // Default count
    
    addBtn.addEventListener('click', function() {
        if (formCount < maxForms) {
            addForm(formCount++);
        }
    });
});
```

### Form Template Example

```html
<!-- Stacked layout template -->
<div class="child-form card mb-3" data-form-index="__prefix__">
    <div class="card-header">
        <h5 class="card-title">Order #<span class="form-number">__prefix__</span></h5>
        <button type="button" class="btn btn-sm btn-danger remove-form">
            <i class="fa fa-trash"></i> Remove
        </button>
    </div>
    <div class="card-body">
        <!-- Dynamic form fields -->
        <input type="hidden" name="orders-__prefix__-DELETE" value="false">
    </div>
</div>
```

## Relationship Views

### Lookup Views

For tables with multiple foreign keys, providing advanced filtering:

```python
class InvoiceLookupView(ModelView):
    datamodel = SQLAInterface(Invoice)
    
    # Enhanced search with relationship filters
    search_form_query_rel_fields = {
        'customer': [['name', FilterStartsWith, '']],
        'project': [['name', FilterStartsWith, '']],
        'employee': [['name', FilterStartsWith, '']],
    }
    
    # Quick lookup methods
    @expose('/lookup_by/<relation>/<pk>')
    def lookup_by_relation(self, relation, pk):
        return redirect(url_for('.list', **{f'_flt_0_{relation}': pk}))
```

### Reference Views

Organize records by their relationships:

```python
class OrdersByCustomerView(ModelView):
    datamodel = SQLAInterface(Order)
    
    # Emphasize the relationship grouping
    list_columns = ['customer', 'order_date', 'total_amount', 'status']
    base_order = ('customer', 'asc')
    
    @expose('/by_customer/<pk>')
    def filter_by_customer(self, pk):
        return redirect(url_for('.list', _flt_0_customer=pk))
```

### Relationship Navigation Views

Dashboard for exploring complex relationships:

```python
class CustomerRelationshipView(BaseView):
    @expose('/')
    def index(self):
        # Relationship statistics and navigation
        return self.render_template(
            'relationship_navigation.html',
            relationship_stats=self._get_relationship_stats()
        )
    
    @expose('/matrix')
    def relationship_matrix(self):
        # Interactive relationship matrix
        return self.render_template(
            'relationship_matrix.html',
            matrix_data=self._build_matrix_data()
        )
```

## CLI Usage

### Basic Generation

```bash
# Generate views with all enhancements
flask fab gen view --uri postgresql://user:pass@localhost/mydb \
                   --output-dir ./generated_views \
                   --include-master-detail \
                   --include-lookup-views \
                   --include-reference-views

# Generate with specific inline layout
flask fab gen view --uri sqlite:///app.db \
                   --output-dir ./views \
                   --inline-form-layout tabular \
                   --max-inline-forms 25
```

### Advanced Options

```bash
# Full feature generation
flask fab gen view \
  --uri postgresql://user:pass@localhost/db \
  --output-dir ./generated_views \
  --modern-widgets \
  --include-api \
  --include-charts \
  --include-calendar \
  --include-master-detail \
  --include-lookup-views \
  --include-reference-views \
  --include-relationship-views \
  --inline-form-layout accordion \
  --max-inline-forms 50 \
  --theme modern \
  --verbose
```

## Configuration

### ViewGenerationConfig Options

```python
config = ViewGenerationConfig(
    # Standard view options
    use_modern_widgets=True,
    generate_api_views=True,
    generate_chart_views=True,
    generate_calendar_views=True,
    
    # Master-detail options
    generate_master_detail_views=True,
    enable_inline_formsets=True,
    max_inline_forms=50,
    inline_form_layouts=['stacked', 'tabular', 'accordion'],
    
    # Relationship view options
    generate_lookup_views=True,
    generate_reference_views=True,
    generate_relationship_views=True,
    
    # UI options
    theme='modern',
    responsive_design=True,
    enable_real_time=True
)
```

### Database Inspector Settings

```python
# Custom master-detail detection
inspector = EnhancedDatabaseInspector(database_uri)

# Analyze specific table for patterns
patterns = inspector.analyze_master_detail_patterns('customers')

# Get relationship view variations
variations = inspector.get_relationship_view_variations('invoices')
```

## Examples

### E-commerce System

**Tables**: `customers`, `orders`, `order_items`, `products`

**Generated Views**:
- `CustomerOrdersMasterDetailView`: Edit customers with inline orders
- `OrderOrderItemsMasterDetailView`: Edit orders with inline order items
- `OrdersLookupView`: Advanced order filtering by customer/product
- `OrdersByCustomerView`: Orders grouped by customer

### Project Management System

**Tables**: `companies`, `projects`, `tasks`, `time_entries`, `employees`

**Generated Views**:
- `CompanyProjectsMasterDetailView`: Companies with inline projects
- `ProjectTasksMasterDetailView`: Projects with inline tasks
- `TaskTimeEntriesMasterDetailView`: Tasks with inline time entries
- `ProjectsLookupView`: Filter projects by company/employee
- `CompanyRelationshipView`: Explore all company relationships

### CRM System

**Tables**: `contacts`, `companies`, `opportunities`, `activities`

**Generated Views**:
- `ContactActivitiesMasterDetailView`: Contacts with inline activities
- `CompanyOpportunitiesMasterDetailView`: Companies with opportunities
- `OpportunitiesLookupView`: Advanced opportunity filtering
- `ContactsByCompanyView`: Contacts grouped by company

## Best Practices

### Master-Detail Design

1. **Limit Child Complexity**: Keep inline forms to 5-8 fields maximum
2. **Use Appropriate Layouts**: 
   - Stacked: Complex forms with multiple field types
   - Tabular: Simple, uniform data entry
   - Accordion: Moderate complexity with grouping
3. **Set Reasonable Limits**: Configure `max_inline_forms` based on expected usage
4. **Provide Validation**: Implement both client-side and server-side validation

### Performance Considerations

1. **Limit Initial Forms**: Set `default_child_count` to 3-5 for better performance
2. **Use Pagination**: For large datasets, implement pagination in list views
3. **Optimize Queries**: Use `select_related` and `prefetch_related` for relationships
4. **Cache Templates**: Enable template caching for better performance

### User Experience

1. **Clear Navigation**: Provide breadcrumbs and back buttons
2. **Visual Feedback**: Show loading states and validation messages
3. **Responsive Design**: Ensure forms work well on mobile devices
4. **Keyboard Support**: Enable keyboard navigation for accessibility

### Security

1. **Validate Relationships**: Ensure users can only edit records they own
2. **CSRF Protection**: Include CSRF tokens in all forms
3. **Permission Checks**: Validate permissions for each inline operation
4. **Data Sanitization**: Sanitize all user inputs

## Troubleshooting

### Common Issues

#### Master-Detail View Not Generated
- Check if relationship is one-to-many
- Verify child table has 2-15 non-system columns
- Ensure parent table has identifiable display fields

#### Inline Forms Not Working
- Verify JavaScript files are loaded
- Check for JavaScript console errors
- Ensure form field names match expected pattern

#### Performance Issues
- Reduce `max_inline_forms` setting
- Implement field-level caching
- Optimize database queries with proper indexing

### Debug Tips

1. **Enable Verbose Output**: Use `--verbose` flag for detailed generation logs
2. **Check Generated Templates**: Verify HTML templates are created correctly
3. **Test with Small Datasets**: Start with limited data for testing
4. **Use Browser DevTools**: Debug JavaScript form management issues

## Migration Guide

### From Basic Views

1. **Backup Existing Views**: Save current view implementations
2. **Generate Enhanced Views**: Use new CLI commands
3. **Update Templates**: Copy new templates to your application
4. **Test Functionality**: Verify all features work as expected
5. **Update Navigation**: Add new views to your application menus

### Customization

1. **Override Templates**: Customize HTML templates for your needs
2. **Extend View Classes**: Add custom methods to generated view classes
3. **Modify Configurations**: Adjust inline formset settings
4. **Add Custom Validation**: Implement domain-specific validation rules

## API Reference

### Database Inspector Methods

```python
inspector.analyze_master_detail_patterns(table_name: str) -> List[MasterDetailInfo]
inspector.get_relationship_view_variations(table_name: str) -> Dict[str, List[str]]
inspector._analyze_master_detail_suitability(...) -> Optional[MasterDetailInfo]
```

### View Generator Methods

```python
generator.generate_master_detail_views(table_info: TableInfo) -> Dict[str, str]
generator.generate_lookup_view(table_info: TableInfo) -> str
generator.generate_reference_views(table_info: TableInfo) -> Dict[str, str]
generator.generate_relationship_navigation_view(table_info: TableInfo) -> str
```

### Configuration Classes

```python
@dataclass
class MasterDetailInfo:
    parent_table: str
    child_table: str
    relationship: RelationshipInfo
    is_suitable_for_inline: bool
    expected_child_count: str
    child_display_fields: List[str]
    parent_display_fields: List[str]
    inline_edit_suitable: bool
    supports_bulk_operations: bool
    default_child_count: int
    min_child_forms: int
    max_child_forms: int
    enable_sorting: bool
    enable_deletion: bool
    child_form_layout: str
```

## Support

For additional support and examples, see:

- [PgForge Documentation](http://flask-appbuilder.readthedocs.org/)
- [Enhanced View Generation Demo](../examples/enhanced_view_generation_demo.py)
- [Test Suite](../tests/test_enhanced_view_generation.py)
- [GitHub Issues](https://github.com/dpgaspar/PgForge/issues)