# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the server (stdio mode — for IDE integration)
uv run python -m src.server

# Run in HTTP mode (remote/team deployment)
uv run python -m src.server --transport streamable-http --port 8000

# Run tests (no Neo4j required)
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_core.py::TestPolicyService::test_security_rules_exist -v

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/

# Start Neo4j locally via Docker
docker-compose up -d

# Seed Neo4j with sample data (requires running Neo4j)
python scripts/seed_kg.py

# Debug with MCP Inspector (uses fastmcp CLI, not mcp CLI)
uv run fastmcp dev inspector src/server.py
```

## Architecture

This is an MCP (Model Context Protocol) server built with **FastMCP** that injects governance context into AI coding tools before code generation. It sits between the IDE (Cursor, Claude Code, Copilot) and the AI, providing security rules, architecture boundaries, existing patterns, and data sensitivity constraints.

### Data Flow

```
IDE calls MCP tool
  -> server.py (tool handlers, FastMCP)
  -> src/services/context_builder.py (orchestrates assembly)
      -> src/services/knowledge_graph.py (queries Neo4j for patterns, boundaries, sensitivity)
      -> src/services/policies.py (resolves policy rules for the file's layer)
  -> Returns formatted prompt context to the IDE
```

### Key Architectural Concepts

**Two data backends:**
- **Neo4j** — stores the code knowledge graph: modules, functions, classes, architecture boundaries, sensitive data fields, dependency metadata. All queries go through `KnowledgeGraphService` in `src/services/knowledge_graph.py`.
- **PostgreSQL** — referenced in config but not yet used in services; planned for policies, users, and audit logs.

**Policy resolution:** `PolicyService` (`src/services/policies.py`) ships with hardcoded default rules (SEC-001 through SEC-006, ARCH-001, ARCH-002, STYLE-001, STYLE-002, TEST-001, PERF-001, PERF-002). Custom profiles can be loaded from YAML. Rules are filtered by `layer` (controller/service/repository/model/middleware/util/test).

**Layer inference:** If a file isn't in Neo4j, `KnowledgeGraphService._infer_layer_from_path()` infers the layer from directory name patterns (e.g., "controllers/" → controller, "repositories/" → repository).

**Graceful degradation:** KG unavailability is non-fatal. All tool handlers catch exceptions and return warning messages, so the server remains useful with policies alone (no Neo4j required for tests or policy-only use). KG queries use tenacity retry (max 3 attempts, exponential backoff 1–10s) before surfacing errors.

**Caching:** `TTLCache` (cachetools) is used in both services. Cache TTL and size are configurable via env vars.

### MCP Surface (what IDEs call)

**Tools** (callable by AI):
- `get_context_for_file` — primary tool; returns full governance context for a file
- `get_security_rules` — security rules for a given layer
- `get_existing_patterns` — functions/classes near a file (from Neo4j)
- `get_architecture_map` — layer boundary rules
- `check_dependency` — package trust/approval check
- `get_data_sensitivity` — PII/PHI/PCI field constraints for a module

**Resources** (readable reference docs):
- `forgeline://policies/active` — all active policy rules
- `forgeline://architecture/graph` — full architecture boundary graph
- `forgeline://standards/style-guide` — coding standards

**Prompts**: `code_with_governance` — template prompt instructing the AI to call tools before generating code.

### Neo4j Graph Schema

Nodes: `Repository`, `Module`, `Function`, `Class`, `Parameter`, `DataField`, `Dependency`, `ArchitectureRule`

Key relationships: `(Module)-[:DEFINES]->(Function|Class)`, `(Repository)-[:HAS_ARCHITECTURE]->(ArchitectureRule)`, `(Repository)-[:DEPENDS_ON]->(Dependency)`

## Environment Setup

Copy `.env.example` to `.env`. Key vars:
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `DATABASE_URL` — PostgreSQL (asyncpg format)
- `TRANSPORT` — `stdio` (default, for IDE), `streamable-http`, or `sse`
- `LOG_LEVEL` — all logging goes to stderr (required for MCP stdio compatibility)

## Testing Notes

Tests in `tests/test_core.py` do not require Neo4j. They test: policy rule loading, layer inference from file paths, `FileContext.to_prompt_context()` output, and language detection. New tests for KG-dependent features should mock `KnowledgeGraphService`.