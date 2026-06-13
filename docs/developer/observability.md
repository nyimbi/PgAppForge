# Observability — OpenTelemetry Integration

PgAppForge ships `pgappforge.telemetry` — a thin, zero-mandatory-dependency
wrapper around the OpenTelemetry Python SDK.  It auto-instruments Flask routes
and SQLAlchemy queries, and provides a decorator + metric helper for custom
business spans.

---

## Installation

OpenTelemetry packages are **optional** — the framework runs without them.
Install what you need:

```bash
# Minimum: SDK + Flask + SQLAlchemy auto-instrumentation
pip install \
    opentelemetry-sdk \
    opentelemetry-instrumentation-flask \
    opentelemetry-instrumentation-sqlalchemy

# OTLP exporter (Jaeger / Grafana Tempo / any OTLP collector)
pip install opentelemetry-exporter-otlp-proto-grpc

# Or add to pyproject.toml extras
[project.optional-dependencies]
otel = [
    "opentelemetry-sdk>=1.24",
    "opentelemetry-instrumentation-flask>=0.45b0",
    "opentelemetry-instrumentation-sqlalchemy>=0.45b0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.24",
]
```

---

## Quickstart

Call `setup_telemetry` once in your app factory, **after** creating the Flask
app and SQLAlchemy engine:

```python
from pgappforge.telemetry import setup_telemetry

def create_app():
    app = Flask(__name__)
    db.init_app(app)

    with app.app_context():
        setup_telemetry(
            app,
            db.engine,
            exporter_endpoint="http://jaeger:4317",
        )

    return app
```

---

## Flask Config Keys

All config is read from `app.config` and can be supplied via environment
variables (Flask reads `FLASK_*` env vars automatically) or `.env`:

| Key                       | Type   | Default          | Description                                        |
|---------------------------|--------|------------------|----------------------------------------------------|
| `OTEL_ENABLED`            | bool   | `True`           | Set `False` to disable entirely                    |
| `OTEL_SERVICE_NAME`       | str    | `"pgappforge"`   | `service.name` resource attribute                  |
| `OTEL_SERVICE_VERSION`    | str    | `"4.8.0"`        | `service.version` resource attribute               |
| `OTEL_EXPORTER_ENDPOINT`  | str    | `None`           | OTLP collector URL, e.g. `http://jaeger:4317`      |
| `OTEL_EXPORTER_TYPE`      | str    | `"otlp"`         | `"otlp"` \| `"console"` \| `"none"`               |

---

## Custom View Spans

Wrap any view method with `@trace_view` to create a named child span:

```python
from pgappforge.telemetry import trace_view
from pgappforge.views import ModelView

class LoanView(ModelView):
    @expose("/disburse/<int:pk>", methods=["POST"])
    @trace_view("loan.disburse")
    def disburse(self, pk):
        ...
```

The span carries `pgappforge.view = "LoanView.disburse"` as an attribute.

---

## Business Metrics

```python
from pgappforge.telemetry import record_business_metric

# In a payment processing view
record_business_metric(
    "payment.disbursed_cents",
    amount_cents,
    {"currency": "KES", "channel": "mpesa"},
)

# Simple event count
record_business_metric("invoice.created")
```

Metrics are exported via the same OTLP endpoint as traces (on a 30-second
flush interval).

---

## Backends

### Jaeger (All-in-One — local dev)

```yaml
# docker-compose.yml snippet
jaeger:
  image: jaegertracing/all-in-one:1.57
  ports:
    - "16686:16686"   # UI
    - "4317:4317"     # OTLP gRPC
```

```bash
OTEL_EXPORTER_ENDPOINT=http://localhost:4317 flask run
```

Open <http://localhost:16686> → select service `pgappforge`.

---

### Grafana Tempo + Grafana

```yaml
# docker-compose.yml snippet
tempo:
  image: grafana/tempo:latest
  command: -config.file=/etc/tempo.yaml
  volumes:
    - ./monitoring/tempo.yaml:/etc/tempo.yaml
  ports:
    - "4317:4317"   # OTLP gRPC ingest

grafana:
  image: grafana/grafana:latest
  environment:
    GF_SECURITY_ADMIN_PASSWORD: admin
  ports:
    - "3000:3000"
```

Minimal `monitoring/tempo.yaml`:

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo/blocks
    wal:
      path: /tmp/tempo/wal
```

Add a Tempo data source in Grafana (`http://tempo:3200`) and enable
**TraceQL** for advanced span querying.

---

### Datadog

```python
setup_telemetry(
    app,
    db.engine,
    exporter_endpoint="http://datadog-agent:4317",
    service_name="pgappforge-prod",
)
```

Ensure the Datadog Agent has OTLP ingest enabled:

```yaml
# datadog.yaml
otlp_config:
  receiver:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
```

Set `DD_SERVICE`, `DD_ENV`, and `DD_VERSION` env vars for unified service
tagging.

---

### Console (zero-infra dev)

```python
setup_telemetry(app, exporter_type="console")
```

Spans print as JSON to stdout — useful for local debugging without a
collector.

---

## Production Checklist

- [ ] Set `OTEL_ENABLED=true` and `OTEL_EXPORTER_ENDPOINT` in production env.
- [ ] Pin `opentelemetry-sdk` version in `pyproject.toml` extras.
- [ ] Confirm collector TLS if endpoint is remote (use `https://` or configure
      channel credentials in your exporter).
- [ ] Add `record_business_metric` calls at payment, invoice, and loan
      disbursement code paths for business KPI dashboards.
- [ ] Sample high-traffic routes via `OTEL_TRACES_SAMPLER=parentbased_traceidratio`
      and `OTEL_TRACES_SAMPLER_ARG=0.1` to cap collector ingestion costs.
