# Predictive Analytics Plugin — SPEC

## Domain
`analytics` — sub-plugin of the Analytics domain.

## Purpose
ML model registry with training→deployment→retirement lifecycle, per-entity
prediction storage, and statistical anomaly detection via z-score.

---

## Entities

### MLModel
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| tenant_id | UUID NOT NULL | |
| model_name | VARCHAR(200) | Unique per (tenant, model_name, version) |
| model_type | VARCHAR(20) | CLASSIFICATION \| REGRESSION \| CLUSTERING \| NLP |
| framework | VARCHAR(20) | SKLEARN \| PYTORCH \| TENSORFLOW \| ANTHROPIC |
| version | VARCHAR(20) | Semver e.g. 1.0.0 |
| artifact_path | TEXT | S3/GCS/local URI to serialised model |
| feature_schema | JSONB | `{"feature": {"dtype": "float", ...}}` |
| target_variable | VARCHAR(200) | Supervised output variable name |
| accuracy_metric | NUMERIC(5,4) | 0.0000–1.0000 |
| trained_at | TIMESTAMPTZ | |
| deployed_at | TIMESTAMPTZ | |
| status | VARCHAR(20) | TRAINING \| DEPLOYED \| RETIRED |

### ModelPrediction
Immutable. Never UPDATE — re-run model to get new prediction.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| model_id | UUID FK MLModel | CASCADE |
| entity_type | VARCHAR(100) | e.g. Party, Lead |
| entity_id | VARCHAR(64) | |
| prediction_value | JSONB | Model-type dependent output |
| confidence | NUMERIC(5,4) | 0–1 |
| predicted_at | TIMESTAMPTZ | DEFAULT NOW() |
| features_snapshot | JSONB | Input features at inference time |

### AnomalyDetection
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| metric_name | VARCHAR(200) | Dotted key e.g. sales.revenue.daily |
| detected_at | TIMESTAMPTZ | DEFAULT NOW() |
| expected_value | NUMERIC(20,4) | |
| actual_value | NUMERIC(20,4) | |
| z_score | NUMERIC(7,3) | Signed; \|z\| ≥ 2 triggers LOW |
| severity | VARCHAR(20) | LOW \| MEDIUM \| HIGH \| CRITICAL |
| acknowledged_by | INT FK ab_user | |
| acknowledged_at | TIMESTAMPTZ | |
| resolution_notes | TEXT | |

---

## Business Rules
1. Only DEPLOYED models can produce predictions.
2. Deploying a model auto-retires any other DEPLOYED version of the same model_name within the tenant.
3. Models with accuracy_metric < 0.60 are blocked from deployment by Rules Engine.
4. z-score severity: |z| < 2 → LOW; < 3 → MEDIUM; < 4 → HIGH; ≥ 4 → CRITICAL.
5. ModelPrediction rows are immutable. Correction = new prediction row.
6. LOW anomalies auto-acknowledge after 24 hours via Rules Engine.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /analytics/ml-models/ | Model registry (HTML) |
| POST | /analytics/ml-models/ | Register model (JSON) |
| POST | /analytics/ml-models/`<id>`/deploy | Deploy model (JSON) |
| POST | /analytics/ml-models/`<id>`/retire | Retire model (JSON) |
| GET | /analytics/predictions/entity/`<type>`/`<id>` | Predictions for entity (JSON) |
| POST | /analytics/predictions/ | Record prediction (JSON) |
| GET | /analytics/anomalies/ | Recent HIGH+CRITICAL anomalies (HTML) |
| GET | /analytics/anomalies/report | Severity distribution report (HTML) |
| POST | /analytics/anomalies/`<id>`/acknowledge | Acknowledge anomaly (JSON) |

---

## Events Emitted
- `analytics.ml_model.deployed` — model promoted to DEPLOYED
- `analytics.ml_model.retired` — model retired
- `analytics.prediction.created` — prediction recorded
- `analytics.anomaly.detected` — anomaly above z-score threshold
- `analytics.anomaly.acknowledged` — anomaly triaged

## Events Consumed
- `analytics.kpi.status_changed` — trigger anomaly check
- `analytics.cdp.profile_computed` — trigger churn prediction

---

## Rules Engine Rulesets (4)
1. `analytics.ml_model.require_accuracy_before_deploy` — block deploy if accuracy < 0.60
2. `analytics.ml_model.single_deployed_per_name` — warn on dual-DEPLOYED versions
3. `analytics.anomaly.escalate_critical` — escalate CRITICAL to on-call channel
4. `analytics.anomaly.auto_acknowledge_low` — auto-acknowledge LOW after 24 hours

---

## ReportForge Templates (3)
1. **ML Model Registry** — status and accuracy table (HTML)
2. **Anomaly Severity Report** — count by severity and metric (HTML)
3. **Anomaly Severity Distribution** — for charting integration (via `/anomalies/report`)
