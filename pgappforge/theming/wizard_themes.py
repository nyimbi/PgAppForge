"""
Advanced Theming System for Wizard Forms

Provides comprehensive theming, styling, and visual customization
capabilities for wizard forms with beautiful, professional designs.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class WizardColorScheme(Enum):
    """Color scheme options for wizard themes"""
    BLUE = "blue"
    GREEN = "green"
    PURPLE = "purple"
    ORANGE = "orange"
    RED = "red"
    TEAL = "teal"
    INDIGO = "indigo"
    PINK = "pink"
    YELLOW = "yellow"
    DARK = "dark"
    LIGHT = "light"


class WizardLayoutStyle(Enum):
    """Layout style options for wizard themes"""
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    CARDS = "cards"
    TABS = "tabs"
    ACCORDION = "accordion"
    STEPPER = "stepper"


class WizardAnimationType(Enum):
    """Animation types for wizard transitions"""
    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    ZOOM = "zoom"
    FLIP = "flip"
    BOUNCE = "bounce"


@dataclass
class WizardColorPalette:
    """Color palette for wizard themes"""
    primary: str
    secondary: str
    success: str
    warning: str
    danger: str
    info: str
    light: str
    dark: str
    background: str
    surface: str
    text_primary: str
    text_secondary: str
    border: str
    shadow: str


@dataclass
class WizardTypography:
    """Typography settings for wizard themes"""
    font_family: str
    font_size_base: str
    font_size_small: str
    font_size_large: str
    font_size_heading: str
    font_weight_normal: str
    font_weight_bold: str
    line_height: str
    letter_spacing: str


@dataclass
class WizardSpacing:
    """Spacing and sizing settings"""
    base_unit: str  # e.g., "8px"
    small: str
    medium: str
    large: str
    extra_large: str
    border_radius: str
    border_width: str
    shadow_blur: str


@dataclass
class WizardAnimationSettings:
    """Animation configuration"""
    type: WizardAnimationType
    duration: str  # e.g., "0.3s"
    easing: str    # e.g., "ease-in-out"
    delay: str
    enabled: bool = True


@dataclass
class WizardTheme:
    """Complete theme configuration for wizard forms"""
    id: str
    name: str
    description: str
    
    # Core styling
    color_scheme: WizardColorScheme
    color_palette: WizardColorPalette
    typography: WizardTypography
    spacing: WizardSpacing
    
    # Layout and interaction
    layout_style: WizardLayoutStyle
    animation: WizardAnimationSettings
    
    # Component-specific styling
    progress_bar_style: str
    button_style: str
    form_field_style: str
    card_style: str
    
    # Advanced features
    custom_css: Optional[str] = None
    custom_js: Optional[str] = None
    responsive_breakpoints: Optional[Dict[str, str]] = None
    accessibility_features: Optional[Dict[str, Any]] = None
    
    def to_css(self) -> str:
        """Generate CSS from theme configuration"""
        css_vars = []
        
        # Color variables
        for attr_name in dir(self.color_palette):
            if not attr_name.startswith('_'):
                value = getattr(self.color_palette, attr_name)
                css_var_name = f"--wizard-{attr_name.replace('_', '-')}"
                css_vars.append(f"{css_var_name}: {value};")
        
        # Typography variables
        for attr_name in dir(self.typography):
            if not attr_name.startswith('_'):
                value = getattr(self.typography, attr_name)
                css_var_name = f"--wizard-{attr_name.replace('_', '-')}"
                css_vars.append(f"{css_var_name}: {value};")
        
        # Spacing variables
        for attr_name in dir(self.spacing):
            if not attr_name.startswith('_'):
                value = getattr(self.spacing, attr_name)
                css_var_name = f"--wizard-{attr_name.replace('_', '-')}"
                css_vars.append(f"{css_var_name}: {value};")
        
        # Animation variables
        css_vars.extend([
            f"--wizard-animation-duration: {self.animation.duration};",
            f"--wizard-animation-easing: {self.animation.easing};",
            f"--wizard-animation-delay: {self.animation.delay};"
        ])
        
        # Base CSS structure
        base_css = f"""
:root {{
    {chr(10).join(css_vars)}
}}

.wizard-container.theme-{self.id} {{
    font-family: var(--wizard-font-family);
    font-size: var(--wizard-font-size-base);
    line-height: var(--wizard-line-height);
    color: var(--wizard-text-primary);
    background-color: var(--wizard-background);
}}

.wizard-container.theme-{self.id} .wizard-step {{
    background: var(--wizard-surface);
    border-radius: var(--wizard-border-radius);
    padding: var(--wizard-large);
    margin-bottom: var(--wizard-medium);
    border: var(--wizard-border-width) solid var(--wizard-border);
    box-shadow: 0 var(--wizard-shadow-blur) calc(var(--wizard-shadow-blur) * 2) var(--wizard-shadow);
}}

.wizard-container.theme-{self.id} .wizard-progress {{
    background: var(--wizard-light);
    border-radius: calc(var(--wizard-border-radius) / 2);
    overflow: hidden;
    height: var(--wizard-medium);
}}

.wizard-container.theme-{self.id} .wizard-progress-bar {{
    background: linear-gradient(90deg, var(--wizard-primary), var(--wizard-secondary));
    height: 100%;
    transition: width var(--wizard-animation-duration) var(--wizard-animation-easing);
}}

.wizard-container.theme-{self.id} .wizard-button {{
    background: var(--wizard-primary);
    color: white;
    border: none;
    border-radius: var(--wizard-border-radius);
    padding: var(--wizard-small) var(--wizard-medium);
    font-size: var(--wizard-font-size-base);
    font-weight: var(--wizard-font-weight-bold);
    cursor: pointer;
    transition: all var(--wizard-animation-duration) var(--wizard-animation-easing);
}}

.wizard-container.theme-{self.id} .wizard-button:hover {{
    transform: translateY(-2px);
    box-shadow: 0 calc(var(--wizard-shadow-blur) * 2) calc(var(--wizard-shadow-blur) * 4) var(--wizard-shadow);
}}

.wizard-container.theme-{self.id} .form-control {{
    border: var(--wizard-border-width) solid var(--wizard-border);
    border-radius: var(--wizard-border-radius);
    padding: var(--wizard-small);
    font-size: var(--wizard-font-size-base);
    background: var(--wizard-surface);
    color: var(--wizard-text-primary);
    transition: border-color var(--wizard-animation-duration) var(--wizard-animation-easing);
}}

.wizard-container.theme-{self.id} .form-control:focus {{
    border-color: var(--wizard-primary);
    box-shadow: 0 0 0 3px rgba({self._hex_to_rgb(self.color_palette.primary)}, 0.1);
    outline: none;
}}

.wizard-container.theme-{self.id} .form-label {{
    color: var(--wizard-text-primary);
    font-weight: var(--wizard-font-weight-bold);
    margin-bottom: calc(var(--wizard-small) / 2);
    display: block;
}}

/* Animation classes based on animation type */
"""
        
        # Add animation-specific CSS
        if self.animation.type == WizardAnimationType.FADE:
            base_css += f"""
.wizard-container.theme-{self.id} .wizard-step-enter {{
    opacity: 0;
}}

.wizard-container.theme-{self.id} .wizard-step-enter-active {{
    opacity: 1;
    transition: opacity var(--wizard-animation-duration) var(--wizard-animation-easing);
}}

.wizard-container.theme-{self.id} .wizard-step-exit {{
    opacity: 1;
}}

.wizard-container.theme-{self.id} .wizard-step-exit-active {{
    opacity: 0;
    transition: opacity var(--wizard-animation-duration) var(--wizard-animation-easing);
}}
"""
        
        elif self.animation.type == WizardAnimationType.SLIDE_LEFT:
            base_css += f"""
.wizard-container.theme-{self.id} .wizard-step-enter {{
    transform: translateX(100%);
}}

.wizard-container.theme-{self.id} .wizard-step-enter-active {{
    transform: translateX(0);
    transition: transform var(--wizard-animation-duration) var(--wizard-animation-easing);
}}

.wizard-container.theme-{self.id} .wizard-step-exit {{
    transform: translateX(0);
}}

.wizard-container.theme-{self.id} .wizard-step-exit-active {{
    transform: translateX(-100%);
    transition: transform var(--wizard-animation-duration) var(--wizard-animation-easing);
}}
"""
        
        # Add custom CSS if provided
        if self.custom_css:
            base_css += f"\n/* Custom CSS */\n{self.custom_css}"
        
        # Add responsive styles if configured
        if self.responsive_breakpoints:
            for breakpoint, styles in self.responsive_breakpoints.items():
                base_css += f"\n@media {breakpoint} {{\n{styles}\n}}"
        
        return base_css
    
    def _hex_to_rgb(self, hex_color: str) -> str:
        """Convert hex color to RGB values"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return "0, 0, 0"  # fallback
        
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return f"{r}, {g}, {b}"
        except ValueError:
            return "0, 0, 0"


class WizardThemeManager:
    """Manages wizard themes and provides theme-related utilities"""
    
    def __init__(self):
        """
        Initialize the wizard theme manager with built-in themes.
        
        Creates an empty themes dictionary and loads the 5 default professional
        themes (modern_blue, dark_mode, elegant_purple, minimal_green, corporate_orange).
        """
        self.themes: Dict[str, WizardTheme] = {}
        self._load_default_themes()
    
    def _load_default_themes(self):
        """Load default wizard themes"""
        
        # Modern Blue Theme
        self.themes['modern_blue'] = WizardTheme(
            id='modern_blue',
            name='Modern Blue',
            description='Clean, modern design with blue accents',
            color_scheme=WizardColorScheme.BLUE,
            color_palette=WizardColorPalette(
                primary='#007bff',
                secondary='#6c757d',
                success='#28a745',
                warning='#ffc107',
                danger='#dc3545',
                info='#17a2b8',
                light='#f8f9fa',
                dark='#343a40',
                background='#ffffff',
                surface='#ffffff',
                text_primary='#212529',
                text_secondary='#6c757d',
                border='#dee2e6',
                shadow='rgba(0,0,0,0.1)'
            ),
            typography=WizardTypography(
                font_family='-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                font_size_base='16px',
                font_size_small='14px',
                font_size_large='18px',
                font_size_heading='24px',
                font_weight_normal='400',
                font_weight_bold='600',
                line_height='1.5',
                letter_spacing='normal'
            ),
            spacing=WizardSpacing(
                base_unit='8px',
                small='8px',
                medium='16px',
                large='24px',
                extra_large='32px',
                border_radius='8px',
                border_width='1px',
                shadow_blur='4px'
            ),
            layout_style=WizardLayoutStyle.VERTICAL,
            animation=WizardAnimationSettings(
                type=WizardAnimationType.FADE,
                duration='0.3s',
                easing='ease-in-out',
                delay='0s'
            ),
            progress_bar_style='gradient',
            button_style='rounded',
            form_field_style='outlined',
            card_style='elevated'
        )
        
        # Dark Theme
        self.themes['dark_mode'] = WizardTheme(
            id='dark_mode',
            name='Dark Mode',
            description='Sleek dark theme for modern applications',
            color_scheme=WizardColorScheme.DARK,
            color_palette=WizardColorPalette(
                primary='#0d6efd',
                secondary='#6c757d',
                success='#198754',
                warning='#fd7e14',
                danger='#dc3545',
                info='#0dcaf0',
                light='#f8f9fa',
                dark='#212529',
                background='#121212',
                surface='#1e1e1e',
                text_primary='#ffffff',
                text_secondary='#b3b3b3',
                border='#333333',
                shadow='rgba(0,0,0,0.3)'
            ),
            typography=WizardTypography(
                font_family='-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                font_size_base='16px',
                font_size_small='14px',
                font_size_large='18px',
                font_size_heading='24px',
                font_weight_normal='400',
                font_weight_bold='600',
                line_height='1.5',
                letter_spacing='normal'
            ),
            spacing=WizardSpacing(
                base_unit='8px',
                small='8px',
                medium='16px',
                large='24px',
                extra_large='32px',
                border_radius='6px',
                border_width='1px',
                shadow_blur='6px'
            ),
            layout_style=WizardLayoutStyle.CARDS,
            animation=WizardAnimationSettings(
                type=WizardAnimationType.SLIDE_LEFT,
                duration='0.4s',
                easing='cubic-bezier(0.4, 0, 0.2, 1)',
                delay='0s'
            ),
            progress_bar_style='neon',
            button_style='modern',
            form_field_style='filled',
            card_style='glass'
        )
        
        # Elegant Purple Theme
        self.themes['elegant_purple'] = WizardTheme(
            id='elegant_purple',
            name='Elegant Purple',
            description='Sophisticated purple theme with elegant typography',
            color_scheme=WizardColorScheme.PURPLE,
            color_palette=WizardColorPalette(
                primary='#6f42c1',
                secondary='#6c757d',
                success='#20c997',
                warning='#fd7e14',
                danger='#e83e8c',
                info='#0dcaf0',
                light='#f8f9fa',
                dark='#495057',
                background='#fdfbff',
                surface='#ffffff',
                text_primary='#2d3436',
                text_secondary='#636e72',
                border='#e9ecef',
                shadow='rgba(111,66,193,0.1)'
            ),
            typography=WizardTypography(
                font_family='"Playfair Display", Georgia, serif',
                font_size_base='16px',
                font_size_small='14px',
                font_size_large='18px',
                font_size_heading='28px',
                font_weight_normal='400',
                font_weight_bold='700',
                line_height='1.6',
                letter_spacing='0.01em'
            ),
            spacing=WizardSpacing(
                base_unit='10px',
                small='10px',
                medium='20px',
                large='30px',
                extra_large='40px',
                border_radius='12px',
                border_width='2px',
                shadow_blur='8px'
            ),
            layout_style=WizardLayoutStyle.STEPPER,
            animation=WizardAnimationSettings(
                type=WizardAnimationType.ZOOM,
                duration='0.5s',
                easing='ease-out',
                delay='0.1s'
            ),
            progress_bar_style='elegant',
            button_style='elegant',
            form_field_style='underlined',
            card_style='elegant'
        )
        
        # Minimal Green Theme
        self.themes['minimal_green'] = WizardTheme(
            id='minimal_green',
            name='Minimal Green',
            description='Clean, minimal design with green accents',
            color_scheme=WizardColorScheme.GREEN,
            color_palette=WizardColorPalette(
                primary='#10b981',
                secondary='#6b7280',
                success='#059669',
                warning='#d97706',
                danger='#dc2626',
                info='#0891b2',
                light='#f9fafb',
                dark='#1f2937',
                background='#ffffff',
                surface='#f9fafb',
                text_primary='#111827',
                text_secondary='#6b7280',
                border='#d1d5db',
                shadow='rgba(0,0,0,0.05)'
            ),
            typography=WizardTypography(
                font_family='"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
                font_size_base='15px',
                font_size_small='13px',
                font_size_large='17px',
                font_size_heading='22px',
                font_weight_normal='400',
                font_weight_bold='500',
                line_height='1.6',
                letter_spacing='-0.01em'
            ),
            spacing=WizardSpacing(
                base_unit='6px',
                small='6px',
                medium='12px',
                large='18px',
                extra_large='24px',
                border_radius='4px',
                border_width='1px',
                shadow_blur='2px'
            ),
            layout_style=WizardLayoutStyle.HORIZONTAL,
            animation=WizardAnimationSettings(
                type=WizardAnimationType.SLIDE_UP,
                duration='0.2s',
                easing='ease-in-out',
                delay='0s'
            ),
            progress_bar_style='minimal',
            button_style='minimal',
            form_field_style='minimal',
            card_style='minimal'
        )
        
        # Corporate Orange Theme
        self.themes['corporate_orange'] = WizardTheme(
            id='corporate_orange',
            name='Corporate Orange',
            description='Professional corporate theme with orange branding',
            color_scheme=WizardColorScheme.ORANGE,
            color_palette=WizardColorPalette(
                primary='#ea580c',
                secondary='#64748b',
                success='#16a34a',
                warning='#eab308',
                danger='#dc2626',
                info='#0ea5e9',
                light='#f1f5f9',
                dark='#0f172a',
                background='#ffffff',
                surface='#fafafa',
                text_primary='#0f172a',
                text_secondary='#475569',
                border='#cbd5e1',
                shadow='rgba(0,0,0,0.08)'
            ),
            typography=WizardTypography(
                font_family='"Open Sans", Arial, sans-serif',
                font_size_base='16px',
                font_size_small='14px',
                font_size_large='18px',
                font_size_heading='26px',
                font_weight_normal='400',
                font_weight_bold='600',
                line_height='1.5',
                letter_spacing='normal'
            ),
            spacing=WizardSpacing(
                base_unit='8px',
                small='8px',
                medium='16px',
                large='24px',
                extra_large='32px',
                border_radius='6px',
                border_width='1px',
                shadow_blur='6px'
            ),
            layout_style=WizardLayoutStyle.TABS,
            animation=WizardAnimationSettings(
                type=WizardAnimationType.SLIDE_RIGHT,
                duration='0.3s',
                easing='ease-in-out',
                delay='0s'
            ),
            progress_bar_style='corporate',
            button_style='corporate',
            form_field_style='corporate',
            card_style='corporate'
        )
    
    def get_theme(self, theme_id: str) -> Optional[WizardTheme]:
        """Get a theme by ID"""
        return self.themes.get(theme_id)
    
    def get_all_themes(self) -> List[WizardTheme]:
        """Get all available themes"""
        return list(self.themes.values())
    
    def create_custom_theme(self, theme_config: Dict[str, Any]) -> WizardTheme:
        """Create a custom theme from configuration"""
        # Parse the config and create a WizardTheme instance
        try:
            # Extract theme properties from configuration
            theme_id = theme_config.get('id', f'custom_{len(self.themes)}')
            theme_name = theme_config.get('name', 'Custom Theme')
            description = theme_config.get('description', 'User-created custom theme')
            
            # Parse color palette
            colors = theme_config.get('colors', {})
            color_palette = WizardColorPalette(
                primary=colors.get('primary', '#007bff'),
                secondary=colors.get('secondary', '#6c757d'),
                success=colors.get('success', '#28a745'),
                info=colors.get('info', '#17a2b8'),
                warning=colors.get('warning', '#ffc107'),
                danger=colors.get('danger', '#dc3545'),
                light=colors.get('light', '#f8f9fa'),
                dark=colors.get('dark', '#343a40'),
                background=colors.get('background', '#ffffff'),
                surface=colors.get('surface', '#f5f5f5'),
                text_primary=colors.get('text_primary', '#212529'),
                text_secondary=colors.get('text_secondary', '#6c757d')
            )
            
            # Parse typography
            typography_config = theme_config.get('typography', {})
            typography = WizardTypography(
                font_family=typography_config.get('font_family', 'system-ui, -apple-system'),
                base_size=typography_config.get('base_size', '14px'),
                line_height=typography_config.get('line_height', '1.5'),
                heading_weight=typography_config.get('heading_weight', '600'),
                body_weight=typography_config.get('body_weight', '400')
            )
            
            # Parse animations
            animations_config = theme_config.get('animations', {})
            animations = WizardAnimations(
                duration=animations_config.get('duration', '0.3s'),
                easing=animations_config.get('easing', 'ease-in-out'),
                hover_scale=animations_config.get('hover_scale', '1.02'),
                transition_properties=animations_config.get('transition_properties', ['all'])
            )
            
            # Create custom theme
            custom_theme = WizardTheme(
                id=theme_id,
                name=theme_name,
                description=description,
                color_scheme=WizardColorScheme.LIGHT if theme_config.get('color_scheme') != 'dark' else WizardColorScheme.DARK,
                color_palette=color_palette,
                typography=typography,
                animations=animations,
                custom_css=theme_config.get('custom_css', '')
            )
            
            # Store the custom theme
            self.themes[theme_id] = custom_theme
            
            return custom_theme
            
        except Exception as e:
            logger.error(f"Error creating custom theme: {e}")
            # Return a copy of the modern_blue theme as fallback
            base_theme = self.themes['modern_blue']
            return WizardTheme(
                id=theme_config.get('id', 'custom_fallback'),
                name=theme_config.get('name', 'Custom Theme'),
                description='Custom theme (fallback)',
                color_scheme=base_theme.color_scheme,
                color_palette=base_theme.color_palette,
                typography=base_theme.typography,
                animations=base_theme.animations
            )
    
    def generate_theme_css(self, theme_id: str) -> str:
        """Generate CSS for a specific theme"""
        theme = self.get_theme(theme_id)
        if not theme:
            return ""
        
        return theme.to_css()
    
    def export_theme(self, theme_id: str) -> str:
        """Export a theme as JSON"""
        theme = self.get_theme(theme_id)
        if not theme:
            return "{}"
        
        return json.dumps(asdict(theme), indent=2, default=str)
    
    def import_theme(self, theme_json: str) -> bool:
        """Import a theme from JSON"""
        try:
            theme_data = json.loads(theme_json)
            # Create WizardTheme from the imported data
            imported_theme = self.create_custom_theme(theme_data)
            
            # Validate the imported theme
            if imported_theme.id in self.themes:
                logger.info(f"Successfully imported theme: {imported_theme.name}")
                return True
            else:
                logger.error(f"Failed to create theme from imported data")
                return False
        except Exception as e:
            logger.error(f"Failed to import theme: {e}")
            return False
    
    def get_theme_preview_data(self, theme_id: str) -> Dict[str, Any]:
        """Get theme preview data for UI"""
        theme = self.get_theme(theme_id)
        if not theme:
            return {}
        
        return {
            'id': theme.id,
            'name': theme.name,
            'description': theme.description,
            'color_scheme': theme.color_scheme.value,
            'primary_color': theme.color_palette.primary,
            'secondary_color': theme.color_palette.secondary,
            'background_color': theme.color_palette.background,
            'text_color': theme.color_palette.text_primary,
            'layout_style': theme.layout_style.value,
            'animation_type': theme.animation.type.value,
            'preview_css': theme.to_css()[:500] + "..." if len(theme.to_css()) > 500 else theme.to_css()
        }


# Global theme manager instance
wizard_theme_manager = WizardThemeManager()