# Composable Data Systems: Architecture Survey

**Date:** 2026-06-14
**Scope:** dbt, Apache Spark, Kafka Streams/Flink, Airflow/Prefect/Dagster, Redpanda Connect, DuckDB

---

## Summary Matrix

| System | Composability Unit | Dependency Declaration | Schema Contract | Primary Composition Killer |
|--------|-------------------|----------------------|-----------------|---------------------------|
| **dbt (models)** | SQL model file | `ref()` macro | Column-level contracts (`constraints:`, `not_null`, `unique`) | Circular refs; renaming a column without updating downstream `ref()`s |
| **dbt Semantic Layer** | Semantic model → Measure → Metric | `model: ref(...)` + entity type links | Entity type system; measure → metric linkage | Missing entity on a table; fan-out joins; mistyped entity breaks joins silently |
| **Apache Spark** | `(DataFrame) => DataFrame` function | Curried parameters + `transform()` chain | Schema inferred at runtime; explicit `StructType` optional | Implicit classes (monkey-patching); non-deterministic UDF side effects |
| **Kafka Streams** | Topology DSL operator | Stream-to-operator linkage in builder | Serde (serializer/deserializer) contract | Repartitioning on `groupBy`/`selectKey`; XCom-style implicit topic naming |
| **Apache Flink** | Keyed operator + state backend | Streaming DAG edges | Barrier alignment; keyed state scoped per partition | Multi-input alignment skipped → at-least-once only; savepoint format changes |
| **Airflow** | Task / TaskGroup / DAG | `>>` operator + TaskFlow return values | None native; XCom is untyped | XCom tight coupling via task_id strings; TaskGroup dependency ordering bugs |
| **Prefect** | Flow / Task / Subflow | Python return values (futures) | Pydantic parameter validation | No native flow-level cross-deployment dependencies; cache key schema drift |
| **Dagster** | Software-Defined Asset (SDA) | `AssetIn` / function argument names | YAML asset checks + `TableSchema` metadata | Monorepo anti-pattern at scale; schema checks are post-hoc (after materialization) |
| **Redpanda Connect** | Processor (YAML block) | Label references (`resource: <label>`) | Label naming rules + startup field validation | Duplicate/missing labels; field typos halt execution; `shutdown_timeout` drops in-flight |
| **DuckDB** | SQL Macro | Implicit (co-deployment) | `columns_parameter_enum` ENUM type pre-creation | No compile-time dependency graph; runtime-only validation via `query()`; single-statement macro constraint |

---

## 1. dbt (Data Build Tool)

### Sources
- dbt packages docs: https://docs.getdbt.com/docs/build/packages
- dbt MetricFlow: https://docs.getdbt.com/docs/build/about-metricflow
- dbt Semantic Layer: https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl
- Atlan semantic layer deep dive: https://atlan.com/dbt-semantic-layer/
- Medium production governance: https://medium.com/tech-with-abhishek/dbt-semantic-layer-in-production-metrics-contracts-and-governance-fa5e368846c9

### a) Composability Unit

Two distinct layers:

**Model layer:** A `.sql` file + optional `.yml` sidecar. Each model is a named, referenceable node in the DAG. Models can be materializations: `table`, `view`, `incremental`, `ephemeral`. Ephemeral models compose inline (CTE expansion); materialized models compose via actual table references.

**Semantic layer:** Five-tier hierarchy:
```
Semantic Model (maps to ref('model'))
├── Entity        (join keys — primary / foreign / unique)
├── Dimension     (time | categorical — slicing axes)
└── Measure       (aggregation building block — sum, count, avg, ...)

Metric           (queryable output — simple | ratio | cumulative | derived)
Saved Query      (pre-defined metric + dimension combinations)
```

Derived metrics compose across other metrics:
```yaml
metrics:
  - name: revenue_per_customer
    type: derived
    type_params:
      expr: revenue / customers
      metrics:
        - name: revenue
        - name: customers
```

### b) Dependency Declaration

**Model layer:**
- `ref('model_name')` — compile-time macro that resolves to the correct schema-qualified table name and registers a DAG edge
- `source('source_name', 'table_name')` — references raw data sources with freshness SLAs
- Package deps in `packages.yml` / `dependencies.yml` with semver pinning; `dbt deps` produces a `package-lock.yml`
- Cross-project refs via dbt Mesh use `dependencies.yml` (no Jinja support there)

**Semantic layer:**
- `model: ref('orders')` — semantic model declares its backing dbt model
- Entities declare join traversal: a `foreign` entity on model A pointing to a `primary` entity on model B creates an edge in the semantic graph
- Metrics reference measures by name; measures reference columns in their parent semantic model

### c) Schema Contracts

**Model layer:**
- Column-level constraints in `.yml`: `not_null`, `unique`, `accepted_values`, `relationships`
- dbt `contracts:` block (dbt 1.5+) enforces column name + type at compile time — materialization fails if the SQL output doesn't match declared schema
- `dbt test` runs contract assertions as a test pass

**Semantic layer:**
- Entity type system is the core contract: MetricFlow resolves joins from entity types (`primary`/`foreign`/`unique`), not arbitrary SQL. This prevents fan-out and chasm joins by construction.
- Measure → metric linkage is by name; missing measures cause broken dependency chain
- OSI (Open Semantic Interchange) documents available from dbt Core v1.12 as alternative contract format

### d) What Breaks Composition

| Failure Mode | Mechanism |
|---|---|
| Column rename without downstream update | All `ref()`-derived models break at compile; semantic model measures break at query time |
| Missing/mistyped entity on a semantic model | That model's dimensions cannot be joined to metrics from other semantic models |
| Fan-out / chasm joins | MetricFlow blocks arbitrary join logic — you must type entities correctly or joins are inferred incorrectly |
| dbt version < 1.6 | Semantic models silently unsupported |
| Denormalized input tables | Reduces aggregation granularity; technically challenging redundancy |
| dbt Cloud gate | MetricFlow Server + Semantic Layer APIs require Team/Enterprise plan; open-source MetricFlow lacks the gateway |
| Circular `ref()` | Compile error — dbt DAG must be acyclic |

---

## 2. Apache Spark

### Sources
- Chaining DataFrame transformations: https://www.mungingdata.com/apache-spark/chaining-custom-dataframe-transformations/
- PySpark UDFs/UDTFs: https://spark.apache.org/docs/latest/api/python/user_guide/udfandudtf.html
- Dataset JavaDoc: https://spark.apache.org/docs/latest/api/java/org/apache/spark/sql/Dataset.html
- Spark data transformation Decube: https://www.decube.io/post/data-transformation-use-case-apache-spark-and-databricks

### a) Composability Unit

The canonical composable unit is a **pure function** with the signature:

```scala
def myTransform(df: DataFrame): DataFrame
```

For parameterized transforms, currying externalizes dependencies:

```scala
def withFiltered(threshold: Int)(df: DataFrame): DataFrame =
  df.filter(col("amount") > threshold)
```

At the RDD level: `map`, `filter`, `join`, `union`, `flatMap` are the primitive combinators. At the DataFrame/Dataset level, `select`, `filter`, `groupBy`, `agg`, `join`, `withColumn` are the higher-level composable operations.

### b) Dependency Declaration

- `Dataset#transform(f)` is the idiomatic chaining method:
  ```scala
  df.transform(withGreeting)
    .transform(withFarewell)
    .transform(withCat("puffy"))
  ```
- Curried parameters make upstream dependencies explicit at the call site before entering the chain
- Lazy evaluation: transformations build a logical plan; Catalyst optimizer composes the plan before execution
- Custom sources declared via `DataFrameReader.format("custom_source").load()` — source class registered via `ServiceLoader` or Spark config

### c) Schema Contracts

- Schema is **inferred at runtime** by default — no compile-time enforcement
- Explicit `StructType` schemas can be passed to readers: `spark.read.schema(mySchema).json(...)`
- `as[T]` on Dataset enables type-safe transformations with case class schemas — type mismatch surfaces as runtime exception, not compile error (in most cases)
- UDF return types declared at registration: `udf((x: String) => x.length, IntegerType)` — mismatch crashes executor
- No inter-transformation schema contract mechanism in the standard API; Delta Lake's schema enforcement is the typical addition

### d) What Breaks Composition

| Failure Mode | Mechanism |
|---|---|
| Implicit class monkey-patching | Attaches behavior to `DataFrame` class; breaks modularity and testability |
| UDF side effects | Non-deterministic UDFs break lazy plan reuse; Spark may execute UDFs multiple times |
| Non-curried parameterization | Closures capturing mutable state break serialization for distributed execution |
| Missing schema declaration | Schema inference on complex nested types produces wrong types silently |
| Ordering-dependent operations on unpartitioned data | `orderBy` followed by `mapPartitions` loses ordering guarantees after shuffle |
| Cross-`SparkSession` composition | DataFrames from different sessions cannot be joined |

---

## 3. Kafka Streams / Apache Flink

### Sources
- State management comparison: https://systemdr.substack.com/p/state-management-in-stream-processing
- Flink stateful stream processing: https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/stateful-stream-processing/
- Kafka Streams vs Flink: https://medium.com/@souquieres.adam/kafka-streams-vs-apache-flink-a-pragmatic-comparison-for-stream-processing-and-why-you-should-66fc0b641b26
- Flink beginner guide 2025: https://www.ververica.com/stream-processing-with-apache-flink-beginners-guide
- 2026 trends: https://www.kai-waehner.de/blog/2025/12/10/top-trends-for-data-streaming-with-apache-kafka-and-flink-in-2026/

### a) Composability Unit

**Kafka Streams:** The `Topology` is the composition artifact. Composable units are DSL operators: `stream()`, `table()`, `filter()`, `map()`, `flatMap()`, `groupBy()`, `aggregate()`, `join()`, `merge()`. The Streams DSL is a fluent builder — each method returns a `KStream`/`KTable`/`KGroupedStream` that the next operator receives.

**Apache Flink:** The `DataStream` / `DataSet` (legacy) API composes operators into a DAG. Composable units:
- `map`, `flatMap`, `filter` — stateless transformation operators
- `keyBy` — partition by key, enabling keyed state access
- `window` — time-bounded aggregation operator
- `process` — low-level `ProcessFunction` with full state + timer access
- `connect` — merges two streams into a `ConnectedStreams` for coordinated processing

The **Key Group** is the atomic unit for state redistribution during rescaling.

### b) Dependency Declaration

**Kafka Streams:**
- Topology is built imperatively: `builder.stream("input-topic").filter(...).to("output-topic")`
- State stores declared via `Materialized.as("store-name")` — named stores create implicit internal changelog topics
- Repartition topics created automatically on key-changing operations

**Flink:**
- DataStream pipeline is declared as a chain: `env.addSource(...).keyBy(...).process(...).addSink(...)`
- State declared inside operators using `getRuntimeContext().getState(new ValueStateDescriptor<>(...))` — state is scoped to the operator + key partition
- Barriers flow from sources through the topology DAG; the checkpoint coordinator drives consistent snapshot alignment

### c) Schema Contracts

**Kafka Streams:**
- Serde (Serializer/Deserializer) is the contract between operators: `Consumed.with(Serdes.String(), Serdes.Long())`
- Schema Registry (Confluent / Redpanda) enforces Avro/Protobuf/JSON schema compatibility at the topic level — enforced at produce/consume, not at operator composition time

**Flink:**
- `TypeInformation` system infers types at pipeline construction; Flink's type extractor handles most cases automatically
- For complex types, explicit `TypeHint` or Avro/Protobuf schemas required
- Barrier-based snapshot protocol enforces a causal contract: operator snapshots state only after receiving all input barriers, before emitting output barriers — this is the core consistency contract

**What constitutes a broken contract:**
- Mismatched Serde between producer and consumer operator → deserialization exception at runtime
- Schema evolution without backward/forward compatibility in Schema Registry → consumer failure
- State descriptor type change between Flink versions → savepoint incompatibility

### d) What Breaks Composition

| Failure Mode | Mechanism |
|---|---|
| **Kafka Streams:** `groupBy`/`selectKey` without repartition | Creates internal repartition topics; multiplies data volume; implicit topology complexity |
| **Kafka Streams:** Input partition count constrains parallelism | Cannot scale beyond partition count without topic restructuring |
| **Flink:** Multi-input alignment skipped | Degrades exactly-once to at-least-once; mixing snapshot epochs |
| **Flink:** Unaligned checkpointing under I/O bottleneck | Does not help when state backend I/O is the bottleneck |
| **Flink:** State descriptor type change | Savepoint incompatibility; breaks upgrade path |
| **Both:** Stateful operator with global side effects | Non-local state mutations (external DB writes) break exactly-once guarantees |
| **Both:** Unbounded out-of-order event time | Watermark strategy must be tuned per topology; wrong watermarks cause incorrect window triggers |

---

## 4. Apache Airflow / Prefect / Dagster

### Sources
- Airflow TaskFlow API: https://airflow.apache.org/docs/apache-airflow/stable/tutorial/taskflow.html
- Airflow XCom coupling: https://moldstud.com/articles/p-the-role-of-xcom-in-managing-task-dependencies-in-apache-airflow-a-comprehensive-guide
- Airflow TaskGroup dependency bugs: https://github.com/apache/airflow/issues/40196
- Prefect flows/tasks: https://docs.prefect.io/v3/concepts/flows
- Prefect composability: https://annageller.medium.com/how-to-build-modular-dataflows-with-tasks-flows-and-subflows-in-prefect-5eaabdfbb70e
- Dagster SDAs: https://dagster.io/glossary/software-defined-assets
- Dagster asset dependencies: https://docs.dagster.io/dagster-basics-tutorial/dependencies
- Dagster data contracts: https://docs.dagster.io/guides/test/data-contracts
- Dagster almanack composability: https://www.ssp.sh/blog/dagster-almanack-open-data-platform/

### a) Composability Unit

**Airflow:**
- `Task` (operator instance) — the atomic unit
- `TaskGroup` — named group of tasks composable as a unit in dependency chains
- `DAG` — the top-level composition; DAGs cannot call other DAGs natively (TriggerDagRunOperator exists but is fire-and-forget, not composable)

**Prefect:**
- `@task` — atomic, cacheable, retryable, concurrency-controllable unit
- `@flow` — composition of tasks and subflows; flows can call other flows (subflows)
- `PrefectFuture` — handle for async task result, composable into downstream tasks
- Cache policies are described as algebraic (composable with `+` operator)

**Dagster:**
- `@asset` — a Software-Defined Asset; the fundamental unit. Produces a named, observable data artifact.
- `@op` / `@graph` — lower-level task/pipeline primitives (pre-SDA era, still valid)
- `AssetIn` — explicit typed dependency reference between assets
- `AssetCheck` — post-materialization contract validator

### b) Dependency Declaration

**Airflow:**
- `>>` operator: `task_a >> task_b` (set downstream)
- TaskFlow API: returning a value from a `@task` and passing it to another creates an automatic XCom-backed dependency
- `set_upstream()` / `set_downstream()` programmatically
- TaskGroup: `group_1 >> group_2` creates group-level dependencies

**Prefect:**
- Python-native: pass `@task` return value directly to another `@task` call
- `submit()` returns `PrefectFuture`; `result()` blocks for resolution
- Subflows called like normal Python functions; their return values are data
- No native cross-deployment flow dependency (feature requested August 2025)

**Dagster:**
- Function argument naming: if asset B's function has parameter `asset_a`, Dagster infers `asset_a` as an upstream dependency
- Explicit: `deps=["asset_a"]` or `ins={"alias": AssetIn("asset_a")}`
- `AssetSelection` for grouping assets into jobs

### c) Schema Contracts

**Airflow:**
- None native. XCom is an untyped key-value store; downstream tasks must know `task_id` + key strings
- External enforcement via Great Expectations / dbt tests / custom operators
- No schema validation between tasks in the standard API

**Prefect:**
- Pydantic models as flow/task parameter types — validated at call time
- Cache key schema drift: solved with versioned cache keys + external validation tools
- `result()` returns Python objects — type is whatever the task returned, no structural enforcement

**Dagster:**
- `TableSchema` metadata attached at materialization via `context.add_output_metadata()`
- Asset checks compare actual materialized schema against YAML contract file:
  ```yaml
  schema:
    columns:
      shipment_id: {type: "int64", required: true}
      amount: {type: "float64", required: true}
  ```
- Schema validation is **post-hoc**: the asset materializes first, then the check runs. A failed check does not prevent materialization, only flags it.

### d) What Breaks Composition

| System | Failure Mode | Mechanism |
|--------|---|---|
| **Airflow** | XCom by task_id string | Hardcodes inter-task relationship; renaming a task silently breaks consumers |
| **Airflow** | TaskGroup dependency order bug | Dependencies declared before tasks added to group cause simultaneous execution (issue #16764) |
| **Airflow** | Dynamic task + TaskGroup XCom | Fetches all dynamic instances' XComs, not the targeted one (issue #41378) |
| **Airflow** | No cross-DAG composition | TriggerDagRunOperator is fire-and-forget; no data return path |
| **Prefect** | No flow-level cross-deployment deps | Cannot natively wait for another deployment's flow to complete |
| **Prefect** | Cache key schema drift | Cached results from old schema returned to tasks expecting new schema |
| **Dagster** | Post-hoc schema checks | Failed contract discovered after materialization, not before |
| **Dagster** | Monorepo at scale | Mixing ingestion, dbt, and ops code causes coordination failures in large orgs |
| **All** | Implicit ordering dependencies | Side-effectful tasks that assume prior tasks ran leave no DAG trace; hard to detect |

---

## 5. Redpanda Connect (formerly Benthos)

### Sources
- Redpanda Connect configuration: https://docs.redpanda.com/redpanda-connect/configuration/about/
- Mastering Redpanda Connect: https://risingwave.com/blog/mastering-redpanda-connect-with-benthos/
- GitHub repo: https://github.com/redpanda-data/connect
- Use cases: https://www.redpanda.com/blog/redpanda-connect-use-cases
- Benthos history: https://taogang.medium.com/the-past-and-present-of-stream-processing-part-16-benthos-the-reliable-guardian-of-ordinary-5a8cdaefad0f
- Webhooks example: https://blog.nobugware.com/post/2024/benthos-redpanda-connect-webhooks-github/

### a) Composability Unit

The **processor** is the atomic composable unit. A processor takes a message batch, transforms it, and returns a message batch. Processors are YAML blocks:

```yaml
pipeline:
  processors:
    - mapping: 'root.user = this.user_id.uppercase()'
    - http:
        url: https://api.example.com/enrich
        verb: POST
    - catch:
        - log:
            message: "Enrichment failed: ${!error()}"
```

Higher-level composable units:
- **Input** — source with optional child processors
- **Output** — sink with optional child processors
- **Buffer** — between input and pipeline; decouples rates
- **Resource** — named, reusable component referenced by label

### b) Dependency Declaration

Dependencies are declared via **label references**:

```yaml
processor_resources:
  - label: my_enricher
    http:
      url: https://api.example.com
      verb: POST

pipeline:
  processors:
    - resource: my_enricher   # reference by label
    - catch:
        - resource: my_enricher  # reuse in fallback
```

The label contract: 3–128 characters, `[A-Za-z0-9_-]` only, case-sensitive. No circular reference detection — a resource referencing itself would loop.

**Bloblang** (the mapping DSL) is the within-processor language for transformations. It has its own composition: named Bloblang functions can be reused within the mapping context.

### c) Schema Contracts

- **Field validation at startup**: unknown fields (`yourl` instead of `url`) produce a lint error and halt execution — this is the primary contract enforcement mechanism
- **Label naming rules** enforced at parse time
- **No message schema enforcement** natively — Redpanda Connect is schema-agnostic at the processor level; it passes raw bytes or structured data through
- Schema Registry integration available for Avro/Protobuf topics when connected to Redpanda/Kafka — enforced at the broker boundary, not within Connect's processor chain
- Templates provide parameterized composition for cases where resources are insufficient

### d) What Breaks Composition

| Failure Mode | Mechanism |
|---|---|
| Missing or duplicate label | Resource reference fails at startup or execution |
| Field typo in YAML | Lint error; halts execution |
| Config parse error during hot-reload | Previous config persists; no partial update |
| `shutdown_timeout` exceeded | In-flight messages are dropped |
| Circular resource references | Infinite loop; no cycle detection |
| Schema mismatch at broker boundary | Fails at Serde layer if Schema Registry enforced, otherwise passes corrupt data silently |
| Bloblang expression errors | Surface at message processing time, not at startup |

---

## 6. DuckDB

### Sources
- SQL-only extensions blog: https://duckdb.org/2024/09/27/sql-only-extensions
- DuckDB macros reusable patterns: https://medium.com/@komalbaparmar007/duckdb-macros-reusable-sql-patterns-for-analyst-velocity-c799f136bcfe
- DuckDB macros with TypeScript: https://medium.com/@npavfan2facts/smarter-sql-duckdb-typescript-macros-8026c8f0e2e6
- Orchestra DuckDB macros: https://www.getorchestra.io/guides/duckdb-sqlconcepts-create-macro
- Top 10 extensions: https://www.definite.app/blog/top-10-duckdb-extensions
- Community extensions: https://duckdb.org/community_extensions/extensions/webmacro

### a) Composability Unit

**SQL Macro** — the primary composable unit. Two forms:
- **Scalar macro**: `(params...) -> expression` — parameterized expression, inlined at call site
- **Table macro**: `(params...) TABLE -> query` — returns a relation

```sql
-- Scalar macro
CREATE OR REPLACE MACRO safe_divide(a, b) AS
  CASE WHEN b = 0 THEN NULL ELSE a / b END;

-- Table macro
CREATE OR REPLACE MACRO recent_orders(days) AS TABLE
  SELECT * FROM orders WHERE created_at > now() - INTERVAL (days) DAY;
```

**Views** are the second composability unit — named, reusable query definitions that compose like tables.

**Extensions** (community, v1.1+) are the package-level unit — a `.duckdb_extension` file that may contain only SQL macros (SQL-only extensions) or C++ code.

Composition hierarchy observed in the `pivot_table` extension:
```
quoting helpers (sq, dq, nq)
    → list variants
        → string builders
            → query() execution
                → table macro output
```

### b) Dependency Declaration

**No explicit dependency declaration system.** Dependencies between macros are implicit — a macro calling another macro fails at runtime if the callee is missing. The extension packaging model makes co-deployment the implicit contract.

`query()` and `query_table()` functions execute SQL strings dynamically — this enables functional composition but defers all validation to execution time.

The `webmacro` community extension allows loading macros from a GitHub Gist URL, enabling remote dependency resolution (informal, no lockfile).

### c) Schema Contracts

- **`columns_parameter_enum`** — a `DUCKDB_TYPE` enum that must be created before calling certain table macros. This is the most explicit contract mechanism:
  ```sql
  DROP TYPE IF EXISTS columns_parameter_enum;
  CREATE TYPE columns_parameter_enum AS ENUM ('col_a', 'col_b', 'col_c');
  SELECT * FROM pivot_table(...);
  ```
- **Quoting helpers** (`nq`/`sq`/`dq`) handle SQL injection — columns/table names injected via `query()` are sanitized but existence is only validated at execution
- **Type checking**: DuckDB's type system catches type mismatches within a query; cross-macro type contracts are not enforced
- **Runtime-only**: no compile-time or definition-time schema validation between composed macros

### d) What Breaks Composition

| Failure Mode | Mechanism |
|---|---|
| Missing ENUM pre-creation | `pivot_table` and similar macros fail; the 3-statement pattern cannot be inlined |
| Single-statement macro constraint | Multi-statement logic cannot be expressed in a scalar macro; requires table macros or workarounds |
| `query()` limited to SELECT | Cannot compose DDL/DML operations within macros; no write composition |
| Runtime-only validation | Wrong column/table names in `query()` fail at execution, not definition |
| No dependency lockfile | Remote macro loading (webmacro) has no version pinning |
| Extension load order | Extensions that depend on each other must be loaded in correct order; no automatic resolution |
| Schema drift in views | Views referencing renamed columns fail silently until queried |

---

## Cross-Cutting Analysis

### Composability Spectrum

```
Strongest contracts ←————————————————————————→ Weakest contracts
Flink TypeInfo    dbt contracts    Dagster checks    DuckDB macros
(compile-like)    (dbt test pass)  (post-hoc YAML)   (runtime only)
```

### Dependency Declaration Patterns

| Pattern | Systems | Trade-off |
|---------|---------|-----------|
| Named reference (string) | Airflow XCom, Redpanda Connect labels | Flexible; breaks silently on rename |
| Macro expansion (compile-time) | dbt `ref()` | Catches broken refs at `dbt compile`; no cross-project type safety |
| Python return value passing | Prefect, Dagster (function args) | Type-checkable with Pydantic; tied to process boundary |
| Operator chaining (builder) | Kafka Streams, Flink, Spark | Type-safe within language; no schema evolution story |
| Implicit co-deployment | DuckDB extensions | Zero boilerplate; zero safety |

### What Universally Breaks Composition

1. **Implicit state between units** — side effects that aren't modeled as outputs (Airflow tasks writing to shared DB, Spark UDFs with mutable closures)
2. **String-keyed dependencies** — any system where the dependency name is an unvalidated string (XCom `task_id`, Redpanda Connect labels, DuckDB macro names) breaks on rename with no static analysis
3. **Post-hoc schema enforcement** — Dagster checks run after materialization; DuckDB validates at query time; Spark infers at execution. All leave a window where bad data propagates before detection.
4. **Stateful operator ordering constraints** — Flink savepoint incompatibility, Kafka Streams repartition topology changes, Airflow TaskGroup ordering bugs all stem from the same root: stateful composition requires ordering contracts that the framework doesn't always enforce
5. **Lack of version pinning on composable units** — dbt packages have `package-lock.yml`; DuckDB macros from webmacro have none; Redpanda Connect resources have none

### dbt Semantic Layer: Composition Model Summary

The semantic layer introduces a **two-level composition contract**:

Level 1 — **Physical**: `semantic_model.model = ref('dbt_model')` — the semantic model is grounded in a dbt model, inheriting the model layer's DAG guarantees.

Level 2 — **Semantic**: `metric.type_params.measure = 'measure_name'` — metrics compose over measures by name. The entity type system (`primary`/`foreign`) is the join contract — MetricFlow derives all SQL join paths from entity declarations, refusing to execute arbitrary join logic.

The composability guarantee: **if you query metric M with dimension D, MetricFlow guarantees D's entity chain connects to M's semantic model without fan-out or chasm joins** — or it raises an error. This is stronger than typical BI tool composability because it is structurally enforced, not convention-based.

The breach points: entity type misconfiguration, missing measure references, and the dbt Cloud commercial gate for the MetricFlow Server and Semantic Layer API.

---

## Open Questions

1. How does dbt Mesh (cross-project `ref()`) enforce contracts at project boundaries — is column-level contract enforcement available cross-project or only within a single project?
2. Flink's unaligned checkpointing behavior under I/O-bound state backends — is there a configuration that gives exactly-once semantics without alignment cost?
3. DuckDB community extension registry — is there a planned lockfile or version pinning mechanism for SQL-only extensions loaded from remote URLs?
4. Prefect cross-deployment flow dependencies — the August 2025 feature request (`@wait_for_deployments`) — what is the current workaround pattern and its failure modes?
5. Kafka Streams `groupBy` repartition — is there a pattern to avoid internal topic proliferation in topologies with many key-changing operations?
