"""
ForgeLine Context Server — Domain Models

Pydantic models for policies, patterns, context responses, and data sensitivity.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# ─── Enums ───


class Severity(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    SUGGEST = "suggest"


class SensitivityTag(str, Enum):
    PII = "PII"
    PHI = "PHI"
    PCI = "PCI"
    FINANCIAL = "FINANCIAL"
    CREDENTIAL = "CREDENTIAL"
    NONE = "NONE"


class PolicyCategory(str, Enum):
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    TESTING = "testing"
    PERFORMANCE = "performance"
    DATA_SENSITIVITY = "data_sensitivity"
    DEPENDENCY = "dependency"


# ─── Policy Models ───


class PolicyRule(BaseModel):
    """A single governance policy rule."""

    rule_id: str
    name: str
    category: PolicyCategory
    severity: Severity
    description: str
    constraint_text: str = Field(
        description="Human-readable constraint to inject into AI prompt context"
    )
    examples: list[str] = Field(default_factory=list, description="Code examples of correct usage")
    anti_patterns: list[str] = Field(default_factory=list, description="Patterns to avoid")


class PolicyProfile(BaseModel):
    """A collection of policy rules assigned to a repository or module."""

    profile_id: str
    name: str
    rules: list[PolicyRule]


# ─── Code Pattern Models ───


class FunctionPattern(BaseModel):
    """An existing function in the codebase that the AI should know about."""

    name: str
    signature: str
    file_path: str
    module: str
    description: str = ""
    is_exported: bool = True
    return_type: str = ""


class ClassPattern(BaseModel):
    """An existing class/interface the AI should reuse."""

    name: str
    file_path: str
    module: str
    kind: str = "class"  # class | interface | enum
    methods: list[str] = Field(default_factory=list)
    description: str = ""


class DependencyInfo(BaseModel):
    """Information about an approved or flagged dependency."""

    package_name: str
    version: str = ""
    registry: str = "npm"  # npm | pypi | maven
    trust_score: int = Field(default=100, ge=0, le=100)
    is_approved: bool = True
    is_phantom: bool = False
    notes: str = ""


# ─── Architecture Models ───


class LayerBoundary(BaseModel):
    """Defines which module layers can call which other layers."""

    layer_name: str
    path_pattern: str = Field(description="Glob pattern, e.g. 'src/controllers/**'")
    allowed_dependencies: list[str] = Field(
        description="Layer names this layer is allowed to import from"
    )
    forbidden_dependencies: list[str] = Field(default_factory=list)


class ArchitectureMap(BaseModel):
    """The repository's architecture boundary definition."""

    repo_name: str
    layers: list[LayerBoundary]
    description: str = ""


# ─── Data Sensitivity Models ───


class SensitiveField(BaseModel):
    """A data field with sensitivity classification."""

    field_name: str
    sensitivity: SensitivityTag
    constraints: list[str] = Field(
        default_factory=list,
        description="e.g. 'Must be encrypted at rest', 'Never log this field'",
    )
    module_path: str = ""


# ─── Context Response Models ───


class FileContext(BaseModel):
    """The complete context payload injected for a specific file location."""

    file_path: str
    language: str = ""
    layer: str = ""

    # Policies applicable to this location
    security_rules: list[str] = Field(default_factory=list)
    architecture_constraints: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)
    testing_requirements: list[str] = Field(default_factory=list)

    # Existing patterns to reuse
    existing_functions: list[FunctionPattern] = Field(default_factory=list)
    existing_classes: list[ClassPattern] = Field(default_factory=list)

    # Data sensitivity
    sensitive_fields: list[SensitiveField] = Field(default_factory=list)

    # Dependencies
    approved_packages: list[str] = Field(default_factory=list)
    forbidden_packages: list[str] = Field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Compile this context into a text block suitable for prompt injection."""
        sections: list[str] = []

        if self.security_rules:
            sections.append("## Security Requirements")
            for rule in self.security_rules:
                sections.append(f"- {rule}")

        if self.architecture_constraints:
            sections.append("\n## Architecture Constraints")
            for c in self.architecture_constraints:
                sections.append(f"- {c}")

        if self.style_rules:
            sections.append("\n## Coding Standards")
            for s in self.style_rules:
                sections.append(f"- {s}")

        if self.existing_functions:
            sections.append("\n## Existing Functions (REUSE these, do NOT recreate)")
            for fn in self.existing_functions:
                sections.append(f"- `{fn.signature}` in {fn.file_path}")
                if fn.description:
                    sections.append(f"  Purpose: {fn.description}")

        if self.existing_classes:
            sections.append("\n## Existing Classes/Interfaces (REUSE these)")
            for cls in self.existing_classes:
                sections.append(f"- `{cls.name}` ({cls.kind}) in {cls.file_path}")
                if cls.methods:
                    sections.append(f"  Methods: {', '.join(cls.methods)}")

        if self.sensitive_fields:
            sections.append("\n## Data Sensitivity Rules")
            for sf in self.sensitive_fields:
                constraints_text = "; ".join(sf.constraints) if sf.constraints else "Handle with care"
                sections.append(f"- `{sf.field_name}` [{sf.sensitivity.value}]: {constraints_text}")

        if self.testing_requirements:
            sections.append("\n## Testing Requirements")
            for t in self.testing_requirements:
                sections.append(f"- {t}")

        if self.approved_packages:
            sections.append("\n## Approved Packages (use ONLY these for new dependencies)")
            sections.append(", ".join(self.approved_packages))

        if self.forbidden_packages:
            sections.append("\n## Forbidden Packages (NEVER use these)")
            sections.append(", ".join(self.forbidden_packages))

        return "\n".join(sections)
