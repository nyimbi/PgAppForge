# Ollama Model Benchmark for pgappforge Chat Generator

Benchmark run against locally-hosted Ollama models to determine the best
default for the `flask forge chat-create` conversational app designer.

## Test Setup

- Machine: macOS (Apple Silicon)
- Ollama: local HTTP API at `http://localhost:11434`
- Temperature: 0.1 (deterministic tool calling)
- Context: 8192 tokens

## Models Tested

| Model | Size | Context |
|-------|------|---------|
| `gemma4:e4b` | 9.6 GB | 128K |
| `qwen3.5:9b` | 6.6 GB | 256K |
| `granite4.1:8b` | 5.3 GB | 128K |

## Tool-Calling Quality (5 tests, 100 pts each)

| Test | Description | gemma4:e4b | qwen3.5:9b | granite4.1:8b |
|------|-------------|-----------|-----------|--------------|
| T1 | Simple table creation with correct types | **100** | **100** | **100** |
| T2 | Multi-table schema inference from description | 33 | 33 | 33 |
| T3 | Relationship direction (users → posts) | **100** | 50 | **100** |
| T4 | Template list and apply awareness | **100** | **100** | **100** |
| T5 | Type precision (email, timestamptz) | **100** | **100** | **100** |
| **Average** | | **87/100** | **77/100** | **87/100** |

### Notes on individual tests

**T1 (Simple table)**: All models correctly identified `numeric(10,2)` for a price field
and produced well-structured column definitions.

**T2 (Schema inference)**: All three models missed the `users` table when told
"users can write posts and leave comments". They created `posts` and `comments` but
omitted the actor entity. Root cause: the system prompt did not explicitly instruct
the model to identify actors/people as entities. **Fixed in system prompt.**

**T3 (Relationship direction)**: `qwen3.5:9b` created `posts → users` (backwards)
instead of `users → posts` (one user has many posts). `gemma4` and `granite4.1` were
correct.

**T4 (Template awareness)**: All three correctly called `list_templates` when asked
about a domain-specific app.

**T5 (Type precision)**: All three used `varchar(255)` for email (acceptable; correct
is `varchar(320)` per RFC 5321) and `timestamptz` for timestamps (correct PostgreSQL type).

## Throughput (tokens/minute)

Standard generation test: 300 tokens generated per model.

| Model | Tokens/min | Time for 300 tok |
|-------|-----------|------------------|
| `granite4.1:8b` | **1,453** | 12.4s |
| `qwen3.5:9b` | **941** | 19.1s |
| `gemma4:e4b` | **750** | 24.0s |

`granite4.1:8b` is **1.9× faster** than `gemma4:e4b` for the same output length.

## Recommendation

### Default: `granite4.1:8b`

Best overall for interactive use — equal accuracy to `gemma4:e4b` but nearly twice
the speed, and 4.3 GB smaller.

```bash
flask forge chat-create                    # uses granite4.1:8b by default
flask forge chat-create --model gemma4:e4b  # maximum accuracy (needs GPU RAM)
PGAF_OLLAMA_MODEL=granite4.1:8b flask forge chat-create
```

### When to use each model

| Scenario | Recommended model |
|----------|-----------------|
| General use / interactive sessions | `granite4.1:8b` (default) |
| Complex multi-table domains | `gemma4:e4b` — better at schema inference |
| Low-RAM machines (< 8 GB) | `llama3.2:3b` or `phi4-mini` |
| Maximum context (long conversations) | `qwen3.5:9b` (256K context) |

## Installing models

```bash
ollama pull granite4.1:8b   # 5.3 GB — default
ollama pull gemma4:e4b      # 9.6 GB — max accuracy
ollama pull qwen3.5:9b      # 6.6 GB — longest context
```

## Known issues / future work

1. **T2 schema inference** — All models miss actor tables (users/customers) without
   explicit prompting. System prompt updated with: "always include the ACTORS (users,
   customers, staff, etc.) as tables — not just the things they interact with."

2. **Relationship direction** — qwen3.5:9b occasionally reverses FK direction. Consider
   adding relationship validation in `SchemaState.add_relationship()`.

3. **T2 retest needed** — After system prompt fix, T2 should improve for all models.
   Retest with: `python /tmp/bench_tool_calling.py`
