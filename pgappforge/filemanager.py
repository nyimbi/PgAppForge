import logging
import os
import os.path as op
import re
import uuid

from flask import current_app, has_app_context
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from wtforms import ValidationError

log = logging.getLogger(__name__)


def uuid_originalname(uuid_filename):
    """
    Extract the original filename from a UUID-prefixed filename.
    
    :param uuid_filename: Filename in format "UUID_sep_originalfilename"
    :return: Original filename part after the "_sep_" separator
    """
    return uuid_filename.split("_sep_")[1]

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None


class FileManager(object):
    """
    Comprehensive file management system for PgForge.
    
    Handles file uploads, storage, validation, and organization
    with support for various file types and custom naming schemes.
    """

    def __init__(
        self,
        base_path=None,
        relative_path="",
        namegen=None,
        allowed_extensions=None,
        permission=0o755,
        **kwargs
    ):
        """
        Initialize the file manager.
        
        :param base_path: Base directory for file storage
        :param relative_path: Relative path within base directory
        :param namegen: Function to generate file names
        :param allowed_extensions: List of allowed file extensions
        :param permission: File permission mode
            **kwargs: Additional configuration options
        """
        self.base_path = base_path or self._get_base_path()
        self.relative_path = relative_path
        self.namegen = namegen or self._uuid_namegen
        self.allowed_extensions = allowed_extensions or []
        self.permission = permission

    def _get_base_path(self):
        """
        Get the default base path for file storage.
        
        Returns:
            Default base path string
        """
        if has_app_context():
            return current_app.static_folder
        return os.getcwd()

    def _uuid_namegen(self, obj, file_data):
        """
        Generate a UUID-based filename.
        
        :param obj: Model object (unused)
        :param file_data: FileStorage object
        :return: UUID-based filename with original extension
        """
        _, ext = op.splitext(file_data.filename)
        return f"{uuid.uuid4().hex}{ext}"

    def get_path(self, filename=None):
        """
        Get the full path for a file.
        
        :param filename: Optional filename to append
        :return: Full file path
        """
        path = op.join(self.base_path, self.relative_path)
        if filename:
            path = op.join(path, filename)
        return path

    def is_file_allowed(self, filename):
        """
        Check if a file extension is allowed.
        
        :param filename: Filename to check
        :return: True if file is allowed, False otherwise
        """
        if not self.allowed_extensions:
            return True
        
        _, ext = op.splitext(filename.lower())
        return ext[1:] in self.allowed_extensions

    def save_file(self, file_data, obj=None):
        """
        Save an uploaded file to storage.
        
        :param file_data: FileStorage object
        :param obj: Associated model object
        :return: Saved filename
            
        Raises:
            ValidationError: If file validation fails
        """
        if not isinstance(file_data, FileStorage):
            raise ValidationError("Invalid file data")
        
        if not self.is_file_allowed(file_data.filename):
            raise ValidationError(
                f"File type not allowed. Allowed extensions: {self.allowed_extensions}"
            )
        
        filename = secure_filename(self.namegen(obj, file_data))
        path = self.get_path()
        
        # Ensure directory exists
        if not op.exists(path):
            os.makedirs(path, mode=self.permission)
        
        # Save file
        full_path = op.join(path, filename)
        file_data.save(full_path)
        
        # Set file permissions
        os.chmod(full_path, self.permission)
        
        return filename

    def delete_file(self, filename):
        """
        Delete a file from storage.
        
        :param filename: Name of file to delete
        :return: True if file was deleted, False if file didn't exist
        """
        path = self.get_path(filename)
        if op.exists(path):
            try:
                os.remove(path)
                return True
            except OSError as e:
                log.error(f"Error deleting file {path}: {e}")
                return False
        return False

    def get_url(self, filename):
        """
        Get the URL for accessing a file.
        
        :param filename: Name of the file
        :return: URL string for the file
        """
        return op.join("/", self.relative_path, filename).replace("\\", "/")


class ImageManager(FileManager):
    """
    Specialized file manager for image files.
    
    Extends FileManager with image-specific functionality like
    thumbnails, resizing, and image format validation.
    """

    def __init__(
        self,
        base_path=None,
        relative_path="images",
        namegen=None,
        allowed_extensions=None,
        permission=0o755,
        size=(150, 150, True),
        thumbnail_size=(64, 64, True),
        **kwargs
    ):
        """
        Initialize the image manager.
        
        :param base_path: Base directory for image storage
        :param relative_path: Relative path for images
        :param namegen: Function to generate image names
        :param allowed_extensions: Allowed image extensions
        :param permission: File permission mode
            size: Image resize dimensions (width, height, crop)
            thumbnail_size: Thumbnail dimensions (width, height, crop)
            **kwargs: Additional configuration options
        """
        if allowed_extensions is None:
            allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
            
        super(ImageManager, self).__init__(
            base_path=base_path,
            relative_path=relative_path,
            namegen=namegen,
            allowed_extensions=allowed_extensions,
            permission=permission,
            **kwargs
        )
        
        self.size = size
        self.thumbnail_size = thumbnail_size

    def save_file(self, file_data, obj=None):
        """
        Save an image file with optional resizing.
        
        :param file_data: FileStorage object with image data
        :param obj: Associated model object
        :return: Saved filename
            
        Raises:
            ValidationError: If image processing fails
        """
        filename = super(ImageManager, self).save_file(file_data, obj)
        
        if Image and self.size:
            self._resize_image(filename, self.size)
            
        if Image and self.thumbnail_size:
            self._create_thumbnail(filename, self.thumbnail_size)
            
        return filename

    def _resize_image(self, filename, size):
        """
        Resize an image to specified dimensions.
        
        :param filename: Name of image file
        :param size: Tuple of (width, height, crop_to_fit)
        """
        try:
            path = self.get_path(filename)
            img = Image.open(path)
            
            width, height, crop = size
            if crop:
                img = ImageOps.fit(img, (width, height), Image.LANCZOS)
            else:
                img.thumbnail((width, height), Image.LANCZOS)
            
            img.save(path)
        except Exception as e:
            log.error(f"Error resizing image {filename}: {e}")

    def _create_thumbnail(self, filename, size):
        """
        Create a thumbnail for an image.
        
        :param filename: Name of image file
        :param size: Tuple of (width, height, crop_to_fit)
        """
        try:
            path = self.get_path(filename)
            img = Image.open(path)
            
            width, height, crop = size
            if crop:
                thumb = ImageOps.fit(img, (width, height), Image.LANCZOS)
            else:
                thumb = img.copy()
                thumb.thumbnail((width, height), Image.LANCZOS)
            
            # Save thumbnail with _thumb suffix
            name, ext = op.splitext(filename)
            thumb_name = f"{name}_thumb{ext}"
            thumb_path = self.get_path(thumb_name)
            thumb.save(thumb_path)
            
        except Exception as e:
            log.error(f"Error creating thumbnail for {filename}: {e}")

    def get_thumbnail_url(self, filename):
        """
        Get URL for an image thumbnail.
        
        :param filename: Original image filename
        :return: URL string for the thumbnail
        """
        name, ext = op.splitext(filename)
        thumb_name = f"{name}_thumb{ext}"
        return self.get_url(thumb_name)