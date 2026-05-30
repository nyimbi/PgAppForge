import logging

from flask_babel import lazy_gettext

from .jsontools import dict_to_json
from .widgets import ChartWidget, DirectChartWidget
from ..baseviews import BaseModelView, expose
from ..exceptions import FABException
from ..models.group import DirectProcessData, GroupByProcessData
from ..security.decorators import has_access
from ..urltools import get_filter_args
from ..widgets import SearchWidget

log = logging.getLogger(__name__)


class BaseChartView(BaseModelView):
    """
    This is the base class for all chart views.
    Use DirectByChartView or GroupByChartView, override their properties
     and their base classes
    (BaseView, BaseModelView, BaseChartView) to customise your charts
    """

    chart_template = "appbuilder/general/charts/chart.html"
    """ The chart template, override to implement your own """
    chart_widget = ChartWidget
    """ Chart widget override to implement your own """
    search_widget = SearchWidget
    """ Search widget override to implement your own """

    chart_title = "Chart"
    """ A title to be displayed on the chart """
    title = "Title"

    group_by_label = lazy_gettext("Group by")
    """ The label that is displayed for the chart selection """

    default_view = "chart"

    chart_type = "PieChart"
    """ The chart type PieChart, ColumnChart, LineChart """
    chart_3d = "true"
    """ Will display in 3D? """
    width = 400
    """ The width """
    height = "400px"

    group_bys = {}
    # New for 0.6.4, on test, don't use yet

    def __init__(self, **kwargs):
        self._init_titles()
        super(BaseChartView, self).__init__(**kwargs)

    def _init_titles(self):
        self.title = self.chart_title

    def _get_chart_widget(self, filters=None, widgets=None, **args):
        raise NotImplementedError

    def _get_view_widget(self, **kwargs):
        """
        :return:
            Returns a widget
        """
        pass
        return self._get_chart_widget(**kwargs).get("chart")


class GroupByChartView(BaseChartView):
    definitions = []
    """
        These charts can display multiple series,
        based on columns or methods defined on models.
        You can display multiple charts on the same view.
        This data can be grouped and aggregated has you like.

        :label: (optional) String label to display on chart selection.
        :group: String with the column name or method from model.
        :formatter: (optional) function that formats the output of 'group' key
        :series: A list of tuples with the aggregation function and the column name
                to apply the aggregation

        ::
    
        PgForge view for groupbychart interface operations.

        The GroupByChartView class provides comprehensive functionality for
        groupbychart view operations.
        It integrates with the PgForge framework to provide
        enterprise-grade features and capabilities.

        Inherits from: BaseChartView

        Example:
            >>> instance = GroupByChartView()
            >>> # Use instance methods to perform operations
            >>> result = instance.main_method()

        

            [{
                'label': 'String',
                'group': '<COLNAME>'|'<FUNCNAME>'
                'formatter: <FUNC>
                'series': [(<AGGR FUNC>, <COLNAME>|'<FUNCNAME>'),...]
                }
            ]

        example::

            class CountryGroupByChartView(GroupByChartView):
                datamodel = SQLAInterface(CountryStats)
                chart_title = 'Statistics'

            definitions = [
                {
                    'label': 'Country Stat',
                    'group': 'country',
                    'series': [(aggregate_avg, 'unemployed_perc'),
                           (aggregate_avg, 'population'),
                           (aggregate_avg, 'college_perc')
                          ]
                }
            ]

    """
    chart_type = "ColumnChart"
    chart_template = "appbuilder/general/charts/jsonchart.html"
    chart_widget = DirectChartWidget
    ProcessClass = GroupByProcessData

    def __init__(self, **kwargs):
        super(GroupByChartView, self).__init__(**kwargs)
        for definition in self.definitions:
            col = definition.get("group")
            # Setup labels
            try:
                self.label_columns[col] = (
                    definition.get("label") or self.label_columns[col]
                )
            except Exception:
                self.label_columns[col] = self._prettify_column(col)
            if not definition.get("label"):
                definition["label"] = self.label_columns[col]
            # Setup Series
            for serie in definition["series"]:
                if isinstance(serie, tuple):
                    if hasattr(serie[0], "_label"):
                        key = serie[0].__name__ + serie[1]
                        self.label_columns[key] = (
                            serie[0]._label + " " + self._prettify_column(serie[1])
                        )
                else:
                    self.label_columns[serie] = self._prettify_column(serie)

    def get_group_by_class(self, definition):
        """
        intantiates the processing class (Direct or Grouped) and returns it.
        """
        pass
        group_by = definition["group"]
        series = definition["series"]
        if "formatter" in definition:
            formatter = {group_by: definition["formatter"]}
        else:
            formatter = {}
        return self.ProcessClass([group_by], series, formatter)

    def _get_chart_widget(
        self,
        filters=None,
        order_column="",
        order_direction="",
        widgets=None,
        direct=None,
        height=None,
        definition="",
        **args
    ):
        height = height or self.height
        widgets = widgets or dict()
        joined_filters = filters.get_joined_filters(self._base_filters)
        # check if order_column may be database ordered
        if not self.datamodel.get_order_columns_list([order_column]):
            order_column = ""
            order_direction = ""
        count, lst = self.datamodel.query(
            filters=joined_filters,
            order_column=order_column,
            order_direction=order_direction,
        )
        if not definition:
            definition = self.definitions[0]
        group = self.get_group_by_class(definition)
        value_columns = group.to_json(
            group.apply(lst, sort=order_column == ""), self.label_columns
        )
        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=height,
            value_columns=value_columns,
            modelview_name=self.__class__.__name__,
            **args
        )
        return widgets

    @expose("/chart/<group_by>")
    @expose("/chart/")
    @has_access
    def chart(self, group_by=0):
        """
                Perform chart operation.

                This method provides functionality for chart.
                Implementation follows PgForge patterns and standards.

                Args:
                    group_by: The group by parameter

                Returns:
                    The result of the operation

                Example:
                    >>> instance = GroupByChartView()
                    >>> result = instance.chart("group_by_value")
                    >>> print(result)

                """
        pass
        group_by = int(group_by)
        form = self.search_form.refresh()
        get_filter_args(self._filters)
        widgets = self._get_chart_widget(
            filters=self._filters,
            definition=self.definitions[group_by],
            order_column=self.definitions[group_by]["group"],
            order_direction="asc",
        )
        widgets = self._get_search_widget(form=form, widgets=widgets)
        self.update_redirect()
        return self.render_template(
            self.chart_template,
            route_base=self.route_base,
            title=self.chart_title,
            label_columns=self.label_columns,
            definitions=self.definitions,
            group_by_label=self.group_by_label,
            height=self.height,
            widgets=widgets,
            appbuilder=self.appbuilder,
        )


class DirectByChartView(GroupByChartView):
    """
    Use this class to display charts with multiple series,
    based on columns or methods defined on models.
    You can display multiple charts on the same view.

    Default routing point is '/chart'

    Setup definitions property to configure the chart

    :label: (optional) String label to display on chart selection.
    :group: String with the column name or method from model.
    :formatter: (optional) function that formats the output of 'group' key
    :series: A list of tuples with the aggregation function and the column name
            to apply the aggregation

    The **definitions** property respects the following grammar::

        definitions = [
                {
                 'label': 'label for chart definition',
                 'group': '<COLNAME>'|'<MODEL FUNCNAME>',
                 'formatter': <FUNC FORMATTER FOR GROUP COL>,
                 'series': ['<COLNAME>'|'<MODEL FUNCNAME>',...]
                }, ...
              ]

    example::

        class CountryDirectChartView(DirectByChartView):
            datamodel = SQLAInterface(CountryStats)
            chart_title = 'Direct Data Example'

            definitions = [
                {
                    'label': 'Unemployment',
                    'group': 'stat_date',
                    'series': ['unemployed_perc',
                        'college_perc']
                }
            ]

    """

    ProcessClass = DirectProcessData


# -------------------------------------------------------
# DEPRECATED SECTION
# -------------------------------------------------------


class BaseSimpleGroupByChartView(BaseChartView):  # pragma: no cover
    group_by_columns = []
    """ A list of columns to be possibly grouped by, this list must be filled """

    def __init__(self, **kwargs):
        """
        PgForge view for basesimplegroupbychart interface operations.

        The BaseSimpleGroupByChartView class provides comprehensive functionality for
        basesimplegroupbychart view operations.
        It integrates with the PgForge framework to provide
        enterprise-grade features and capabilities.

        Inherits from: BaseChartView

        Example:
            >>> instance = BaseSimpleGroupByChartView()
            >>> # Use instance methods to perform operations
            >>> result = instance.main_method()

        """
        pass
        if not self.group_by_columns:
            raise FABException(
                "Base Chart View property <group_by_columns> must not be empty"
            )
        else:
            super(BaseSimpleGroupByChartView, self).__init__(**kwargs)

    def _get_chart_widget(
        self,
        filters=None,
        order_column="",
        order_direction="",
        widgets=None,
        group_by=None,
        height=None,
        **args
    ):
        height = height or self.height
        widgets = widgets or dict()
        group_by = group_by or self.group_by_columns[0]
        joined_filters = filters.get_joined_filters(self._base_filters)
        value_columns = self.datamodel.query_simple_group(
            group_by, filters=joined_filters
        )

        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=height,
            value_columns=value_columns,
            modelview_name=self.__class__.__name__,
            **args
        )
        return widgets


class BaseSimpleDirectChartView(BaseChartView):  # pragma: no cover
    direct_columns = []
    """
        Make chart using the column on the dict
        chart_columns = {'chart label 1':('X column','Y1 Column','Y2 Column', ...),
                        'chart label 2': ('X Column','Y1 Column',...),...}
    """

    def __init__(self, **kwargs):
        """
        PgForge view for basesimpledirectchart interface operations.

        The BaseSimpleDirectChartView class provides comprehensive functionality for
        basesimpledirectchart view operations.
        It integrates with the PgForge framework to provide
        enterprise-grade features and capabilities.

        Inherits from: BaseChartView

        Example:
            >>> instance = BaseSimpleDirectChartView()
            >>> # Use instance methods to perform operations
            >>> result = instance.main_method()

        """
        pass
        if not self.direct_columns:
            raise FABException(
                "Base Chart View property <direct_columns> must not be empty"
            )
        else:
            super(BaseSimpleDirectChartView, self).__init__(**kwargs)

    def get_group_by_columns(self):
        """
        returns the keys from direct_columns
        Used in template, so that user can choose from options
        """
        pass
        return list(self.direct_columns.keys())

    def _get_chart_widget(
        self,
        filters=None,
        order_column="",
        order_direction="",
        widgets=None,
        direct=None,
        height=None,
        **args
    ):
        height = height or self.height
        widgets = widgets or dict()
        joined_filters = filters.get_joined_filters(self._base_filters)
        count, lst = self.datamodel.query(
            filters=joined_filters,
            order_column=order_column,
            order_direction=order_direction,
        )
        value_columns = self.datamodel.get_values(lst, list(direct))
        value_columns = dict_to_json(
            direct[0], direct[1:], self.label_columns, value_columns
        )

        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=height,
            value_columns=value_columns,
            modelview_name=self.__class__.__name__,
            **args
        )
        return widgets


class ChartView(BaseSimpleGroupByChartView):  # pragma: no cover
    """
    **DEPRECATED**

    Provides a simple (and hopefully nice) way to draw charts on your application.

    This will show Google Charts based on group by of your tables.
    """

    @expose("/chart/<group_by>")
    @expose("/chart/")
    @has_access
    def chart(self, group_by=""):
        """
                Perform chart operation.

                This method provides functionality for chart.
                Implementation follows PgForge patterns and standards.

                Args:
                    group_by: The group by parameter
                    period: The period parameter

                Returns:
                    The result of the operation

                Example:
                    >>> instance = TimeChartView()
                    >>> result = instance.chart("group_by_value", "period_value")
                    >>> print(result)

                """
        pass
        form = self.search_form.refresh()
        get_filter_args(self._filters)

        group_by = group_by or self.group_by_columns[0]

        widgets = self._get_chart_widget(filters=self._filters, group_by=group_by)
        widgets = self._get_search_widget(form=form, widgets=widgets)
        return self.render_template(
            self.chart_template,
            route_base=self.route_base,
            title=self.chart_title,
            label_columns=self.label_columns,
            group_by_columns=self.group_by_columns,
            group_by_label=self.group_by_label,
            height=self.height,
            widgets=widgets,
            appbuilder=self.appbuilder,
        )


class TimeChartView(BaseSimpleGroupByChartView):  # pragma: no cover
    """
    **DEPRECATED**

    Provides a simple way to draw some time charts on your application.

    This will show Google Charts based on count and group
    by month and year for your tables.
    """

    chart_template = "appbuilder/general/charts/chart_time.html"
    chart_type = "ColumnChart"

    def _get_chart_widget(
        self,
        filters=None,
        order_column="",
        order_direction="",
        widgets=None,
        group_by=None,
        period=None,
        height=None,
        **args
    ):
        """
                Perform chart operation.

                This method provides functionality for chart.
                Implementation follows PgForge patterns and standards.

                Args:
                    group_by: The group by parameter

                Returns:
                    The result of the operation

                Example:
                    >>> instance = DirectChartView()
                    >>> result = instance.chart("group_by_value")
                    >>> print(result)

                """
        pass
        height = height or self.height
        widgets = widgets or dict()
        group_by = group_by or self.group_by_columns[0]
        joined_filters = filters.get_joined_filters(self._base_filters)

        if period == "month" or not period:
            value_columns = self.datamodel.query_month_group(
                group_by, filters=joined_filters
            )
        elif period == "year":
            value_columns = self.datamodel.query_year_group(
                group_by, filters=joined_filters
            )

        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=height,
            value_columns=value_columns,
            modelview_name=self.__class__.__name__,
            **args
        )
        return widgets

    @expose("/chart/<group_by>/<period>")
    @expose("/chart/")
    @has_access
    def chart(self, group_by="", period=""):
        form = self.search_form.refresh()
        get_filter_args(self._filters)

        group_by = group_by or self.group_by_columns[0]

        widgets = self._get_chart_widget(
            filters=self._filters, group_by=group_by, period=period, height=self.height
        )

        widgets = self._get_search_widget(form=form, widgets=widgets)
        return self.render_template(
            self.chart_template,
            route_base=self.route_base,
            title=self.chart_title,
            label_columns=self.label_columns,
            group_by_columns=self.group_by_columns,
            group_by_label=self.group_by_label,
            widgets=widgets,
            appbuilder=self.appbuilder,
        )


class DirectChartView(BaseSimpleDirectChartView):  # pragma: no cover
    """
    **DEPRECATED**

    This class is responsible for displaying a Google chart with
    direct model values. Chart widget uses json.
    No group by is processed, example::

        class StatsChartView(DirectChartView):
            datamodel = SQLAInterface(Stats)
            chart_title = lazy_gettext('Statistics')
            direct_columns = {'Some Stats': ('X_col_1', 'stat_col_1', 'stat_col_2'),
                              'Other Stats': ('X_col2', 'stat_col_3')}

    """

    chart_type = "ColumnChart"

    chart_widget = DirectChartWidget

    @expose("/chart/<group_by>")
    @expose("/chart/")
    @has_access
    def chart(self, group_by=""):
        form = self.search_form.refresh()
        get_filter_args(self._filters)

        direct_key = group_by or list(self.direct_columns.keys())[0]

        direct = self.direct_columns.get(direct_key)

        if self.base_order:
            order_column, order_direction = self.base_order
        else:
            order_column, order_direction = "", ""

        widgets = self._get_chart_widget(
            filters=self._filters,
            order_column=order_column,
            order_direction=order_direction,
            direct=direct,
        )
        widgets = self._get_search_widget(form=form, widgets=widgets)
        return self.render_template(
            self.chart_template,
            route_base=self.route_base,
            title=self.chart_title,
            label_columns=self.label_columns,
            group_by_columns=self.get_group_by_columns(),
            group_by_label=self.group_by_label,
            height=self.height,
            widgets=widgets,
            appbuilder=self.appbuilder,
        )


class ProcessStatusChartView(BaseChartView):
    """
    Chart view for displaying process status distribution.
    
    Extends BaseChartView to show status distribution for models
    that use StateTrackingMixin or have a status field.
    
    This chart automatically groups records by status and shows
    the count for each status in a pie chart format.
    
    Example usage:
        class MyProcessStatusChart(ProcessStatusChartView):
            datamodel = SQLAInterface(MyModel)
            chart_title = "My Process Status Overview"
    """
    
    chart_type = "PieChart"
    chart_title = "Process Status Overview"
    chart_3d = "true"
    
    def __init__(self, **kwargs):
        """Initialize process status chart view."""
        super(ProcessStatusChartView, self).__init__(**kwargs)
        
        # Set up default definitions for status grouping
        if not hasattr(self, 'definitions') or not self.definitions:
            self.definitions = [
                {
                    'label': 'Status Distribution',
                    'group': 'status',
                    'formatter': self._format_status_label,
                    'series': [('Count', 'id')]
                }
            ]
    
    def _format_status_label(self, value):
        """
        Format status labels for display.
        
        :param value: Status value to format
        :return: Formatted status label
        """
        if not value:
            return 'Unknown'
        
        # Convert snake_case to Title Case
        return str(value).replace('_', ' ').title()
    
    def _get_chart_widget(self, filters=None, definition=None, **kwargs):
        """
        Get chart widget with status data.
        
        :param filters: Query filters
        :param definition: Chart definition
        :param kwargs: Additional arguments
        :return: Chart widget dictionary
        """
        if not definition:
            definition = self.definitions[0] if self.definitions else {}
        
        # Use GroupByProcessData for status aggregation
        group_by = GroupByProcessData(
            self.datamodel,
            ['status'],  # Group by status field
            'count'      # Count aggregation
        )
        
        # Apply filters if provided
        if filters:
            group_by._apply_filters(filters)
        
        # Get the grouped data
        chart_data = group_by.apply_filter_and_group()
        
        # Format data for chart widget
        formatted_data = self._format_chart_data(chart_data, definition)
        
        widgets = {}
        widgets["chart"] = self.chart_widget(
            route_base=self.route_base,
            chart_title=self.chart_title,
            chart_type=self.chart_type,
            chart_3d=self.chart_3d,
            height=self.height,
            chart_data=formatted_data,
            modelview_name=self.__class__.__name__,
            **kwargs
        )
        
        return widgets
    
    def _format_chart_data(self, raw_data, definition):
        """
        Format raw status data for chart display.
        
        :param raw_data: Raw data from GroupByProcessData
        :param definition: Chart definition with formatter
        :return: Formatted data for chart widget
        """
        formatted_data = []
        
        # Get formatter from definition
        formatter = definition.get('formatter', lambda x: x)
        
        for item in raw_data:
            if isinstance(item, dict):
                status = item.get('status', 'Unknown')
                count = item.get('count', 0)
            else:
                # Handle different data formats
                status = getattr(item, 'status', 'Unknown')
                count = getattr(item, 'count', 1)
            
            formatted_data.append({
                'label': formatter(status),
                'value': int(count),
                'status': status
            })
        
        return formatted_data
    
    @expose("/chart/")
    @expose("/chart/<int:group_by>")
    @has_access
    def chart(self, group_by=0):
        """
        Render process status chart.
        
        :param group_by: Group by index (defaults to 0 for status grouping)
        :return: Rendered chart template
        """
        try:
            # Get chart definition
            definition = self.definitions[group_by] if group_by < len(self.definitions) else self.definitions[0]
            
            # Get chart widget with data
            widgets = self._get_chart_widget(
                filters=getattr(self, '_filters', []),
                definition=definition
            )
            
            # Add search widget if available
            if hasattr(self, 'search_form'):
                form = self.search_form.refresh()
                widgets = self._get_search_widget(form=form, widgets=widgets)
            
            self.update_redirect()
            
            return self.render_template(
                self.chart_template,
                route_base=self.route_base,
                title=self.chart_title,
                widgets=widgets,
                appbuilder=self.appbuilder,
                chart_data=widgets.get('chart', {}).get('chart_data', [])
            )
            
        except Exception as e:
            log.error(f"Error rendering process status chart: {e}")
            # Return error message or empty chart
            return self.render_template(
                self.chart_template,
                route_base=self.route_base,
                title=f"{self.chart_title} (Error)",
                widgets={},
                appbuilder=self.appbuilder,
                error_message=f"Failed to load chart: {str(e)}"
            )
    
    def get_status_summary(self):
        """
        Get status summary data for dashboard widgets.
        
        :return: Dictionary with status counts and percentages
        """
        try:
            # Get raw status data
            group_by = GroupByProcessData(self.datamodel, ['status'], 'count')
            raw_data = group_by.apply_filter_and_group()
            
            # Calculate summary statistics
            total_count = sum(item.get('count', 0) for item in raw_data)
            status_summary = {}
            
            for item in raw_data:
                status = item.get('status', 'Unknown')
                count = item.get('count', 0)
                percentage = (count / total_count * 100) if total_count > 0 else 0
                
                status_summary[status] = {
                    'count': count,
                    'percentage': round(percentage, 1),
                    'label': self._format_status_label(status)
                }
            
            return {
                'total_count': total_count,
                'status_breakdown': status_summary,
                'most_common_status': max(status_summary.items(), 
                                        key=lambda x: x[1]['count'])[0] if status_summary else None
            }
            
        except Exception as e:
            log.error(f"Error getting status summary: {e}")
            return {
                'total_count': 0,
                'status_breakdown': {},
                'most_common_status': None,
                'error': str(e)
            }
