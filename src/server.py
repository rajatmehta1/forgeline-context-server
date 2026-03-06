"""
ForgeLine Pre-Generation Context Server (MCP)

The MCP server that AI coding tools connect to for governance-aware context.
Exposes tools, resources, and prompts that inject security rules, architecture
boundaries, existing patterns, and data sensitivity into AI code generation.

Run:
    # stdio mode (for IDE integration — Cursor, Claude Desktop)
    python -m src.server

    # HTTP mode (for remote/team deployment)
    python -m src.server --transport streamable-http --port 8000
"""

from __future__ import annotations

import sys
import structlog
from fastmcp import FastMCP

from src.config.settings import settings
from src.services.knowledge_graph import kg_service
from src.services.policies import policy_service
from src.services.context_builder import context_builder

# ─── Logging Setup ───
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),  # CRITICAL: stderr for MCP stdio
)
logger = structlog.get_logger(__name__)

# ─── Initialize FastMCP Server ───
mcp = FastMCP(
    "ForgeLine Context Server",
    instructions="""
    You are connected to the ForgeLine governance context server.
    Use the available tools to get security rules, architecture constraints,
    existing code patterns, and data sensitivity rules BEFORE generating code.
    Always call `get_context_for_file` first to understand what policies apply
    to the file you're working on.
    """,
)


# ═══════════════════════════════════════════════════════════
# TOOLS — Functions the AI assistant can call
# ═══════════════════════════════════════════════════════════


@mcp.tool
async def get_context_for_file(
    file_path: str,
    repo_name: str = "",
    profile_id: str = "default",
) -> str:
    """
    Get the COMPLETE governance context for a file you're about to edit or create.

    Call this FIRST before generating any code. It returns:
    - Security rules that apply to this module
    - Architecture constraints (what layers this code can/cannot call)
    - Existing functions and classes to REUSE (don't reinvent the wheel)
    - Data sensitivity rules (PII/PHI/PCI handling requirements)
    - Testing requirements
    - Approved packages

    Args:
        file_path: The path of the file being edited (e.g., "src/services/payment.ts")
        repo_name: Repository name (optional, for multi-repo setups)
        profile_id: Policy profile to use (default: "default")

    Returns:
        Formatted context text to guide code generation
    """
    try:
        context = await context_builder.build_context(
            file_path=file_path,
            repo_name=repo_name,
            profile_id=profile_id,
        )
        prompt_text = context.to_prompt_context()

        header = (
            f"# ForgeLine Governance Context\n"
            f"**File:** `{file_path}` | **Layer:** {context.layer} | **Language:** {context.language}\n"
            f"---\n"
            f"Follow ALL rules below when generating code for this file.\n\n"
        )
        return header + prompt_text

    except Exception as e:
        logger.error("Failed to build context", file_path=file_path, error=str(e))
        return f"⚠️ ForgeLine context unavailable: {e}. Proceed with standard best practices."


@mcp.tool
async def get_security_rules(
    layer: str = "service",
    profile_id: str = "default",
) -> str:
    """
    Get the security rules that apply to a specific architecture layer.

    Use this when you need JUST the security constraints (not full context).

    Args:
        layer: The architecture layer (controller, service, repository, middleware, util, model)
        profile_id: Policy profile to use

    Returns:
        Formatted security rules with examples and anti-patterns
    """
    from src.models import PolicyCategory

    rules = policy_service.get_rules_for_layer(layer, profile_id, [PolicyCategory.SECURITY])

    if not rules:
        return f"No specific security rules for layer '{layer}'."

    sections = [f"# Security Rules for '{layer}' layer\n"]
    for rule in rules:
        sections.append(f"## [{rule.severity.value.upper()}] {rule.name}")
        sections.append(rule.constraint_text)
        if rule.examples:
            sections.append(f"✅ Good: `{rule.examples[0]}`")
        if rule.anti_patterns:
            sections.append(f"❌ Bad: `{rule.anti_patterns[0]}`")
        sections.append("")

    return "\n".join(sections)


@mcp.tool
async def get_existing_patterns(
    file_path: str,
    repo_name: str = "",
) -> str:
    """
    Get existing functions and classes near a file that you should REUSE.

    Call this to avoid generating duplicate code. If a function already exists
    for what you need, import and use it instead of creating a new one.

    Args:
        file_path: The file path you're working on
        repo_name: Repository name

    Returns:
        List of existing reusable functions and classes with signatures
    """
    try:
        functions = await kg_service.get_functions_in_module(file_path, repo_name)
        classes = await kg_service.get_classes_in_module(file_path, repo_name)

        if not functions and not classes:
            return f"No existing patterns found near '{file_path}'. You may create new ones."

        sections = ["# Existing Code Patterns — REUSE these\n"]

        if functions:
            sections.append("## Functions")
            for fn in functions:
                sections.append(f"- `{fn.signature}` → {fn.file_path}")
                if fn.description:
                    sections.append(f"  Purpose: {fn.description}")

        if classes:
            sections.append("\n## Classes / Interfaces")
            for cls in classes:
                sections.append(f"- `{cls.name}` ({cls.kind}) → {cls.file_path}")
                if cls.methods:
                    sections.append(f"  Methods: {', '.join(cls.methods[:10])}")

        return "\n".join(sections)

    except Exception as e:
        logger.error("Pattern query failed", error=str(e))
        return f"⚠️ Pattern lookup unavailable: {e}"


@mcp.tool
async def get_architecture_map(
    repo_name: str = "",
) -> str:
    """
    Get the architecture boundary rules — which layers can call which.

    Use this to understand the project's architecture before generating
    cross-module code or creating new service/repository files.

    Args:
        repo_name: Repository name

    Returns:
        Architecture boundary definitions with allowed/forbidden dependencies
    """
    try:
        boundaries = await kg_service.get_architecture_boundaries(repo_name)

        sections = ["# Architecture Boundaries\n"]
        sections.append("Follow these rules for all imports and function calls:\n")

        for b in boundaries:
            sections.append(f"## Layer: {b.layer_name}")
            sections.append(f"Path pattern: `{b.path_pattern}`")
            sections.append(f"✅ CAN import from: {', '.join(b.allowed_dependencies)}")
            if b.forbidden_dependencies:
                sections.append(f"❌ MUST NOT import from: {', '.join(b.forbidden_dependencies)}")
            sections.append("")

        return "\n".join(sections)

    except Exception as e:
        logger.error("Architecture query failed", error=str(e))
        return f"⚠️ Architecture map unavailable: {e}"


@mcp.tool
async def check_dependency(
    package_name: str,
) -> str:
    """
    Check if a package is approved, exists, and is safe to use.

    Call this BEFORE adding any new import or dependency. Catches:
    - Phantom/hallucinated packages (don't exist on registry)
    - Unapproved packages (not on the team's allowlist)
    - Vulnerable packages (known CVEs)
    - Low-trust packages (recently created, few downloads)

    Args:
        package_name: The package name to check (e.g., "lodash", "pandas", "express")

    Returns:
        Trust assessment with score and recommendation
    """
    try:
        info = await kg_service.check_dependency(package_name)

        trust_score = info.get("trust_score", 0)
        is_approved = info.get("is_approved", False)
        is_phantom = info.get("is_phantom")
        cve_count = info.get("cve_count", 0)

        sections = [f"# Dependency Check: `{package_name}`\n"]

        if is_phantom is True:
            sections.append("🚨 **PHANTOM PACKAGE DETECTED** — This package does NOT exist on the registry.")
            sections.append("The AI likely hallucinated this name. Do NOT use it.")
            sections.append("Search for a real alternative package instead.")
            return "\n".join(sections)

        if is_phantom is None:
            sections.append("⚠️ **UNKNOWN PACKAGE** — Not found in ForgeLine's Knowledge Graph.")
            sections.append("Verify it exists on the package registry before using.")

        sections.append(f"Trust Score: {trust_score}/100")
        sections.append(f"Approved: {'✅ Yes' if is_approved else '❌ No'}")

        if cve_count and cve_count > 0:
            sections.append(f"⚠️ Known CVEs: {cve_count}")

        if trust_score < 20:
            sections.append("\n🚨 **LOW TRUST** — Do not use this package without explicit team approval.")
        elif trust_score < 60:
            sections.append("\n⚠️ **MODERATE TRUST** — Review this package before adding as a dependency.")
        elif not is_approved:
            sections.append("\n⚠️ Package exists but is not on the approved list. Request approval first.")
        else:
            sections.append("\n✅ Package is approved and trusted. Safe to use.")

        return "\n".join(sections)

    except Exception as e:
        logger.error("Dependency check failed", error=str(e))
        return f"⚠️ Dependency check unavailable: {e}. Verify the package manually."


@mcp.tool
async def get_data_sensitivity(
    file_path: str,
    repo_name: str = "",
) -> str:
    """
    Get data sensitivity rules for fields accessible from this module.

    Shows which data fields are PII, PHI, PCI, or FINANCIAL, and what
    handling constraints apply (encryption, logging, storage, transmission).

    Args:
        file_path: The file path you're working on
        repo_name: Repository name

    Returns:
        Data sensitivity classifications and handling rules
    """
    try:
        fields = await kg_service.get_sensitive_fields_for_module(file_path, repo_name)

        if not fields:
            return f"No sensitive data fields found near '{file_path}'."

        sections = ["# Data Sensitivity Rules\n"]
        sections.append("Handle these fields according to their classification:\n")

        for field in fields:
            tag = field.sensitivity.value
            sections.append(f"## `{field.field_name}` [{tag}]")
            for constraint in field.constraints:
                sections.append(f"  - {constraint}")
            sections.append("")

        return "\n".join(sections)

    except Exception as e:
        logger.error("Sensitivity query failed", error=str(e))
        return f"⚠️ Data sensitivity info unavailable: {e}"


# ═══════════════════════════════════════════════════════════
# RESOURCES — Data the AI can read for reference
# ═══════════════════════════════════════════════════════════


@mcp.resource("forgeline://policies/active")
async def get_active_policies() -> str:
    """Get all active governance policies as a reference document."""
    profile = policy_service.get_profile("default")
    sections = [f"# ForgeLine Active Policies ({profile.name})\n"]
    sections.append(f"Total rules: {len(profile.rules)}\n")

    for category in ["security", "architecture", "style", "testing", "performance"]:
        cat_rules = [r for r in profile.rules if r.category.value == category]
        if cat_rules:
            sections.append(f"\n## {category.upper()} ({len(cat_rules)} rules)")
            for rule in cat_rules:
                sections.append(f"\n### [{rule.severity.value}] {rule.rule_id}: {rule.name}")
                sections.append(rule.constraint_text)

    return "\n".join(sections)


@mcp.resource("forgeline://architecture/graph")
async def get_architecture_graph() -> str:
    """Get the full architecture boundary graph."""
    try:
        boundaries = await kg_service.get_architecture_boundaries()
        sections = ["# Architecture Boundary Graph\n"]
        for b in boundaries:
            sections.append(f"**{b.layer_name}** ({b.path_pattern})")
            sections.append(f"  → Can call: {', '.join(b.allowed_dependencies)}")
            if b.forbidden_dependencies:
                sections.append(f"  ✗ Cannot call: {', '.join(b.forbidden_dependencies)}")
        return "\n".join(sections)
    except Exception:
        return "Architecture graph unavailable. Using default layered architecture rules."


@mcp.resource("forgeline://standards/style-guide")
async def get_style_guide() -> str:
    """Get the team's coding standards and style guide."""
    from src.models import PolicyCategory

    rules = policy_service.get_rules_for_layer("service", "default", [PolicyCategory.STYLE])
    sections = ["# ForgeLine Coding Standards\n"]
    for rule in rules:
        sections.append(f"## {rule.name}")
        sections.append(rule.constraint_text)
        sections.append("")
    return "\n".join(sections)


# ═══════════════════════════════════════════════════════════
# PROMPTS — Reusable prompt templates
# ═══════════════════════════════════════════════════════════


@mcp.prompt
def code_with_governance(
    task: str,
    file_path: str,
    language: str = "typescript",
) -> str:
    """
    Generate a governance-aware coding prompt.

    Use this prompt template when you want to ensure the AI follows
    all ForgeLine policies for a specific coding task.

    Args:
        task: What you want the AI to build (e.g., "user registration API")
        file_path: Where the code will live
        language: Programming language
    """
    return f"""You are writing {language} code for the file `{file_path}`.

TASK: {task}

BEFORE writing any code, you MUST:
1. Call `get_context_for_file("{file_path}")` to get governance rules
2. Call `get_existing_patterns("{file_path}")` to find reusable code
3. Call `check_dependency("<package>")` for any new packages you want to use

RULES:
- Follow ALL security rules from the context
- REUSE existing functions and classes — do NOT duplicate
- Follow the architecture boundaries — respect layer constraints
- Handle sensitive data according to classification rules
- Write tests as specified in testing requirements
- Use ONLY approved packages

Now generate the code for: {task}
"""


# ═══════════════════════════════════════════════════════════
# LIFECYCLE — Server startup and shutdown
# ═══════════════════════════════════════════════════════════


@mcp.on_event("startup")
async def on_startup() -> None:
    """Initialize services on server start."""
    logger.info("ForgeLine Context Server starting...")
    try:
        await kg_service.connect()
        logger.info("Knowledge Graph connected")
    except Exception as e:
        logger.warning(
            "Knowledge Graph unavailable — running with policies only",
            error=str(e),
        )
    logger.info("ForgeLine Context Server ready")


@mcp.on_event("shutdown")
async def on_shutdown() -> None:
    """Cleanup on server shutdown."""
    await kg_service.disconnect()
    logger.info("ForgeLine Context Server stopped")
