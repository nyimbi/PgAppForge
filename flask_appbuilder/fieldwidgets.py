from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import widgets
from wtforms.widgets import html_params


class DatePickerWidget:
    """
    Date Time picker from Eonasdan GitHub

    """

    data_template = (
        '<div class="input-group date appbuilder_date"'
        ' data-provide="datepicker" id="datepicker">'
        '<span class="input-group-addon"><i class="fa fa-calendar cursor-hand"></i>'
        "</span>"
        '<input class="form-control" data-format="yyyy-MM-dd" %(text)s />'
        "</div>"
    )

    def __call__(self, field, **kwargs):
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)
        if not field.data:
            field.data = ""
        template = self.data_template

        return Markup(
            template % {"text": html_params(type="text", value=field.data, **kwargs)}
        )


class DateTimePickerWidget:
    """
    Date Time picker from Eonasdan GitHub

    """

    data_template = (
        '<div class="input-group date appbuilder_datetime" '
        'data-provide="datepicker" id="datetimepicker">'
        '<span class="input-group-addon"><i class="fa fa-calendar cursor-hand"></i>'
        "</span>"
        '<input class="form-control" data-format="yyyy-MM-dd hh:mm:ss" %(text)s />'
        "</div>"
    )

    def __call__(self, field, **kwargs):
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)
        if not field.data:
            field.data = ""
        template = self.data_template

        return Markup(
            template % {"text": html_params(type="text", value=field.data, **kwargs)}
        )


class BS3TextFieldWidget(widgets.TextInput):
    """Bootstrap 3 text field widget with form-control styling."""
    
    def __call__(self, field, **kwargs):
        """
        Render the text field widget with Bootstrap 3 styling.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the text input field
        """
        kwargs["class"] = "form-control"
        if field.label:
            kwargs["placeholder"] = field.label.text
        if "name_" in kwargs:
            field.name = kwargs["name_"]
        return super(BS3TextFieldWidget, self).__call__(field, **kwargs)


class BS3TextAreaFieldWidget(widgets.TextArea):
    """Bootstrap 3 textarea widget with form-control styling."""

    def __init__(self, rows=3):
        self.rows = rows

    def __call__(self, field, **kwargs):
        kwargs["class"] = "form-control"
        kwargs["rows"] = self.rows
        if field.label:
            kwargs["placeholder"] = field.label.text
        return super(BS3TextAreaFieldWidget, self).__call__(field, **kwargs)


class BS3PasswordFieldWidget(widgets.PasswordInput):
    """Bootstrap 3 password field widget with form-control styling."""
    
    def __call__(self, field, **kwargs):
        """
        Render the password field widget with Bootstrap 3 styling.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the password input field
        """
        kwargs["class"] = "form-control"
        if field.label:
            kwargs["placeholder"] = field.label.text
        return super(BS3PasswordFieldWidget, self).__call__(field, **kwargs)


class BS3SelectFieldWidget(widgets.Select):
    """Bootstrap 3 select field widget with form-control styling."""

    def __call__(self, field, **kwargs):
        kwargs["class"] = "form-control"
        return super(BS3SelectFieldWidget, self).__call__(field, **kwargs)


class BS3SelectMultipleFieldWidget(widgets.Select):
    """Bootstrap 3 multiple-select field widget with form-control styling."""

    def __call__(self, field, **kwargs):
        kwargs["class"] = "form-control"
        kwargs["multiple"] = True
        return super(BS3SelectMultipleFieldWidget, self).__call__(field, **kwargs)


class Select2AJAXWidget:
    """Select2 widget with AJAX support for dynamic option loading."""
    
    data_template = "<input %(text)s />"

    def __init__(self, endpoint, extra_classes=None, style=None):
        """
        Initialize the Select2 AJAX widget.
        
        Args:
            endpoint: AJAX endpoint URL for fetching options
            extra_classes: Additional CSS classes to apply
            style: Inline CSS styles to apply
        """
        self.endpoint = endpoint
        self.extra_classes = extra_classes
        self.style = style or ""

    def __call__(self, field, **kwargs):
        """
        Render the Select2 AJAX widget.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the Select2 AJAX input field
        """
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)
        kwargs.setdefault("endpoint", self.endpoint)
        if self.style:
            kwargs.setdefault("style", self.style)
        input_classes = "input-group my_select2_ajax"
        if self.extra_classes:
            input_classes = input_classes + " " + self.extra_classes
        kwargs.setdefault("class", input_classes)
        if not field.data:
            field.data = ""
        template = self.data_template

        return Markup(
            template % {"text": html_params(type="text", value=field.data, **kwargs)}
        )


class Select2SlaveAJAXWidget:
    """Select2 slave widget that depends on a master field for AJAX filtering."""
    
    data_template = '<input class="input-group my_select2_ajax_slave" %(text)s />'

    def __init__(self, master_id, endpoint, extra_classes=None, style=None):
        """
        Initialize the Select2 slave AJAX widget.
        
        Args:
            master_id: ID of the master field that controls this slave field
            endpoint: AJAX endpoint URL for fetching filtered options
            extra_classes: Additional CSS classes to apply
            style: Inline CSS styles to apply
        """
        self.endpoint = endpoint
        self.master_id = master_id
        self.extra_classes = extra_classes
        self.style = style or ""

    def __call__(self, field, **kwargs):
        """
        Render the Select2 slave AJAX widget.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the Select2 slave AJAX input field
        """
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)
        kwargs.setdefault("endpoint", self.endpoint)
        kwargs.setdefault("master_id", self.master_id)
        if self.style:
            kwargs.setdefault("style", self.style)
        input_classes = "input-group my_select2_ajax"
        if self.extra_classes:
            input_classes = input_classes + " " + self.extra_classes
        kwargs.setdefault("class", input_classes)

        if not field.data:
            field.data = ""
        template = self.data_template

        return Markup(
            template % {"text": html_params(type="text", value=field.data, **kwargs)}
        )


class Select2Widget(widgets.Select):
    """Select2 widget for enhanced select dropdowns."""
    
    extra_classes = None

    def __init__(self, extra_classes=None, style=None):
        """
        Initialize the Select2 widget.
        
        Args:
            extra_classes: Additional CSS classes to apply
            style: Inline CSS styles to apply
        """
        self.extra_classes = extra_classes
        self.style = style
        super(Select2Widget, self).__init__()

    def __call__(self, field, **kwargs):
        """
        Render the Select2 widget.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the Select2 select field
        """
        kwargs["class"] = "my_select2 form-control"
        if self.extra_classes:
            kwargs["class"] = kwargs["class"] + " " + self.extra_classes
        if self.style:
            kwargs["style"] = self.style
        kwargs["data-placeholder"] = _("Select Value")
        if "name_" in kwargs:
            field.name = kwargs["name_"]
        return super(Select2Widget, self).__call__(field, **kwargs)


class Select2ManyWidget(widgets.Select):
    """Select2 widget for multiple selection dropdowns."""
    
    extra_classes = None

    def __init__(self, extra_classes=None, style=None):
        """
        Initialize the Select2 many widget.
        
        Args:
            extra_classes: Additional CSS classes to apply
            style: Inline CSS styles to apply
        """
        self.extra_classes = extra_classes
        self.style = style
        super(Select2ManyWidget, self).__init__()

    def __call__(self, field, **kwargs):
        """
        Render the Select2 multiple selection widget.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the Select2 multi-select field
        """
        kwargs["class"] = "my_select2 form-control"
        if self.extra_classes:
            kwargs["class"] = kwargs["class"] + " " + self.extra_classes
        if self.style:
            kwargs["style"] = self.style
        kwargs["data-placeholder"] = _("Select Value")
        kwargs["multiple"] = "true"
        if "name_" in kwargs:
            field.name = kwargs["name_"]
        return super(Select2ManyWidget, self).__call__(field, **kwargs)
