"""Global search view for Flask-AppBuilder.

Renders a Bootstrap 3 compatible search page with results grouped by model.
"""
from __future__ import annotations

from flask import current_app, render_template_string, request
from flask_appbuilder.baseviews import BaseView, expose

from .manager import GlobalSearchManager, SearchResult


# ---------------------------------------------------------------------------
# Bootstrap 3 template — self-contained, no external template file required.
# ---------------------------------------------------------------------------
SEARCH_TEMPLATE = """\
{% extends 'appbuilder/base.html' %}
{% block content %}
<div class="container-fluid">
  <div class="row">
    <div class="col-md-12">

      {# ── Search box ── #}
      <form method="GET" action="" class="form-inline" role="search"
            style="margin: 20px 0;">
        <div class="input-group" style="width:100%; max-width:640px;">
          <input type="text"
                 name="q"
                 value="{{ q | e }}"
                 class="form-control input-lg"
                 placeholder="Search…"
                 autofocus>
          <span class="input-group-btn">
            <button class="btn btn-default btn-lg" type="submit">
              <span class="glyphicon glyphicon-search"></span>
            </button>
          </span>
        </div>
      </form>

      {# ── Result summary ── #}
      {% if q %}
        {% if total == 0 %}
          <div class="alert alert-info">
            No results found for <strong>{{ q | e }}</strong>.
          </div>
        {% else %}
          <p class="text-muted">
            {{ total }} result{{ 's' if total != 1 else '' }}
            for <strong>{{ q | e }}</strong>
          </p>

          {# ── Results grouped by model ── #}
          {% for label, items in grouped.items() %}
            <div class="panel panel-default" style="margin-bottom:24px;">
              <div class="panel-heading">
                <h3 class="panel-title">
                  {{ label | e }}
                  <span class="badge">{{ items | length }}</span>
                </h3>
              </div>
              <div class="list-group" style="margin-bottom:0;">
                {% for r in items %}
                  <a href="{{ r.url | e }}"
                     class="list-group-item">
                    <h4 class="list-group-item-heading">
                      {{ r.display | e }}
                    </h4>
                    {% if r.snippet and r.snippet != r.display %}
                      <p class="list-group-item-text text-muted"
                         style="margin:0; font-size:0.9em;">
                        {{ r.snippet | e }}
                      </p>
                    {% endif %}
                  </a>
                {% endfor %}
              </div>
            </div>
          {% endfor %}

        {% endif %}
      {% endif %}

    </div>
  </div>
</div>
{% endblock %}
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def get_search_manager() -> GlobalSearchManager | None:
	"""Return the GlobalSearchManager bound to the current app, or None."""
	return current_app.extensions.get("fab_search_manager")


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class GlobalSearchView(BaseView):
	"""App-wide search view.

	Register with AppBuilder::

	    appbuilder.add_view_no_menu(GlobalSearchView)

	Then navigate to ``/search/`` or link to ``/search/?q=<term>``.
	"""

	route_base = "/search"
	default_view = "search"

	@expose("/", methods=["GET"])
	def search(self) -> str:
		q: str = request.args.get("q", "").strip()
		results: list[SearchResult] = []
		grouped: dict[str, list[SearchResult]] = {}

		if q:
			manager = get_search_manager()
			if manager:
				results = manager.search(q, limit=30)
				for r in results:
					grouped.setdefault(r.label, []).append(r)

		return render_template_string(
			SEARCH_TEMPLATE,
			q=q,
			grouped=grouped,
			total=len(results),
		)


__all__ = ["GlobalSearchView", "get_search_manager", "SEARCH_TEMPLATE"]
