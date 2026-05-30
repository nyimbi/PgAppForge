from flask_babel import gettext
from markupsafe import Markup
from werkzeug.datastructures import FileStorage
from wtforms import fields, ValidationError
from wtforms.widgets import html_params

from .filemanager import FileManager, ImageManager

try:
    from wtforms.fields.core import _unset_value as unset_value
except ImportError:
    from wtforms.utils import unset_value


"""
    Based and thanks to
    https://github.com/mrjoes/flask-admin/blob/master/flask_admin/form/upload.py
"""


class BS3FileUploadFieldWidget(object):
    """Bootstrap 3 file upload widget with styling."""
    
    empty_template = (
        '<div class="input-group">'
        '<span class="input-group-addon"><i class="fa fa-upload"></i>'
        "</span>"
        '<input class="form-control" %(file)s/>'
        "</div>"
    )

    data_template = (
        "<div>"
        " <input %(text)s>"
        ' <input type="checkbox" name="%(marker)s">Delete</input>'
        "</div>"
        '<div class="input-group">'
        '<span class="input-group-addon"><i class="fa fa-upload"></i>'
        "</span>"
        '<input class="form-control" %(file)s/>'
        "</div>"
    )

    def __call__(self, field, **kwargs):
        """
        Render the file upload field widget.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the file upload field
        """
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)

        if not field.data:
            template = self.empty_template
            return Markup(template % {"file": html_params(type="file", **kwargs)})
        else:
            delete_name = field.name + "-delete"
            template = self.data_template
            return Markup(
                template
                % {
                    "text": html_params(
                        type="text", value=field.data, readonly=True
                    ),
                    "file": html_params(type="file", **kwargs),
                    "marker": delete_name,
                }
            )


class BS3ImageUploadFieldWidget(BS3FileUploadFieldWidget):
    """Bootstrap 3 image upload widget with preview."""
    
    data_template = (
        "<div>"
        ' <img style="width: 150px;" src="%(image)s"/>'
        "</div>"
        "<div>"
        " <input %(text)s>"
        ' <input type="checkbox" name="%(marker)s">Delete</input>'
        "</div>"
        '<div class="input-group">'
        '<span class="input-group-addon"><i class="fa fa-upload"></i>'
        "</span>"
        '<input class="form-control" %(file)s/>'
        "</div>"
    )

    def __call__(self, field, **kwargs):
        """
        Render the image upload field widget with preview.
        
        Args:
            field: The form field to render
            **kwargs: Additional HTML attributes
            
        Returns:
            Rendered HTML markup for the image upload field
        """
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("name", field.name)

        if not field.data:
            template = self.empty_template
            return Markup(template % {"file": html_params(type="file", **kwargs)})
        else:
            delete_name = field.name + "-delete"
            template = self.data_template
            return Markup(
                template
                % {
                    "text": html_params(
                        type="text", value=field.data, readonly=True
                    ),
                    "file": html_params(type="file", **kwargs),
                    "marker": delete_name,
                    "image": field.data,
                }
            )


class FileUploadField(fields.StringField):
    """
    File upload field that handles file storage and validation.
    
    Attributes:
        allowed_extensions: List of allowed file extensions
        namegen: Function to generate uploaded file names
        permission: File permission mode
        base_path: Base path for file storage
    """
    
    widget = BS3FileUploadFieldWidget()

    def __init__(
        self,
        label=None,
        validators=None,
        allowed_extensions=None,
        namegen=None,
        permission=0o666,
        base_path=None,
        **kwargs
    ):
        """
        Initialize the file upload field.
        
        Args:
            label: Field label
            validators: List of field validators
            allowed_extensions: Allowed file extensions
            namegen: Function to generate file names
            permission: File permission mode
            base_path: Base storage path
            **kwargs: Additional field arguments
        """
        self.allowed_extensions = allowed_extensions or []
        self.namegen = namegen
        self.permission = permission
        self.base_path = base_path
        
        super(FileUploadField, self).__init__(label, validators, **kwargs)

    def pre_validate(self, form):
        """
        Validate the uploaded file before processing.
        
        Args:
            form: The form instance
            
        Raises:
            ValidationError: If file validation fails
        """
        if self.data:
            filename = self.data.filename
            if filename and self.allowed_extensions:
                if not any(filename.lower().endswith('.' + ext) 
                          for ext in self.allowed_extensions):
                    raise ValidationError(
                        gettext("Invalid file extension. Allowed: %s") % 
                        ', '.join(self.allowed_extensions)
                    )

    def process_formdata(self, valuelist):
        """
        Process form data for file uploads.
        
        Args:
            valuelist: List of form values
        """
        if valuelist:
            if valuelist[0] and isinstance(valuelist[0], FileStorage):
                self.data = valuelist[0]
            else:
                self.data = None


class ImageUploadField(FileUploadField):
    """
    Image upload field with image-specific validation and handling.
    
    Automatically restricts to common image file extensions.
    """
    
    widget = BS3ImageUploadFieldWidget()

    def __init__(
        self,
        label=None,
        validators=None,
        allowed_extensions=None,
        namegen=None,
        permission=0o666,
        base_path=None,
        **kwargs
    ):
        """
        Initialize the image upload field.
        
        Args:
            label: Field label
            validators: List of field validators
            allowed_extensions: Allowed image extensions (defaults to common image types)
            namegen: Function to generate file names
            permission: File permission mode
            base_path: Base storage path
            **kwargs: Additional field arguments
        """
        if allowed_extensions is None:
            allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
            
        super(ImageUploadField, self).__init__(
            label=label,
            validators=validators,
            allowed_extensions=allowed_extensions,
            namegen=namegen,
            permission=permission,
            base_path=base_path,
            **kwargs
        )