from flask import abort, redirect, session
from flask_babel import refresh

from ..baseviews import BaseView, expose


class LocaleView(BaseView):
    """
    PgForge view for locale interface operations.

    The LocaleView class provides comprehensive functionality for
    locale view operations.
    """
    
    route_base = "/lang"

    default_view = "index"

    @expose("/<string:locale>")
    def index(self, locale):
        """
        Perform index operation.

        This method provides functionality for index.

        Args:
            locale: The locale parameter

        Returns:
            The result of the operation
        """
        if locale not in self.appbuilder.bm.languages:
            abort(404, description="Locale not supported.")
        session["locale"] = locale
        refresh()
        self.update_redirect()
        return redirect(self.get_redirect())
