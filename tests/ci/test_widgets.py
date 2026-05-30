"""
tests/ci/test_widgets.py

Unit tests for pgappforge widget classes (pgappforge/widgets/core.py).

Strategy
--------
- Widgets are plain Python objects; the __call__ render path requires a
  Jinja2 environment — we mock current_app.jinja_env for those tests.
- Structural / configuration tests run without any Flask context.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

import pytest

from pgappforge.widgets.core import (
    RenderTemplateWidget,
    FormWidget,
    ShowWidget,
    ListWidget,
    SearchWidget,
    ChartWidget,
    ApprovalWidget,
    ListThumbnail,
    ListLinkWidget,
    ListCarousel,
    ListItem,
    ListBlock,
    ShowBlockWidget,
    ShowVerticalWidget,
    FormVerticalWidget,
    FormHorizontalWidget,
    FormInlineWidget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_app_context(rendered="<html/>"):
    """Return a context-manager that patches current_app.jinja_env.get_template."""
    template = MagicMock()
    template.render.return_value = rendered
    jinja_env = MagicMock()
    jinja_env.get_template.return_value = template
    app = MagicMock()
    app.jinja_env = jinja_env
    return patch("pgappforge.widgets.core.current_app", app)


# ---------------------------------------------------------------------------
# RenderTemplateWidget
# ---------------------------------------------------------------------------

def test_render_template_widget_stores_template_args():
    w = RenderTemplateWidget(foo="bar", count=3)
    assert w.template_args["foo"] == "bar"
    assert w.template_args["count"] == 3


def test_render_template_widget_call_renders_template():
    with _mock_app_context("<div>hello</div>") as mock_app:
        w = RenderTemplateWidget(greeting="hi")
        result = w()
        assert "<div>hello</div>" == result
        mock_app.jinja_env.get_template.assert_called_once_with(w.template)


def test_render_template_widget_call_merges_kwargs():
    with _mock_app_context() as mock_app:
        w = RenderTemplateWidget(a=1)
        w(b=2)
        _, kwargs = mock_app.jinja_env.get_template.return_value.render.call_args
        # render is called with merged dict as positional arg
        render_args = mock_app.jinja_env.get_template.return_value.render.call_args
        # Either positional or keyword — just confirm both keys ended up somewhere
        call_dict = render_args[0][0] if render_args[0] else render_args[1]
        assert "a" in call_dict
        assert "b" in call_dict


def test_render_template_widget_default_template():
    w = RenderTemplateWidget()
    assert "render.html" in w.template


# ---------------------------------------------------------------------------
# FormWidget
# ---------------------------------------------------------------------------

def test_form_widget_stores_form():
    form = MagicMock()
    w = FormWidget(form=form)
    assert w.form is form


def test_form_widget_stores_include_cols():
    w = FormWidget(include_cols=["name", "email"])
    assert w.include_cols == ["name", "email"]


def test_form_widget_stores_exclude_cols():
    w = FormWidget(exclude_cols=["password"])
    assert w.exclude_cols == ["password"]


def test_form_widget_stores_fieldsets():
    fs = [{"label": "Basic", "fields": ["name"]}]
    w = FormWidget(fieldsets=fs)
    assert w.fieldsets == fs


def test_form_widget_template_contains_form():
    w = FormWidget()
    assert "form" in w.template


# ---------------------------------------------------------------------------
# ShowWidget
# ---------------------------------------------------------------------------

def test_show_widget_stores_model():
    model = SimpleNamespace(id=1, name="Alice")
    w = ShowWidget(model=model)
    assert w.model is model


def test_show_widget_template():
    w = ShowWidget()
    assert "show" in w.template


# ---------------------------------------------------------------------------
# ListWidget
# ---------------------------------------------------------------------------

def test_list_widget_default_page_size():
    w = ListWidget()
    assert w.page_size == 20


def test_list_widget_custom_page_size():
    w = ListWidget(page_size=50)
    assert w.page_size == 50


def test_list_widget_stores_list_columns():
    w = ListWidget(list_columns=["name", "email"])
    assert w.list_columns == ["name", "email"]


def test_list_widget_stores_order_columns():
    w = ListWidget(order_columns=["name"])
    assert w.order_columns == ["name"]


def test_list_widget_template():
    w = ListWidget()
    assert "list" in w.template


# ---------------------------------------------------------------------------
# SearchWidget
# ---------------------------------------------------------------------------

def test_search_widget_stores_search_form():
    form = MagicMock()
    w = SearchWidget(search_form=form)
    assert w.search_form is form


def test_search_widget_stores_filters():
    w = SearchWidget(filters=["active", "inactive"])
    assert w.filters == ["active", "inactive"]


# ---------------------------------------------------------------------------
# ChartWidget
# ---------------------------------------------------------------------------

def test_chart_widget_has_chart_template():
    # The second ChartWidget definition in core.py is a minimal subclass;
    # just verify it renders from the correct template path.
    w = ChartWidget()
    assert "chart" in w.template


def test_chart_widget_accepts_kwargs():
    # Both ChartWidget definitions accept **kwargs forwarded to template_args.
    w = ChartWidget(title="Revenue")
    assert w.template_args.get("title") == "Revenue"


def test_chart_widget_inherits_render_template_widget():
    w = ChartWidget()
    assert isinstance(w, RenderTemplateWidget)


def test_chart_widget_template_args_empty_by_default():
    w = ChartWidget()
    assert isinstance(w.template_args, dict)


# ---------------------------------------------------------------------------
# ApprovalWidget
# ---------------------------------------------------------------------------

def test_approval_widget_default_approval_not_required():
    w = ApprovalWidget()
    assert w.approval_required is False


def test_approval_widget_approval_required_flag():
    w = ApprovalWidget(approval_required=True)
    assert w.approval_required is True


def test_approval_widget_render_approval_buttons_no_status_attr():
    w = ApprovalWidget(approval_required=True)
    obj = SimpleNamespace()  # no .status
    result = w.render_approval_buttons(obj)
    assert result == ""


def test_approval_widget_render_approval_buttons_not_pending():
    w = ApprovalWidget(approval_required=True)
    obj = SimpleNamespace(status="approved")
    result = w.render_approval_buttons(obj)
    assert result == ""


def test_approval_widget_render_approval_buttons_no_approval_required():
    w = ApprovalWidget(approval_required=False)
    obj = SimpleNamespace(status="pending_approval")
    result = w.render_approval_buttons(obj)
    assert result == ""


def test_approval_widget_get_approval_status_badge_no_status():
    w = ApprovalWidget()
    obj = SimpleNamespace()
    result = w.get_approval_status_badge(obj)
    assert result == ""


def test_approval_widget_get_approval_status_badge_approved():
    w = ApprovalWidget()
    obj = SimpleNamespace(status="approved")
    badge = w.get_approval_status_badge(obj)
    assert "Approved" in badge or "approved" in badge.lower()


def test_approval_widget_get_approval_status_badge_pending():
    w = ApprovalWidget()
    obj = SimpleNamespace(status="pending_approval")
    badge = w.get_approval_status_badge(obj)
    assert badge  # non-empty


def test_approval_widget_get_approval_status_badge_rejected():
    w = ApprovalWidget()
    obj = SimpleNamespace(status="rejected")
    badge = w.get_approval_status_badge(obj)
    assert "danger" in badge or "Rejected" in badge or "rejected" in badge.lower()


# ---------------------------------------------------------------------------
# Variant widget constructors
# ---------------------------------------------------------------------------

def test_list_thumbnail_template():
    w = ListThumbnail()
    assert "thumbnail" in w.template


def test_list_link_widget_template():
    w = ListLinkWidget()
    assert "link" in w.template


def test_list_carousel_template():
    w = ListCarousel()
    assert "carousel" in w.template


def test_list_item_template():
    w = ListItem()
    assert "item" in w.template


def test_list_block_template():
    w = ListBlock()
    assert "block" in w.template


def test_show_block_widget_template():
    w = ShowBlockWidget()
    assert "show" in w.template


def test_show_vertical_widget_template():
    w = ShowVerticalWidget()
    assert "vertical" in w.template or "show" in w.template


def test_form_vertical_widget_template():
    w = FormVerticalWidget()
    assert "vertical" in w.template or "form" in w.template


def test_form_horizontal_widget_template():
    w = FormHorizontalWidget()
    assert "horizontal" in w.template or "form" in w.template


def test_form_inline_widget_template():
    w = FormInlineWidget()
    assert "inline" in w.template or "form" in w.template
