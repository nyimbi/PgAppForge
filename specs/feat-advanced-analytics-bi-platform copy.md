# Advanced Analytics & BI Platform

## Status
Draft

## Authors
Claude Code Assistant - September 2025

## Overview
Transform Flask-AppBuilder into a comprehensive business intelligence platform by enhancing existing analytics capabilities with smart dashboards, custom report builders, predictive analytics, and real-time metrics. This feature enables any Flask-AppBuilder application to become a data-driven decision platform for business users.

## Background/Problem Statement
Flask-AppBuilder already has substantial analytics foundations including charts, dashboards, and monitoring capabilities. However, organizations need more advanced BI features:

**Current Limitations:**
- Chart system requires technical knowledge to configure
- Limited self-service analytics for business users  
- No predictive analytics or forecasting capabilities
- Dashboard creation requires developer intervention
- Reports are mostly static with limited interactivity
- Missing advanced visualization types (sankey, network graphs, heatmaps)

**Business Requirements:**
- Self-service analytics for non-technical users
- Predictive insights and forecasting
- Real-time business metrics and KPIs
- Advanced visualizations for complex data relationships
- Automated report generation and distribution
- Interactive dashboard building without coding

## Goals
- **Smart Dashboard Builder**: Drag-and-drop dashboard creation with AI-suggested insights
- **Self-Service Analytics**: Enable business users to create reports without technical knowledge
- **Predictive Analytics**: ML-powered forecasting, trend analysis, and anomaly detection
- **Real-Time Metrics**: Live KPI tracking with alerts and notifications
- **Advanced Visualizations**: Comprehensive chart library including network graphs, heatmaps, and custom visualizations
- **Automated Insights**: AI-powered data analysis with natural language summaries
- **Export & Sharing**: Rich export options and collaborative sharing features

## Non-Goals
- Replace existing Flask-AppBuilder chart system (enhance it instead)
- Full ETL pipeline capabilities (focus on analysis, not data preparation)
- Complex data warehouse management
- Advanced statistical modeling beyond ML predictions
- Real-time streaming data processing (batch analytics focus)

## Technical Dependencies

### External Libraries
- **Plotly >= 5.17.0**: Advanced interactive visualizations
- **Pandas >= 2.1.0**: Data manipulation and analysis
- **Scikit-learn >= 1.3.0**: Machine learning for predictive analytics
- **NumPy >= 1.24.0**: Numerical computing foundation
- **Apache Arrow >= 14.0.0**: Columnar data processing for performance
- **DuckDB >= 0.9.0**: Fast analytical query processing
- **Prophet >= 1.1.4**: Time series forecasting
- **NetworkX >= 3.0**: Network graph analysis (already planned for process engine)

### Internal Dependencies
- Existing Flask-AppBuilder chart system for foundation
- Current analytics infrastructure (wizard_analytics, federated_analytics)
- Widget system for dashboard components
- Security system for data access control
- Real-time collaboration system for shared dashboards

## Detailed Design

### Architecture Overview
```
┌─────────────────────────────────────────────────────────────────┐
│                 Advanced Analytics & BI Platform                │
├─────────────────────────────────────────────────────────────────┤
│  Smart Dashboards │  Report Builder   │  Predictive Analytics  │
│  ┌─────────────┐   │  ┌─────────────┐  │  ┌─────────────────┐   │
│  │ AI Insights │   │  │ Query Builder│  │  │ ML Models      │   │
│  │ Drag & Drop │   │  │ Self-Service │  │  │ Forecasting    │   │
│  │ Templates   │   │  │ Export Tools │  │  │ Anomaly Detect │   │
│  └─────────────┘   │  └─────────────┘  │  └─────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                      Data Processing Layer                      │
│  ┌─────────────┐   │  ┌─────────────┐  │  ┌─────────────────┐   │
│  │ Query Engine│   │  │ Data Cache  │  │  │ Metric Engine   │   │
│  │ (DuckDB)    │   │  │ (Apache     │  │  │ Real-time KPIs  │   │
│  │             │   │  │  Arrow)     │  │  │                 │   │
│  └─────────────┘   │  └─────────────┘  │  └─────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                Enhanced Chart Foundation                        │
│   Existing Charts │ New Visualizations │ Interactive Features  │
├─────────────────────────────────────────────────────────────────┤
│                   Flask-AppBuilder Foundation                  │
│    Security │ Models │ Views │ Widgets │ Collaboration         │
└─────────────────────────────────────────────────────────────────┘
```

### Enhanced Data Models

#### Dashboard
```python
class Dashboard(AuditMixin, Model):
    __tablename__ = 'ab_dashboards'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    slug = Column(String(50), unique=True, nullable=False)
    
    # Dashboard configuration
    layout = Column(JSONB, nullable=False)  # Grid layout definition
    settings = Column(JSONB, default=lambda: {})
    theme = Column(String(30), default='default')
    
    # Access control
    is_public = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey('ab_user.id'))
    
    # Performance optimization  
    cache_duration = Column(Integer, default=300)  # seconds
    last_generated = Column(DateTime)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    widgets = relationship("DashboardWidget", back_populates="dashboard", 
                          cascade="all, delete-orphan")
    shares = relationship("DashboardShare", back_populates="dashboard",
                         cascade="all, delete-orphan")

class DashboardWidget(AuditMixin, Model):
    __tablename__ = 'ab_dashboard_widgets'
    
    id = Column(Integer, primary_key=True)
    dashboard_id = Column(Integer, ForeignKey('ab_dashboards.id'))
    
    # Widget configuration
    widget_type = Column(String(50), nullable=False)  # chart, metric, table, text
    title = Column(String(100))
    configuration = Column(JSONB, nullable=False)
    
    # Layout positioning
    position_x = Column(Integer, default=0)
    position_y = Column(Integer, default=0) 
    width = Column(Integer, default=4)
    height = Column(Integer, default=3)
    
    # Data source
    data_source = Column(JSONB, nullable=False)  # Query configuration
    
    # Relationships
    dashboard = relationship("Dashboard", back_populates="widgets")
```

#### Report Definition
```python
class ReportDefinition(AuditMixin, Model):
    __tablename__ = 'ab_report_definitions'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    category = Column(String(50))
    
    # Report configuration
    query_config = Column(JSONB, nullable=False)  # Query builder output
    visualization_config = Column(JSONB, nullable=False)
    parameters = Column(JSONB, default=lambda: {})  # Report parameters
    
    # Scheduling and automation
    schedule_config = Column(JSONB)  # Cron-like scheduling
    auto_export = Column(Boolean, default=False)
    export_formats = Column(JSONB, default=lambda: ['pdf', 'excel'])
    
    # Access control
    created_by = Column(Integer, ForeignKey('ab_user.id'))
    is_template = Column(Boolean, default=False)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    executions = relationship("ReportExecution", back_populates="definition")
```

#### ML Model Registry
```python
class MLModel(AuditMixin, Model):
    __tablename__ = 'ab_ml_models'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    model_type = Column(String(50), nullable=False)  # forecast, classification, anomaly
    description = Column(Text)
    
    # Model configuration
    features = Column(JSONB, nullable=False)  # Input features
    target = Column(String(100))  # Target variable
    hyperparameters = Column(JSONB, default=lambda: {})
    
    # Model performance
    metrics = Column(JSONB, default=lambda: {})  # Accuracy, RMSE, etc.
    training_data = Column(JSONB)  # Training dataset metadata
    
    # Model storage
    model_path = Column(String(255))  # Path to serialized model
    version = Column(String(20), default='1.0')
    status = Column(String(20), default='training')  # training, active, deprecated
    
    # Performance tracking
    last_prediction = Column(DateTime)
    prediction_count = Column(Integer, default=0)
```

### Smart Dashboard Builder

#### Dashboard Designer Interface
```python
class DashboardDesigner(BaseView):
    route_base = "/dashboard/designer"
    
    @expose("/")
    @has_access
    def index(self):
        """Dashboard gallery and creation interface"""
        return self.render_template(
            'appbuilder/analytics/dashboard_designer.html',
            dashboard_templates=self.get_templates(),
            recent_dashboards=self.get_recent_dashboards()
        )
    
    @expose("/create")
    @has_access  
    def create(self):
        """Visual dashboard creation interface"""
        return self.render_template(
            'appbuilder/analytics/dashboard_canvas.html',
            data_sources=self.get_available_data_sources(),
            widget_library=self.get_widget_library()
        )
    
    def get_widget_library(self):
        """Get available widget types with configuration"""
        return {
            'charts': {
                'line': {'name': 'Line Chart', 'icon': '📈', 'config_fields': ['x_axis', 'y_axis', 'groupby']},
                'bar': {'name': 'Bar Chart', 'icon': '📊', 'config_fields': ['x_axis', 'y_axis', 'groupby']},
                'pie': {'name': 'Pie Chart', 'icon': '🥧', 'config_fields': ['value', 'category']},
                'heatmap': {'name': 'Heatmap', 'icon': '🔥', 'config_fields': ['x_axis', 'y_axis', 'intensity']},
                'network': {'name': 'Network Graph', 'icon': '🕸️', 'config_fields': ['nodes', 'edges', 'layout']},
                'sankey': {'name': 'Sankey Diagram', 'icon': '🌊', 'config_fields': ['source', 'target', 'value']}
            },
            'metrics': {
                'kpi': {'name': 'KPI Card', 'icon': '🎯', 'config_fields': ['metric', 'target', 'format']},
                'gauge': {'name': 'Gauge', 'icon': '🌡️', 'config_fields': ['value', 'min', 'max', 'thresholds']},
                'sparkline': {'name': 'Sparkline', 'icon': '⚡', 'config_fields': ['timeseries', 'period']}
            },
            'data': {
                'table': {'name': 'Data Table', 'icon': '📋', 'config_fields': ['columns', 'filters', 'sorting']},
                'pivot': {'name': 'Pivot Table', 'icon': '🔄', 'config_fields': ['rows', 'columns', 'values']}
            }
        }
```

#### AI-Powered Insights Engine
```python
class InsightsEngine:
    def __init__(self):
        self.anomaly_detector = self._load_anomaly_model()
        self.trend_analyzer = self._load_trend_model()
    
    def analyze_dataset(self, data: pd.DataFrame, 
                       context: dict = None) -> Dict[str, Any]:
        """Generate AI insights for dataset"""
        insights = {
            'summary_stats': self._generate_summary_stats(data),
            'trends': self._detect_trends(data),
            'anomalies': self._detect_anomalies(data),
            'correlations': self._find_correlations(data),
            'recommendations': self._generate_recommendations(data, context)
        }
        
        # Generate natural language summary
        insights['narrative'] = self._generate_narrative(insights)
        
        return insights
    
    def _generate_recommendations(self, data: pd.DataFrame, 
                                context: dict) -> List[Dict]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Recommend best visualizations
        if self._is_time_series(data):
            recommendations.append({
                'type': 'visualization',
                'title': 'Time Series Analysis',
                'description': 'Your data has time components. Consider line charts or trend analysis.',
                'suggested_charts': ['line', 'area', 'sparkline'],
                'confidence': 0.9
            })
        
        if self._has_categorical_data(data):
            recommendations.append({
                'type': 'visualization', 
                'title': 'Category Breakdown',
                'description': 'Found categorical data. Bar charts or pie charts would be effective.',
                'suggested_charts': ['bar', 'pie', 'treemap'],
                'confidence': 0.8
            })
            
        # Recommend KPIs based on data
        numeric_columns = data.select_dtypes(include=[np.number]).columns
        for col in numeric_columns[:3]:  # Top 3 numeric columns
            recommendations.append({
                'type': 'metric',
                'title': f'Track {col.title()}',
                'description': f'Consider monitoring {col} as a key performance indicator.',
                'suggested_widgets': ['kpi', 'gauge', 'trend'],
                'confidence': 0.7
            })
        
        return recommendations
```

### Self-Service Report Builder

#### Visual Query Builder
```python
class QueryBuilder:
    def __init__(self, data_source_config):
        self.data_source = data_source_config
        self.query_cache = {}
    
    def build_query(self, query_config: dict) -> str:
        """Convert visual query config to SQL"""
        tables = query_config.get('tables', [])
        columns = query_config.get('columns', [])
        filters = query_config.get('filters', [])
        groupby = query_config.get('groupby', [])
        orderby = query_config.get('orderby', [])
        
        # Build SELECT clause
        select_clause = self._build_select_clause(columns, groupby)
        
        # Build FROM clause with joins
        from_clause = self._build_from_clause(tables, query_config.get('joins', []))
        
        # Build WHERE clause
        where_clause = self._build_where_clause(filters)
        
        # Build GROUP BY clause
        group_clause = self._build_group_by_clause(groupby)
        
        # Build ORDER BY clause
        order_clause = self._build_order_by_clause(orderby)
        
        # Combine clauses
        query = f"SELECT {select_clause} FROM {from_clause}"
        
        if where_clause:
            query += f" WHERE {where_clause}"
        
        if group_clause:
            query += f" GROUP BY {group_clause}"
            
        if order_clause:
            query += f" ORDER BY {order_clause}"
            
        return query
    
    def preview_query(self, query_config: dict, limit: int = 100) -> pd.DataFrame:
        """Generate preview of query results"""
        query = self.build_query(query_config)
        preview_query = f"SELECT * FROM ({query}) LIMIT {limit}"
        
        return self._execute_query(preview_query)
    
    def _build_select_clause(self, columns: List[dict], 
                           groupby: List[dict]) -> str:
        """Build SELECT clause with aggregations"""
        select_items = []
        
        for col in columns:
            if col['type'] == 'dimension':
                select_items.append(f"{col['table']}.{col['name']}")
            elif col['type'] == 'measure':
                agg_func = col.get('aggregation', 'SUM')
                select_items.append(f"{agg_func}({col['table']}.{col['name']}) as {col.get('alias', col['name'])}")
        
        return ', '.join(select_items)
```

### Predictive Analytics Engine

#### Time Series Forecasting
```python
class ForecastingEngine:
    def __init__(self):
        self.models = {
            'prophet': Prophet(),
            'arima': None,  # Initialize on demand
            'linear_trend': None
        }
    
    def create_forecast(self, data: pd.DataFrame, 
                       config: dict) -> Dict[str, Any]:
        """Create forecast based on configuration"""
        
        # Prepare data
        ts_data = self._prepare_time_series_data(data, config)
        
        # Select appropriate model
        model_type = config.get('model', 'prophet')
        model = self._get_model(model_type, config)
        
        # Train model
        model.fit(ts_data)
        
        # Generate predictions
        future_periods = config.get('periods', 30)
        future = model.make_future_dataframe(periods=future_periods)
        forecast = model.predict(future)
        
        # Calculate model performance metrics
        metrics = self._calculate_forecast_metrics(
            ts_data, forecast[:len(ts_data)]
        )
        
        # Detect anomalies in historical data
        anomalies = self._detect_forecast_anomalies(
            ts_data, forecast[:len(ts_data)]
        )
        
        return {
            'forecast': forecast.to_dict('records'),
            'metrics': metrics,
            'anomalies': anomalies,
            'model_info': {
                'type': model_type,
                'parameters': model.get_params() if hasattr(model, 'get_params') else {}
            }
        }
    
    def _calculate_forecast_metrics(self, actual: pd.DataFrame, 
                                  predicted: pd.DataFrame) -> Dict[str, float]:
        """Calculate forecast accuracy metrics"""
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        
        actual_values = actual['y'].values
        predicted_values = predicted['yhat'].values
        
        return {
            'mae': mean_absolute_error(actual_values, predicted_values),
            'rmse': np.sqrt(mean_squared_error(actual_values, predicted_values)),
            'mape': np.mean(np.abs((actual_values - predicted_values) / actual_values)) * 100
        }
```

#### Real-Time Anomaly Detection
```python
class AnomalyDetector:
    def __init__(self):
        self.models = {}
        self.threshold_cache = {}
    
    def train_anomaly_model(self, model_config: dict) -> str:
        """Train anomaly detection model"""
        model_id = model_config['id']
        
        # Load training data
        training_data = self._load_training_data(model_config['data_source'])
        
        # Feature engineering
        features = self._extract_features(training_data, model_config['features'])
        
        # Train isolation forest model
        from sklearn.ensemble import IsolationForest
        model = IsolationForest(
            contamination=model_config.get('contamination', 0.1),
            random_state=42
        )
        
        model.fit(features)
        
        # Store model
        self.models[model_id] = {
            'model': model,
            'config': model_config,
            'trained_at': datetime.utcnow()
        }
        
        return model_id
    
    def detect_anomalies(self, model_id: str, 
                        new_data: pd.DataFrame) -> List[Dict]:
        """Detect anomalies in new data"""
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not found")
        
        model_info = self.models[model_id]
        model = model_info['model']
        config = model_info['config']
        
        # Extract features
        features = self._extract_features(new_data, config['features'])
        
        # Predict anomalies
        anomaly_scores = model.decision_function(features)
        is_anomaly = model.predict(features) == -1
        
        # Package results
        anomalies = []
        for idx, (score, is_anom) in enumerate(zip(anomaly_scores, is_anomaly)):
            if is_anom:
                anomalies.append({
                    'index': idx,
                    'score': score,
                    'data': new_data.iloc[idx].to_dict(),
                    'detected_at': datetime.utcnow().isoformat()
                })
        
        return anomalies
```

### Real-Time Metrics Engine

```python
class MetricsEngine:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.metric_definitions = {}
        self.alert_rules = {}
    
    def register_metric(self, metric_config: dict):
        """Register a real-time metric"""
        metric_id = metric_config['id']
        
        self.metric_definitions[metric_id] = {
            'name': metric_config['name'],
            'query': metric_config['query'],
            'refresh_interval': metric_config.get('refresh_interval', 60),
            'data_source': metric_config['data_source'],
            'aggregation': metric_config.get('aggregation', 'latest'),
            'format': metric_config.get('format', 'number')
        }
        
        # Schedule metric calculation
        self._schedule_metric_calculation(metric_id)
    
    def calculate_metric(self, metric_id: str) -> Dict[str, Any]:
        """Calculate current metric value"""
        if metric_id not in self.metric_definitions:
            raise ValueError(f"Metric {metric_id} not defined")
        
        metric_def = self.metric_definitions[metric_id]
        
        # Execute query
        result = self._execute_metric_query(metric_def['query'], metric_def['data_source'])
        
        # Apply aggregation
        value = self._apply_aggregation(result, metric_def['aggregation'])
        
        # Format value
        formatted_value = self._format_metric_value(value, metric_def['format'])
        
        # Store in Redis for real-time access
        metric_data = {
            'value': value,
            'formatted_value': formatted_value,
            'calculated_at': datetime.utcnow().isoformat(),
            'trend': self._calculate_trend(metric_id, value)
        }
        
        self.redis.setex(
            f"metric:{metric_id}", 
            metric_def['refresh_interval'] * 2,  # Cache for 2x refresh interval
            json.dumps(metric_data)
        )
        
        # Check alert rules
        self._check_alert_rules(metric_id, value)
        
        return metric_data
    
    def _calculate_trend(self, metric_id: str, current_value: float) -> Dict[str, Any]:
        """Calculate trend compared to previous values"""
        trend_key = f"metric_history:{metric_id}"
        
        # Get recent values
        recent_values = self.redis.lrange(trend_key, 0, 9)  # Last 10 values
        recent_values = [float(v) for v in recent_values]
        
        if len(recent_values) < 2:
            return {'direction': 'unknown', 'change': 0, 'percent_change': 0}
        
        # Calculate trend
        previous_value = recent_values[0]
        change = current_value - previous_value
        percent_change = (change / previous_value * 100) if previous_value != 0 else 0
        
        direction = 'up' if change > 0 else 'down' if change < 0 else 'flat'
        
        # Store current value in history
        self.redis.lpush(trend_key, current_value)
        self.redis.ltrim(trend_key, 0, 19)  # Keep last 20 values
        
        return {
            'direction': direction,
            'change': change,
            'percent_change': percent_change
        }
```

## User Experience

### Smart Dashboard Interface
1. **Dashboard Gallery**: Browse templates and existing dashboards with previews
2. **Drag-and-Drop Builder**: Visual dashboard creation with real-time preview
3. **AI Suggestions**: Smart recommendations for charts and metrics based on data
4. **Collaborative Editing**: Multiple users can edit dashboards simultaneously  
5. **Mobile Responsive**: Dashboards work perfectly on mobile devices

### Self-Service Analytics Experience
1. **Visual Query Builder**: Point-and-click interface for creating complex queries
2. **Data Explorer**: Browse available tables and columns with metadata
3. **Instant Preview**: See query results immediately as you build
4. **Export Options**: Download reports in PDF, Excel, CSV, or PowerPoint formats
5. **Scheduled Reports**: Set up automated report generation and distribution

### Predictive Analytics Interface
1. **Forecasting Wizard**: Step-by-step forecast creation with model selection
2. **Model Comparison**: Compare different forecasting approaches side-by-side
3. **Anomaly Alerts**: Real-time notifications when anomalies are detected
4. **Performance Tracking**: Monitor forecast accuracy over time
5. **What-If Scenarios**: Test different assumptions and see predicted outcomes

## Testing Strategy

### Unit Tests
```python
class TestInsightsEngine(unittest.TestCase):
    """Test AI-powered insights generation"""
    
    def test_trend_detection(self):
        """Verify trend detection in time series data"""
        # Purpose: Ensures the engine can identify upward, downward, and seasonal trends
        engine = InsightsEngine()
        
        # Create synthetic trending data
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        upward_trend = np.arange(100) + np.random.normal(0, 5, 100)
        data = pd.DataFrame({'date': dates, 'value': upward_trend})
        
        insights = engine.analyze_dataset(data)
        
        self.assertIn('trends', insights)
        trends = insights['trends']
        self.assertTrue(any(t['direction'] == 'increasing' for t in trends))
        # This test can fail if trend detection algorithm has bugs
        
    def test_anomaly_detection_accuracy(self):
        """Test anomaly detection with known outliers"""
        # Purpose: Validates anomaly detection doesn't have false positives/negatives
        detector = AnomalyDetector()
        
        # Create data with known anomalies
        normal_data = np.random.normal(100, 10, 1000)
        anomaly_data = np.concatenate([normal_data, [200, 300, -50]])  # Clear outliers
        df = pd.DataFrame({'value': anomaly_data})
        
        model_id = detector.train_anomaly_model({
            'id': 'test_model',
            'data_source': df,
            'features': ['value'],
            'contamination': 0.01
        })
        
        # Test on data with known anomalies
        test_data = pd.DataFrame({'value': [100, 95, 250, 90]})  # 250 is anomaly
        anomalies = detector.detect_anomalies(model_id, test_data)
        
        self.assertTrue(len(anomalies) >= 1)
        self.assertTrue(any(a['data']['value'] == 250 for a in anomalies))
        # This test can fail if anomaly thresholds are incorrectly calibrated
```

### Integration Tests  
```python
class TestDashboardBuilder(FABTestCase):
    """Test dashboard creation and management"""
    
    def test_dashboard_creation_workflow(self):
        """Test complete dashboard creation from UI to database"""
        # Purpose: Ensures dashboards can be created and persisted correctly
        with self.app.test_client() as client:
            self.login(client, 'analyst', 'password')
            
            # Create dashboard
            dashboard_data = {
                'name': 'Sales Dashboard',
                'description': 'Monthly sales analysis',
                'layout': {
                    'widgets': [
                        {
                            'type': 'chart',
                            'chart_type': 'line',
                            'position': {'x': 0, 'y': 0, 'w': 6, 'h': 4},
                            'data_source': {
                                'table': 'sales',
                                'columns': ['date', 'amount'],
                                'filters': []
                            }
                        }
                    ]
                }
            }
            
            response = client.post('/dashboard/create', json=dashboard_data)
            self.assertEqual(response.status_code, 201)
            
            # Verify dashboard was created
            dashboard = Dashboard.query.filter_by(name='Sales Dashboard').first()
            self.assertIsNotNone(dashboard)
            self.assertEqual(len(dashboard.widgets), 1)
            # This test can fail if dashboard persistence logic has issues
            
    def test_real_time_metrics_update(self):
        """Test real-time metric calculation and caching"""
        # Purpose: Ensures metrics are calculated and cached properly
        metrics_engine = MetricsEngine(self.redis_client)
        
        # Register test metric
        metrics_engine.register_metric({
            'id': 'daily_sales',
            'name': 'Daily Sales',
            'query': 'SELECT SUM(amount) FROM sales WHERE date = CURRENT_DATE',
            'data_source': 'main_db',
            'refresh_interval': 30
        })
        
        # Calculate metric
        result = metrics_engine.calculate_metric('daily_sales')
        
        self.assertIn('value', result)
        self.assertIn('formatted_value', result)
        self.assertIn('trend', result)
        
        # Verify caching
        cached_result = self.redis_client.get('metric:daily_sales')
        self.assertIsNotNone(cached_result)
        # This test can fail if Redis caching or metric calculation breaks
```

### E2E Tests
```python 
class TestAnalyticsPlatform(SeleniumTestCase):
    """End-to-end tests for analytics platform"""
    
    def test_self_service_report_creation(self):
        """Test business user creating report without technical knowledge"""
        # Purpose: Validates that non-technical users can successfully create reports
        driver = self.driver
        
        # Navigate to report builder
        driver.get(f"{self.base_url}/analytics/report-builder")
        
        # Select data source
        data_source_dropdown = driver.find_element(By.ID, "data-source-select")
        Select(data_source_dropdown).select_by_visible_text("Sales Data")
        
        # Add columns to report
        available_columns = driver.find_element(By.ID, "available-columns")
        report_columns = driver.find_element(By.ID, "report-columns")
        
        # Drag date column
        date_column = available_columns.find_element(By.XPATH, "//div[text()='Date']")
        ActionChains(driver).drag_and_drop(date_column, report_columns).perform()
        
        # Add filter
        filter_button = driver.find_element(By.ID, "add-filter-btn")
        filter_button.click()
        
        # Configure date filter
        filter_field = Select(driver.find_element(By.CLASS_NAME, "filter-field"))
        filter_field.select_by_visible_text("Date")
        
        filter_operator = Select(driver.find_element(By.CLASS_NAME, "filter-operator"))
        filter_operator.select_by_visible_text("Last 30 days")
        
        # Preview report
        preview_btn = driver.find_element(By.ID, "preview-report")
        preview_btn.click()
        
        # Verify data appears
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "report-data-table"))
        )
        
        data_rows = driver.find_elements(By.CSS_SELECTOR, ".report-data-table tbody tr")
        self.assertGreater(len(data_rows), 0)
        # This test can fail if report builder UI or data processing breaks
```

### Performance Tests
```python
class TestAnalyticsPerformance(unittest.TestCase):
    """Test analytics platform performance"""
    
    def test_large_dataset_query_performance(self):
        """Test query performance with large datasets"""
        # Purpose: Ensures platform can handle enterprise-scale data volumes
        start_time = time.time()
        
        # Execute complex query on large dataset
        query_builder = QueryBuilder({'type': 'duckdb', 'path': 'large_dataset.parquet'})
        
        query_config = {
            'tables': ['sales'],
            'columns': [
                {'table': 'sales', 'name': 'date', 'type': 'dimension'},
                {'table': 'sales', 'name': 'amount', 'type': 'measure', 'aggregation': 'SUM'}
            ],
            'groupby': [{'table': 'sales', 'name': 'date'}],
            'filters': [
                {'field': 'date', 'operator': '>=', 'value': '2023-01-01'},
                {'field': 'amount', 'operator': '>', 'value': 0}
            ]
        }
        
        result = query_builder.preview_query(query_config, limit=10000)
        
        execution_time = time.time() - start_time
        
        self.assertLess(execution_time, 5.0)  # Should complete within 5 seconds
        self.assertEqual(len(result), 10000)
        # This test can fail if query optimization is insufficient
```

## Performance Considerations

### Query Performance
- **DuckDB Integration**: Use DuckDB for fast analytical queries on large datasets
- **Apache Arrow**: Columnar data format for efficient memory usage
- **Query Caching**: Cache query results with intelligent invalidation
- **Incremental Processing**: Only process new/changed data where possible

### Dashboard Performance
- **Widget Lazy Loading**: Load dashboard widgets on demand
- **Data Pagination**: Paginate large datasets in tables and charts  
- **WebSocket Updates**: Real-time updates without full page refresh
- **CDN Integration**: Cache static visualization assets

### ML Model Performance
- **Model Caching**: Cache trained models in memory for fast predictions
- **Batch Prediction**: Process multiple predictions together
- **Model Versioning**: A/B test model performance and roll back if needed
- **Feature Caching**: Cache expensive feature calculations

### Scalability Strategies
- **Horizontal Scaling**: Distribute analytics processing across multiple workers
- **Database Read Replicas**: Separate analytics queries from transactional load
- **Data Partitioning**: Partition large tables by date or other dimensions
- **Async Processing**: Use Celery for long-running analytics tasks

## Security Considerations

### Data Access Control
- **Row-Level Security**: Control access to specific data rows based on user attributes
- **Column-Level Security**: Hide sensitive columns from unauthorized users
- **Dashboard Sharing**: Granular control over dashboard visibility and editing
- **Query Validation**: Prevent SQL injection and unauthorized data access

### ML Model Security  
- **Model Access Control**: Control who can create, train, and use ML models
- **Adversarial Attack Protection**: Detect and prevent adversarial inputs to models
- **Model Audit Trails**: Complete logging of model training and prediction activities
- **Feature Data Privacy**: Encrypt sensitive features used in ML models

### Export Security
- **Watermarking**: Add watermarks to exported reports for tracking
- **Export Logging**: Log all data exports for compliance
- **Format Security**: Ensure exported files don't contain malicious code
- **Access Expiration**: Time-limited access to exported files

## Documentation

### User Guides
- **Dashboard Builder Tutorial**: Step-by-step guide to creating dashboards
- **Self-Service Analytics Manual**: How to build reports without SQL knowledge
- **Predictive Analytics Guide**: Using ML features for forecasting
- **Mobile Analytics Guide**: Using dashboards and reports on mobile devices

### Administrator Documentation
- **Installation & Configuration**: Setting up the analytics platform
- **Data Source Management**: Connecting and managing data sources
- **Performance Tuning**: Optimizing query and dashboard performance  
- **Security Configuration**: Setting up access controls and data security

### Developer Resources
- **Custom Visualization Guide**: Creating custom chart types and widgets
- **ML Model Integration**: Adding custom ML models and algorithms
- **API Documentation**: REST API for programmatic access
- **Plugin Development**: Extending analytics capabilities

## Implementation Phases

### Phase 1: Enhanced Dashboard Foundation
**Smart Dashboard Builder Core**
- Enhanced dashboard data model with widget support
- Drag-and-drop dashboard designer interface  
- Extended chart library with new visualization types (heatmaps, network graphs)
- Basic AI insights engine with trend detection
- Dashboard sharing and collaboration features
- Mobile-responsive dashboard viewing

**Success Criteria:**
- Non-technical users can create dashboards visually
- New visualization types working correctly
- AI provides useful insights and recommendations
- Dashboards work seamlessly on mobile devices

### Phase 2: Self-Service Analytics
**Report Builder & Advanced Analytics**
- Visual query builder for business users
- Self-service report creation with drag-and-drop interface
- Predictive analytics with time series forecasting
- Real-time metrics engine with KPI tracking
- Automated report scheduling and distribution
- Advanced export options (PDF, PowerPoint, Excel)

**Success Criteria:**
- Business users can create complex reports without SQL
- Forecasting models provide accurate predictions
- Real-time metrics update correctly and efficiently
- Scheduled reports generate and distribute successfully

### Phase 3: AI-Powered Intelligence
**Advanced ML & Automation**
- Advanced anomaly detection with custom models
- Natural language query interface ("Show me sales trends")
- Automated insight discovery and alerting
- Advanced ML model registry and management
- Performance optimization and enterprise scalability
- Advanced collaboration features with commenting and annotations

**Success Criteria:**
- Anomaly detection accurately identifies real issues
- Natural language queries work reliably
- Platform handles enterprise-scale data volumes
- Advanced collaboration features enhance team productivity

## Open Questions

1. **Natural Language Processing**: Should we integrate with external NLP services or build custom models?
2. **Data Source Limits**: What are reasonable limits for data volume per dashboard/report?
3. **Real-Time Streaming**: Should we support real-time streaming data in addition to batch analytics?
4. **Mobile Experience**: How sophisticated should mobile dashboard editing capabilities be?
5. **Multi-Language Support**: Should analytics interfaces be localized for international users?
6. **External Integrations**: Which third-party analytics tools should have first-class integration?
7. **Data Governance**: How should we handle data lineage and governance in self-service analytics?

## References

### Existing Flask-AppBuilder Analytics
- [Chart Views](../flask_appbuilder/charts/views.py) - Foundation chart system to enhance
- [Analytics Wizard](../flask_appbuilder/analytics/wizard_analytics.py) - Event tracking patterns
- [Dashboard Implementation](../flask_appbuilder/views/dashboard.py) - Current dashboard capabilities
- [AI Analytics Assistant](../flask_appbuilder/database/ai_analytics_assistant.py) - AI integration patterns

### External Libraries
- [Plotly Python](https://plotly.com/python/) - Interactive visualizations  
- [Apache Arrow Documentation](https://arrow.apache.org/docs/) - Columnar data processing
- [DuckDB Documentation](https://duckdb.org/docs/) - Analytical SQL engine
- [Prophet Documentation](https://facebook.github.io/prophet/) - Time series forecasting
- [Scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html) - Machine learning algorithms

### Design Patterns  
- [Data Visualization Best Practices](https://www.tableau.com/learn/articles/data-visualization) - Effective chart design
- [Self-Service Analytics Patterns](https://www.gartner.com/en/documents/3956937) - Business user empowerment
- [Real-Time Dashboard Patterns](https://aws.amazon.com/blogs/big-data/build-a-real-time-dashboard-with-amazon-kinesis/) - Live data visualization
- [ML Model Serving Patterns](https://ml-ops.org/content/model-serving) - Production ML deployment