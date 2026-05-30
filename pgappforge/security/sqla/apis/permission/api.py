from pgappforge import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.sqla.models import Permission


class PermissionApi(ModelRestApi):
    resource_name = "security/permissions"
    openapi_spec_tag = "Security Permissions"

    class_permission_name = "Permission"
    datamodel = SQLAInterface(Permission)
    allow_browser_login = True
    include_route_methods = {"info", "get", "get_list"}

    list_columns = ["id", "name"]
    show_columns = list_columns
    add_columns = ["name"]
    edit_columns = add_columns
    search_columns = list_columns
