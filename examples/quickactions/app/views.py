from flask import redirect
from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.actions import action

from app import appbuilder
from .models import ContactGroup


class GroupModelView(ModelView):
    datamodel = SQLAInterface(ContactGroup)
    list_columns = ["name"]

    @action(
        "myaction", "Do something on this record", "Do you really want to?", "fa-rocket"
    )
    def myaction(self, item):
        """
            do something with the item record
        """
        return redirect(self.get_redirect())

    @action("muldelete", "Delete", "Delete all Really?", "fa-rocket")
    def muldelete(self, items):
        if isinstance(items, list):
            self.datamodel.delete_all(items)
            self.update_redirect()
        else:
            self.datamodel.delete(items)
        return redirect(self.get_redirect())


appbuilder.add_view(
    GroupModelView,
    "List Groups",
    icon="fa-folder-open-o",
    category="Contacts",
    category_icon="fa-envelope",
)
