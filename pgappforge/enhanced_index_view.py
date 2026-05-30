"""
Enhanced Beautiful Index View

This module provides a drop-in replacement for PgForge's default 
bland index view with a comprehensive, visually stunning dashboard.
"""

from .views.dashboard import DashboardIndexView
from .baseviews import expose

class IndexView(DashboardIndexView):
	"""Beautiful modern index view that replaces the default welcome page"""
	
	route_base = ""
	
	@expose("/")
	def index(self):
		"""Render the beautiful dashboard index page"""
		return self.get()

# Make this the default index view
DefaultIndexView = IndexView