# Extended Fields Documentation

Comprehensive documentation for PgAppForge's extended field types, showcasing 24 advanced widgets for modern web applications.

## Table of Contents

1. [Core Extended Fields (14)](#core-extended-fields)
2. [Advanced Extended Fields (10)](#advanced-extended-fields)
3. [Integration Guide](#integration-guide)
4. [Configuration Reference](#configuration-reference)

---

## Core Extended Fields

### 1. RichTextEditorField

**Purpose**: WYSIWYG text editing with advanced formatting capabilities

**Features**:
- Multiple editor backends (TinyMCE, CKEditor, Quill, Summernote)
- Rich formatting: bold, italic, headers, lists, tables
- Media insertion: images, videos, links
- Real-time word/character count and reading time estimation
- Image and link extraction for metadata
- HTML content validation and sanitization

**Use Cases**:
- Blog post content
- Product descriptions
- Email templates
- Documentation writing
- News articles

**Configuration Options**:
```python
RichTextEditorField(
    editor_type=EditorType.TINYMCE,  # or CKEDITOR, QUILL, SUMMERNOTE
    height=300,  # Editor height in pixels
    validators=[RichTextValidator(max_words=1000, max_chars=5000)]
)
```

**Technical Specifications**:
- Data Storage: JSON with content, metadata, and statistics
- Validation: Word count, character limits, allowed HTML tags
- Export: HTML, Markdown, Plain text
- Performance: Debounced input handling, lazy loading of editors

---

### 2. CodeEditorField

**Purpose**: Syntax-highlighted code editing with IDE-like features

**Features**:
- 20+ programming languages support
- Monaco Editor (VS Code engine) or CodeMirror backend
- Syntax highlighting and error detection
- Code formatting and auto-completion
- Multiple themes (light, dark, high contrast)
- Line numbers, word wrap, and minimap
- Fullscreen editing mode

**Use Cases**:
- Configuration files
- SQL queries
- JavaScript/Python code snippets
- JSON/YAML editing
- Template editing

**Configuration Options**:
```python
CodeEditorField(
    language=CodeLanguage.PYTHON,
    theme="vs-dark",
    validators=[CodeValidator(max_lines=500, syntax_check=True)]
)
```

**Technical Specifications**:
- Data Storage: JSON with code, language, theme, and settings
- Validation: Syntax checking, line count limits
- Export: Raw code, formatted code, syntax-highlighted HTML
- Performance: Lazy loading, virtual scrolling for large files

---

### 3. DateTimePickerField

**Purpose**: Advanced date and time selection with timezone support

**Features**:
- Date, time, and datetime modes
- Timezone selection and conversion
- Multiple date formats and locales
- Calendar type support (Gregorian, etc.)
- Real-time format preview
- Keyboard navigation and accessibility

**Use Cases**:
- Event scheduling
- Appointment booking
- Log timestamps
- International applications
- Deadline management

**Configuration Options**:
```python
DateTimePickerField(
    include_time=True,
    include_timezone=True,
    validators=[DateRange(min=datetime.now())]
)
```

**Technical Specifications**:
- Data Storage: JSON with datetime, timezone, format, and locale
- Validation: Date ranges, business hours, timezone validation
- Export: ISO format, localized strings, Unix timestamps
- Performance: Efficient timezone conversion, cached locale data

---

### 4. ColorPickerField

**Purpose**: Comprehensive color selection with multiple format support

**Features**:
- Color picker with visual interface
- Multiple formats: HEX, RGB, RGBA, HSL, HSLA
- Alpha channel support for transparency
- Color swatches and palette management
- Eyedropper tool (where supported)
- Color name suggestions

**Use Cases**:
- Theme customization
- Brand color selection
- UI design tools
- Chart color schemes
- Image editing

**Configuration Options**:
```python
ColorPickerField(
    include_alpha=True,
    show_swatches=True,
    validators=[ColorValidator(allowed_formats=['hex', 'rgb'])]
)
```

**Technical Specifications**:
- Data Storage: JSON with hex, RGB, HSL values and alpha
- Validation: Format validation, color space constraints
- Export: CSS color strings, image swatches
- Performance: Real-time color conversion, optimized rendering

---

### 5. SignatureField

**Purpose**: Digital signature capture for legal and authentication purposes

**Features**:
- Touch and mouse signature capture
- Customizable pen size and color
- Undo/redo functionality
- Canvas size configuration
- Multiple export formats (PNG, SVG, JPEG)
- Metadata capture (timestamp, IP, user agent)

**Use Cases**:
- Legal document signing
- Terms of service acceptance
- Delivery confirmations
- Medical consent forms
- Financial agreements

**Configuration Options**:
```python
SignatureField(
    width=600,
    height=200,
    validators=[SignatureValidator(required=True)]
)
```

**Technical Specifications**:
- Data Storage: Base64 encoded image with metadata
- Validation: Signature presence, image quality
- Export: PNG, SVG, JPEG, PDF embedding
- Performance: Optimized canvas rendering, stroke smoothing

---

### 6. RatingField

**Purpose**: Star ratings with review capabilities and analytics

**Features**:
- Configurable star count (1-10)
- Half-star precision
- Review text with character limits
- Rating analytics and aggregation
- Verified reviewer badges
- Helpful/unhelpful voting

**Use Cases**:
- Product reviews
- Service feedback
- Content rating
- Employee evaluations
- Survey responses

**Configuration Options**:
```python
RatingField(
    max_rating=5,
    allow_half_stars=True,
    show_review=True,
    validators=[RatingValidator(min_rating=1)]
)
```

**Technical Specifications**:
- Data Storage: JSON with rating, review, metadata, and verification
- Validation: Rating range, review length, profanity filtering
- Export: Rating statistics, review exports
- Performance: Efficient aggregation, cached calculations

---

### 7. QRCodeField

**Purpose**: QR code generation and scanning capabilities

**Features**:
- Dynamic QR code generation
- Customizable size and error correction
- QR code scanning with camera
- Batch QR code processing
- Multiple data types (URL, text, contact, WiFi)
- Download and sharing options

**Use Cases**:
- Contact information sharing
- WiFi credentials
- Payment links
- Event tickets
- Inventory tracking

**Configuration Options**:
```python
QRCodeField(
    size=200,
    allow_scanning=True,
    validators=[QRValidator(max_content_length=1000)]
)
```

**Technical Specifications**:
- Data Storage: JSON with content and QR image data
- Validation: Content length, format validation
- Export: PNG, SVG, PDF formats
- Performance: Cached QR generation, optimized scanning

---

### 8. FileUploadField

**Purpose**: Advanced file upload with comprehensive validation and processing

**Features**:
- Drag-and-drop interface
- Multiple file selection
- Upload progress tracking
- File type and size validation
- Virus scanning integration
- Thumbnail generation for images
- Chunked upload for large files

**Use Cases**:
- Document management
- Image galleries
- Media libraries
- Report attachments
- Bulk data imports

**Configuration Options**:
```python
FileUploadField(
    max_files=5,
    max_size_mb=50,
    allowed_types=['image/*', 'application/pdf'],
    validators=[FileValidator(virus_scan=True)]
)
```

**Technical Specifications**:
- Data Storage: File metadata with checksums and scan results
- Validation: MIME type, file size, virus scanning
- Export: File archives, metadata reports
- Performance: Chunked uploads, background processing

---

### 9. JSONEditorField

**Purpose**: Structured JSON editing with schema validation

**Features**:
- Multiple view modes (text, tree, form)
- JSON schema validation
- Syntax highlighting and error detection
- Auto-formatting and minification
- Schema-based form generation
- Import/export capabilities

**Use Cases**:
- Configuration editing
- API payload design
- Data structure definition
- Schema validation
- Dynamic form generation

**Configuration Options**:
```python
JSONEditorField(
    schema={
        "type": "object",
        "properties": {"name": {"type": "string"}}
    },
    height=400,
    validators=[JSONValidator(schema_required=True)]
)
```

**Technical Specifications**:
- Data Storage: Native JSON with validation metadata
- Validation: JSON Schema validation, syntax checking
- Export: JSON, schema, form definitions
- Performance: Incremental validation, lazy rendering

---

### 10. TagField

**Purpose**: Tag selection with autocomplete and categorization

**Features**:
- Autocomplete with suggestions
- Tag categorization and grouping
- Custom tag creation
- Tag validation and restrictions
- Visual tag management
- Bulk tag operations

**Use Cases**:
- Content tagging
- Skill selection
- Category assignment
- Keyword management
- Metadata annotation

**Configuration Options**:
```python
TagField(
    max_tags=10,
    allow_custom=True,
    suggestions=['python', 'flask', 'web'],
    validators=[TagValidator(min_tags=1)]
)
```

**Technical Specifications**:
- Data Storage: JSON array with tag metadata
- Validation: Tag count limits, allowed characters
- Export: Tag lists, category reports
- Performance: Efficient search, cached suggestions

---

### 11. PasswordStrengthField

**Purpose**: Secure password input with strength analysis and generation

**Features**:
- Real-time strength calculation
- Visual strength meter
- Security requirement checking
- Password generation with policies
- Breach detection (HaveIBeenPwned)
- Entropy calculation

**Use Cases**:
- User registration
- Password changes
- Security policies
- Account creation
- Admin password management

**Configuration Options**:
```python
PasswordStrengthField(
    show_suggestions=True,
    show_generator=True,
    validators=[PasswordStrengthValidator(min_score=70)]
)
```

**Technical Specifications**:
- Data Storage: Hashed password with strength metadata
- Validation: Strength scoring, policy compliance
- Export: Strength reports, policy compliance
- Performance: Client-side validation, secure hashing

---

### 12. PhoneNumberField

**Purpose**: International phone number input with comprehensive validation

**Features**:
- International format support
- Country code selection
- Phone number validation
- Carrier detection
- Geographic location info
- Format conversion (national/international)

**Use Cases**:
- Contact forms
- User profiles
- Emergency contacts
- International applications
- Customer databases

**Configuration Options**:
```python
PhoneNumberField(
    default_country='US',
    show_validation=True,
    validators=[PhoneValidator(number_types=['mobile'])]
)
```

**Technical Specifications**:
- Data Storage: JSON with number, country, carrier, and location
- Validation: Phone number format, carrier verification
- Export: Various phone number formats
- Performance: Cached validation, efficient parsing

---

### 13. AddressField

**Purpose**: Structured address input with geocoding and validation

**Features**:
- Address autocomplete
- Geocoding and reverse geocoding
- Map integration and visualization
- Address validation and standardization
- Multiple address formats
- Geographic coordinate capture

**Use Cases**:
- Shipping addresses
- Business locations
- Event venues
- Service areas
- Geographic data collection

**Configuration Options**:
```python
AddressField(
    include_geocoding=True,
    country_default='US',
    validators=[AddressValidator(require_valid_address=True)]
)
```

**Technical Specifications**:
- Data Storage: JSON with address components and coordinates
- Validation: Address format, geocoding verification
- Export: Formatted addresses, coordinate data
- Performance: Cached geocoding, optimized API calls

---

### 14. DrawingField

**Purpose**: Digital drawing and sketching with professional tools

**Features**:
- Multiple drawing tools (pen, brush, shapes)
- Layer management
- Undo/redo with history
- Color palette and brush settings
- Export to multiple formats
- Touch and stylus support

**Use Cases**:
- Digital art creation
- Diagram sketching
- Signature capture
- Annotation tools
- Creative applications

**Configuration Options**:
```python
DrawingField(
    width=800,
    height=600,
    tools=['pen', 'brush', 'eraser', 'shapes'],
    validators=[DrawingValidator(max_layers=10)]
)
```

**Technical Specifications**:
- Data Storage: SVG or raster data with layer information
- Validation: Canvas size, layer limits, file size
- Export: PNG, SVG, PDF formats
- Performance: Optimized rendering, efficient layer management

---

## Advanced Extended Fields

*Documentation for 10 additional advanced widgets will be added next...*

---

## Integration Guide

### Basic Usage

```python
from pgappforge.fields.extended_fields import (
    RichTextEditorField, CodeEditorField, ColorPickerField
)

class MyForm(FlaskForm):
    description = RichTextEditorField(
        'Description',
        validators=[DataRequired()]
    )
    
    config = CodeEditorField(
        'Configuration',
        language=CodeLanguage.JSON
    )
    
    theme_color = ColorPickerField(
        'Theme Color',
        include_alpha=True
    )
```

### ModelView Integration

```python
class MyModelView(ModelView):
    datamodel = SQLAInterface(MyModel)
    
    edit_form_extra_fields = {
        'description': RichTextEditorField('Description'),
        'config': CodeEditorField('Config', language=CodeLanguage.YAML),
        'signature': SignatureField('Signature', width=400)
    }
```

### Custom Validation

```python
from pgappforge.fields.extended_fields import (
    RichTextValidator, CodeValidator, ColorValidator
)

# Rich text with word limit
description = RichTextEditorField(
    'Description',
    validators=[
        RichTextValidator(max_words=500, allowed_tags=['p', 'b', 'i'])
    ]
)

# Code with syntax checking
script = CodeEditorField(
    'Script',
    validators=[
        CodeValidator(max_lines=100, syntax_check=True)
    ]
)
```

---

## Configuration Reference

### Global Configuration

```python
# config.py
EXTENDED_FIELDS_CONFIG = {
    'RICHTEXT_DEFAULT_EDITOR': 'tinymce',
    'CODE_EDITOR_THEME': 'vs-dark',
    'SIGNATURE_DEFAULT_SIZE': (400, 200),
    'FILE_UPLOAD_MAX_SIZE': 50 * 1024 * 1024,  # 50MB
    'QR_CODE_DEFAULT_SIZE': 200,
    'DATETIME_DEFAULT_TIMEZONE': 'UTC',
    'PHONE_DEFAULT_COUNTRY': 'US',
    'MAP_DEFAULT_PROVIDER': 'leaflet'
}
```

### CSS and JavaScript Inclusion

```html
<!-- Include extended fields assets -->
<link rel="stylesheet" href="{{ url_for('appbuilder.static', filename='css/extended-fields.css') }}">
<script src="{{ url_for('appbuilder.static', filename='js/extended-fields.js') }}"></script>
```

### Performance Optimization

```python
# Lazy loading configuration
EXTENDED_FIELDS_LAZY_LOAD = True

# CDN configuration for editor libraries
EXTENDED_FIELDS_CDN = {
    'tinymce': 'https://cdn.tiny.cloud/1/your-api-key/tinymce/5/tinymce.min.js',
    'monaco': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.34.0/min/vs',
    'leaflet': 'https://unpkg.com/leaflet@1.7.1/dist/leaflet.js'
}
```

This comprehensive documentation provides detailed information about each widget's capabilities, use cases, and integration methods. The fields offer professional-grade functionality that significantly enhances PgAppForge's capabilities for modern web applications.