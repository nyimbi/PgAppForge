"""
Extended Field Types for PgForge

Comprehensive collection of advanced field types for modern web applications:
- RichTextEditorField: WYSIWYG editor with formatting, media, tables
- CodeEditorField: Syntax highlighting for multiple programming languages  
- DateTimePickerField: Advanced date/time selection with timezone support
- ColorPickerField: Color selection with multiple formats and palettes
- SignatureField: Digital signature capture with touch/mouse support
- RatingField: Star ratings with reviews and analytics
- QRCodeField: QR code generation and scanning capabilities
- FileUploadField: Advanced file upload with progress and validation
- JSONEditorField: Structured JSON editing with schema validation
- TagField: Tag selection with autocomplete and categorization
- PasswordStrengthField: Password input with strength indicators
- PhoneNumberField: International phone number input with validation
- AddressField: Structured address input with geocoding
- DrawingField: Digital drawing canvas with layers and tools
"""

import json
import base64
import re
import hashlib
import secrets
from typing import Optional, Dict, Any, List, Union, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import phonenumbers
from phonenumbers import geocoder, carrier

from wtforms import Field, ValidationError, StringField, TextAreaField
from wtforms.widgets import HTMLString, html_params
from markupsafe import Markup
from sqlalchemy import TypeDecorator, Text, JSON, DateTime
from sqlalchemy.ext.mutable import MutableDict, MutableList

from flask import current_app, url_for, request
from flask_babel import gettext as __, lazy_gettext as _l


class EditorType(Enum):
    """Rich text editor types."""
    TINYMCE = "tinymce"
    CKEDITOR = "ckeditor"
    QUILL = "quill"
    SUMMERNOTE = "summernote"


class CodeLanguage(Enum):
    """Supported programming languages for code editor."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    HTML = "html"
    CSS = "css"
    JAVA = "java"
    CSHARP = "csharp"
    CPP = "cpp"
    C = "c"
    GO = "go"
    RUST = "rust"
    PHP = "php"
    RUBY = "ruby"
    SQL = "sql"
    JSON = "json"
    XML = "xml"
    YAML = "yaml"
    MARKDOWN = "markdown"
    SHELL = "shell"
    DOCKERFILE = "dockerfile"


class ColorFormat(Enum):
    """Color format types."""
    HEX = "hex"
    RGB = "rgb"
    RGBA = "rgba"
    HSL = "hsl"
    HSLA = "hsla"


class SignatureFormat(Enum):
    """Signature output formats."""
    PNG = "image/png"
    SVG = "image/svg+xml"
    JPEG = "image/jpeg"


@dataclass
class RichTextData:
    """Rich text content with metadata."""
    content: str
    format: str = "html"  # html, markdown, delta
    word_count: int = 0
    character_count: int = 0
    reading_time: int = 0  # minutes
    images: List[str] = None
    links: List[str] = None
    created_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.created_at:
            result['created_at'] = self.created_at.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RichTextData':
        """Create from dictionary."""
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


@dataclass
class CodeData:
    """Code content with metadata."""
    code: str
    language: str
    theme: str = "vs-dark"
    line_numbers: bool = True
    word_wrap: bool = False
    font_size: int = 14
    tab_size: int = 4
    syntax_errors: List[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodeData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class DateTimeData:
    """Date/time data with timezone support."""
    datetime: datetime
    timezone: str
    format: str = "YYYY-MM-DD HH:mm:ss"
    locale: str = "en"
    calendar_type: str = "gregorian"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'datetime': self.datetime.isoformat(),
            'timezone': self.timezone,
            'format': self.format,
            'locale': self.locale,
            'calendar_type': self.calendar_type
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DateTimeData':
        """Create from dictionary."""
        dt_str = data['datetime']
        dt = datetime.fromisoformat(dt_str)
        return cls(
            datetime=dt,
            timezone=data['timezone'],
            format=data.get('format', "YYYY-MM-DD HH:mm:ss"),
            locale=data.get('locale', "en"),
            calendar_type=data.get('calendar_type', "gregorian")
        )


@dataclass
class ColorData:
    """Color data with multiple format support."""
    hex: str
    rgb: Tuple[int, int, int]
    hsl: Tuple[int, int, int]
    alpha: float = 1.0
    name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ColorData':
        """Create from dictionary."""
        return cls(**data)
    
    @classmethod
    def from_hex(cls, hex_color: str) -> 'ColorData':
        """Create from hex color."""
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        # Convert RGB to HSL
        r, g, b = [x/255.0 for x in rgb]
        max_val = max(r, g, b)
        min_val = min(r, g, b)
        diff = max_val - min_val
        
        # Lightness
        l = (max_val + min_val) / 2
        
        if diff == 0:
            h = s = 0
        else:
            # Saturation
            s = diff / (2 - max_val - min_val) if l > 0.5 else diff / (max_val + min_val)
            
            # Hue
            if max_val == r:
                h = (g - b) / diff + (6 if g < b else 0)
            elif max_val == g:
                h = (b - r) / diff + 2
            else:
                h = (r - g) / diff + 4
            h /= 6
        
        hsl = (int(h * 360), int(s * 100), int(l * 100))
        
        return cls(
            hex=f"#{hex_color}",
            rgb=rgb,
            hsl=hsl
        )


@dataclass
class SignatureData:
    """Digital signature data."""
    signature_data: str  # Base64 encoded image
    format: str = "image/png"
    width: int = 400
    height: int = 200
    timestamp: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SignatureData':
        """Create from dictionary."""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class RatingData:
    """Rating data with review support."""
    rating: float
    max_rating: int = 5
    review: Optional[str] = None
    reviewer_name: Optional[str] = None
    verified: bool = False
    helpful_votes: int = 0
    total_votes: int = 0
    timestamp: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.timestamp:
            result['timestamp'] = self.timestamp.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RatingData':
        """Create from dictionary."""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class QRCodeData:
    """QR code data."""
    content: str
    qr_code_image: str  # Base64 encoded PNG
    error_correction: str = "M"  # L, M, Q, H
    size: int = 200
    border: int = 4
    format: str = "PNG"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QRCodeData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class FileUploadData:
    """Advanced file upload data."""
    filename: str
    size: int
    mime_type: str
    file_data: str  # Base64 encoded or file path
    upload_progress: float = 100.0
    checksum: Optional[str] = None
    virus_scan_status: str = "pending"  # pending, clean, infected
    upload_timestamp: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.upload_timestamp:
            result['upload_timestamp'] = self.upload_timestamp.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FileUploadData':
        """Create from dictionary."""
        if 'upload_timestamp' in data and isinstance(data['upload_timestamp'], str):
            data['upload_timestamp'] = datetime.fromisoformat(data['upload_timestamp'])
        return cls(**data)


@dataclass
class TagData:
    """Tag data with categorization."""
    tags: List[str]
    categories: Dict[str, List[str]] = None
    suggestions: List[str] = None
    max_tags: int = 10
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TagData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class PasswordStrengthData:
    """Password strength data."""
    password: str
    strength_score: int  # 0-100
    strength_label: str  # Very Weak, Weak, Fair, Good, Strong
    suggestions: List[str]
    has_uppercase: bool = False
    has_lowercase: bool = False
    has_numbers: bool = False
    has_symbols: bool = False
    length: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        # Don't include actual password in output
        result = asdict(self)
        result.pop('password', None)
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PasswordStrengthData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class PhoneNumberData:
    """International phone number data."""
    number: str
    country_code: str
    national_number: str
    international_format: str
    national_format: str
    is_valid: bool
    number_type: str  # mobile, fixed_line, etc.
    carrier: Optional[str] = None
    country_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhoneNumberData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class AddressData:
    """Structured address data."""
    street_address: str
    city: str
    state: str
    postal_code: str
    country: str
    apartment: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    plus_code: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AddressData':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class DrawingData:
    """Digital drawing data."""
    drawing_data: str  # SVG or base64 image
    width: int = 800
    height: int = 600
    background_color: str = "#ffffff"
    brush_size: int = 2
    brush_color: str = "#000000"
    layers: List[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DrawingData':
        """Create from dictionary."""
        return cls(**data)


# SQLAlchemy Type Decorators for new field types
class RichTextType(TypeDecorator):
    """SQLAlchemy type for rich text data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, RichTextData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return RichTextData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class CodeType(TypeDecorator):
    """SQLAlchemy type for code data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, CodeData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return CodeData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class ColorType(TypeDecorator):
    """SQLAlchemy type for color data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, ColorData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return ColorData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class SignatureType(TypeDecorator):
    """SQLAlchemy type for signature data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, SignatureData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return SignatureData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class PhoneNumberType(TypeDecorator):
    """SQLAlchemy type for phone number data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, PhoneNumberData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return PhoneNumberData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


class AddressType(TypeDecorator):
    """SQLAlchemy type for address data."""
    impl = Text
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, AddressData):
                return json.dumps(value.to_dict())
            elif isinstance(value, dict):
                return json.dumps(value)
            elif isinstance(value, str):
                return value
        return value
    
    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                data = json.loads(value) if isinstance(value, str) else value
                return AddressData.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return value
        return value


# Utility functions
def calculate_password_strength(password: str) -> PasswordStrengthData:
    """Calculate password strength score and suggestions."""
    length = len(password)
    has_upper = bool(re.search(r'[A-Z]', password))
    has_lower = bool(re.search(r'[a-z]', password))
    has_numbers = bool(re.search(r'\d', password))
    has_symbols = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
    
    score = 0
    suggestions = []
    
    # Length scoring
    if length >= 12:
        score += 25
    elif length >= 8:
        score += 15
    else:
        suggestions.append(__("Use at least 8 characters"))
    
    # Character type scoring
    if has_upper:
        score += 15
    else:
        suggestions.append(__("Include uppercase letters"))
    
    if has_lower:
        score += 15
    else:
        suggestions.append(__("Include lowercase letters"))
    
    if has_numbers:
        score += 15
    else:
        suggestions.append(__("Include numbers"))
    
    if has_symbols:
        score += 20
    else:
        suggestions.append(__("Include special characters"))
    
    # Common patterns penalty
    common_patterns = ['123', 'abc', 'password', 'admin', 'user']
    for pattern in common_patterns:
        if pattern.lower() in password.lower():
            score -= 10
            suggestions.append(__("Avoid common patterns"))
            break
    
    # Sequential characters penalty
    if re.search(r'(.)\1{2,}', password):
        score -= 5
        suggestions.append(__("Avoid repeating characters"))
    
    score = max(0, min(100, score))
    
    if score >= 90:
        strength_label = __("Very Strong")
    elif score >= 70:
        strength_label = __("Strong")
    elif score >= 50:
        strength_label = __("Good")
    elif score >= 30:
        strength_label = __("Fair")
    else:
        strength_label = __("Weak")
    
    return PasswordStrengthData(
        password=password,
        strength_score=score,
        strength_label=strength_label,
        suggestions=suggestions,
        has_uppercase=has_upper,
        has_lowercase=has_lower,
        has_numbers=has_numbers,
        has_symbols=has_symbols,
        length=length
    )


def parse_phone_number(phone_str: str, country_code: str = None) -> PhoneNumberData:
    """Parse and validate international phone number."""
    try:
        parsed = phonenumbers.parse(phone_str, country_code)
        is_valid = phonenumbers.is_valid_number(parsed)
        
        if is_valid:
            country_code = phonenumbers.region_code_for_number(parsed)
            national_number = str(parsed.national_number)
            international_format = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            national_format = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
            number_type = phonenumbers.number_type(parsed)
            
            # Get carrier and country info
            carrier_name = carrier.name_for_number(parsed, 'en')
            country_name = geocoder.description_for_number(parsed, 'en')
            
            type_mapping = {
                phonenumbers.PhoneNumberType.MOBILE: 'mobile',
                phonenumbers.PhoneNumberType.FIXED_LINE: 'fixed_line',
                phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: 'fixed_line_or_mobile',
                phonenumbers.PhoneNumberType.TOLL_FREE: 'toll_free',
                phonenumbers.PhoneNumberType.PREMIUM_RATE: 'premium_rate',
                phonenumbers.PhoneNumberType.SHARED_COST: 'shared_cost',
                phonenumbers.PhoneNumberType.VOIP: 'voip',
                phonenumbers.PhoneNumberType.PERSONAL_NUMBER: 'personal_number',
                phonenumbers.PhoneNumberType.PAGER: 'pager',
                phonenumbers.PhoneNumberType.UAN: 'uan',
                phonenumbers.PhoneNumberType.VOICEMAIL: 'voicemail',
                phonenumbers.PhoneNumberType.UNKNOWN: 'unknown'
            }
            
            return PhoneNumberData(
                number=phone_str,
                country_code=country_code,
                national_number=national_number,
                international_format=international_format,
                national_format=national_format,
                is_valid=is_valid,
                number_type=type_mapping.get(number_type, 'unknown'),
                carrier=carrier_name,
                country_name=country_name
            )
        else:
            return PhoneNumberData(
                number=phone_str,
                country_code="",
                national_number="",
                international_format="",
                national_format="",
                is_valid=False,
                number_type="invalid"
            )
    
    except phonenumbers.NumberParseException:
        return PhoneNumberData(
            number=phone_str,
            country_code="",
            national_number="",
            international_format="",
            national_format="",
            is_valid=False,
            number_type="invalid"
        )


def generate_qr_code(content: str, size: int = 200, error_correction: str = "M") -> QRCodeData:
    """Generate QR code from content."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
        import io
        
        error_levels = {
            'L': ERROR_CORRECT_L,
            'M': ERROR_CORRECT_M,
            'Q': ERROR_CORRECT_Q,
            'H': ERROR_CORRECT_H
        }
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=error_levels.get(error_correction, ERROR_CORRECT_M),
            box_size=10,
            border=4,
        )
        qr.add_data(content)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size))
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_code_image = base64.b64encode(buffer.getvalue()).decode()
        
        return QRCodeData(
            content=content,
            qr_code_image=qr_code_image,
            error_correction=error_correction,
            size=size,
            format="PNG"
        )
        
    except ImportError:
        # Fallback if qrcode library not available
        return QRCodeData(
            content=content,
            qr_code_image="",
            error_correction=error_correction,
            size=size,
            format="PNG"
        )


def calculate_file_checksum(file_data: bytes) -> str:
    """Calculate SHA-256 checksum of file data."""
    return hashlib.sha256(file_data).hexdigest()


def analyze_rich_text(content: str) -> RichTextData:
    """Analyze rich text content for metadata."""
    # Remove HTML tags for word count
    import re
    text_only = re.sub(r'<[^>]+>', '', content)
    
    word_count = len(text_only.split())
    character_count = len(text_only)
    reading_time = max(1, word_count // 200)  # Assume 200 words per minute
    
    # Extract images and links
    images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', content)
    links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', content)
    
    return RichTextData(
        content=content,
        format="html",
        word_count=word_count,
        character_count=character_count,
        reading_time=reading_time,
        images=images,
        links=links,
        created_at=datetime.now()
    )


# ========================================
# Widget Classes
# ========================================

class RichTextEditorWidget:
    """Widget for rich text editor with WYSIWYG capabilities."""
    
    def __init__(self, editor_type: EditorType = EditorType.TINYMCE, height: int = 300):
        self.editor_type = editor_type
        self.height = height
    
    def __call__(self, field, **kwargs):
        """Render the rich text editor widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, RichTextData):
                content = field.data.content
            elif isinstance(field.data, dict):
                content = field.data.get('content', '')
            else:
                content = str(field.data)
        else:
            content = ''
        
        # Generate unique editor ID
        editor_id = f"richtext_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="richtext-editor-container" data-editor-type="{self.editor_type.value}">
            <textarea id="{editor_id}" name="{field.name}" 
                      class="richtext-editor" 
                      data-height="{self.height}"
                      {html_params(**kwargs)}>{content}</textarea>
            <input type="hidden" id="{editor_id}_metadata" name="{field.name}_metadata" />
            <div class="richtext-stats">
                <span class="word-count">0 words</span>
                <span class="char-count">0 characters</span>
                <span class="reading-time">0 min read</span>
            </div>
        </div>
        '''
        
        return HTMLString(html)


class CodeEditorWidget:
    """Widget for code editor with syntax highlighting."""
    
    def __init__(self, language: CodeLanguage = CodeLanguage.PYTHON, theme: str = "vs-dark"):
        self.language = language
        self.theme = theme
    
    def __call__(self, field, **kwargs):
        """Render the code editor widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, CodeData):
                code = field.data.code
                language = field.data.language
                theme = field.data.theme
            elif isinstance(field.data, dict):
                code = field.data.get('code', '')
                language = field.data.get('language', self.language.value)
                theme = field.data.get('theme', self.theme)
            else:
                code = str(field.data)
                language = self.language.value
                theme = self.theme
        else:
            code = ''
            language = self.language.value
            theme = self.theme
        
        editor_id = f"code_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="code-editor-container">
            <div class="code-editor-toolbar">
                <select class="language-selector" data-target="{editor_id}">
                    {self._generate_language_options(language)}
                </select>
                <select class="theme-selector" data-target="{editor_id}">
                    <option value="vs-dark" {"selected" if theme == "vs-dark" else ""}>Dark</option>
                    <option value="vs-light" {"selected" if theme == "vs-light" else ""}>Light</option>
                    <option value="hc-black" {"selected" if theme == "hc-black" else ""}>High Contrast</option>
                </select>
                <button type="button" class="format-code-btn" data-target="{editor_id}">Format</button>
                <button type="button" class="fullscreen-btn" data-target="{editor_id}">Fullscreen</button>
            </div>
            <div id="{editor_id}" class="code-editor" 
                 data-language="{language}" 
                 data-theme="{theme}"
                 data-field-name="{field.name}">{code}</div>
            <input type="hidden" id="{editor_id}_data" name="{field.name}" />
            <div class="code-editor-stats">
                <span class="line-count">0 lines</span>
                <span class="char-count">0 characters</span>
                <span class="syntax-status">✓ No errors</span>
            </div>
        </div>
        '''
        
        return HTMLString(html)
    
    def _generate_language_options(self, selected_language: str) -> str:
        """Generate language selector options."""
        options = []
        for lang in CodeLanguage:
            selected = 'selected' if lang.value == selected_language else ''
            display_name = lang.value.title()
            options.append(f'<option value="{lang.value}" {selected}>{display_name}</option>')
        return '
'.join(options)


class DateTimePickerWidget:
    """Widget for advanced date/time picker with timezone support."""
    
    def __init__(self, include_time: bool = True, include_timezone: bool = True):
        self.include_time = include_time
        self.include_timezone = include_timezone
    
    def __call__(self, field, **kwargs):
        """Render the datetime picker widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, DateTimeData):
                dt_value = field.data.datetime.isoformat()
                timezone_value = field.data.timezone
                format_value = field.data.format
            elif isinstance(field.data, dict):
                dt_value = field.data.get('datetime', '')
                timezone_value = field.data.get('timezone', 'UTC')
                format_value = field.data.get('format', 'YYYY-MM-DD HH:mm:ss')
            else:
                dt_value = str(field.data) if field.data else ''
                timezone_value = 'UTC'
                format_value = 'YYYY-MM-DD HH:mm:ss'
        else:
            dt_value = ''
            timezone_value = 'UTC'
            format_value = 'YYYY-MM-DD HH:mm:ss'
        
        picker_id = f"datetime_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="datetime-picker-container">
            <div class="datetime-input-group">
                <input type="datetime-local" 
                       id="{picker_id}" 
                       class="datetime-picker-input"
                       value="{dt_value}"
                       data-include-time="{str(self.include_time).lower()}"
                       data-include-timezone="{str(self.include_timezone).lower()}" />
        '''
        
        if self.include_timezone:
            html += f'''
                <select class="timezone-selector" data-target="{picker_id}">
                    {self._generate_timezone_options(timezone_value)}
                </select>
            '''
        
        html += f'''
            </div>
            <div class="datetime-format-group">
                <label>Format:</label>
                <select class="format-selector" data-target="{picker_id}">
                    <option value="YYYY-MM-DD HH:mm:ss" {"selected" if format_value == "YYYY-MM-DD HH:mm:ss" else ""}>YYYY-MM-DD HH:mm:ss</option>
                    <option value="MM/DD/YYYY HH:mm:ss" {"selected" if format_value == "MM/DD/YYYY HH:mm:ss" else ""}>MM/DD/YYYY HH:mm:ss</option>
                    <option value="DD/MM/YYYY HH:mm:ss" {"selected" if format_value == "DD/MM/YYYY HH:mm:ss" else ""}>DD/MM/YYYY HH:mm:ss</option>
                    <option value="YYYY-MM-DD" {"selected" if format_value == "YYYY-MM-DD" else ""}>YYYY-MM-DD (Date only)</option>
                </select>
            </div>
            <input type="hidden" id="{picker_id}_data" name="{field.name}" />
            <div class="datetime-preview">
                <span class="formatted-datetime"></span>
            </div>
        </div>
        '''
        
        return HTMLString(html)
    
    def _generate_timezone_options(self, selected_tz: str) -> str:
        """Generate timezone selector options."""
        common_timezones = [
            ('UTC', 'UTC'),
            ('US/Eastern', 'Eastern Time'),
            ('US/Central', 'Central Time'),
            ('US/Mountain', 'Mountain Time'),
            ('US/Pacific', 'Pacific Time'),
            ('Europe/London', 'London'),
            ('Europe/Paris', 'Paris'),
            ('Europe/Berlin', 'Berlin'),
            ('Asia/Tokyo', 'Tokyo'),
            ('Asia/Shanghai', 'Shanghai'),
            ('Asia/Kolkata', 'India'),
            ('Australia/Sydney', 'Sydney'),
        ]
        
        options = []
        for tz_id, tz_name in common_timezones:
            selected = 'selected' if tz_id == selected_tz else ''
            options.append(f'<option value="{tz_id}" {selected}>{tz_name}</option>')
        return '
'.join(options)


class ColorPickerWidget:
    """Widget for color picker with multiple format support."""
    
    def __init__(self, include_alpha: bool = True, show_swatches: bool = True):
        self.include_alpha = include_alpha
        self.show_swatches = show_swatches
    
    def __call__(self, field, **kwargs):
        """Render the color picker widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, ColorData):
                hex_value = field.data.hex
                alpha_value = field.data.alpha
            elif isinstance(field.data, dict):
                hex_value = field.data.get('hex', '#000000')
                alpha_value = field.data.get('alpha', 1.0)
            else:
                hex_value = str(field.data) if field.data else '#000000'
                alpha_value = 1.0
        else:
            hex_value = '#000000'
            alpha_value = 1.0
        
        picker_id = f"color_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="color-picker-container">
            <div class="color-input-group">
                <input type="color" 
                       id="{picker_id}" 
                       class="color-picker-input"
                       value="{hex_value}"
                       data-include-alpha="{str(self.include_alpha).lower()}" />
                <div class="color-preview" style="background-color: {hex_value};"></div>
            </div>
            
            <div class="color-formats">
                <div class="format-group">
                    <label>HEX:</label>
                    <input type="text" class="hex-input" value="{hex_value}" />
                </div>
                <div class="format-group">
                    <label>RGB:</label>
                    <input type="text" class="rgb-input" placeholder="255, 255, 255" />
                </div>
                <div class="format-group">
                    <label>HSL:</label>
                    <input type="text" class="hsl-input" placeholder="360, 100%, 50%" />
                </div>
        '''
        
        if self.include_alpha:
            html += f'''
                <div class="format-group">
                    <label>Alpha:</label>
                    <input type="range" class="alpha-slider" min="0" max="1" step="0.01" value="{alpha_value}" />
                    <span class="alpha-value">{alpha_value}</span>
                </div>
            '''
        
        html += '''
            </div>
        '''
        
        if self.show_swatches:
            html += '''
            <div class="color-swatches">
                <div class="swatch" data-color="#ff0000" style="background-color: #ff0000;"></div>
                <div class="swatch" data-color="#00ff00" style="background-color: #00ff00;"></div>
                <div class="swatch" data-color="#0000ff" style="background-color: #0000ff;"></div>
                <div class="swatch" data-color="#ffff00" style="background-color: #ffff00;"></div>
                <div class="swatch" data-color="#ff00ff" style="background-color: #ff00ff;"></div>
                <div class="swatch" data-color="#00ffff" style="background-color: #00ffff;"></div>
                <div class="swatch" data-color="#000000" style="background-color: #000000;"></div>
                <div class="swatch" data-color="#ffffff" style="background-color: #ffffff;"></div>
            </div>
            '''
        
        html += f'''
            <input type="hidden" id="{picker_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class SignatureWidget:
    """Widget for digital signature capture."""
    
    def __init__(self, width: int = 400, height: int = 200):
        self.width = width
        self.height = height
    
    def __call__(self, field, **kwargs):
        """Render the signature widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, SignatureData):
                signature_data = field.data.signature_data
            elif isinstance(field.data, dict):
                signature_data = field.data.get('signature_data', '')
            else:
                signature_data = str(field.data) if field.data else ''
        else:
            signature_data = ''
        
        canvas_id = f"signature_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="signature-container">
            <div class="signature-toolbar">
                <button type="button" class="clear-signature" data-target="{canvas_id}">Clear</button>
                <button type="button" class="undo-signature" data-target="{canvas_id}">Undo</button>
                <select class="pen-size" data-target="{canvas_id}">
                    <option value="1">Thin</option>
                    <option value="2" selected>Normal</option>
                    <option value="3">Thick</option>
                </select>
                <input type="color" class="pen-color" value="#000000" data-target="{canvas_id}" />
            </div>
            <canvas id="{canvas_id}" 
                    class="signature-canvas"
                    width="{self.width}" 
                    height="{self.height}"
                    data-signature-data="{signature_data}"></canvas>
            <input type="hidden" id="{canvas_id}_data" name="{field.name}" />
            <div class="signature-info">
                <small>Sign above using your mouse or touch</small>
            </div>
        </div>
        '''
        
        return HTMLString(html)


class RatingWidget:
    """Widget for star ratings with reviews."""
    
    def __init__(self, max_rating: int = 5, allow_half_stars: bool = False, show_review: bool = True):
        self.max_rating = max_rating
        self.allow_half_stars = allow_half_stars
        self.show_review = show_review
    
    def __call__(self, field, **kwargs):
        """Render the rating widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, RatingData):
                rating_value = field.data.rating
                review_text = field.data.review or ''
            elif isinstance(field.data, dict):
                rating_value = field.data.get('rating', 0)
                review_text = field.data.get('review', '')
            else:
                rating_value = float(field.data) if field.data else 0
                review_text = ''
        else:
            rating_value = 0
            review_text = ''
        
        rating_id = f"rating_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="rating-container">
            <div class="star-rating" data-rating="{rating_value}" data-max="{self.max_rating}">
        '''
        
        for i in range(1, self.max_rating + 1):
            filled_class = 'filled' if i <= rating_value else ''
            if self.allow_half_stars and (i - 0.5) == rating_value:
                filled_class = 'half-filled'
            
            html += f'''
                <span class="star {filled_class}" data-value="{i}">★</span>
            '''
        
        html += f'''
            </div>
            <div class="rating-value">
                <span class="current-rating">{rating_value}</span> / {self.max_rating}
            </div>
        '''
        
        if self.show_review:
            html += f'''
            <div class="review-section">
                <textarea class="review-text" 
                         placeholder="Write your review..."
                         data-target="{rating_id}">{review_text}</textarea>
            </div>
            '''
        
        html += f'''
            <input type="hidden" id="{rating_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class QRCodeWidget:
    """Widget for QR code generation and scanning."""
    
    def __init__(self, size: int = 200, allow_scanning: bool = True):
        self.size = size
        self.allow_scanning = allow_scanning
    
    def __call__(self, field, **kwargs):
        """Render the QR code widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, QRCodeData):
                content = field.data.content
                qr_image = field.data.qr_code_image
            elif isinstance(field.data, dict):
                content = field.data.get('content', '')
                qr_image = field.data.get('qr_code_image', '')
            else:
                content = str(field.data) if field.data else ''
                qr_image = ''
        else:
            content = ''
            qr_image = ''
        
        qr_id = f"qrcode_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="qrcode-container">
            <div class="qrcode-input-section">
                <label>Content:</label>
                <textarea class="qrcode-content" 
                         data-target="{qr_id}"
                         placeholder="Enter text to generate QR code">{content}</textarea>
                <button type="button" class="generate-qr" data-target="{qr_id}">Generate QR Code</button>
            </div>
            
            <div class="qrcode-display-section">
                <div class="qrcode-preview">
        '''
        
        if qr_image:
            html += f'<img src="data:image/png;base64,{qr_image}" alt="QR Code" />'
        else:
            html += '<div class="qrcode-placeholder">QR Code will appear here</div>'
        
        html += '''
                </div>
                <div class="qrcode-actions">
                    <button type="button" class="download-qr">Download</button>
                    <button type="button" class="copy-qr">Copy</button>
                </div>
            </div>
        '''
        
        if self.allow_scanning:
            html += f'''
            <div class="qrcode-scan-section">
                <button type="button" class="scan-qr" data-target="{qr_id}">Scan QR Code</button>
                <video class="qr-scanner" style="display: none;"></video>
                <canvas class="qr-canvas" style="display: none;"></canvas>
            </div>
            '''
        
        html += f'''
            <input type="hidden" id="{qr_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class FileUploadWidget:
    """Widget for advanced file upload with progress and validation."""
    
    def __init__(self, max_files: int = 1, max_size_mb: int = 10, allowed_types: List[str] = None):
        self.max_files = max_files
        self.max_size_mb = max_size_mb
        self.allowed_types = allowed_types or ['*']
    
    def __call__(self, field, **kwargs):
        """Render the file upload widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        upload_id = f"upload_{field.id}_{secrets.token_hex(4)}"
        accept_attr = ','.join(self.allowed_types) if self.allowed_types != ['*'] else ''
        
        html = f'''
        <div class="file-upload-container">
            <div class="upload-area" data-target="{upload_id}">
                <div class="upload-icon">📁</div>
                <div class="upload-text">
                    <p>Drag & drop files here or <strong>browse</strong></p>
                    <p class="upload-limits">
                        Max {self.max_files} file(s), {self.max_size_mb}MB each
                        {f"<br>Allowed: {', '.join(self.allowed_types)}" if self.allowed_types != ['*'] else ""}
                    </p>
                </div>
                <input type="file" 
                       id="{upload_id}" 
                       class="file-input"
                       {"multiple" if self.max_files > 1 else ""}
                       accept="{accept_attr}"
                       data-max-files="{self.max_files}"
                       data-max-size="{self.max_size_mb * 1024 * 1024}" />
            </div>
            
            <div class="file-list">
                <!-- Uploaded files will appear here -->
            </div>
            
            <div class="upload-progress" style="display: none;">
                <div class="progress-bar">
                    <div class="progress-fill"></div>
                </div>
                <div class="progress-text">Uploading...</div>
            </div>
            
            <input type="hidden" id="{upload_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class JSONEditorWidget:
    """Widget for JSON editing with validation."""
    
    def __init__(self, schema: Dict[str, Any] = None, height: int = 300):
        self.schema = schema
        self.height = height
    
    def __call__(self, field, **kwargs):
        """Render the JSON editor widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, dict):
                json_value = json.dumps(field.data, indent=2)
            else:
                json_value = str(field.data) if field.data else '{}'
        else:
            json_value = '{}'
        
        editor_id = f"json_{field.id}_{secrets.token_hex(4)}"
        schema_json = json.dumps(self.schema) if self.schema else 'null'
        
        html = f'''
        <div class="json-editor-container">
            <div class="json-editor-toolbar">
                <button type="button" class="format-json" data-target="{editor_id}">Format</button>
                <button type="button" class="validate-json" data-target="{editor_id}">Validate</button>
                <button type="button" class="minify-json" data-target="{editor_id}">Minify</button>
                <select class="json-view-mode" data-target="{editor_id}">
                    <option value="text">Text</option>
                    <option value="tree">Tree</option>
                    <option value="form">Form</option>
                </select>
            </div>
            
            <div class="json-editor-area">
                <textarea id="{editor_id}" 
                         class="json-editor-text"
                         data-height="{self.height}"
                         data-schema='{schema_json}'>{json_value}</textarea>
                <div class="json-tree-view" style="display: none;"></div>
                <div class="json-form-view" style="display: none;"></div>
            </div>
            
            <div class="json-validation-status">
                <span class="validation-icon">✓</span>
                <span class="validation-message">Valid JSON</span>
            </div>
            
            <input type="hidden" id="{editor_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)


class TagWidget:
    """Widget for tag selection with autocomplete."""
    
    def __init__(self, suggestions: List[str] = None, max_tags: int = 10, allow_custom: bool = True):
        self.suggestions = suggestions or []
        self.max_tags = max_tags
        self.allow_custom = allow_custom
    
    def __call__(self, field, **kwargs):
        """Render the tag widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, TagData):
                tags = field.data.tags
            elif isinstance(field.data, dict):
                tags = field.data.get('tags', [])
            elif isinstance(field.data, list):
                tags = field.data
            else:
                tags = [str(field.data)] if field.data else []
        else:
            tags = []
        
        tag_id = f"tags_{field.id}_{secrets.token_hex(4)}"
        suggestions_json = json.dumps(self.suggestions)
        
        html = f'''
        <div class="tag-container">
            <div class="tag-input-area">
                <div class="selected-tags">
        '''
        
        for tag in tags:
            html += f'''
                    <span class="tag-item">
                        {tag}
                        <button type="button" class="remove-tag" data-tag="{tag}">×</button>
                    </span>
            '''
        
        html += f'''
                </div>
                <input type="text" 
                       id="{tag_id}" 
                       class="tag-input"
                       placeholder="Type to add tags..."
                       data-suggestions='{suggestions_json}'
                       data-max-tags="{self.max_tags}"
                       data-allow-custom="{str(self.allow_custom).lower()}" />
            </div>
            
            <div class="tag-suggestions" style="display: none;">
                <!-- Suggestions will appear here -->
            </div>
            
            <div class="tag-stats">
                <span class="tag-count">{len(tags)}</span> / {self.max_tags} tags
            </div>
            
            <input type="hidden" id="{tag_id}_data" name="{field.name}" value='{json.dumps(tags)}' />
        </div>
        '''
        
        return HTMLString(html)


class PasswordStrengthWidget:
    """Widget for password input with strength validation."""
    
    def __init__(self, show_suggestions: bool = True, show_generator: bool = True):
        self.show_suggestions = show_suggestions
        self.show_generator = show_generator
    
    def __call__(self, field, **kwargs):
        """Render the password strength widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        kwargs.setdefault('type', 'password')
        
        password_id = f"password_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="password-strength-container">
            <div class="password-input-group">
                <input type="password" 
                       id="{password_id}" 
                       class="password-input"
                       name="{field.name}"
                       placeholder="Enter password..."
                       {html_params(**kwargs)} />
                <button type="button" class="toggle-password" data-target="{password_id}">👁</button>
        '''
        
        if self.show_generator:
            html += f'''
                <button type="button" class="generate-password" data-target="{password_id}">Generate</button>
            '''
        
        html += '''
            </div>
            
            <div class="strength-meter">
                <div class="strength-bar">
                    <div class="strength-fill"></div>
                </div>
                <div class="strength-text">Enter password to check strength</div>
            </div>
            
            <div class="password-requirements">
                <div class="requirement" data-check="length">
                    <span class="check-icon">○</span> At least 8 characters
                </div>
                <div class="requirement" data-check="uppercase">
                    <span class="check-icon">○</span> Uppercase letter
                </div>
                <div class="requirement" data-check="lowercase">
                    <span class="check-icon">○</span> Lowercase letter
                </div>
                <div class="requirement" data-check="numbers">
                    <span class="check-icon">○</span> Numbers
                </div>
                <div class="requirement" data-check="symbols">
                    <span class="check-icon">○</span> Special characters
                </div>
            </div>
        '''
        
        if self.show_suggestions:
            html += '''
            <div class="password-suggestions" style="display: none;">
                <strong>Suggestions:</strong>
                <ul class="suggestion-list"></ul>
            </div>
            '''
        
        html += '''
        </div>
        '''
        
        return HTMLString(html)


class PhoneNumberWidget:
    """Widget for international phone number input."""
    
    def __init__(self, default_country: str = 'US', show_validation: bool = True):
        self.default_country = default_country
        self.show_validation = show_validation
    
    def __call__(self, field, **kwargs):
        """Render the phone number widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, PhoneNumberData):
                phone_value = field.data.number
                country_code = field.data.country_code
            elif isinstance(field.data, dict):
                phone_value = field.data.get('number', '')
                country_code = field.data.get('country_code', self.default_country)
            else:
                phone_value = str(field.data) if field.data else ''
                country_code = self.default_country
        else:
            phone_value = ''
            country_code = self.default_country
        
        phone_id = f"phone_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="phone-number-container">
            <div class="phone-input-group">
                <select class="country-selector" data-target="{phone_id}">
                    {self._generate_country_options(country_code)}
                </select>
                <input type="tel" 
                       id="{phone_id}" 
                       class="phone-input"
                       value="{phone_value}"
                       placeholder="Enter phone number..." />
            </div>
        '''
        
        if self.show_validation:
            html += '''
            <div class="phone-validation">
                <div class="validation-status">
                    <span class="validation-icon">○</span>
                    <span class="validation-text">Enter a phone number</span>
                </div>
                <div class="phone-info" style="display: none;">
                    <div class="carrier-info"></div>
                    <div class="location-info"></div>
                    <div class="type-info"></div>
                </div>
            </div>
            '''
        
        html += f'''
            <input type="hidden" id="{phone_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)
    
    def _generate_country_options(self, selected_country: str) -> str:
        """Generate country selector options."""
        countries = [
            ('US', '🇺🇸 United States (+1)'),
            ('CA', '🇨🇦 Canada (+1)'),
            ('GB', '🇬🇧 United Kingdom (+44)'),
            ('DE', '🇩🇪 Germany (+49)'),
            ('FR', '🇫🇷 France (+33)'),
            ('ES', '🇪🇸 Spain (+34)'),
            ('IT', '🇮🇹 Italy (+39)'),
            ('JP', '🇯🇵 Japan (+81)'),
            ('CN', '🇨🇳 China (+86)'),
            ('IN', '🇮🇳 India (+91)'),
            ('AU', '🇦🇺 Australia (+61)'),
            ('BR', '🇧🇷 Brazil (+55)'),
        ]
        
        options = []
        for code, name in countries:
            selected = 'selected' if code == selected_country else ''
            options.append(f'<option value="{code}" {selected}>{name}</option>')
        return '
'.join(options)


class AddressWidget:
    """Widget for structured address input with geocoding."""
    
    def __init__(self, include_geocoding: bool = True, country_default: str = 'US'):
        self.include_geocoding = include_geocoding
        self.country_default = country_default
    
    def __call__(self, field, **kwargs):
        """Render the address widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, AddressData):
                street = field.data.street_address
                city = field.data.city
                state = field.data.state
                postal = field.data.postal_code
                country = field.data.country
                apartment = field.data.apartment or ''
            elif isinstance(field.data, dict):
                street = field.data.get('street_address', '')
                city = field.data.get('city', '')
                state = field.data.get('state', '')
                postal = field.data.get('postal_code', '')
                country = field.data.get('country', self.country_default)
                apartment = field.data.get('apartment', '')
            else:
                street = city = state = postal = apartment = ''
                country = self.country_default
        else:
            street = city = state = postal = apartment = ''
            country = self.country_default
        
        address_id = f"address_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="address-container">
            <div class="address-search">
                <input type="text" 
                       class="address-autocomplete" 
                       placeholder="Start typing an address..."
                       data-target="{address_id}" />
                <button type="button" class="use-current-location" data-target="{address_id}">📍 Use Current Location</button>
            </div>
            
            <div class="address-fields">
                <div class="field-row">
                    <input type="text" 
                           class="street-address" 
                           placeholder="Street Address"
                           value="{street}"
                           data-field="street_address" />
                </div>
                <div class="field-row">
                    <input type="text" 
                           class="apartment" 
                           placeholder="Apt, Suite, etc. (optional)"
                           value="{apartment}"
                           data-field="apartment" />
                </div>
                <div class="field-row">
                    <input type="text" 
                           class="city" 
                           placeholder="City"
                           value="{city}"
                           data-field="city" />
                    <input type="text" 
                           class="state" 
                           placeholder="State/Province"
                           value="{state}"
                           data-field="state" />
                </div>
                <div class="field-row">
                    <input type="text" 
                           class="postal-code" 
                           placeholder="ZIP/Postal Code"
                           value="{postal}"
                           data-field="postal_code" />
                    <select class="country" data-field="country">
                        {self._generate_country_options(country)}
                    </select>
                </div>
            </div>
        '''
        
        if self.include_geocoding:
            html += '''
            <div class="address-map" style="height: 200px; display: none;">
                <!-- Map will be rendered here -->
            </div>
            <div class="geocoding-info" style="display: none;">
                <span class="coordinates"></span>
                <span class="plus-code"></span>
            </div>
            '''
        
        html += f'''
            <input type="hidden" id="{address_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)
    
    def _generate_country_options(self, selected_country: str) -> str:
        """Generate country selector options."""
        countries = [
            ('US', 'United States'),
            ('CA', 'Canada'),
            ('GB', 'United Kingdom'),
            ('DE', 'Germany'),
            ('FR', 'France'),
            ('ES', 'Spain'),
            ('IT', 'Italy'),
            ('JP', 'Japan'),
            ('CN', 'China'),
            ('IN', 'India'),
            ('AU', 'Australia'),
            ('BR', 'Brazil'),
        ]
        
        options = []
        for code, name in countries:
            selected = 'selected' if code == selected_country else ''
            options.append(f'<option value="{code}" {selected}>{name}</option>')
        return '
'.join(options)


class DrawingWidget:
    """Widget for digital drawing canvas."""
    
    def __init__(self, width: int = 800, height: int = 600, tools: List[str] = None):
        self.width = width
        self.height = height
        self.tools = tools or ['pen', 'brush', 'eraser', 'line', 'rectangle', 'circle', 'text']
    
    def __call__(self, field, **kwargs):
        """Render the drawing widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        if field.data:
            if isinstance(field.data, DrawingData):
                drawing_data = field.data.drawing_data
                bg_color = field.data.background_color
            elif isinstance(field.data, dict):
                drawing_data = field.data.get('drawing_data', '')
                bg_color = field.data.get('background_color', '#ffffff')
            else:
                drawing_data = str(field.data) if field.data else ''
                bg_color = '#ffffff'
        else:
            drawing_data = ''
            bg_color = '#ffffff'
        
        canvas_id = f"drawing_{field.id}_{secrets.token_hex(4)}"
        
        html = f'''
        <div class="drawing-container">
            <div class="drawing-toolbar">
                <div class="tool-group">
                    <label>Tools:</label>
        '''
        
        for tool in self.tools:
            tool_icon = {
                'pen': '🖊️',
                'brush': '🖌️',
                'eraser': '🧽',
                'line': '📏',
                'rectangle': '▭',
                'circle': '○',
                'text': '📝'
            }.get(tool, '🔧')
            
            html += f'''
                    <button type="button" class="tool-btn" data-tool="{tool}" data-target="{canvas_id}">
                        {tool_icon} {tool.title()}
                    </button>
            '''
        
        html += f'''
                </div>
                <div class="color-group">
                    <label>Color:</label>
                    <input type="color" class="brush-color" value="#000000" data-target="{canvas_id}" />
                    <input type="color" class="bg-color" value="{bg_color}" data-target="{canvas_id}" />
                </div>
                <div class="size-group">
                    <label>Size:</label>
                    <input type="range" class="brush-size" min="1" max="50" value="2" data-target="{canvas_id}" />
                    <span class="size-display">2px</span>
                </div>
                <div class="action-group">
                    <button type="button" class="undo-btn" data-target="{canvas_id}">↶ Undo</button>
                    <button type="button" class="redo-btn" data-target="{canvas_id}">↷ Redo</button>
                    <button type="button" class="clear-btn" data-target="{canvas_id}">🗑️ Clear</button>
                    <button type="button" class="save-btn" data-target="{canvas_id}">💾 Save</button>
                </div>
            </div>
            
            <div class="canvas-area">
                <canvas id="{canvas_id}" 
                        class="drawing-canvas"
                        width="{self.width}" 
                        height="{self.height}"
                        data-drawing-data="{drawing_data}"
                        style="background-color: {bg_color};"></canvas>
            </div>
            
            <div class="layer-panel" style="display: none;">
                <h4>Layers</h4>
                <div class="layer-list">
                    <div class="layer-item active" data-layer="0">
                        <span class="layer-name">Background</span>
                        <button class="layer-visible">👁</button>
                    </div>
                </div>
                <button class="add-layer">+ Add Layer</button>
            </div>
            
            <input type="hidden" id="{canvas_id}_data" name="{field.name}" />
        </div>
        '''
        
        return HTMLString(html)