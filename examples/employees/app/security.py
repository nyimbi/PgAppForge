__author__ = "dpgaspar"

from flask import redirect
from pgappforge.actions import action
from pgappforge.security.sqla.manager import SecurityManager
from pgappforge.security.views import UserDBModelView


class MyUserDBView(UserDBModelView):
    @action("muldelete", "Delete", "Delete all Really?", "fa-rocket", single=False)
    def muldelete(self, items):
        self.datamodel.delete_all(items)
        self.update_redirect()
        return redirect(self.get_redirect())


class MySecurityManager(SecurityManager):
    userdbmodelview = MyUserDBView
