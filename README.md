# ForgeLine Context Server (MCP)

**Pre-Generation Policy Context Injection for AI Coding Tools**

An MCP (Model Context Protocol) server that enriches AI coding prompts with governance context — security rules, architecture boundaries, naming conventions, existing patterns, and data sensitivity constraints — before code is generated.

## What It Does

When a developer uses an AI coding tool (Cursor, Claude Code, Copilot, Windsurf), this MCP server intercepts the interaction and provides:

- **Security constraints** based on the module being edited (OWASP rules, input validation requirements)
- **Existing code patterns** from the repository (functions to reuse, not reinvent)
- **Architecture boundaries** (which layers can call which other layers)
- **Data sensitivity rules** (PII/PHI/PCI field handling requirements)
- **Naming conventions** and coding standards for the team
- **Approved dependency lists** (prevent phantom package hallucinations)

## Architecture

```
Developer IDE (Cursor / Claude Code / VS Code)
        │
        ▼
┌─────────────────────────────┐
│  ForgeLine MCP Server       │
│  (this repository)          │
│                             │
│  Tools:                     │
│  ├─ get_context_for_file    │
│  ├─ get_security_rules      │
│  ├─ get_architecture_map    │
│  ├─ get_existing_patterns   │
│  ├─ check_dependency        │
│  └─ get_data_sensitivity    │
│                             │
│  Resources:                 │
│  ├─ policies://active       │
│  ├─ architecture://graph    │
│  └─ standards://style-guide │
│                             │
│  Prompts:                   │
│  └─ code_with_governance    │
└──────────┬──────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
  Neo4j KG    PostgreSQL
  (patterns)  (policies)
```

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/forgeline-context-server.git
cd forgeline-context-server

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e ".[dev]"

# Copy env template
cp .env.example .env
# Edit .env with your database credentials

# Run the server (stdio mode for IDE integration)
uv run python -m src.server

# Run in HTTP mode (for remote/team deployment)
uv run python -m src.server --transport http --port 8000
```

## IDE Integration

### Cursor
Add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "forgeline": {
      "command": "uv",
      "args": ["--directory", "/path/to/forgeline-context-server", "run", "python", "-m", "src.server"]
    }
  }
}
```

### Claude Desktop
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "forgeline": {
      "command": "uv",
      "args": ["--directory", "/path/to/forgeline-context-server", "run", "python", "-m", "src.server"]
    }
  }
}
```

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Run with MCP Inspector (debugging)
uv run mcp dev src/server.py

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/
```

## License

Proprietary — ForgeLine Inc.
