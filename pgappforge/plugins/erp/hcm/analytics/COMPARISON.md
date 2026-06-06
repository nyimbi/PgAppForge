# HR Analytics — World-Class Comparison

## Our Implementation

- **Headcount**: point-in-time active headcount with GROUP BY on department, employment type, and gender; uses COUNT-only queries (no full-row fetch for aggregates)
- **Turnover**: period-based termination count with voluntary/involuntary split, average-headcount denominator, turnover rate %, and annualised rate; auto-emits `TurnoverAlertEvent` when rate exceeds 15% threshold
- **Diversity**: gender distribution + 5-bracket age distribution; Shannon entropy representation index [0,1] normalised over non-empty gender categories — a principled mathematical measure, not a simple ratio
- **Flight risk scoring**: additive 5-factor model (short tenure +30, no promotion +20, low engagement +25, new manager +15, market salary gap +10) capped at 100; persisted as `HrFlightRiskScore` with `is_current` flag; emits `FlightRiskAlertEvent` for HIGH/CRITICAL
- **Cost-per-hire**: sums `recruitment_cost_cents` from employee metadata for hires in a date range; integer arithmetic throughout
- **Snapshot engine**: `generate_snapshot` dispatches to any compute method and persists an `HrAnalyticsSnapshot`; supports HEADCOUNT, TURNOVER, DIVERSITY, COST_PER_HIRE, TIME_TO_FILL (stub), ENGAGEMENT (stub)
- **Dashboard**: single call combining live headcount, YTD turnover, HIGH/CRITICAL flight risk count, open positions, and latest snapshot per type

Kenya/Africa-specific features:
- Voluntary/involuntary termination split is directly relevant to Kenya's Employment Act severance obligations
- Annualised turnover rate is the standard metric for CBK and NSE human capital disclosures
- Shannon entropy diversity index supports Kenya's Gender Mainstreaming Advisory Committee (GMAC) 30% rule reporting

Integration points:
- **BPM**: `hcm.analytics.compute_flight_risk` registered as BPM action — can trigger retention workflows automatically
- **Recruitment**: `get_dashboard` queries `JobOpening.status == OPEN` from recruitment module (graceful import guard)
- **Event bus**: `HeadcountChangedEvent`, `TurnoverAlertEvent`, `FlightRiskAlertEvent`, `AnalyticsReportGeneratedEvent`

---

## Benchmark: Workday / SAP SuccessFactors

| Feature | Status |
|---|---|
| Headcount by department / type / gender | ✓ |
| Turnover with voluntary/involuntary split | ✓ |
| Annualised turnover rate (Decimal-safe) | ✓ |
| Flight risk scoring with factor decomposition | ✓ |
| Shannon entropy diversity index | ✓ (exceeds typical vendor offering) |
| Snapshot persistence and historical trend | ✓ |
| Consolidated HR dashboard | ✓ |
| Predictive attrition (ML-based, not rule-based) | ✗ |
| Time-to-fill recruiting metric | ✗ (stub only) |
| Engagement score (survey-driven) | ✗ (stub only) |
| Pay equity / gender pay gap analysis | ✗ |
| Succession readiness index | ✗ |
| Workforce planning / FTE modelling | ✗ |
| Configurable KPI thresholds | ✗ (turnover alert threshold is a code constant) |
| Embedded BI / report builder | ✗ |

---

## Benchmark: Darwinbox (African market leader)

Darwinbox People Analytics offers configurable dashboards, org-chart visualisations, and some predictive elements. It does not publish its scoring methodology.

| Feature | Status |
|---|---|
| Headcount and turnover dashboards | ✓ (we match) |
| Voluntary/involuntary turnover split | ✓ (we match) |
| Flight risk / attrition risk scoring | ✓ (we match on output; we exceed on transparency) |
| Gender diversity reporting | ✓ (we exceed with entropy index) |
| Cost-per-hire metric | ✓ (we match) |
| Configurable dashboard widgets | ✗ |
| Org-chart / reporting-line visualisation | ✗ |
| Pulse survey integration | ✗ |
| Benchmarking against industry peers | ✗ |
| Mobile analytics access | ✗ |

---

## Differentiation

Where we exceed the benchmark:
- Transparent, auditable flight risk model with factor decomposition — Workday/Darwinbox black-box predictive scores are not explainable to employees or regulators; ours is
- Shannon entropy representation index is mathematically sounder than a simple female-% ratio used by most vendors
- Snapshot persistence with `AnalyticsReportGeneratedEvent` creates a full audit trail of every analytics computation — useful for board reporting and ESG disclosures
- BPM-callable flight risk computation enables automated retention escalation workflows

Remaining gaps:
- TIME_TO_FILL and ENGAGEMENT snapshot types are stubs; no data source wired
- Turnover alert threshold is a module-level constant, not a tenant-configurable value
- No ML/statistical attrition model beyond the additive rule-based flight risk score
- No pay equity or gender pay gap analysis
- No workforce planning or scenario modelling
- No visualisation layer — all output is structured dicts for downstream rendering
