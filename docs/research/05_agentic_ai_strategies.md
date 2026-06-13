# Agentic AI Embedding Strategies for PgAppForge

_Research date: 2026-06-13_

---

## 1. Overview

AI is bifurcating into two distinct capability tiers:
1. **Builder AI** — AI that generates applications, code, and configurations
2. **End-user AI** — AI embedded in running applications (NL queries, document processing, predictions)

PgAppForge must address both. This document covers the competitive landscape, key frameworks, and an implementation roadmap for embedding agentic AI throughout the platform.

---

## 2. Builder AI Landscape

### 2.1 AI App Generation Tools

| Tool | Company | Funding | ARR | Model | Notes |
|---|---|---|---|---|---|
| Lovable | Lovable AB | $330M raised | $200M ARR | GPT-4o + Claude | Full-stack app from description |
| v0.dev | Vercel | (Vercel $2.5B) | N/A | Custom | React/Next.js UI from description |
| Bolt.new | StackBlitz | (StackBlitz) | N/A | Claude Sonnet | Full-stack app in browser sandbox |
| Cursor | Anysphere | $900M raised | $500M ARR | GPT-4o, Claude, Gemini | 18% IDE market share |
| GitHub Copilot | Microsoft | ($10B R&D) | est. $300M ARR | GPT-4o | 42% market share, 20M users |
| Retool AI AppGen | Retool | $165M raised | $120M ARR | GPT-4 | Enterprise governance layer |
| Tooljet AI | Tooljet | $23M raised | N/A | GPT-4 | PRD → full app |

**Critical finding**: Lovable's $200M ARR in under 2 years, built on "generate a full-stack app from a description," proves the market for NL-to-application generation. PgAppForge must have an equivalent: "describe your ERP module → working Python CRUD app."

### 2.2 IDE AI Market Share (2025)
- GitHub Copilot: 42% (20M users)
- Cursor: 18%
- Tabnine: 8%
- Amazon CodeWhisperer: 7%
- Others: 25%

**Implication**: 60% of professional developers use an AI coding assistant. PgAppForge must be the preferred framework these tools generate code into. This requires:
- Published prompt templates ("how to create a PgAppForge model")
- CLAUDE.md / `.cursorrules` reference files for PgAppForge projects
- Context7 library registration for PgAppForge documentation

---

## 3. End-User AI Landscape

### 3.1 NL Analytics / Text-to-SQL

| Tool | Company | Pricing | Approach |
|---|---|---|---|
| ThoughtSpot Spotter | ThoughtSpot | $25/user/month | NL → SpotIQ analytics |
| Power BI Copilot | Microsoft | Included in Power BI Premium | NL → DAX measures |
| Tableau AI | Salesforce | Add-on | NL → Tableau vizzes |
| Metabase | Metabase | $500/month | NL → SQL (Metabase AI) |
| Cube.dev | Cube | $500/month | Semantic layer + NL |
| Vanna.ai | OSS | Free/cloud | Fine-tuned NL → SQL |
| Text2SQL.ai | Commercial | $99/month | GPT → SQL |

**PgAppForge target**: Inline NL-to-SQL on any ModelView list view. "Show me invoices from Kenya customers in Q1" → SQL → filtered list. This is a P1 feature (high user demand, moderate implementation complexity).

### 3.2 Document Intelligence

| Use case | Current cost | AI-processed cost | Reduction |
|---|---|---|---|
| Invoice processing | $12.88 per invoice | $2.36 per invoice | 82% |
| Expense receipt OCR | $5.00 per receipt | $0.80 per receipt | 84% |
| Contract extraction | $250 per contract | $15 per contract | 94% |
| KYC document verification | $10 per document | $1.50 per document | 85% |

Source: McKinsey AI ROI study, 2024.

**PgAppForge opportunity**: The Africa fintech plugins have heavy document processing needs (KYC, loan applications, payslips, tax certificates). Building AI document intelligence into the plugin layer creates immediate ROI for SACCO and digital lending customers.

### 3.3 Predictive Features

| Feature | Vertical | Value |
|---|---|---|
| Credit scoring from mobile money history | Digital lending | Replace bureau scoring (no bureau in many Africa markets) |
| Churn prediction for SACCO members | SACCO | Identify at-risk members before exit |
| Demand forecasting | Inventory | Reduce stockouts by 30-40% |
| Payroll anomaly detection | HR | Flag fraud, data entry errors |
| Cash flow prediction | Finance | 30/60/90 day forecast |

---

## 4. Agent Frameworks

### 4.1 LangGraph (LangChain)

**Status**: GA as of 2024, 400+ companies in production (Replit, Uber, LinkedIn)
**License**: MIT
**Key capabilities**:
- Stateful multi-agent graphs with cycle support
- Checkpointing: persist and resume long-running agent workflows
- Human-in-the-loop (HITL): pause graph for human approval before continuing
- Streaming: token-by-token output from any node
- Tool calling: native function calling + custom tools
- Memory: built-in short-term (thread) and long-term (LangGraph Store)

**PgAppForge integration pattern**:
```python
# Example: PgAppForge LangGraph agent for invoice processing
from langgraph.graph import StateGraph, END
from pgappforge.ai import PgAppForgeTools

graph = StateGraph(InvoiceState)
graph.add_node("extract_fields", extract_invoice_fields)
graph.add_node("validate_vendor", validate_against_db)
graph.add_node("human_review", human_approval_node)  # HITL
graph.add_node("post_to_gl", post_to_general_ledger)

graph.add_conditional_edges(
	"validate_vendor",
	lambda s: "human_review" if s.confidence < 0.85 else "post_to_gl"
)
```

### 4.2 CrewAI

**Status**: Production, $18M raised, 60% of Fortune 500 piloting
**License**: MIT
**Key capabilities**:
- Role-based agent teams (assign specific roles, goals, backstories)
- Sequential and parallel task execution
- Memory: short-term, long-term, entity, contextual
- Tool library: 30+ pre-built tools

**PgAppForge integration pattern**: CrewAI is better for structured workflows with defined roles (e.g., "Accountant Agent reviews GL, Compliance Agent flags tax issues, CFO Agent approves"). LangGraph is better for dynamic, branching workflows.

### 4.3 AutoGen + Semantic Kernel (Microsoft)

**Status**: Merged ecosystem (Microsoft unified AutoGen + SK in 2025)
**License**: MIT
**Key capabilities**:
- Multi-agent conversation orchestration
- Kernel plugins: expose functions as AI-callable tools
- Memory: vector store integration (Azure AI Search, Chroma, Qdrant)
- Best for: Microsoft-centric enterprises with Azure OpenAI

**PgAppForge integration**: Lower priority given Africa's preference for on-premise LLMs. AutoGen's HITL patterns are worth studying.

### 4.4 PydanticAI

**Status**: GA 2025, built by Pydantic team
**License**: MIT
**Key capabilities**:
- Type-safe agent framework built on Pydantic v2
- Structured output validation (agents return typed Pydantic models)
- Dependency injection for tools
- Async-first
- Works with OpenAI, Anthropic, Groq, Ollama

**PgAppForge relevance**: PydanticAI is the most natural fit for PgAppForge's existing Pydantic v2 stack. Agent responses are typed, validated, and directly usable as SQLAlchemy model inputs.

```python
from pydantic_ai import Agent
from pgappforge.plugins.fintech.models import LoanApplication

agent = Agent(
	'anthropic:claude-sonnet-4-6',
	result_type=LoanApplication,
	system_prompt="Extract loan application details from the uploaded document."
)

result = await agent.run(document_text)
# result.data is a typed LoanApplication Pydantic model
```

---

## 5. On-Premise LLM Infrastructure

### 5.1 Production: vLLM

| Metric | vLLM | Naive Transformers |
|---|---|---|
| Requests per second | 35× higher | baseline |
| Memory efficiency | PagedAttention | naive KV cache |
| Deployment | Docker, k8s | manual |
| GPU support | NVIDIA, AMD, Intel | NVIDIA |
| Models | Llama 3, Mistral, Qwen, Phi-3 | same |

**Recommended for**: Africa fintech deployments where data residency is mandatory (CBK, CBN, Bank of Uganda regulations prohibit PII leaving country).

```bash
# Docker deployment
docker run --runtime nvidia --gpus all \
	-v ~/.cache/huggingface:/root/.cache/huggingface \
	-p 8000:8000 \
	vllm/vllm-openai:latest \
	--model meta-llama/Meta-Llama-3-8B-Instruct \
	--api-key token-abc123
```

### 5.2 Development: Ollama

| Use case | Model | VRAM required |
|---|---|---|
| Code generation | CodeQwen 7B | 6GB |
| Text extraction | Mistral 7B | 5GB |
| SQL generation | SQLCoder 7B | 6GB |
| Document QA | Llama 3 8B | 6GB |
| Multilingual (Swahili, Hausa) | Aya 35B | 20GB |

```python
# PgAppForge Ollama integration
import ollama

async def generate_sql(question: str, schema: str) -> str:
	response = await ollama.AsyncClient().chat(
		model='sqlcoder:7b',
		messages=[
			{'role': 'system', 'content': f'Schema: {schema}'},
			{'role': 'user', 'content': question}
		]
	)
	return response['message']['content']
```

### 5.3 LLM Selection Matrix for PgAppForge

| Task | Cloud option | On-premise option | Latency target |
|---|---|---|---|
| AI app generation | Claude Sonnet 4.6 | Llama 3 70B (vLLM) | < 30s |
| NL to SQL | GPT-4o | SQLCoder 7B (Ollama) | < 3s |
| Document OCR/extraction | Claude 3.5 Sonnet | Mistral 7B | < 5s |
| Code completion | GitHub Copilot | CodeQwen 7B | < 1s |
| Long-term memory | Anthropic Claude | on-prem Llama 3 8B | N/A (async) |
| Swahili/French | GPT-4o (multilingual) | Aya 35B | < 5s |

---

## 6. Model Context Protocol (MCP)

### What is MCP?
MCP (Model Context Protocol, Anthropic 2024) is the emerging standard for exposing application functionality as AI-callable tools. When an AI agent (Claude, GPT, Gemini) encounters an MCP server, it can discover and call tools without custom integration code.

### Current MCP adoption
- Directus: shipped native MCP server Q4 2025 (permission-aware)
- Supabase: MCP server for database operations
- GitHub: MCP server for repo operations
- Linear: MCP server for project management
- PowerApps/Dataverse: MCP endpoint (Microsoft, 2025)

### Why PgAppForge needs an MCP server

Without MCP:
```
User → Claude → "write code to query PgAppForge" → Python code → run code → result
```

With MCP:
```
User → Claude (with PgAppForge MCP) → call pgappforge:list_invoices → result
```

The user gets answers from their PgAppForge data without writing a single line of code. This is the AI-native interface for the 2.0M-creator market (Bubble's market).

### PgAppForge MCP Server Design

```python
# pgappforge/mcp/server.py
from mcp.server import Server
from mcp.types import Tool, TextContent
from pgappforge.security import check_permission

app = Server("pgappforge")

@app.list_tools()
async def list_tools() -> list[Tool]:
	return [
		Tool(
			name="query_model",
			description="Query any PgAppForge model with filters",
			inputSchema={
				"type": "object",
				"properties": {
					"model": {"type": "string"},
					"filters": {"type": "object"},
					"limit": {"type": "integer", "default": 100}
				}
			}
		),
		Tool(name="create_record", ...),
		Tool(name="run_report", ...),
		Tool(name="trigger_workflow", ...),
	]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
	# Permission check before any operation
	if not await check_permission(current_user, name, arguments):
		raise PermissionError(f"Access denied: {name}")
	# ... execute tool
```

**Critical design constraint**: MCP tools must respect PgAppForge's existing RBAC. A user who cannot see invoices in the UI must not be able to see them via the MCP server. Directus solved this — PgAppForge must match it.

---

## 7. Long-Term Agent Memory

### The problem
AI agents in enterprise applications need to remember:
- User preferences ("always show amounts in KES, not USD")
- Organizational context ("our fiscal year runs July–June")
- Past decisions ("we rejected vendor X for quality reasons")
- Learned patterns ("finance team reviews invoices on Mondays")

### Memory architectures

| Type | Technology | Use case |
|---|---|---|
| Short-term (thread) | In-memory dict / Redis | Single conversation context |
| Long-term (episodic) | PostgreSQL + pgvector | Past interactions, decisions |
| Semantic | pgvector similarity search | "Find similar past invoices" |
| Entity | PostgreSQL structured store | Facts about customers, vendors, products |
| Procedural | SQLAlchemy models | Workflows, approval rules |

### PgAppForge implementation

```python
# pgappforge/ai/memory.py
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column
from pgappforge.base import db

class AgentMemory(db.Model):
	__tablename__ = 'pgaf_agent_memory'

	id: Mapped[str] = mapped_column(primary_key=True)
	user_id: Mapped[str] = mapped_column(index=True)
	memory_type: Mapped[str]  # episodic | semantic | entity
	content: Mapped[str]
	embedding: Mapped[list[float]] = mapped_column(Vector(1536))
	created_at: Mapped[datetime]
	expires_at: Mapped[datetime | None]

	@classmethod
	async def search_similar(cls, query_embedding: list[float], user_id: str, k: int = 5):
		return db.session.execute(
			select(cls)
			.where(cls.user_id == user_id)
			.order_by(cls.embedding.cosine_distance(query_embedding))
			.limit(k)
		).scalars().all()
```

---

## 8. PgAppForge AI Feature Roadmap

### P0 — Must ship to remain competitive

| Feature | Description | Implementation | Effort |
|---|---|---|---|
| NL-to-SQL on list views | Text box on list view → filtered results | Vanna.ai or SQLCoder 7B + prompt template | 2 weeks |
| AI audit log | Log all AI actions (query, generation, extraction) with user, timestamp, input, output | SQLAlchemy event + `pgaf_ai_audit` table | 1 week |
| RBAC on AI features | AI features respect existing FAB roles | Wrap every AI call in `check_permission()` | 1 week |

### P1 — Ship to differentiate

| Feature | Description | Implementation | Effort |
|---|---|---|---|
| pgvector RAG | Semantic search over documents, contracts, policies | pgvector + Ollama embeddings | 3 weeks |
| Document extraction | Extract structured data from invoices, receipts, ID cards | Claude 3.5 Sonnet or Mistral 7B | 2 weeks |
| AI app generation | "Describe your module" → SQLAlchemy models + views | Claude Sonnet + Jinja templates | 4 weeks |
| Agent tool-calling | Expose PgAppForge CRUD as MCP tools | MCP server implementation | 2 weeks |
| HITL for agent actions | Pause agent workflow for human approval | LangGraph interrupt + FAB notification | 3 weeks |

### P2 — Future differentiation

| Feature | Description | Effort |
|---|---|---|
| Predictive columns | ML predictions inline in list/detail views | 6 weeks |
| Churn prediction | SACCO member retention risk score | 4 weeks |
| Credit scoring | Mobile money history → credit risk | 8 weeks |
| Swahili/French NL | Multilingual NL-to-SQL using Aya 35B | 2 weeks |
| Fine-tuned domain LLM | Train on Africa ERP data | 3 months |

---

## 9. AI Governance Requirements

### Why AI governance is non-negotiable for enterprise

Enterprise AI buyers require:
1. **Audit trail**: Every AI action logged with user, timestamp, model used, input, output
2. **Usage controls**: Per-role AI feature access (not all users can use AI)
3. **Cost controls**: Token usage budgets per user/department
4. **Model governance**: Ability to swap models without application changes
5. **HITL**: Human approval before AI executes consequential actions

ServiceNow's AI Control Tower and Microsoft's Copilot Studio are the enterprise benchmarks. PgAppForge needs an equivalent "AI Control Panel" view.

### Minimum viable AI governance

```python
# pgappforge/ai/governance.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class AIAuditEntry:
	id: str
	user_id: str
	feature: str           # 'nl_query' | 'doc_extract' | 'app_gen' | 'agent_action'
	model: str             # 'claude-sonnet-4-6' | 'llama-3-8b' | 'sqlcoder-7b'
	input_tokens: int
	output_tokens: int
	cost_usd: float
	input_preview: str     # first 500 chars of input
	output_preview: str    # first 500 chars of output
	duration_ms: int
	success: bool
	error: str | None
	created_at: datetime

async def ai_action(
	feature: str,
	user_id: str,
	func,
	*args,
	require_approval: bool = False,
	**kwargs
):
	"""Wrapper for all AI actions — enforces governance."""
	if not await check_ai_permission(user_id, feature):
		raise PermissionError(f"AI feature '{feature}' not enabled for this role")

	if require_approval:
		await request_human_approval(user_id, feature, args, kwargs)
		# blocks until approved or rejected

	start = datetime.utcnow()
	try:
		result = await func(*args, **kwargs)
		await log_ai_action(feature, user_id, result, success=True)
		return result
	except Exception as e:
		await log_ai_action(feature, user_id, None, success=False, error=str(e))
		raise
```

---

## 10. Africa-Specific AI Considerations

### Multilingual support
- Swahili (150M speakers): most important for East Africa
- Hausa (100M speakers): critical for North/West Nigeria
- French (sub-Saharan): Senegal, Côte d'Ivoire, Cameroon, DRC
- Amharic (40M speakers): Ethiopia

Recommended model: **Aya 35B** (Cohere, multilingual, MIT license) for on-premise multilingual NL-to-SQL.

### Data residency
- CBK (Kenya): financial data must remain in Kenya
- CBN (Nigeria): BVN data must remain in Nigeria
- Bank of Uganda: customer financial data must remain in Uganda
- Recommendation: **vLLM on-premise** for regulated financial data. Cloud LLMs for non-PII tasks.

### Connectivity constraints
- Average Africa broadband: 10-20 Mbps (vs 100+ Mbps global average)
- Frequent connectivity drops in rural areas
- LLM inference must work offline or on slow connections
- Recommendation: **Ollama local inference** on the application server for connectivity-constrained deployments

### Cost constraints
- OpenAI GPT-4o: $15/1M input tokens
- Anthropic Claude Sonnet: $3/1M input tokens
- Llama 3 8B (self-hosted): $0.05/1M tokens (compute only)
- For Africa pricing sensitivity: default to local inference, offer cloud as premium tier

---

## 11. Sources

- Lovable ARR: TechCrunch, April 2025
- GitHub Copilot users: Microsoft Build 2025 keynote
- Cursor market share: Andreessen Horowitz Developer Tools Survey 2025
- LangGraph production: LangChain blog, "LangGraph in Production" 2025
- CrewAI Fortune 500: CrewAI press release, Q1 2025
- MCP protocol: modelcontextprotocol.io (Anthropic, 2024)
- Directus MCP: directus.io/blog/mcp-server, December 2025
- vLLM performance: vllm.readthedocs.io/benchmarks
- Document intelligence costs: McKinsey "The Economic Potential of Generative AI" 2024
- Africa data residency: CBK Data Protection Act 2019, CBN Circular on Cloud Computing 2021
- Aya model: Cohere, cohere.com/aya
