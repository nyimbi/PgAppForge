from pgappforge import ModelRestApi
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.sqla.models import ViewMenu


class ViewMenuApi(ModelRestApi):
    resource_name = "security/resources"
    openapi_spec_tag = "Security Resources (View Menus)"

    class_permission_name = "ViewMenu"
    datamodel = SQLAInterface(ViewMenu)
    allow_browser_login = True

    list_columns = ["id", "name"]
    show_columns = list_columns
    add_columns = ["name"]
    edit_columns = add_columns
    search_columns = list_columns
