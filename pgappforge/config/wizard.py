"""
PgForge Wizard Forms Configuration

Comprehensive configuration system for wizard forms with extreme customization
capabilities including themes, validation rules, UI behaviors, and more.
"""

from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum


class WizardTheme(Enum):
    """Pre-defined wizard themes"""
    DEFAULT = "default"
    DARK = "dark" 
    MINIMAL = "minimal"
    PROFESSIONAL = "professional"
    COLORFUL = "colorful"
    ACCESSIBLE = "accessible"
    MOBILE_FIRST = "mobile_first"
    MATERIAL_DESIGN = "material_design"
    BOOTSTRAP_5 = "bootstrap_5"
    TAILWIND = "tailwind"


class WizardAnimation(Enum):
    """Animation types for step transitions"""
    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    FLIP = "flip"
    ROTATE = "rotate"


class WizardLayout(Enum):
    """Wizard layout options"""
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    TABS = "tabs"
    ACCORDION = "accordion"
    STEPPER = "stepper"
    SIDEBAR = "sidebar"
    MODAL = "modal"
    FULLSCREEN = "fullscreen"


class WizardValidationMode(Enum):
    """Validation modes"""
    IMMEDIATE = "immediate"  # Validate as user types
    ON_BLUR = "on_blur"     # Validate when field loses focus
    ON_SUBMIT = "on_submit" # Validate only on form submission
    ON_STEP_CHANGE = "on_step_change"  # Validate when changing steps
    CUSTOM = "custom"       # Use custom validation triggers


@dataclass 
class WizardUIConfig:
    """User interface configuration for wizard forms"""
    
    # Theme and appearance
    theme: WizardTheme = WizardTheme.DEFAULT
    custom_css_classes: List[str] = field(default_factory=list)
    custom_css_file: Optional[str] = None
    custom_js_file: Optional[str] = None
    
    # Layout and structure
    layout: WizardLayout = WizardLayout.VERTICAL
    show_progress_bar: bool = True
    show_step_numbers: bool = True
    show_step_titles: bool = True
    show_step_descriptions: bool = True
    show_step_icons: bool = True
    
    # Progress indicators
    progress_bar_style: str = "linear"  # linear, circular, stepped
    progress_bar_color: str = "#007bff"
    progress_bar_height: int = 8
    progress_show_percentage: bool = True
    progress_show_step_count: bool = True
    
    # Step indicators
    step_indicator_style: str = "numbered"  # numbered, icons, dots, custom
    step_indicator_size: str = "medium"    # small, medium, large
    step_completed_icon: str = "fa-check"
    step_current_icon: str = "fa-edit" 
    step_pending_icon: str = "fa-circle"
    
    # Animations
    animation_type: WizardAnimation = WizardAnimation.FADE
    animation_duration: int = 300  # milliseconds
    animation_easing: str = "ease"
    disable_animations_on_mobile: bool = True
    
    # Spacing and sizing
    container_max_width: str = "1200px"
    step_padding: str = "30px"
    field_spacing: str = "20px"
    button_size: str = "medium"  # small, medium, large
    
    # Colors (can be overridden by theme)
    primary_color: str = "#007bff"
    secondary_color: str = "#6c757d"
    success_color: str = "#28a745"
    warning_color: str = "#ffc107" 
    error_color: str = "#dc3545"
    background_color: str = "#ffffff"
    text_color: str = "#495057"
    
    # Responsive design
    mobile_breakpoint: int = 768  # pixels
    tablet_breakpoint: int = 1024 # pixels
    stack_on_mobile: bool = True
    hide_step_titles_on_mobile: bool = False
    
    # Accessibility
    high_contrast_mode: bool = False
    keyboard_navigation: bool = True
    screen_reader_support: bool = True
    focus_indicators: bool = True
    aria_labels: bool = True


@dataclass
class WizardBehaviorConfig:
    """Behavior and functionality configuration"""
    
    # Navigation
    allow_step_navigation: bool = True
    allow_backward_navigation: bool = True
    allow_forward_navigation: bool = True
    require_step_completion: bool = True
    auto_advance_on_complete: bool = False
    show_step_navigation_buttons: bool = True
    
    # Validation
    validation_mode: WizardValidationMode = WizardValidationMode.ON_BLUR
    validate_on_step_change: bool = True
    show_validation_summary: bool = True
    scroll_to_first_error: bool = True
    highlight_invalid_steps: bool = True
    
    # Auto-save
    enable_auto_save: bool = True
    auto_save_interval: int = 30000  # 30 seconds
    save_on_step_change: bool = True
    save_on_field_change: bool = False
    show_save_indicator: bool = True
    
    # Form submission
    confirm_before_submit: bool = True
    submit_confirmation_message: str = "Are you ready to submit this form?"
    prevent_duplicate_submission: bool = True
    show_submission_progress: bool = True
    
    # Session management
    session_timeout_warning: bool = True
    session_timeout_minutes: int = 30
    auto_extend_session: bool = True
    
    # Error handling
    show_error_details: bool = False  # In production, set to False
    retry_failed_operations: bool = True
    max_retry_attempts: int = 3
    error_reporting_enabled: bool = False
    
    # Performance
    lazy_load_steps: bool = False
    cache_validation_results: bool = True
    debounce_validation: bool = True
    debounce_delay: int = 500  # milliseconds


@dataclass
class WizardPersistenceConfig:
    """Data persistence configuration"""
    
    # Storage backend
    storage_backend: str = "session"  # session, database, cache, custom
    storage_prefix: str = "wizard_"
    
    # Expiration settings
    data_expiration_days: int = 7
    cleanup_expired_data: bool = True
    cleanup_interval_hours: int = 24
    
    # Database settings (when using database backend)
    database_table_name: str = "wizard_form_data"
    use_compression: bool = True
    encryption_key: Optional[str] = None  # For sensitive data
    
    # Cache settings (when using cache backend)
    cache_key_prefix: str = "wizard_"
    cache_timeout: int = 604800  # 7 days in seconds
    
    # Backup and recovery
    enable_data_backup: bool = False
    backup_interval_hours: int = 6
    max_backup_versions: int = 10


@dataclass
class WizardSecurityConfig:
    """Security configuration for wizard forms"""
    
    # CSRF protection
    csrf_protection: bool = True
    csrf_token_expiry: int = 3600  # 1 hour
    
    # Input sanitization
    sanitize_input: bool = True
    allowed_html_tags: List[str] = field(default_factory=lambda: [])
    strip_dangerous_content: bool = True
    
    # Rate limiting
    enable_rate_limiting: bool = False
    max_submissions_per_hour: int = 10
    rate_limit_by_ip: bool = True
    rate_limit_by_user: bool = True
    
    # Content validation
    max_file_size_mb: int = 10
    allowed_file_extensions: List[str] = field(default_factory=lambda: ['.pdf', '.doc', '.docx', '.jpg', '.png'])
    scan_uploaded_files: bool = False
    
    # Session security
    secure_session_cookies: bool = True
    session_cookie_httponly: bool = True
    session_cookie_samesite: str = "Lax"
    
    # Audit logging
    log_form_access: bool = False
    log_form_submissions: bool = True
    log_validation_errors: bool = False
    log_security_events: bool = True


@dataclass
class WizardIntegrationConfig:
    """Integration configuration with external systems"""
    
    # Email notifications
    send_confirmation_emails: bool = False
    email_template_path: Optional[str] = None
    email_from_address: Optional[str] = None
    
    # Webhooks
    webhook_url: Optional[str] = None
    webhook_events: List[str] = field(default_factory=list)  # step_complete, form_submit, etc.
    webhook_authentication: Optional[Dict[str, str]] = None
    
    # API integrations
    external_validation_api: Optional[str] = None
    data_export_api: Optional[str] = None
    
    # Analytics
    google_analytics_id: Optional[str] = None
    track_step_completion: bool = False
    track_form_abandonment: bool = False
    track_validation_errors: bool = False
    
    # CRM integration
    crm_system: Optional[str] = None  # salesforce, hubspot, etc.
    crm_api_endpoint: Optional[str] = None
    crm_field_mapping: Dict[str, str] = field(default_factory=dict)


@dataclass 
class WizardAccessibilityConfig:
    """Accessibility configuration for compliance with WCAG guidelines"""
    
    # WCAG compliance level
    wcag_level: str = "AA"  # A, AA, AAA
    
    # Screen reader support
    screen_reader_announcements: bool = True
    step_change_announcements: bool = True
    error_announcements: bool = True
    
    # Keyboard navigation
    keyboard_shortcuts: bool = True
    custom_key_bindings: Dict[str, str] = field(default_factory=dict)
    skip_navigation_links: bool = True
    
    # Visual accessibility
    high_contrast_support: bool = True
    font_size_scaling: bool = True
    color_blind_friendly: bool = True
    focus_indicators: bool = True
    
    # Motor accessibility
    large_click_targets: bool = True
    no_time_limits: bool = False
    pause_animations: bool = True
    
    # Cognitive accessibility
    clear_instructions: bool = True
    progress_indicators: bool = True
    error_prevention: bool = True
    help_text_available: bool = True


@dataclass
class WizardPerformanceConfig:
    """Performance optimization configuration"""
    
    # Loading optimization
    lazy_load_steps: bool = False
    preload_next_step: bool = True
    minimize_dom_size: bool = True
    
    # Caching
    cache_form_definitions: bool = True
    cache_validation_rules: bool = True
    cache_templates: bool = True
    
    # Network optimization
    compress_api_responses: bool = True
    batch_api_requests: bool = True
    use_cdn_resources: bool = False
    
    # Memory management
    cleanup_hidden_steps: bool = True
    limit_form_data_size: bool = True
    max_form_data_size_mb: int = 5
    
    # Monitoring
    performance_monitoring: bool = False
    log_slow_operations: bool = True
    slow_operation_threshold_ms: int = 1000


@dataclass
class WizardAdvancedConfig:
    """Advanced configuration options for power users"""
    
    # Custom validation functions
    custom_validators: Dict[str, Callable] = field(default_factory=dict)
    
    # Custom step processors
    step_processors: Dict[str, Callable] = field(default_factory=dict)
    
    # Custom field renderers
    field_renderers: Dict[str, Callable] = field(default_factory=dict)
    
    # Event hooks
    before_step_change: Optional[Callable] = None
    after_step_change: Optional[Callable] = None
    before_form_submit: Optional[Callable] = None
    after_form_submit: Optional[Callable] = None
    on_validation_error: Optional[Callable] = None
    on_save_draft: Optional[Callable] = None
    
    # Custom templates
    custom_step_template: Optional[str] = None
    custom_progress_template: Optional[str] = None
    custom_navigation_template: Optional[str] = None
    
    # Plugin system
    enabled_plugins: List[str] = field(default_factory=list)
    plugin_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Experimental features
    experimental_features: Dict[str, bool] = field(default_factory=dict)


@dataclass
class WizardConfig:
    """Complete wizard configuration combining all aspects"""
    
    # Core configuration sections
    ui: WizardUIConfig = field(default_factory=WizardUIConfig)
    behavior: WizardBehaviorConfig = field(default_factory=WizardBehaviorConfig)
    persistence: WizardPersistenceConfig = field(default_factory=WizardPersistenceConfig)
    security: WizardSecurityConfig = field(default_factory=WizardSecurityConfig)
    integration: WizardIntegrationConfig = field(default_factory=WizardIntegrationConfig)
    accessibility: WizardAccessibilityConfig = field(default_factory=WizardAccessibilityConfig)
    performance: WizardPerformanceConfig = field(default_factory=WizardPerformanceConfig)
    advanced: WizardAdvancedConfig = field(default_factory=WizardAdvancedConfig)
    
    # Global settings
    debug_mode: bool = False
    environment: str = "production"  # development, testing, production
    locale: str = "en"
    timezone: str = "UTC"
    
    def validate_config(self) -> List[str]:
        """
        Validate the configuration and return any issues found
        
        Returns:
            List of validation error messages
        """
        errors = []
        
        # Validate UI config
        if self.ui.animation_duration < 0:
            errors.append("Animation duration must be positive")
        
        if self.ui.mobile_breakpoint <= 0:
            errors.append("Mobile breakpoint must be positive")
        
        # Validate behavior config
        if self.behavior.auto_save_interval < 1000:
            errors.append("Auto-save interval should be at least 1 second")
        
        if self.behavior.session_timeout_minutes < 1:
            errors.append("Session timeout must be at least 1 minute")
        
        # Validate persistence config
        if self.persistence.data_expiration_days < 1:
            errors.append("Data expiration must be at least 1 day")
        
        # Validate security config
        if self.security.max_file_size_mb < 0:
            errors.append("Max file size must be positive")
        
        if self.security.max_submissions_per_hour < 1:
            errors.append("Max submissions per hour must be at least 1")
        
        # Validate performance config
        if self.performance.max_form_data_size_mb < 1:
            errors.append("Max form data size must be at least 1MB")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        import dataclasses
        return dataclasses.asdict(self)
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'WizardConfig':
        """Create configuration from dictionary"""
        # Handle nested dataclasses
        ui_dict = config_dict.get('ui', {})
        behavior_dict = config_dict.get('behavior', {})
        persistence_dict = config_dict.get('persistence', {})
        security_dict = config_dict.get('security', {})
        integration_dict = config_dict.get('integration', {})
        accessibility_dict = config_dict.get('accessibility', {})
        performance_dict = config_dict.get('performance', {})
        advanced_dict = config_dict.get('advanced', {})
        
        # Convert enum strings to enum values
        if 'theme' in ui_dict and isinstance(ui_dict['theme'], str):
            ui_dict['theme'] = WizardTheme(ui_dict['theme'])
        if 'animation_type' in ui_dict and isinstance(ui_dict['animation_type'], str):
            ui_dict['animation_type'] = WizardAnimation(ui_dict['animation_type'])
        if 'layout' in ui_dict and isinstance(ui_dict['layout'], str):
            ui_dict['layout'] = WizardLayout(ui_dict['layout'])
        if 'validation_mode' in behavior_dict and isinstance(behavior_dict['validation_mode'], str):
            behavior_dict['validation_mode'] = WizardValidationMode(behavior_dict['validation_mode'])
        
        return cls(
            ui=WizardUIConfig(**ui_dict),
            behavior=WizardBehaviorConfig(**behavior_dict),
            persistence=WizardPersistenceConfig(**persistence_dict),
            security=WizardSecurityConfig(**security_dict),
            integration=WizardIntegrationConfig(**integration_dict),
            accessibility=WizardAccessibilityConfig(**accessibility_dict),
            performance=WizardPerformanceConfig(**performance_dict),
            advanced=WizardAdvancedConfig(**advanced_dict),
            debug_mode=config_dict.get('debug_mode', False),
            environment=config_dict.get('environment', 'production'),
            locale=config_dict.get('locale', 'en'),
            timezone=config_dict.get('timezone', 'UTC')
        )
    
    def merge_with(self, other_config: 'WizardConfig') -> 'WizardConfig':
        """
        Merge this configuration with another, with the other taking precedence
        
        Args:
            other_config: Configuration to merge with
            
        Returns:
            New merged configuration
        """
        import dataclasses
        
        self_dict = dataclasses.asdict(self)
        other_dict = dataclasses.asdict(other_config)
        
        def deep_merge(dict1, dict2):
            result = dict1.copy()
            for key, value in dict2.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result
        
        merged_dict = deep_merge(self_dict, other_dict)
        return WizardConfig.from_dict(merged_dict)


# Pre-defined configuration presets
WIZARD_CONFIG_PRESETS = {
    "minimal": WizardConfig(
        ui=WizardUIConfig(
            theme=WizardTheme.MINIMAL,
            show_step_descriptions=False,
            show_step_icons=False,
            animation_type=WizardAnimation.NONE
        ),
        behavior=WizardBehaviorConfig(
            enable_auto_save=False,
            show_save_indicator=False,
            confirm_before_submit=False
        )
    ),
    
    "professional": WizardConfig(
        ui=WizardUIConfig(
            theme=WizardTheme.PROFESSIONAL,
            progress_bar_style="stepped",
            step_indicator_style="icons",
            animation_type=WizardAnimation.SLIDE_LEFT
        ),
        behavior=WizardBehaviorConfig(
            validation_mode=WizardValidationMode.ON_BLUR,
            confirm_before_submit=True,
            show_submission_progress=True
        ),
        security=WizardSecurityConfig(
            csrf_protection=True,
            sanitize_input=True,
            enable_rate_limiting=True
        )
    ),
    
    "accessible": WizardConfig(
        ui=WizardUIConfig(
            theme=WizardTheme.ACCESSIBLE,
            high_contrast_mode=True,
            animation_type=WizardAnimation.NONE,
            button_size="large"
        ),
        accessibility=WizardAccessibilityConfig(
            wcag_level="AAA",
            large_click_targets=True,
            no_time_limits=True,
            keyboard_shortcuts=True
        ),
        behavior=WizardBehaviorConfig(
            auto_advance_on_complete=False,
            show_validation_summary=True,
            scroll_to_first_error=True
        )
    ),
    
    "mobile_optimized": WizardConfig(
        ui=WizardUIConfig(
            theme=WizardTheme.MOBILE_FIRST,
            layout=WizardLayout.VERTICAL,
            stack_on_mobile=True,
            button_size="large",
            step_padding="15px"
        ),
        behavior=WizardBehaviorConfig(
            enable_auto_save=True,
            auto_save_interval=15000,  # More frequent for mobile
            validation_mode=WizardValidationMode.ON_SUBMIT
        ),
        performance=WizardPerformanceConfig(
            lazy_load_steps=True,
            minimize_dom_size=True,
            compress_api_responses=True
        )
    ),
    
    "high_security": WizardConfig(
        security=WizardSecurityConfig(
            csrf_protection=True,
            sanitize_input=True,
            enable_rate_limiting=True,
            max_submissions_per_hour=5,
            secure_session_cookies=True,
            log_security_events=True,
            scan_uploaded_files=True
        ),
        persistence=WizardPersistenceConfig(
            storage_backend="database",
            use_compression=True,
            encryption_key="your-encryption-key",
            data_expiration_days=1
        ),
        behavior=WizardBehaviorConfig(
            prevent_duplicate_submission=True,
            max_retry_attempts=1
        )
    )
}


def get_wizard_config(preset_name: str = "default") -> WizardConfig:
    """
    Get a wizard configuration by preset name
    
    Args:
        preset_name: Name of the preset configuration
        
    Returns:
        WizardConfig instance
    """
    if preset_name == "default":
        return WizardConfig()
    
    if preset_name not in WIZARD_CONFIG_PRESETS:
        raise ValueError(f"Unknown preset '{preset_name}'. Available presets: {list(WIZARD_CONFIG_PRESETS.keys())}")
    
    return WIZARD_CONFIG_PRESETS[preset_name]


def create_custom_config(**kwargs) -> WizardConfig:
    """
    Create a custom wizard configuration
    
    Args:
        **kwargs: Configuration parameters
        
    Returns:
        WizardConfig instance
    """
    return WizardConfig.from_dict(kwargs)