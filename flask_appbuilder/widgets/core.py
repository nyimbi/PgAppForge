"""
Created on Oct 12, 2013

@author: Daniel Gaspar
"""

import logging

from flask import current_app

from flask_appbuilder._compat import as_unicode
from .xss_security import XSSProtection


log = logging.getLogger(__name__)


class RenderTemplateWidget(object):
    """
    Base template for every widget.
    Enables the possibility of rendering a template inside a template 
    with run time options.
    """

    template = "appbuilder/general/widgets/render.html"
    template_args = None

    def __init__(self, **kwargs):
        """
        Initialize the widget with template arguments.
        
        :param kwargs: Template arguments to pass to the widget
        """
        self.template_args = kwargs

    def __call__(self, **kwargs):
        """
        Render the widget template with the provided arguments.
        
        :param kwargs: Additional template arguments
        :return: Rendered HTML string
        """
        jinja_env = current_app.jinja_env

        template = jinja_env.get_template(self.template)
        args = self.template_args.copy()
        args.update(kwargs)
        return template.render(args)


class FormWidget(RenderTemplateWidget):
    """
    Widget for rendering forms.
    
    Attributes:
        form: The form instance to render
        include_cols: List of columns to include in the form
        exclude_cols: List of columns to exclude from the form  
        fieldsets: List of fieldsets for organizing form fields
    """

    template = "appbuilder/general/widgets/form.html"
    form = None
    include_cols = []
    exclude_cols = []
    fieldsets = []

    def __init__(self, form=None, include_cols=None, exclude_cols=None, fieldsets=None, **kwargs):
        """
        Initialize the form widget.
        
        :param form: Form instance to render
        :param include_cols: Columns to include
        :param exclude_cols: Columns to exclude
        :param fieldsets: Fieldset configuration
        :param kwargs: Additional template arguments
        """
        super(FormWidget, self).__init__(**kwargs)
        if form:
            self.form = form
        if include_cols:
            self.include_cols = include_cols
        if exclude_cols:
            self.exclude_cols = exclude_cols
        if fieldsets:
            self.fieldsets = fieldsets


class ShowWidget(RenderTemplateWidget):
    """
    Widget for rendering show/detail views.
    
    Attributes:
        model: The model instance to display
        include_cols: List of columns to include
        exclude_cols: List of columns to exclude
        fieldsets: List of fieldsets for organizing fields
    """

    template = "appbuilder/general/widgets/show.html"
    model = None
    include_cols = []
    exclude_cols = []
    fieldsets = []

    def __init__(self, model=None, include_cols=None, exclude_cols=None, fieldsets=None, **kwargs):
        """
        Initialize the show widget.
        
        :param model: Model instance to display
        :param include_cols: Columns to include
        :param exclude_cols: Columns to exclude
        :param fieldsets: Fieldset configuration
        :param kwargs: Additional template arguments
        """
        super(ShowWidget, self).__init__(**kwargs)
        if model:
            self.model = model
        if include_cols:
            self.include_cols = include_cols
        if exclude_cols:
            self.exclude_cols = exclude_cols
        if fieldsets:
            self.fieldsets = fieldsets


class ListWidget(RenderTemplateWidget):
    """
    Widget for rendering list/table views.
    
    Attributes:
        list_columns: List of columns to display
        order_columns: List of columns that can be ordered
        page_size: Number of records per page
        search_columns: List of searchable columns
    """

    template = "appbuilder/general/widgets/list.html"
    list_columns = []
    order_columns = []
    page_size = 20
    search_columns = []

    def __init__(self, list_columns=None, order_columns=None, page_size=None, 
                 search_columns=None, **kwargs):
        """
        Initialize the list widget.
        
        :param list_columns: Columns to display in the list
        :param order_columns: Columns available for ordering
        :param page_size: Records per page
        :param search_columns: Searchable columns
        :param kwargs: Additional template arguments
        """
        super(ListWidget, self).__init__(**kwargs)
        if list_columns:
            self.list_columns = list_columns
        if order_columns:
            self.order_columns = order_columns
        if page_size:
            self.page_size = page_size
        if search_columns:
            self.search_columns = search_columns


class SearchWidget(RenderTemplateWidget):
    """
    Widget for rendering search forms.
    
    Attributes:
        search_form: The search form instance
        search_columns: List of searchable columns
        filters: Available filters for the search
    """

    template = "appbuilder/general/widgets/search.html"
    search_form = None
    search_columns = []
    filters = []

    def __init__(self, search_form=None, search_columns=None, filters=None, **kwargs):
        """
        Initialize the search widget.
        
        :param search_form: Search form instance
        :param search_columns: Columns available for search
        :param filters: Available filter options
        :param kwargs: Additional template arguments
        """
        super(SearchWidget, self).__init__(**kwargs)
        if search_form:
            self.search_form = search_form
        if search_columns:
            self.search_columns = search_columns
        if filters:
            self.filters = filters


class MenuWidget(RenderTemplateWidget):
    """
    Widget for rendering navigation menus.
    
    Attributes:
        menu: Menu structure to render
        template: Template for menu rendering
    """

    template = "appbuilder/general/widgets/menu.html"
    menu = None

    def __init__(self, menu=None, **kwargs):
        """
        Initialize the menu widget.
        
        :param menu: Menu structure to render
        :param kwargs: Additional template arguments
        """
        super(MenuWidget, self).__init__(**kwargs)
        if menu:
            self.menu = menu


class ChartWidget(RenderTemplateWidget):
    """
    Widget for rendering charts and graphs.
    
    Attributes:
        chart_type: Type of chart (line, bar, pie, etc.)
        data: Chart data
        options: Chart configuration options
    """

    template = "appbuilder/general/widgets/chart.html"
    chart_type = "line"
    data = None
    options = {}

    def __init__(self, chart_type=None, data=None, options=None, **kwargs):
        """
        Initialize the chart widget.
        
        :param chart_type: Type of chart to render
        :param data: Chart data
        :param options: Chart configuration
        :param kwargs: Additional template arguments
        """
        super(ChartWidget, self).__init__(**kwargs)
        if chart_type:
            self.chart_type = chart_type
        if data:
            self.data = data
        if options:
            self.options = options


class GroupFormListWidget(RenderTemplateWidget):
    """
    Widget for rendering group form lists.
    
    Provides structured display of grouped form elements
    with enhanced organization and presentation.
    """
    
    template = "appbuilder/general/widgets/group_form_list.html"


class ListMasterWidget(RenderTemplateWidget):
    """Widget for rendering master list views."""
    
    template = "appbuilder/general/widgets/list_master.html"


class ListAddWidget(RenderTemplateWidget):
    """Widget for rendering add item lists."""
    
    template = "appbuilder/general/widgets/list_add.html"


class ListThumbnail(RenderTemplateWidget):
    """Widget for rendering thumbnail list views."""
    
    template = "appbuilder/general/widgets/list_thumbnail.html"


class ListLinkWidget(RenderTemplateWidget):
    """Widget for rendering link list views."""
    
    template = "appbuilder/general/widgets/list_link.html"


class ListCarousel(RenderTemplateWidget):
    """Widget for rendering carousel list views."""
    
    template = "appbuilder/general/widgets/list_carousel.html"


class ListItem(RenderTemplateWidget):
    """Widget for rendering individual list items."""
    
    template = "appbuilder/general/widgets/list_item.html"


class ListBlock(RenderTemplateWidget):
    """Widget for rendering block-style lists."""
    
    template = "appbuilder/general/widgets/list_block.html"


class ShowBlockWidget(RenderTemplateWidget):
    """Widget for rendering block-style show views."""
    
    template = "appbuilder/general/widgets/show_block.html"


class ShowVerticalWidget(RenderTemplateWidget):
    """Widget for rendering vertical show views."""
    
    template = "appbuilder/general/widgets/show_vertical.html"


class FormVerticalWidget(RenderTemplateWidget):
    """Widget for rendering vertical forms."""
    
    template = "appbuilder/general/widgets/form_vertical.html"


class FormHorizontalWidget(RenderTemplateWidget):
    """Widget for rendering horizontal forms."""
    
    template = "appbuilder/general/widgets/form_horizontal.html"


class FormInlineWidget(RenderTemplateWidget):
    """Widget for rendering inline forms."""
    
    template = "appbuilder/general/widgets/form_inline.html"


class ApprovalWidget(FormWidget):
    """
    Widget for adding approval functionality to Flask-AppBuilder forms.
    
    Integrates with existing Flask-AppBuilder security system to provide
    simple approval/rejection capabilities for records with status tracking.
    """
    
    template = "appbuilder/general/widgets/approval.html"
    
    def __init__(self, approval_required=False, **kwargs):
        """
        Initialize the approval widget.
        
        :param approval_required: Whether approval is required for this form
        :param kwargs: Additional template arguments
        """
        super(ApprovalWidget, self).__init__(**kwargs)
        self.approval_required = approval_required
    
    def render_approval_buttons(self, obj, user=None):
        """
        Render approval/rejection buttons if user has permission.
        
        :param obj: The object being approved
        :param user: User attempting the action (defaults to current_user)
        :return: Rendered HTML for approval buttons or empty string
        """
        from flask_login import current_user
        
        if not user:
            user = current_user
        
        # Only show buttons if approval is required and object is pending approval
        if not self.approval_required or not hasattr(obj, 'status'):
            return ''
            
        if obj.status != 'pending_approval':
            return ''
        
        # Check if user has approval permissions
        if not self._can_approve_user(user):
            return ''
        
        # Render approval buttons template
        jinja_env = current_app.jinja_env
        
        try:
            template = jinja_env.get_template('appbuilder/widgets/approval_buttons.html')
            return template.render(
                object_id=getattr(obj, 'id', None),
                object_name=XSSProtection.escape_html(getattr(obj, 'name', str(obj))),
                can_approve=True,
                csrf_token=self._get_csrf_token()
            )
        except Exception as e:
            log.warning(f"Failed to render approval buttons: {e}")
            return ''
    
    def _can_approve_user(self, user):
        """
        Check if current user can approve using existing security patterns.
        
        :param user: User to check permissions for
        :return: True if user can approve
        """
        if not user or not hasattr(user, 'has_permission'):
            return False
        
        # Check standard Flask-AppBuilder permissions
        return (user.has_permission('approve_records') or 
                user.has_permission('can_approve') or
                user.has_role('Admin'))
    
    def _get_csrf_token(self):
        """Get CSRF token for approval forms."""
        try:
            from flask_wtf.csrf import generate_csrf
            return generate_csrf()
        except ImportError:
            # Fallback if Flask-WTF is not available
            return ''
    
    def get_approval_status_badge(self, obj):
        """
        Get HTML badge for approval status.

        :param obj: Object to get status for
        :return: HTML badge showing approval status
        """
        if not hasattr(obj, 'status'):
            return ''

        status_classes = {
            'draft': 'badge-secondary',
            'pending_approval': 'badge-warning',
            'approved': 'badge-success',
            'rejected': 'badge-danger',
            'archived': 'badge-dark'
        }

        css_class = status_classes.get(obj.status, 'badge-secondary')
        status_text = XSSProtection.escape_html(obj.status.replace('_', ' ').title())

        # Use safe HTML generation instead of f-string formatting
        return XSSProtection.create_safe_html(
            'span',
            content=status_text,
            attributes={'class': f'badge {css_class}'}
        )


class MenuWidget(RenderTemplateWidget):
    """Widget for rendering navigation menus."""
    
    template = "appbuilder/general/widgets/menu.html"


class ChartWidget(RenderTemplateWidget):
    """Widget for rendering charts."""
    
    template = "appbuilder/general/widgets/chart.html"