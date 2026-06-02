# AI Agents Plugin — SPEC

## Domain
`analytics` — sub-plugin of the Analytics domain.

## Purpose
AI agent registry with four operational types, conversation lifecycle management,
append-only message log, and a human-in-the-loop action approval workflow for
agents with side-effecting capabilities.

---

## Entities

### AIAgent
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| agent_name | VARCHAR(200) | Unique per tenant |
| agent_type | VARCHAR(20) | ASSISTANT \| ANALYST \| EXECUTOR \| ORCHESTRATOR |
| model_id | VARCHAR(100) | e.g. claude-sonnet-4-5, gpt-4o |
| system_prompt | TEXT | Agent instruction prompt |
| tools_config | JSONB | `[{name, description, parameters}]` Anthropic format |
| guardrails | JSONB | `{"max_tokens":4096,"forbidden_topics":[],...}` |
| is_active | BOOLEAN | |
| created_by | INT FK ab_user | |

Agent types:
- **ASSISTANT** — conversational Q&A, no side-effects
- **ANALYST** — data analysis, read-only tool calls
- **EXECUTOR** — can write/update records; all actions require human approval
- **ORCHESTRATOR** — coordinates sub-agents; delegates work

### AgentConversation
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID NOT NULL | |
| agent_id | UUID FK AIAgent | CASCADE |
| user_id | INT FK ab_user nullable | |
| session_id | VARCHAR(200) | |
| started_at | TIMESTAMPTZ | DEFAULT NOW() |
| ended_at | TIMESTAMPTZ | NULL = open |
| message_count | INT | Denormalised; incremented on append |
| outcome | TEXT | Summary of what was achieved |
| rating | INT | 1–5 user rating; NULL if not rated |

### AgentMessage
Append-only. NEVER update or delete.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| conversation_id | UUID FK AgentConversation | CASCADE |
| role | VARCHAR(20) | USER \| ASSISTANT \| TOOL |
| content | TEXT | Message text |
| tool_calls | JSONB nullable | Anthropic tool_use blocks |
| tool_results | JSONB nullable | tool_result blocks |
| tokens_used | INT | Total tokens this turn |
| model_used | VARCHAR(100) | Actual serving model |
| latency_ms | INT | Wall-clock ms to first token |
| sent_at | TIMESTAMPTZ | DEFAULT NOW() |

### AgentAction
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| conversation_id | UUID FK AgentConversation | CASCADE |
| action_type | VARCHAR(100) | e.g. update_record, send_email, run_query |
| target_entity_type | VARCHAR(100) nullable | |
| target_entity_id | VARCHAR(64) nullable | |
| parameters | JSONB | Action input |
| status | VARCHAR(20) | PROPOSED \| APPROVED \| EXECUTED \| REJECTED \| FAILED |
| approved_by | INT FK ab_user nullable | |
| executed_at | TIMESTAMPTZ | |
| result | JSONB nullable | Action output or error |

Status lifecycle: PROPOSED → (APPROVED → EXECUTED \| FAILED) \| REJECTED

---

## Business Rules
1. EXECUTOR agents must have non-empty guardrails (blocked by Rules Engine).
2. Conversations cannot be started with inactive agents.
3. AgentAction must be APPROVED before transitioning to EXECUTED.
4. AgentMessage rows are immutable — correction = new SYSTEM message.
5. Conversations with 200+ messages trigger a Rules Engine warning.
6. `rating` is clamped to 1–5 in the service layer.
7. `end_conversation()` is idempotent — already-ended conversations are returned unchanged.

---

## Key Service Methods

### AIAgentService
| Method | Signature | Description |
|---|---|---|
| start_conversation | `(agent_id, session, user_id, session_id)` | Creates conversation |
| end_conversation | `(conversation_id, session, outcome, rating)` | Closes conversation |
| append_message | `(conversation_id, role, content, session, ...)` | Appends immutable message |
| propose_action | `(conversation_id, action_type, parameters, session, ...)` | Records PROPOSED action |
| approve_action | `(action_id, approver_id, session)` | PROPOSED→APPROVED |
| reject_action | `(action_id, session)` | PROPOSED→REJECTED |
| execute_action | `(action_id, executor_fn, session)` | APPROVED→EXECUTED or FAILED |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /analytics/ai/agents/ | Agent registry (HTML) |
| POST | /analytics/ai/agents/ | Create agent (JSON) |
| GET | /analytics/ai/conversations/ | Recent conversations (HTML) |
| POST | /analytics/ai/conversations/ | Start conversation (JSON) |
| POST | /analytics/ai/conversations/`<id>`/message | Append message (JSON) |
| POST | /analytics/ai/conversations/`<id>`/end | End conversation (JSON) |
| GET | /analytics/ai/actions/pending | Pending approval queue (HTML) |
| POST | /analytics/ai/actions/`<id>`/approve | Approve action (JSON) |
| POST | /analytics/ai/actions/`<id>`/reject | Reject action (JSON) |
| GET | /analytics/ai/reports/agent_usage | Agent usage report (HTML) |
| GET | /analytics/ai/reports/token_spend | Token spend by model (JSON) |

---

## Events Emitted
- `analytics.ai.conversation_started`
- `analytics.ai.conversation_ended`
- `analytics.ai.message_sent`
- `analytics.ai.action_proposed`
- `analytics.ai.action_approved`
- `analytics.ai.action_rejected`
- `analytics.ai.action_executed`
- `analytics.ai.action_failed`

## Events Consumed
- `analytics.anomaly.detected` — optionally trigger investigator agent
- `analytics.kpi.status_changed` — optionally trigger analyst agent

---

## Rules Engine Rulesets (4)
1. `analytics.ai.block_executor_without_guardrails`
2. `analytics.ai.require_approval_for_executor_actions`
3. `analytics.ai.max_message_count`
4. `analytics.ai.block_inactive_agent_conversation`

---

## ReportForge Templates (2)
1. **Agent Usage Report** — conversations, messages, avg rating per agent (HTML)
2. **Token Spend Report** — total tokens and avg latency by model (JSON for charting)
