"""
Enhanced Menu Rendering System for PgForge

Provides configurable menu rendering with support for multiple layouts:
- Traditional navbar dropdown (default)
- Collapsible tree sidebar
- Compact sidebar 
- Breadcrumb navigation
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from enum import Enum

from flask import current_app, render_template_string
from flask_babel import gettext as __


class MenuRenderMode(Enum):
    """Available menu rendering modes."""
    NAVBAR = "navbar"
    TREE = "tree"
    SIDEBAR = "sidebar"
    BREADCRUMB = "breadcrumb"
    MEGA_MENU = "mega_menu"
    TABS = "tabs"
    CONTEXT_MENU = "context_menu"
    FLOATING_ACTION = "floating_action"
    ACCORDION = "accordion"
    HORIZONTAL_SCROLL = "horizontal_scroll"


class MenuPosition(Enum):
    """Available menu positions."""
    TOP = "top"
    LEFT = "left"
    RIGHT = "right"


class MenuTheme(Enum):
    """Available menu themes."""
    LIGHT = "light"
    DARK = "dark"
    CUSTOM = "custom"


class MenuRenderConfig:
    """Configuration for menu rendering."""
    
    def __init__(self, 
                 render_mode: MenuRenderMode = MenuRenderMode.NAVBAR,
                 position: MenuPosition = MenuPosition.TOP,
                 collapsible: bool = True,
                 theme: MenuTheme = MenuTheme.LIGHT,
                 max_depth: int = 3,
                 show_icons: bool = True,
                 show_badges: bool = True,
                 animation_duration: int = 300,
                 auto_collapse: bool = False,
                 compact_mode: bool = False):
        """
        Initialize menu render configuration.
        
        Args:
            render_mode: How to render the menu (navbar, tree, sidebar, breadcrumb)
            position: Where to position the menu (top, left, right)
            collapsible: Whether menu items can be collapsed
            theme: Visual theme for the menu
            max_depth: Maximum nesting depth to render
            show_icons: Whether to show icons
            show_badges: Whether to show notification badges
            animation_duration: Duration for animations in milliseconds
            auto_collapse: Auto-collapse other sections when expanding
            compact_mode: Use compact spacing and sizing
        """
        self.render_mode = render_mode
        self.position = position
        self.collapsible = collapsible
        self.theme = theme
        self.max_depth = max_depth
        self.show_icons = show_icons
        self.show_badges = show_badges
        self.animation_duration = animation_duration
        self.auto_collapse = auto_collapse
        self.compact_mode = compact_mode

    @classmethod
    def from_app_config(cls, app=None):
        """
        Create configuration from Flask app config.
        
        Args:
            app: Flask application instance
            
        Returns:
            MenuRenderConfig instance
        """
        if app is None:
            app = current_app
            
        config = app.config
        
        return cls(
            render_mode=MenuRenderMode(config.get('MENU_RENDER_MODE', 'navbar')),
            position=MenuPosition(config.get('MENU_POSITION', 'top')),
            collapsible=config.get('MENU_COLLAPSIBLE', True),
            theme=MenuTheme(config.get('MENU_THEME', 'light')),
            max_depth=config.get('MENU_MAX_DEPTH', 3),
            show_icons=config.get('MENU_SHOW_ICONS', True),
            show_badges=config.get('MENU_SHOW_BADGES', True),
            animation_duration=config.get('MENU_ANIMATION_DURATION', 300),
            auto_collapse=config.get('MENU_AUTO_COLLAPSE', False),
            compact_mode=config.get('MENU_COMPACT_MODE', False)
        )


class BaseMenuRenderer(ABC):
    """Abstract base class for menu renderers."""
    
    def __init__(self, config: MenuRenderConfig):
        """
        Initialize the renderer.
        
        Args:
            config: Menu rendering configuration
        """
        self.config = config
    
    @abstractmethod
    def render(self, menu_items: List, **kwargs) -> str:
        """
        Render the menu items.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for the rendered menu
        """
        pass
    
    @abstractmethod
    def get_css_classes(self) -> str:
        """
        Get CSS classes for this renderer.
        
        Returns:
            CSS classes string
        """
        pass
    
    @abstractmethod
    def get_javascript(self) -> str:
        """
        Get JavaScript code for this renderer.
        
        Returns:
            JavaScript code string
        """
        pass
    
    def _should_render_item(self, item) -> bool:
        """
        Check if a menu item should be rendered.
        
        Args:
            item: MenuItem to check
            
        Returns:
            True if item should be rendered
        """
        if hasattr(item, 'should_render'):
            return item.should_render()
        return True
    
    def _get_item_depth(self, item, current_depth: int = 0) -> int:
        """
        Get the depth of a menu item.
        
        Args:
            item: MenuItem to check
            current_depth: Current depth level
            
        Returns:
            Depth of the item
        """
        if current_depth >= self.config.max_depth:
            return current_depth
        
        if hasattr(item, 'childs') and item.childs:
            return max(self._get_item_depth(child, current_depth + 1) 
                      for child in item.childs)
        
        return current_depth


class NavbarRenderer(BaseMenuRenderer):
    """Traditional navbar dropdown renderer (default PgForge style)."""
    
    def render(self, menu_items: List, **kwargs) -> str:
        """
        Render menu as traditional navbar dropdown.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for navbar menu
        """
        template = '''
        {% for item1 in menu_items %}
            {% if item1 | is_menu_visible %}
                {% if item1.childs %}
                    <li class="dropdown">
                    <a class="dropdown-toggle" data-toggle="dropdown" href="#">
                    {% if config.show_icons and item1.icon %}
                        <i class="fa {{item1.icon}}"></i>&nbsp;
                    {% endif %}
                    {{_(item1.label)}}<b class="caret"></b></a>
                    <ul class="dropdown-menu">
                    {% for item2 in item1.childs %}
                        {% if item2 %}
                            {% if item2.name == '-' %}
                                {% if not loop.last %}
                                  <li class="divider"></li>
                                {% endif %}
                            {% elif item2 | is_menu_visible %}
                                <li><a tabindex="-1" href="{{item2.get_url()}}">
                                {% if config.show_icons and item2.icon %}
                                    <i class="fa fa-fw {{item2.icon}}"></i>&nbsp;
                                {% endif %}
                                {{_(item2.label)}}</a></li>
                            {% endif %}
                        {% endif %}
                    {% endfor %}
                    </ul></li>
                {% else %}
                    <li>
                        <a href="{{item1.get_url()}}">
                        {% if config.show_icons and item1.icon %}
                            <i class="fa {{item1.icon}}"></i>&nbsp;
                        {% endif %}
                        {{_(item1.label)}}</a>
                    </li>
                {% endif %}
            {% endif %}
        {% endfor %}
        '''
        
        return render_template_string(template, 
                                    menu_items=menu_items, 
                                    config=self.config,
                                    _=__)
    
    def get_css_classes(self) -> str:
        """Get CSS classes for navbar renderer."""
        classes = ['fab-navbar-menu']
        if self.config.theme == MenuTheme.DARK:
            classes.append('navbar-dark')
        elif self.config.theme == MenuTheme.LIGHT:
            classes.append('navbar-light')
        if self.config.compact_mode:
            classes.append('navbar-compact')
        return ' '.join(classes)
    
    def get_javascript(self) -> str:
        """Get JavaScript for navbar renderer."""
        return '''
        $(document).ready(function() {
            $('.dropdown-toggle').dropdown();
        });
        '''


class CollapsibleTreeRenderer(BaseMenuRenderer):
    """Collapsible tree sidebar renderer with hierarchical navigation."""
    
    def render(self, menu_items: List, **kwargs) -> str:
        """
        Render menu as collapsible tree sidebar.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for tree menu
        """
        template = '''
        <div class="fab-tree-menu {{self.get_css_classes()}}" data-config="{{config_json}}">
            <div class="tree-menu-header">
                {% if kwargs.get('title') %}
                    <h4>{{kwargs.get('title')}}</h4>
                {% endif %}
                {% if config.collapsible %}
                    <button class="btn btn-sm btn-outline-secondary tree-collapse-all">
                        <i class="fa fa-compress"></i> Collapse All
                    </button>
                {% endif %}
            </div>
            <ul class="tree-menu-root">
                {{ self._render_tree_level(menu_items, 0) }}
            </ul>
        </div>
        '''
        
        config_json = {
            'animation_duration': self.config.animation_duration,
            'auto_collapse': self.config.auto_collapse,
            'max_depth': self.config.max_depth
        }
        
        return render_template_string(template,
                                    menu_items=menu_items,
                                    config=self.config,
                                    config_json=config_json,
                                    self=self,
                                    kwargs=kwargs,
                                    _=__)
    
    def _render_tree_level(self, items: List, depth: int) -> str:
        """
        Render a level of the tree.
        
        Args:
            items: Menu items at this level
            depth: Current depth level
            
        Returns:
            HTML for this tree level
        """
        if depth >= self.config.max_depth:
            return ""
        
        template = '''
        {% for item in items %}
            {% if item | is_menu_visible %}
                <li class="tree-item depth-{{depth}}" data-depth="{{depth}}">
                    {% if item.childs %}
                        <div class="tree-node-header expandable">
                            <span class="tree-toggle">
                                <i class="fa fa-chevron-right toggle-icon"></i>
                            </span>
                            {% if config.show_icons and item.icon %}
                                <i class="fa {{item.icon}} tree-icon"></i>
                            {% endif %}
                            <span class="tree-label">{{_(item.label)}}</span>
                            {% if config.show_badges and hasattr(item, 'badge') and item.badge %}
                                <span class="badge badge-secondary">{{item.badge}}</span>
                            {% endif %}
                        </div>
                        <ul class="tree-children collapsed">
                            {{ self._render_tree_level(item.childs, depth + 1) }}
                        </ul>
                    {% else %}
                        <div class="tree-node-header leaf">
                            <a href="{{item.get_url()}}" class="tree-link">
                                {% if config.show_icons and item.icon %}
                                    <i class="fa {{item.icon}} tree-icon"></i>
                                {% endif %}
                                <span class="tree-label">{{_(item.label)}}</span>
                                {% if config.show_badges and hasattr(item, 'badge') and item.badge %}
                                    <span class="badge badge-secondary">{{item.badge}}</span>
                                {% endif %}
                            </a>
                        </div>
                    {% endif %}
                </li>
            {% endif %}
        {% endfor %}
        '''
        
        return render_template_string(template,
                                    items=items,
                                    depth=depth,
                                    config=self.config,
                                    self=self,
                                    _=__)
    
    def get_css_classes(self) -> str:
        """Get CSS classes for tree renderer."""
        classes = ['fab-tree-menu']
        classes.append(f'theme-{self.config.theme.value}')
        if self.config.compact_mode:
            classes.append('tree-compact')
        return ' '.join(classes)
    
    def get_javascript(self) -> str:
        """Get JavaScript for tree renderer."""
        return f'''
        $(document).ready(function() {{
            var config = {{
                animation_duration: {self.config.animation_duration},
                auto_collapse: {str(self.config.auto_collapse).lower()}
            }};
            
            // Initialize tree menu
            initializeTreeMenu(config);
        }});
        
        function initializeTreeMenu(config) {{
            // Toggle functionality
            $('.tree-toggle').click(function(e) {{
                e.preventDefault();
                var $header = $(this).closest('.tree-node-header');
                var $children = $header.siblings('.tree-children');
                var $icon = $(this).find('.toggle-icon');
                
                if ($children.hasClass('collapsed')) {{
                    // Expand
                    if (config.auto_collapse) {{
                        // Collapse siblings
                        $header.closest('.tree-item').siblings()
                            .find('.tree-children').addClass('collapsed');
                        $header.closest('.tree-item').siblings()
                            .find('.toggle-icon').removeClass('fa-chevron-down')
                            .addClass('fa-chevron-right');
                    }}
                    
                    $children.removeClass('collapsed').slideDown(config.animation_duration);
                    $icon.removeClass('fa-chevron-right').addClass('fa-chevron-down');
                }} else {{
                    // Collapse
                    $children.addClass('collapsed').slideUp(config.animation_duration);
                    $icon.removeClass('fa-chevron-down').addClass('fa-chevron-right');
                }}
            }});
            
            // Collapse all functionality
            $('.tree-collapse-all').click(function() {{
                $('.tree-children').addClass('collapsed').slideUp(config.animation_duration);
                $('.toggle-icon').removeClass('fa-chevron-down').addClass('fa-chevron-right');
            }});
            
            // Highlight active path
            var currentPath = window.location.pathname;
            $('.tree-link').each(function() {{
                if ($(this).attr('href') === currentPath) {{
                    $(this).addClass('active');
                    // Expand parent trees
                    $(this).parents('.tree-children').removeClass('collapsed').show();
                    $(this).parents('.tree-children').siblings('.tree-node-header')
                        .find('.toggle-icon').removeClass('fa-chevron-right')
                        .addClass('fa-chevron-down');
                }}
            }});
        }}
        '''


class SidebarRenderer(BaseMenuRenderer):
    """Compact sidebar renderer with minimal design."""
    
    def render(self, menu_items: List, **kwargs) -> str:
        """
        Render menu as compact sidebar.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for sidebar menu
        """
        template = '''
        <div class="fab-sidebar-menu {{self.get_css_classes()}}" data-position="{{config.position.value}}">
            {% if kwargs.get('title') %}
                <div class="sidebar-header">
                    <h5>{{kwargs.get('title')}}</h5>
                </div>
            {% endif %}
            <nav class="sidebar-nav">
                {{ self._render_sidebar_items(menu_items, 0) }}
            </nav>
        </div>
        '''
        
        return render_template_string(template,
                                    menu_items=menu_items,
                                    config=self.config,
                                    self=self,
                                    kwargs=kwargs,
                                    _=__)
    
    def _render_sidebar_items(self, items: List, depth: int) -> str:
        """
        Render sidebar menu items.
        
        Args:
            items: Menu items to render
            depth: Current depth level
            
        Returns:
            HTML for sidebar items
        """
        template = '''
        {% for item in items %}
            {% if item | is_menu_visible %}
                {% if item.childs %}
                    <div class="sidebar-group depth-{{depth}}">
                        <div class="sidebar-group-header">
                            {% if config.show_icons and item.icon %}
                                <i class="fa {{item.icon}} sidebar-icon"></i>
                            {% endif %}
                            <span class="sidebar-label">{{_(item.label)}}</span>
                        </div>
                        <div class="sidebar-group-items">
                            {{ self._render_sidebar_items(item.childs, depth + 1) }}
                        </div>
                    </div>
                {% else %}
                    <a href="{{item.get_url()}}" class="sidebar-item depth-{{depth}}">
                        {% if config.show_icons and item.icon %}
                            <i class="fa {{item.icon}} sidebar-icon"></i>
                        {% endif %}
                        <span class="sidebar-label">{{_(item.label)}}</span>
                        {% if config.show_badges and hasattr(item, 'badge') and item.badge %}
                            <span class="badge badge-primary sidebar-badge">{{item.badge}}</span>
                        {% endif %}
                    </a>
                {% endif %}
            {% endif %}
        {% endfor %}
        '''
        
        return render_template_string(template,
                                    items=items,
                                    depth=depth,
                                    config=self.config,
                                    self=self,
                                    _=__)
    
    def get_css_classes(self) -> str:
        """Get CSS classes for sidebar renderer."""
        classes = ['fab-sidebar-menu']
        classes.append(f'position-{self.config.position.value}')
        classes.append(f'theme-{self.config.theme.value}')
        if self.config.compact_mode:
            classes.append('sidebar-compact')
        return ' '.join(classes)
    
    def get_javascript(self) -> str:
        """Get JavaScript for sidebar renderer."""
        return '''
        $(document).ready(function() {
            // Highlight active item
            var currentPath = window.location.pathname;
            $('.sidebar-item').each(function() {
                if ($(this).attr('href') === currentPath) {
                    $(this).addClass('active');
                }
            });
            
            // Hover effects
            $('.sidebar-item').hover(
                function() { $(this).addClass('hover'); },
                function() { $(this).removeClass('hover'); }
            );
        });
        '''


class HorizontalScrollRenderer(BaseMenuRenderer):
    """Horizontal scrolling menu renderer for many items."""
    
    def render(self, menu_items: List, **kwargs) -> str:
        """
        Render menu as horizontal scrolling navigation.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for horizontal scroll menu
        """
        template = '''
        <div class="fab-horizontal-scroll-menu {{self.get_css_classes()}}">
            <div class="scroll-container">
                <div class="scroll-content">
                    {% for item in menu_items %}
                        {% if item | is_menu_visible %}
                            <div class="scroll-item">
                                {% if item.childs %}
                                    <div class="scroll-item-dropdown">
                                        <a href="#" class="scroll-link dropdown-toggle" data-toggle="dropdown">
                                            {% if config.show_icons and item.icon %}
                                                <i class="fa {{item.icon}}"></i>
                                            {% endif %}
                                            <span class="scroll-label">{{_(item.label)}}</span>
                                        </a>
                                        <ul class="dropdown-menu">
                                            {% for child in item.childs %}
                                                {% if child | is_menu_visible %}
                                                    <li><a class="dropdown-item" href="{{child.get_url()}}">
                                                        {% if config.show_icons and child.icon %}
                                                            <i class="fa {{child.icon}}"></i>
                                                        {% endif %}
                                                        {{_(child.label)}}
                                                    </a></li>
                                                {% endif %}
                                            {% endfor %}
                                        </ul>
                                    </div>
                                {% else %}
                                    <a href="{{item.get_url()}}" class="scroll-link">
                                        {% if config.show_icons and item.icon %}
                                            <i class="fa {{item.icon}}"></i>
                                        {% endif %}
                                        <span class="scroll-label">{{_(item.label)}}</span>
                                        {% if config.show_badges and hasattr(item, 'badge') and item.badge %}
                                            <span class="badge badge-primary">{{item.badge}}</span>
                                        {% endif %}
                                    </a>
                                {% endif %}
                            </div>
                        {% endif %}
                    {% endfor %}
                </div>
                <button class="scroll-btn scroll-left" onclick="scrollMenuLeft()">
                    <i class="fa fa-chevron-left"></i>
                </button>
                <button class="scroll-btn scroll-right" onclick="scrollMenuRight()">
                    <i class="fa fa-chevron-right"></i>
                </button>
            </div>
        </div>
        '''
        
        return render_template_string(template,
                                    menu_items=menu_items,
                                    config=self.config,
                                    self=self,
                                    _=__)
    
    def get_css_classes(self) -> str:
        """Get CSS classes for horizontal scroll renderer."""
        classes = ['fab-horizontal-scroll-menu']
        classes.append(f'theme-{self.config.theme.value}')
        if self.config.compact_mode:
            classes.append('scroll-compact')
        return ' '.join(classes)
    
    def get_javascript(self) -> str:
        """Get JavaScript for horizontal scroll renderer."""
        return '''
        function scrollMenuLeft() {
            $('.scroll-content').animate({
                scrollLeft: '-=200'
            }, 300);
        }
        
        function scrollMenuRight() {
            $('.scroll-content').animate({
                scrollLeft: '+=200'
            }, 300);
        }
        
        $(document).ready(function() {
            var $scrollContent = $('.scroll-content');
            var $scrollLeft = $('.scroll-left');
            var $scrollRight = $('.scroll-right');
            
            // Show/hide scroll buttons based on content
            function toggleScrollButtons() {
                var scrollLeft = $scrollContent.scrollLeft();
                var scrollWidth = $scrollContent[0].scrollWidth;
                var clientWidth = $scrollContent[0].clientWidth;
                
                $scrollLeft.toggle(scrollLeft > 0);
                $scrollRight.toggle(scrollLeft < scrollWidth - clientWidth);
            }
            
            $scrollContent.on('scroll', toggleScrollButtons);
            $(window).on('resize', toggleScrollButtons);
            toggleScrollButtons();
            
            // Highlight active item
            var currentPath = window.location.pathname;
            $('.scroll-link').each(function() {
                if ($(this).attr('href') === currentPath) {
                    $(this).addClass('active');
                }
            });
        });
        '''


class MenuRenderingEngine:
    """Factory for creating menu renderers based on configuration."""
    
    def __init__(self, config: MenuRenderConfig = None):
        """
        Initialize the rendering engine.
        
        Args:
            config: Menu rendering configuration
        """
        self.config = config or MenuRenderConfig.from_app_config()
        self._renderers = {
            MenuRenderMode.NAVBAR: NavbarRenderer,
            MenuRenderMode.TREE: CollapsibleTreeRenderer,
            MenuRenderMode.SIDEBAR: SidebarRenderer,
            MenuRenderMode.BREADCRUMB: BreadcrumbRenderer,
            MenuRenderMode.MEGA_MENU: MegaMenuRenderer,
            MenuRenderMode.TABS: TabMenuRenderer,
            MenuRenderMode.CONTEXT_MENU: ContextMenuRenderer,
            MenuRenderMode.FLOATING_ACTION: FloatingActionMenuRenderer,
            MenuRenderMode.ACCORDION: AccordionMenuRenderer,
            MenuRenderMode.HORIZONTAL_SCROLL: HorizontalScrollRenderer,
        }
    
    def get_renderer(self) -> BaseMenuRenderer:
        """
        Get the appropriate renderer for the current configuration.
        
        Returns:
            BaseMenuRenderer instance
        """
        renderer_class = self._renderers.get(self.config.render_mode, NavbarRenderer)
        return renderer_class(self.config)
    
    def render_menu(self, menu_items: List, **kwargs) -> str:
        """
        Render menu with the configured renderer.
        
        Args:
            menu_items: List of MenuItem objects
            **kwargs: Additional rendering options
            
        Returns:
            HTML string for rendered menu
        """
        renderer = self.get_renderer()
        return renderer.render(menu_items, **kwargs)
    
    def get_css(self) -> str:
        """
        Get CSS for the current renderer.
        
        Returns:
            CSS string
        """
        renderer = self.get_renderer()
        return f'''
        /* Menu Renderer CSS - {self.config.render_mode.value} */
        .{renderer.get_css_classes().replace(' ', '.')} {{
            /* Base styles will be added here */
        }}
        '''
    
    def get_javascript(self) -> str:
        """
        Get JavaScript for the current renderer.
        
        Returns:
            JavaScript string
        """
        renderer = self.get_renderer()
        return renderer.get_javascript()
    
    def register_renderer(self, mode: MenuRenderMode, renderer_class: type):
        """
        Register a custom renderer.
        
        Args:
            mode: Menu render mode
            renderer_class: Renderer class
        """
        self._renderers[mode] = renderer_class


# Global instance
_menu_engine = None

def get_menu_engine() -> MenuRenderingEngine:
    """
    Get the global menu rendering engine.
    
    Returns:
        MenuRenderingEngine instance
    """
    global _menu_engine
    if _menu_engine is None:
        _menu_engine = MenuRenderingEngine()
    return _menu_engine


def set_menu_engine(engine: MenuRenderingEngine):
    """
    Set the global menu rendering engine.
    
    Args:
        engine: MenuRenderingEngine instance
    """
    global _menu_engine
    _menu_engine = engine