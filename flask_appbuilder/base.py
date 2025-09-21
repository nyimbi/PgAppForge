from functools import reduce
import logging
from typing import Any, Callable, cast, Dict, List, Optional, Type, TYPE_CHECKING, Union

from flask import Blueprint, current_app, Flask, url_for
from sqlalchemy.orm.session import Session as SessionBase

from . import __version__
from .api.manager import OpenApiManager
from .babel.manager import BabelManager
from .const import (
    LOGMSG_ERR_FAB_ADD_PERMISSION_MENU,
    LOGMSG_ERR_FAB_ADD_PERMISSION_VIEW,
    LOGMSG_ERR_FAB_ADDON_IMPORT,
    LOGMSG_ERR_FAB_ADDON_PROCESS,
    LOGMSG_INF_FAB_ADD_VIEW,
    LOGMSG_INF_FAB_ADDON_ADDED,
    LOGMSG_WAR_FAB_VIEW_EXISTS,
)
# from .filters import TemplateFilters  # Class doesn't exist
from .menu import Menu, MenuApi
from .views import IndexView, UtilView
# Enhanced plugin system imports
from .plugins import PluginManager, PluginLoader, SecurePluginLoader, BasePlugin

if TYPE_CHECKING:
    from flask_appbuilder.basemanager import BaseManager
    from flask_appbuilder.baseviews import BaseView, AbstractViewApi
    from flask_appbuilder.security.manager import BaseSecurityManager

log = logging.getLogger(__name__)


DynamicImportType = Union[
    Type["BaseManager"],
    Type["BaseView"],
    Type["BaseSecurityManager"],
    Type[Menu],
    Type["AbstractViewApi"],
]


def dynamic_class_import(class_path: str) -> Optional[DynamicImportType]:
    """
    Will dynamically import a class from a string path
    :param class_path: string with class path
    :return: class
    """
    # Split first occurrence of path
    try:
        tmp = class_path.split(".")
        module_path = ".".join(tmp[0:-1])
        package = __import__(module_path)
        return reduce(getattr, tmp[1:], package)
    except Exception as e:
        log.exception(e)
        log.error(LOGMSG_ERR_FAB_ADDON_IMPORT, class_path, e)
        return None


class AppBuilder:
    """
    This is the base class for all the framework.
    This is where you will register all your views and create the menu structure.
    Will hold your flask app object, all your views, and security classes.

    initialize your application like this for SQLAlchemy::

        from flask import Flask
        from flask_appbuilder import SQLA, AppBuilder

        app = Flask(__name__)
        app.config.from_object('config')
        db = SQLA(app)
        appbuilder = AppBuilder(app, db.session)

    When using MongoEngine::

        from flask import Flask
        from flask_appbuilder import AppBuilder
        from flask_appbuilder.security.mongoengine.manager import SecurityManager
        from flask_mongoengine import MongoEngine

        app = Flask(__name__)
        app.config.from_object('config')
        dbmongo = MongoEngine(app)
        appbuilder = AppBuilder(app, security_manager_class=SecurityManager)

    You can also create everything as an application factory.
    """

    security_manager_class = None

    template_filters = None

    def __init__(
        self,
        app: Optional[Flask] = None,
        session: Optional[SessionBase] = None,
        menu: Optional[Menu] = None,
        indexview: Optional[Type["AbstractViewApi"]] = None,
        base_template: str = "appbuilder/baselayout.html",
        static_folder: str = "static/appbuilder",
        static_url_path: str = "/appbuilder",
        security_manager_class: Optional[Type["BaseSecurityManager"]] = None,
        update_perms: bool = True,
    ) -> None:
        """
        AppBuilder init

        :param app:
            The flask app object
        :param session:
            The SQLAlchemy session object
        :param menu:
            optional, a previous contructed menu
        :param indexview:
            optional, your customized indexview
        :param static_folder:
            optional, your override for the global static folder
        :param static_url_path:
            optional, your override for the global static url path
        :param security_manager_class:
            optional, pass your own security manager class
        :param update_perms:
            optional, update permissions flag (Boolean) you can use
            FAB_UPDATE_PERMS config key also
        """
        self.baseviews: List[Union[Type["AbstractViewApi"], "AbstractViewApi"]] = []

        # temporary list that hold addon_managers config key
        self._addon_managers: List[str] = []
        # dict with addon name has key and instantiated class has value
        self.addon_managers: Dict[str, Any] = {}

        # Enhanced plugin system
        self.plugin_manager: PluginManager = None  # type: ignore
        self.plugin_loader: PluginLoader = None  # type: ignore
        self.menu = menu
        self.base_template = base_template
        self.security_manager_class = security_manager_class
        self.indexview = indexview
        self.static_folder = static_folder
        self.static_url_path = static_url_path
        self.app = app
        self.update_perms = update_perms

        # Security Manager Class
        self.sm: BaseSecurityManager = None  # type: ignore
        # Babel Manager Class
        self.bm: BabelManager = None  # type: ignore
        self.openapi_manager: OpenApiManager = None  # type: ignore
        self.menuapi_manager: MenuApi = None  # type: ignore

        if app is not None:
            self.init_app(app, session)

    def init_app(self, app: Flask, session: SessionBase) -> None:
        """
        Will initialize the Flask app, supporting the app factory pattern.

        :param app:
        :param session: The SQLAlchemy session

        """
        app.config.setdefault("APP_NAME", "F.A.B.")
        app.config.setdefault("APP_THEME", "")
        app.config.setdefault("APP_ICON", "")
        app.config.setdefault("LANGUAGES", {"en": {"flag": "gb", "name": "English"}})
        app.config.setdefault("ADDON_MANAGERS", [])
        app.config.setdefault("RATELIMIT_ENABLED", False)
        app.config.setdefault("FAB_API_MAX_PAGE_SIZE", 100)
        app.config.setdefault("FAB_BASE_TEMPLATE", self.base_template)
        app.config.setdefault("FAB_STATIC_FOLDER", self.static_folder)
        app.config.setdefault("FAB_STATIC_URL_PATH", self.static_url_path)

        self.app = app

        self.base_template = app.config.get("FAB_BASE_TEMPLATE", self.base_template)
        self.static_folder = app.config.get("FAB_STATIC_FOLDER", self.static_folder)
        self.static_url_path = app.config.get(
            "FAB_STATIC_URL_PATH", self.static_url_path
        )
        _index_view = app.config.get("FAB_INDEX_VIEW", None)
        if _index_view:
            self.indexview = dynamic_class_import(_index_view)  # type: ignore
        else:
            self.indexview = self.indexview or IndexView

        _menu = app.config.get("FAB_MENU", None)

        # Setup Menu
        if _menu is not None:
            menu = dynamic_class_import(_menu)
            if menu is not None and issubclass(menu, Menu):
                self.menu = menu()
        else:
            self.menu = self.menu or Menu()

        if self.update_perms:  # default is True, if False takes precedence from config
            self.update_perms = app.config.get("FAB_UPDATE_PERMS", True)
        _security_manager_class_name = app.config.get(
            "FAB_SECURITY_MANAGER_CLASS", None
        )
        if _security_manager_class_name is not None:
            security_manager_class = dynamic_class_import(_security_manager_class_name)
            self.security_manager_class = cast(
                Type["BaseSecurityManager"], security_manager_class
            )
        if self.security_manager_class is None:
            from flask_appbuilder.security.sqla.manager import SecurityManager

            self.security_manager_class = SecurityManager

        self._addon_managers = app.config["ADDON_MANAGERS"]
        self.session = session
        self.sm = self.security_manager_class(self)
        self.bm = BabelManager(self)
        self.openapi_manager = OpenApiManager(self)
        self.menuapi_manager = MenuApi()

        # Initialize enhanced plugin system
        self._init_plugin_system(app)

        # Initialize enhanced security modules
        self._init_enhanced_security(app)
        
        self._add_global_static()
        self._add_global_filters()
        app.before_request(self.sm.before_request)
        self._add_admin_views()
        self._add_addon_views()
        if self.app:
            self._add_menu_permissions()
        else:
            self.post_init()
        self._init_extension(app)

    def _init_extension(self, app: Flask) -> None:
        app.appbuilder = self
        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["appbuilder"] = self

    def post_init(self) -> None:
        """
        Perform post-initialization tasks for the AppBuilder instance.
        
        This method is called after the AppBuilder instance is initialized
        to set up views and configure the application.
        """
        for baseview in self.baseviews:
            # instantiate the views and add session
            baseview = self._check_and_init(baseview)
            # Register the views has blueprints
            if baseview.__class__.__name__ not in self.get_app.blueprints.keys():
                self.register_blueprint(baseview)
            # Add missing permissions where needed
        self.add_permissions()

    @property
    def get_app(self) -> Flask:
        """
        Get current or configured flask app

        :return: Flask App
        """
        if self.app:
            return self.app
        else:
            return current_app

    @property
    def get_session(self) -> SessionBase:
        """
        Get the current sqlalchemy session.

        :return: SQLAlchemy Session
        """
        return self.session

    @property
    def app_name(self) -> str:
        """
        Get the App name

        :return: String with app name
        """
        return self.get_app.config["APP_NAME"]

    @property
    def app_theme(self) -> str:
        """
        Get the App theme name

        :return: String app theme name
        """
        return self.get_app.config["APP_THEME"]

    @property
    def app_icon(self) -> str:
        """
        Get the App icon location

        :return: String with relative app icon location
        """
        return self.get_app.config["APP_ICON"]

    @property
    def languages(self) -> Dict[str, Any]:
        """
        Get configured languages for the application.

        :return: Dict with language configuration
        """
        return self.get_app.config["LANGUAGES"]

    @property
    def version(self) -> str:
        """
        Get the current F.A.B. version

        :return: String with the current F.A.B. version
        """
        return __version__

    def _add_global_filters(self) -> None:
        # self.template_filters = TemplateFilters(self.get_app, self.sm)  # Class doesn't exist
        self.template_filters = None

    def _add_global_static(self) -> None:
        bp = Blueprint(
            "appbuilder",
            __name__,
            url_prefix="/static",
            template_folder="templates",
            static_folder=self.static_folder,
            static_url_path=self.static_url_path,
        )
        self.get_app.register_blueprint(bp)

    def _add_admin_views(self) -> None:
        """
        Registers indexview, utilview (back function), babel views and Security views.
        """
        if self.indexview:
            self._indexview = self.add_view_no_menu(self.indexview)
        self.add_view_no_menu(UtilView)
        self.bm.register_views()
        self.sm.register_views()
        self.openapi_manager.register_views()
        self.menuapi_manager.register_views()

    def _init_plugin_system(self, app: Flask) -> None:
        """
        Initialize the enhanced plugin system.

        Args:
            app: Flask application instance
        """
        # Set up plugin configuration
        app.config.setdefault("FAB_PLUGINS", [])
        app.config.setdefault("FAB_PLUGIN_SECURITY_STRICT", False)
        app.config.setdefault("FAB_PLUGIN_PATHS", [])

        # Initialize plugin loader based on security settings
        strict_security = app.config.get("FAB_PLUGIN_SECURITY_STRICT", False)
        plugin_paths = app.config.get("FAB_PLUGIN_PATHS", [])

        if strict_security:
            from pathlib import Path
            allowed_paths = [Path(p) for p in plugin_paths] if plugin_paths else []
            self.plugin_loader = SecurePluginLoader(
                strict_security=True,
                allowed_paths=allowed_paths
            )
        else:
            self.plugin_loader = PluginLoader()

        # Add configured plugin paths
        for path_str in plugin_paths:
            from pathlib import Path
            path = Path(path_str)
            if path.exists():
                self.plugin_loader.add_plugin_path(path)

        # Initialize plugin manager
        self.plugin_manager = PluginManager(self)

        log.info("Enhanced plugin system initialized with %s security mode",
                "strict" if strict_security else "standard")

    def _add_addon_views(self) -> None:
        """
        Registers declared addon's and plugins with enhanced plugin system support.

        Supports both legacy ADDON_MANAGERS and new plugin architecture for
        backward compatibility and gradual migration.
        """
        # Process legacy ADDON_MANAGERS
        self._process_legacy_addons()

        # Process new plugin system
        self._process_plugins()

    def _process_legacy_addons(self) -> None:
        """Process legacy ADDON_MANAGERS for backward compatibility."""
        for addon in self._addon_managers:
            addon_class_ = dynamic_class_import(addon)
            addon_class = cast(Type["BaseManager"], addon_class_)
            if addon_class:
                try:
                    # Check if this is a modern plugin
                    if issubclass(addon_class, BasePlugin):
                        # Handle as new plugin
                        plugin_instance = addon_class(self)
                        if self.plugin_manager.load_plugin(plugin_instance.metadata.name):
                            log.info(f"Loaded modern plugin via legacy config: {addon}")
                        continue

                    # Handle as legacy manager
                    inst_addon_class: "BaseManager" = addon_class(self)
                    inst_addon_class.pre_process()
                    inst_addon_class.register_views()
                    inst_addon_class.post_process()
                    self.addon_managers[addon] = inst_addon_class
                    log.info(LOGMSG_INF_FAB_ADDON_ADDED, addon)

                    # Optionally wrap legacy manager in plugin adapter
                    if hasattr(self.get_app.config, 'FAB_AUTO_WRAP_LEGACY') and self.get_app.config['FAB_AUTO_WRAP_LEGACY']:
                        try:
                            adapter_class = self.plugin_loader.load_legacy_manager(addon_class)
                            self.plugin_manager.register_plugin_class(adapter_class)
                            log.info(f"Auto-wrapped legacy manager as plugin: {addon}")
                        except Exception as wrap_error:
                            log.warning(f"Failed to auto-wrap legacy manager {addon}: {wrap_error}")

                except Exception as e:
                    log.exception(e)
                    log.error(LOGMSG_ERR_FAB_ADDON_PROCESS, addon, e)

    def _process_plugins(self) -> None:
        """Process new plugin system configurations."""
        if not self.plugin_manager:
            return

        # Get plugin configurations from Flask config
        plugin_configs = self.get_app.config.get("FAB_PLUGINS", [])

        for plugin_config in plugin_configs:
            try:
                if isinstance(plugin_config, str):
                    # Simple plugin name/module string
                    plugin_class = self.plugin_loader.load_plugin_from_module(plugin_config)
                    self.plugin_manager.register_plugin_class(plugin_class)
                    self.plugin_manager.load_plugin(plugin_class(self).metadata.name)

                elif isinstance(plugin_config, dict):
                    # Plugin configuration dictionary
                    plugin_name = plugin_config.get('name')
                    plugin_module = plugin_config.get('module')
                    plugin_file = plugin_config.get('file')
                    plugin_config_data = plugin_config.get('config', {})

                    if plugin_module:
                        plugin_class = self.plugin_loader.load_plugin_from_module(plugin_module)
                    elif plugin_file:
                        from pathlib import Path
                        plugin_class = self.plugin_loader.load_plugin_from_file(Path(plugin_file))
                    else:
                        log.error(f"Invalid plugin configuration, missing module or file: {plugin_config}")
                        continue

                    self.plugin_manager.register_plugin_class(plugin_class)
                    metadata = plugin_class(self).metadata
                    plugin_name = plugin_name or metadata.name

                    if self.plugin_manager.load_plugin(plugin_name, plugin_config_data):
                        log.info(f"Successfully loaded plugin: {plugin_name}")
                    else:
                        log.error(f"Failed to load plugin: {plugin_name}")

                else:
                    log.warning(f"Invalid plugin configuration format: {plugin_config}")

            except Exception as e:
                log.exception(e)
                log.error(f"Error processing plugin configuration {plugin_config}: {e}")

    def _check_and_init(
        self, baseview: Union[Type["AbstractViewApi"], "AbstractViewApi"]
    ) -> "AbstractViewApi":
        # If class if not instantiated, instantiate it
        # and add db session from security models.
        if hasattr(baseview, "datamodel"):
            if getattr(baseview, "datamodel").session is None:
                getattr(baseview, "datamodel").session = self.session
        if isinstance(baseview, type):
            baseview = baseview()
        return baseview

    def add_view(
        self,
        baseview: Union[Type["AbstractViewApi"], "AbstractViewApi"],
        name: str,
        href: str = "",
        icon: str = "",
        label: str = "",
        category: str = "",
        category_icon: str = "",
        category_label: str = "",
        menu_cond: Optional[Callable[..., bool]] = None,
    ) -> "AbstractViewApi":
        """
        Add your views associated with menus using this method.

        :param baseview:
            A BaseView type class instantiated or not.
            This method will instantiate the class for you if needed.
        :param name:
            The string name that identifies the menu.
        :param href:
            Override the generated href for the menu.
            You can use an url string or an endpoint name
            if non provided default_view from view will be set as href.
        :param icon:
            Font-Awesome icon name, optional.
        :param label:
            The label that will be displayed on the menu,
            if absent param name will be used
        :param category:
            The menu category where the menu will be included,
            if non provided the view will be acessible as a top menu.
        :param category_icon:
            Font-Awesome icon name for the category, optional.
        :param category_label:
            The label that will be displayed on the menu,
            if absent param name will be used
        :param menu_cond:
            If a callable, :code:`menu_cond` will be invoked when
            constructing the menu items. If it returns :code:`True`,
            then this link will be a part of the menu. Otherwise, it
            will not be included in the menu items. Defaults to
            :code:`None`, meaning the item will always be present.

        Examples::

            appbuilder = AppBuilder(app, db)
            # Register a view, rendering a top menu without icon.
            appbuilder.add_view(MyModelView(), "My View")
            # or not instantiated
            appbuilder.add_view(MyModelView, "My View")
            # Register a view, a submenu "Other View" from "Other" with a phone icon.
            appbuilder.add_view(
                MyOtherModelView,
                "Other View",
                icon='fa-phone',
                category="Others"
            )
            # Register a view, with category icon and translation.
            appbuilder.add_view(
                YetOtherModelView,
                "Other View",
                icon='fa-phone',
                label=_('Other View'),
                category="Others",
                category_icon='fa-envelop',
                category_label=_('Other View')
            )
            # Register a view whose menu item will be conditionally displayed
            appbuilder.add_view(
                YourFeatureView,
                "Your Feature",
                icon='fa-feature',
                label=_('Your Feature'),
                menu_cond=lambda: is_feature_enabled("your-feature"),
            )
            # Add a link
            appbuilder.add_link("google", href="www.google.com", icon = "fa-google-plus")
        """
        baseview = self._check_and_init(baseview)
        log.info(LOGMSG_INF_FAB_ADD_VIEW, baseview.__class__.__name__, name)

        if not self._view_exists(baseview):
            baseview.appbuilder = self
            self.baseviews.append(baseview)
            self._process_inner_views()
            if self.app:
                self.register_blueprint(baseview)
                self._add_permission(baseview)
                self.add_limits(baseview)
        self.add_link(
            name=name,
            href=href,
            icon=icon,
            label=label,
            category=category,
            category_icon=category_icon,
            category_label=category_label,
            baseview=baseview,
            cond=menu_cond,
        )
        return baseview

    def add_link(
        self,
        name: str,
        href: str,
        icon: str = "",
        label: str = "",
        category: str = "",
        category_icon: str = "",
        category_label: str = "",
        baseview: Optional["AbstractViewApi"] = None,
        cond: Optional[Callable[..., bool]] = None,
    ) -> None:
        """
        Add your own links to menu using this method

        :param baseview:
        :param name:
            The string name that identifies the menu.
        :param href:
            Override the generated href for the menu.
            You can use an url string or an endpoint name
        :param icon:
            Font-Awesome icon name, optional.
        :param label:
            The label that will be displayed on the menu,
            if absent param name will be used
        :param category:
            The menu category where the menu will be included,
            if non provided the view will be accessible as a top menu.
        :param category_icon:
            Font-Awesome icon name for the category, optional.
        :param category_label:
            The label that will be displayed on the menu,
            if absent param name will be used
        :param cond:
            If a callable, :code:`cond` will be invoked when
            constructing the menu items. If it returns :code:`True`,
            then this link will be a part of the menu. Otherwise, it
            will not be included in the menu items. Defaults to
            :code:`None`, meaning the item will always be present.
        """
        if self.menu is None:
            return
        self.menu.add_link(
            name=name,
            href=href,
            icon=icon,
            label=label,
            category=category,
            category_icon=category_icon,
            category_label=category_label,
            baseview=baseview,
            cond=cond,
        )
        if self.app:
            self._add_permissions_menu(name)
            if category:
                self._add_permissions_menu(category)

    def add_separator(
        self, category: str, cond: Optional[Callable[..., bool]] = None
    ) -> None:
        """
        Add a separator to the menu, you will sequentially create the menu

        :param category:
            The menu category where the separator will be included.
        :param cond:
            If a callable, :code:`cond` will be invoked when
            constructing the menu items. If it returns :code:`True`,
            then this separator will be a part of the menu. Otherwise,
            it will not be included in the menu items. Defaults to
            :code:`None`, meaning the separator will always be present.
        """
        if self.menu is None:
            return
        self.menu.add_separator(category, cond=cond)

    def add_view_no_menu(
        self,
        baseview: Union[Type["AbstractViewApi"], "AbstractViewApi"],
        endpoint: Optional[str] = None,
        static_folder: Optional[str] = None,
    ) -> "AbstractViewApi":
        """
        Add your views without creating a menu.

        :param baseview:
            A BaseView type class instantiated.
        :param endpoint: The endpoint path for the Flask blueprint
        :param static_folder: The static folder for the Flask blueprint

        """
        baseview = self._check_and_init(baseview)
        log.info(LOGMSG_INF_FAB_ADD_VIEW, baseview.__class__.__name__, "")

        if not self._view_exists(baseview):
            baseview.appbuilder = self
            self.baseviews.append(baseview)
            self._process_inner_views()
            if self.app:
                self.register_blueprint(
                    baseview, endpoint=endpoint, static_folder=static_folder
                )
                self._add_permission(baseview)
                self.add_limits(baseview)
        else:
            log.warning(LOGMSG_WAR_FAB_VIEW_EXISTS, baseview.__class__.__name__)
        return baseview

    def add_api(self, baseview: Type["AbstractViewApi"]) -> "AbstractViewApi":
        """
        Add a BaseApi class or child to AppBuilder

        :param baseview: A BaseApi type class
        :return: The instantiated base view
        """
        return self.add_view_no_menu(baseview)

    def security_cleanup(self) -> None:
        """
        This method is useful if you have changed
        the name of your menus or classes,
        changing them will leave behind permissions
        that are not associated with anything.

        You can use it always or just sometimes to
        perform a security cleanup. Warning this will delete any permission
        that is no longer part of any registered view or menu.

        Remember invoke ONLY AFTER YOU HAVE REGISTERED ALL VIEWS
        """
        self.sm.security_cleanup(self.baseviews, self.menu)

    def security_converge(self, dry: bool = False) -> Dict[str, Any]:
        """
        Converge security permissions across the application.
        
        This method is useful when you use:

        - `class_permission_name`
        - `previous_class_permission_name`
        - `method_permission_name`
        - `previous_method_permission_name`

        migrates all permissions to the new names on all the Roles

        :param dry: If True will not change DB
        :return: Dict with all computed necessary operations
        """
        if self.menu is None:
            return {}
        return self.sm.security_converge(self.baseviews, self.menu.menu, dry)

    def get_url_for_login_with(self, next_url: str = None) -> str:
        """
        Get URL for login with next_url parameter.

        :param next_url: The URL to redirect to after login
        :return: The login URL with next parameter
        """
        if self.sm.auth_view is None:
            return ""
        return url_for("%s.%s" % (self.sm.auth_view.endpoint, "login"), next=next_url)

    @property
    def get_url_for_login(self) -> str:
        """
        Get the URL for login page.

        :return: The login URL
        """
        if self.sm.auth_view is None:
            return ""
        return url_for("%s.%s" % (self.sm.auth_view.endpoint, "login"))

    @property
    def get_url_for_logout(self) -> str:
        """
        Get the URL for logout action.

        :return: The logout URL
        """
        if self.sm.auth_view is None:
            return ""
        return url_for("%s.%s" % (self.sm.auth_view.endpoint, "logout"))

    @property
    def get_url_for_index(self) -> str:
        """
        Get the URL for the index/home page.

        :return: The index URL
        """
        if self._indexview is None:
            return ""
        return url_for(
            "%s.%s" % (self._indexview.endpoint, self._indexview.default_view)
        )

    @property
    def get_url_for_userinfo(self) -> str:
        """
        Get the URL for user information page.

        :return: The user info URL
        """
        if self.sm.user_view is None:
            return ""
        return url_for("%s.%s" % (self.sm.user_view.endpoint, "userinfo"))

    def get_url_for_locale(self, lang: str) -> str:
        """
        Get the URL for locale switching.

        :param lang: The language code to switch to
        :return: The locale URL
        """
        if self.bm.locale_view is None:
            return ""
        return url_for(
            "%s.%s" % (self.bm.locale_view.endpoint, self.bm.locale_view.default_view),
            locale=lang,
        )

    def add_limits(self, baseview: "AbstractViewApi") -> None:
        """
        Add rate limits for a view if it has limits defined.

        :param baseview: The view to add limits for
        """
        if hasattr(baseview, "limits"):
            self.sm.add_limit_view(baseview)

    def add_permissions(self, update_perms: bool = False) -> None:
        """
        Add permissions for all registered views and menu items.

        :param update_perms: Whether to force update permissions
        """
        from flask_appbuilder.baseviews import AbstractViewApi

        if self.update_perms or update_perms:
            for baseview in self.baseviews:
                baseview = cast(AbstractViewApi, baseview)
                self._add_permission(baseview, update_perms=update_perms)
            self._add_menu_permissions(update_perms=update_perms)

    def _add_permission(
        self, baseview: "AbstractViewApi", update_perms: bool = False
    ) -> None:
        if self.update_perms or update_perms:
            try:
                self.sm.add_permissions_view(
                    baseview.base_permissions, baseview.class_permission_name
                )
            except Exception as e:
                log.exception(e)
                log.error(LOGMSG_ERR_FAB_ADD_PERMISSION_VIEW, e)

    def _add_permissions_menu(self, name: str, update_perms: bool = False) -> None:
        if self.update_perms or update_perms:
            try:
                self.sm.add_permissions_menu(name)
            except Exception as e:
                log.exception(e)
                log.error(LOGMSG_ERR_FAB_ADD_PERMISSION_MENU, e)

    def _add_menu_permissions(self, update_perms: bool = False) -> None:
        if self.menu is None:
            return
        if self.update_perms or update_perms:
            for category in self.menu.get_list():
                self._add_permissions_menu(category.name, update_perms=update_perms)
                for item in category.childs:
                    # don't add permission for menu separator
                    if item.name != "-":
                        self._add_permissions_menu(item.name, update_perms=update_perms)

    def register_blueprint(
        self,
        baseview: "AbstractViewApi",
        endpoint: Optional[str] = None,
        static_folder: Optional[str] = None,
    ) -> None:
        """
        Register a view's blueprint with the Flask application.

        :param baseview: The view to register
        :param endpoint: Optional custom endpoint for the blueprint
        :param static_folder: Optional custom static folder for the blueprint
        """
        self.get_app.register_blueprint(
            baseview.create_blueprint(
                self, endpoint=endpoint, static_folder=static_folder
            )
        )

    def _view_exists(self, view: "AbstractViewApi") -> bool:
        for baseview in self.baseviews:
            if baseview.__class__ == view.__class__:
                return True
        return False

    def _process_inner_views(self) -> None:
        from flask_appbuilder.baseviews import AbstractViewApi

        for view in self.baseviews:
            view = cast(AbstractViewApi, view)
            for inner_class in view.get_uninit_inner_views():
                for v in self.baseviews:
                    if (
                        isinstance(v, inner_class)
                        and v not in view.get_init_inner_views()
                    ):
                        view.get_init_inner_views().append(v)

    def _init_enhanced_security(self, app: Flask) -> None:
        """
        Initialize enhanced security features if enabled.
        
        This method initializes security modules including:
        - Security headers middleware
        - Rate limiting system
        - Input validation framework
        """
        import logging
        log = logging.getLogger(__name__)
        
        # Initialize security headers
        if app.config.get('SECURITY_HEADERS_ENABLED', True):
            try:
                from .security.security_headers import init_security_headers
                init_security_headers(app)
                log.info("Security headers middleware initialized")
            except ImportError:
                log.warning("Security headers module not available")
        
        # Initialize rate limiting
        if app.config.get('RATE_LIMITING_ENABLED', True):
            try:
                from .security.rate_limiting import init_rate_limiting
                self._rate_limiter = init_rate_limiting(app)
                log.info("Rate limiting system initialized")
            except ImportError:
                log.warning("Rate limiting module not available")
        
        # Store references for use by views
        if hasattr(self, '_rate_limiter'):
            self.rate_limiter = self._rate_limiter

    # ========================================================================
    # Enhanced Plugin System API
    # ========================================================================

    def register_plugin(self, plugin_class: Type[BasePlugin]) -> bool:
        """
        Register a plugin class with the plugin system.

        Args:
            plugin_class: Plugin class to register

        Returns:
            True if registration successful, False otherwise

        Example:
            appbuilder.register_plugin(MyCustomPlugin)
        """
        try:
            self.plugin_manager.register_plugin_class(plugin_class)
            return True
        except Exception as e:
            log.error(f"Failed to register plugin {plugin_class.__name__}: {e}")
            return False

    def load_plugin(self, name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Load and activate a registered plugin.

        Args:
            name: Plugin name to load
            config: Optional plugin configuration

        Returns:
            True if load successful, False otherwise

        Example:
            appbuilder.load_plugin("my_plugin", {"feature_x": True})
        """
        if not self.plugin_manager:
            log.error("Plugin system not initialized")
            return False

        try:
            return self.plugin_manager.load_plugin(name, config)
        except Exception as e:
            log.error(f"Failed to load plugin {name}: {e}")
            return False

    def unload_plugin(self, name: str) -> bool:
        """
        Unload and deactivate a plugin.

        Args:
            name: Plugin name to unload

        Returns:
            True if unload successful, False otherwise

        Example:
            appbuilder.unload_plugin("my_plugin")
        """
        if not self.plugin_manager:
            log.error("Plugin system not initialized")
            return False

        try:
            return self.plugin_manager.unload_plugin(name)
        except Exception as e:
            log.error(f"Failed to unload plugin {name}: {e}")
            return False

    def get_plugin_status(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get status information for a plugin.

        Args:
            name: Plugin name

        Returns:
            Plugin status dictionary or None if not found

        Example:
            status = appbuilder.get_plugin_status("my_plugin")
            print(f"Status: {status['status']}")
        """
        if not self.plugin_manager:
            return None

        return self.plugin_manager.get_plugin_status(name)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """
        List all registered plugins with their status.

        Returns:
            List of plugin status dictionaries

        Example:
            plugins = appbuilder.list_plugins()
            for plugin in plugins:
                print(f"{plugin['name']}: {plugin['status']}")
        """
        if not self.plugin_manager:
            return []

        return self.plugin_manager.list_plugins()

    def get_plugin_dependency_info(self, name: str) -> Dict[str, Any]:
        """
        Get dependency information for a plugin.

        Args:
            name: Plugin name

        Returns:
            Dependency information dictionary

        Example:
            deps = appbuilder.get_plugin_dependency_info("my_plugin")
            print(f"Dependencies: {deps['dependencies']}")
        """
        if not self.plugin_manager:
            return {}

        return self.plugin_manager.get_dependency_info(name)

    def reload_plugin(self, name: str, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Reload a plugin (unload then load).

        Args:
            name: Plugin name to reload
            config: Optional new configuration

        Returns:
            True if reload successful, False otherwise

        Example:
            appbuilder.reload_plugin("my_plugin", {"debug": True})
        """
        if not self.plugin_manager:
            log.error("Plugin system not initialized")
            return False

        try:
            return self.plugin_manager.reload_plugin(name, config)
        except Exception as e:
            log.error(f"Failed to reload plugin {name}: {e}")
            return False