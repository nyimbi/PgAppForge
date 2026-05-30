import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath('..'))
try:
    import pgappforge
    from pgappforge import __version__
except ImportError:
    __version__ = '0.90.0'

project = 'PgAppForge'
current_year = datetime.now().year
copyright = f'{current_year}, Nyimbi Odero. Inspired by Flask-AppBuilder (Daniel Vaz Gaspar).'
author = 'Nyimbi Odero'
version = __version__
release = __version__

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx_rtd_theme',
    'myst_parser',
]

templates_path = ['_templates']
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}
master_doc = 'index'
exclude_patterns = ['_build', 'archive']
pygments_style = 'sphinx'
show_authors = True

html_theme = 'sphinx_rtd_theme'
html_title = 'PgAppForge Documentation'
html_theme_options = {
    'collapse_navigation': False,
    'display_version': True,
    'navigation_depth': 3,
    'logo_only': False,
}
html_static_path = ['_static']
htmlhelp_basename = 'PgAppForgedoc'

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'flask': ('https://flask.palletsprojects.com/', None),
    'sqlalchemy': ('https://docs.sqlalchemy.org/en/20/', None),
}

latex_documents = [
    ('index', 'PgAppForge.tex', 'PgAppForge Documentation', author, 'manual'),
]
man_pages = [
    ('index', 'pgappforge', 'PgAppForge Documentation', [author], 1),
]
