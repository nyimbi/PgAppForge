from pgappforge import BaseView, expose
from pgappforge.basemanager import BaseManager


class DummyView(BaseView):
    route_base = "/dummy"

    @expose("/method1/<string:param1>")
    def method1(self, param1):
        return param1


class DummyAddOnManager(BaseManager):
    def register_views(self):
        self.appbuilder.add_view_no_menu(DummyView)
