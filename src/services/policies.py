"""
ForgeLine Context Server — Policy Service

Loads governance policies from local YAML files or the ForgeLine API.
Resolves which policies apply to a given file path and module layer.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from cachetools import TTLCache

import structlog

from src.config.settings import settings
from src.models import PolicyCategory, PolicyProfile, PolicyRule, Severity

logger = structlog.get_logger(__name__)

# ─── Default Policy Templates ───
# These ship with ForgeLine and can be customized per-repo

DEFAULT_SECURITY_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="SEC-001",
        name="Parameterized Queries Required",
        category=PolicyCategory.SECURITY,
        severity=Severity.BLOCK,
        description="All database queries must use parameterized queries, never string concatenation.",
        constraint_text="NEVER build SQL queries with string concatenation or f-strings. ALWAYS use parameterized queries with your ORM or database library's parameter binding.",
        examples=["db.execute('SELECT * FROM users WHERE id = ?', (user_id,))"],
        anti_patterns=["f\"SELECT * FROM users WHERE id = {user_id}\""],
    ),
    PolicyRule(
        rule_id="SEC-002",
        name="No eval() or exec()",
        category=PolicyCategory.SECURITY,
        severity=Severity.BLOCK,
        description="Never use eval(), exec(), or Function() constructor on user-provided input.",
        constraint_text="NEVER use eval(), exec(), Function(), or similar dynamic code execution. Use a safe expression parser instead (e.g., ast.literal_eval for Python, math.js for JS).",
        examples=["import ast; result = ast.literal_eval(user_input)"],
        anti_patterns=["eval(user_input)", "exec(code_string)"],
    ),
    PolicyRule(
        rule_id="SEC-003",
        name="Input Validation Required",
        category=PolicyCategory.SECURITY,
        severity=Severity.BLOCK,
        description="All user inputs must be validated and sanitized before use.",
        constraint_text="ALWAYS validate and sanitize ALL user inputs. Validate type, length, format, and range. Sanitize against XSS (escape HTML), SQL injection, and path traversal. Use a validation library (Pydantic, Zod, Joi).",
        examples=["from pydantic import BaseModel, EmailStr, constr"],
        anti_patterns=["request.body directly used without validation"],
    ),
    PolicyRule(
        rule_id="SEC-004",
        name="Secure Password Handling",
        category=PolicyCategory.SECURITY,
        severity=Severity.BLOCK,
        description="Passwords must be hashed with bcrypt/argon2, never stored or compared in plaintext.",
        constraint_text="ALWAYS hash passwords with bcrypt (salt rounds >= 12) or argon2. NEVER store plaintext passwords. NEVER compare passwords with == (use constant-time comparison). NEVER include passwords in logs or API responses.",
        examples=["hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))"],
        anti_patterns=["if password == stored_password:", "log.info(f'User {email} password: {pwd}')"],
    ),
    PolicyRule(
        rule_id="SEC-005",
        name="No Hardcoded Secrets",
        category=PolicyCategory.SECURITY,
        severity=Severity.BLOCK,
        description="API keys, tokens, passwords, and secrets must come from environment variables.",
        constraint_text="NEVER hardcode API keys, tokens, passwords, database URLs, or any secrets in source code. ALWAYS load secrets from environment variables or a secrets manager (e.g., os.environ, dotenv, AWS Secrets Manager).",
        examples=["api_key = os.environ['STRIPE_API_KEY']"],
        anti_patterns=["API_KEY = 'sk_live_abc123...'", "password = 'admin123'"],
    ),
    PolicyRule(
        rule_id="SEC-006",
        name="Structured Error Responses",
        category=PolicyCategory.SECURITY,
        severity=Severity.WARN,
        description="Never expose raw stack traces or internal details in error responses.",
        constraint_text="NEVER return raw exception messages or stack traces in API responses. ALWAYS use structured error responses with safe error codes and user-friendly messages. Log the full error server-side only.",
        examples=["return {'error': 'Invalid request', 'code': 'VALIDATION_ERROR'}"],
        anti_patterns=["return {'error': str(exception)}", "return traceback.format_exc()"],
    ),
]

DEFAULT_ARCHITECTURE_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="ARCH-001",
        name="Layer Boundary Enforcement",
        category=PolicyCategory.ARCHITECTURE,
        severity=Severity.WARN,
        description="Controllers must not directly access repositories; use the service layer.",
        constraint_text="Follow the layered architecture: Controllers → Services → Repositories. Controllers should NEVER import or call repository/database functions directly. Always go through a service class.",
        examples=["# In controller: result = await user_service.get_user(user_id)"],
        anti_patterns=["# In controller: result = await user_repo.find_by_id(user_id)"],
    ),
    PolicyRule(
        rule_id="ARCH-002",
        name="No Circular Dependencies",
        category=PolicyCategory.ARCHITECTURE,
        severity=Severity.BLOCK,
        description="Modules must not have circular import dependencies.",
        constraint_text="NEVER create circular imports. If module A imports module B, module B must NOT import module A. Extract shared types to a common/types module instead.",
    ),
]

DEFAULT_STYLE_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="STYLE-001",
        name="Consistent Naming Conventions",
        category=PolicyCategory.STYLE,
        severity=Severity.SUGGEST,
        description="Follow the project's naming conventions consistently.",
        constraint_text="Use camelCase for variables and functions in TypeScript/JavaScript. Use snake_case for variables and functions in Python. Use PascalCase for classes in all languages. Use UPPER_SNAKE_CASE for constants.",
    ),
    PolicyRule(
        rule_id="STYLE-002",
        name="Async/Await Consistency",
        category=PolicyCategory.STYLE,
        severity=Severity.SUGGEST,
        description="Use async/await consistently, not a mix of callbacks and promises.",
        constraint_text="Use async/await for all asynchronous operations. Do NOT mix callbacks, raw Promises with .then(), and async/await in the same module. Choose async/await as the standard pattern.",
    ),
]

DEFAULT_TESTING_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="TEST-001",
        name="Test Coverage for New Endpoints",
        category=PolicyCategory.TESTING,
        severity=Severity.WARN,
        description="All new API endpoints must have at least one happy-path and one error-path test.",
        constraint_text="For every new API endpoint or public function, write: (1) at least one test for the successful case, (2) at least one test for an error/edge case (invalid input, missing auth, not found), (3) use the project's test framework (pytest/Jest).",
    ),
]

DEFAULT_PERFORMANCE_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="PERF-001",
        name="No N+1 Query Patterns",
        category=PolicyCategory.PERFORMANCE,
        severity=Severity.WARN,
        description="Do not make database or API calls inside loops.",
        constraint_text="NEVER put a database query or HTTP API call inside a for/while loop. Use batch queries, JOINs, or bulk fetch operations instead. Example: instead of looping db.get_user(id) for each ID, use db.get_users(ids) once.",
        examples=["users = await user_repo.find_by_ids(user_ids)  # single batch query"],
        anti_patterns=["for uid in user_ids: user = await user_repo.find_by_id(uid)  # N+1!"],
    ),
    PolicyRule(
        rule_id="PERF-002",
        name="Paginate Large Result Sets",
        category=PolicyCategory.PERFORMANCE,
        severity=Severity.WARN,
        description="Never load entire database tables into memory.",
        constraint_text="ALWAYS use LIMIT/OFFSET or cursor-based pagination for database queries. NEVER use SELECT * without a WHERE clause or LIMIT on large tables. For APIs returning lists, support pagination parameters.",
    ),
]


class PolicyService:
    """Manages policy loading, caching, and resolution."""

    def __init__(self) -> None:
        self._profiles: dict[str, PolicyProfile] = {}
        self._cache: TTLCache = TTLCache(maxsize=100, ttl=settings.cache_ttl_seconds)
        self._default_profile = PolicyProfile(
            profile_id="default",
            name="ForgeLine Default Profile",
            rules=(
                DEFAULT_SECURITY_RULES
                + DEFAULT_ARCHITECTURE_RULES
                + DEFAULT_STYLE_RULES
                + DEFAULT_TESTING_RULES
                + DEFAULT_PERFORMANCE_RULES
            ),
        )

    async def load_policies_from_file(self, path: str) -> None:
        """Load custom policy profiles from a YAML file."""
        policy_path = Path(path)
        if not policy_path.exists():
            logger.warning("Policy file not found, using defaults", path=path)
            return

        with open(policy_path) as f:
            data = yaml.safe_load(f)

        if not data or "profiles" not in data:
            logger.warning("No profiles found in policy file", path=path)
            return

        for profile_data in data["profiles"]:
            rules = [PolicyRule(**r) for r in profile_data.get("rules", [])]
            profile = PolicyProfile(
                profile_id=profile_data["profile_id"],
                name=profile_data["name"],
                rules=rules,
            )
            self._profiles[profile.profile_id] = profile
            logger.info("Loaded policy profile", profile=profile.name, rules=len(rules))

    def get_profile(self, profile_id: str = "default") -> PolicyProfile:
        """Get a policy profile by ID, falling back to default."""
        return self._profiles.get(profile_id, self._default_profile)

    def get_rules_for_layer(
        self,
        layer: str,
        profile_id: str = "default",
        categories: list[PolicyCategory] | None = None,
    ) -> list[PolicyRule]:
        """Get all policy rules applicable to a given architecture layer."""
        profile = self.get_profile(profile_id)
        rules = profile.rules

        if categories:
            rules = [r for r in rules if r.category in categories]

        # Layer-specific filtering
        if layer == "controller":
            # Controllers get all security + architecture rules
            pass
        elif layer == "repository":
            # Repos don't need architecture boundary rules about controllers
            rules = [r for r in rules if r.rule_id != "ARCH-001"]
        elif layer == "test":
            # Tests get testing rules only
            rules = [r for r in rules if r.category == PolicyCategory.TESTING]

        return rules

    def get_constraint_texts(
        self, layer: str, category: PolicyCategory, profile_id: str = "default"
    ) -> list[str]:
        """Get human-readable constraint texts for prompt injection."""
        rules = self.get_rules_for_layer(layer, profile_id, [category])
        return [r.constraint_text for r in rules]


# Singleton instance
policy_service = PolicyService()
