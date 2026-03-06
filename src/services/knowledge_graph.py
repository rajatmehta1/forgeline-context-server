"""
ForgeLine Context Server — Knowledge Graph Service

Queries the Neo4j Knowledge Graph for existing code patterns,
architecture boundaries, data sensitivity, and dependency information.
"""

from __future__ import annotations

import structlog
from cachetools import TTLCache
from neo4j import AsyncDriver, AsyncGraphDatabase
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import settings
from src.models import (
    ClassPattern,
    FunctionPattern,
    LayerBoundary,
    SensitiveField,
    SensitivityTag,
)

logger = structlog.get_logger(__name__)


class KnowledgeGraphService:
    """Service for querying the Neo4j Knowledge Graph."""

    def __init__(self) -> None:
        self._driver: AsyncDriver | None = None
        self._pattern_cache: TTLCache = TTLCache(
            maxsize=settings.pattern_cache_max_size,
            ttl=settings.cache_ttl_seconds,
        )

    async def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        logger.info("Connected to Neo4j", uri=settings.neo4j_uri)

    async def disconnect(self) -> None:
        """Close Neo4j connection."""
        if self._driver:
            await self._driver.close()
            logger.info("Disconnected from Neo4j")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _run_query(self, query: str, params: dict | None = None) -> list[dict]:
        """Execute a Cypher query with retry logic."""
        if not self._driver:
            await self.connect()
        assert self._driver is not None

        async with self._driver.session(database=settings.neo4j_database) as session:
            result = await session.run(query, params or {})
            records = await result.data()
            return records

    # ─── Pattern Queries ───

    async def get_functions_in_module(
        self, file_path: str, repo_name: str = ""
    ) -> list[FunctionPattern]:
        """Get all functions defined in the same module and its siblings."""

        # Extract directory from file path for sibling lookup
        parts = file_path.rsplit("/", 1)
        dir_pattern = parts[0] + "/%" if len(parts) > 1 else "%"

        cache_key = f"functions:{repo_name}:{dir_pattern}"
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]

        query = """
        MATCH (m:Module)-[:DEFINES]->(f:Function)
        WHERE m.file_path STARTS WITH $dir_prefix
          AND f.is_exported = true
        RETURN f.name AS name,
               f.signature AS signature,
               m.file_path AS file_path,
               m.module_name AS module,
               f.return_type AS return_type,
               f.description AS description
        ORDER BY m.file_path, f.name
        LIMIT 50
        """
        dir_prefix = parts[0] + "/" if len(parts) > 1 else ""
        records = await self._run_query(query, {"dir_prefix": dir_prefix})

        patterns = [
            FunctionPattern(
                name=r["name"],
                signature=r.get("signature", r["name"]),
                file_path=r["file_path"],
                module=r.get("module", ""),
                return_type=r.get("return_type", ""),
                description=r.get("description", ""),
            )
            for r in records
        ]

        self._pattern_cache[cache_key] = patterns
        return patterns

    async def get_classes_in_module(
        self, file_path: str, repo_name: str = ""
    ) -> list[ClassPattern]:
        """Get all classes/interfaces near the target file."""

        parts = file_path.rsplit("/", 1)
        dir_prefix = parts[0] + "/" if len(parts) > 1 else ""

        cache_key = f"classes:{repo_name}:{dir_prefix}"
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]

        query = """
        MATCH (m:Module)-[:DEFINES]->(c:Class)
        WHERE m.file_path STARTS WITH $dir_prefix
          AND c.is_exported = true
        OPTIONAL MATCH (c)-[:DEFINES]->(method:Function)
        WITH c, m, collect(method.name) AS methods
        RETURN c.name AS name,
               m.file_path AS file_path,
               m.module_name AS module,
               c.kind AS kind,
               methods,
               c.description AS description
        ORDER BY m.file_path, c.name
        LIMIT 30
        """
        records = await self._run_query(query, {"dir_prefix": dir_prefix})

        classes = [
            ClassPattern(
                name=r["name"],
                file_path=r["file_path"],
                module=r.get("module", ""),
                kind=r.get("kind", "class"),
                methods=r.get("methods", []),
                description=r.get("description", ""),
            )
            for r in records
        ]

        self._pattern_cache[cache_key] = classes
        return classes

    # ─── Architecture Queries ───

    async def get_layer_for_file(self, file_path: str) -> str:
        """Determine which architecture layer a file belongs to."""
        query = """
        MATCH (m:Module)
        WHERE m.file_path = $file_path
        RETURN m.layer AS layer
        """
        records = await self._run_query(query, {"file_path": file_path})
        if records:
            return records[0].get("layer", "unknown")
        return self._infer_layer_from_path(file_path)

    @staticmethod
    def _infer_layer_from_path(file_path: str) -> str:
        """Fallback: infer layer from common directory patterns."""
        path_lower = file_path.lower()
        layer_patterns = {
            "controller": ["controller", "route", "endpoint", "handler", "api"],
            "service": ["service", "usecase", "use_case", "business"],
            "repository": ["repo", "repository", "dal", "dao", "database", "db"],
            "model": ["model", "entity", "schema", "dto"],
            "middleware": ["middleware", "guard", "interceptor", "filter"],
            "util": ["util", "helper", "lib", "common", "shared"],
            "config": ["config", "setting"],
            "test": ["test", "spec", "__test__"],
        }
        for layer, patterns in layer_patterns.items():
            if any(p in path_lower for p in patterns):
                return layer
        return "unknown"

    async def get_architecture_boundaries(self, repo_name: str = "") -> list[LayerBoundary]:
        """Get the architecture boundary rules for a repository."""

        cache_key = f"arch:{repo_name}"
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]

        query = """
        MATCH (r:Repository {name: $repo_name})-[:HAS_ARCHITECTURE]->(a:ArchitectureRule)
        RETURN a.layer_name AS layer_name,
               a.path_pattern AS path_pattern,
               a.allowed_dependencies AS allowed_dependencies,
               a.forbidden_dependencies AS forbidden_dependencies
        """
        records = await self._run_query(query, {"repo_name": repo_name})

        if not records:
            # Return sensible defaults
            return self._default_boundaries()

        boundaries = [
            LayerBoundary(
                layer_name=r["layer_name"],
                path_pattern=r.get("path_pattern", ""),
                allowed_dependencies=r.get("allowed_dependencies", []),
                forbidden_dependencies=r.get("forbidden_dependencies", []),
            )
            for r in records
        ]

        self._pattern_cache[cache_key] = boundaries
        return boundaries

    @staticmethod
    def _default_boundaries() -> list[LayerBoundary]:
        """Sensible default architecture boundaries."""
        return [
            LayerBoundary(
                layer_name="controller",
                path_pattern="**/controllers/**",
                allowed_dependencies=["service", "middleware", "model", "util"],
                forbidden_dependencies=["repository"],
            ),
            LayerBoundary(
                layer_name="service",
                path_pattern="**/services/**",
                allowed_dependencies=["repository", "model", "util"],
                forbidden_dependencies=["controller"],
            ),
            LayerBoundary(
                layer_name="repository",
                path_pattern="**/repositories/**",
                allowed_dependencies=["model", "util"],
                forbidden_dependencies=["controller", "service"],
            ),
        ]

    # ─── Data Sensitivity Queries ───

    async def get_sensitive_fields_for_module(
        self, file_path: str, repo_name: str = ""
    ) -> list[SensitiveField]:
        """Get all sensitive data fields accessible from this module."""

        query = """
        MATCH (m:Module)-[:DEFINES]->(:Function)-[:HAS_PARAM]->(p:Parameter)
        WHERE m.file_path STARTS WITH $dir_prefix
          AND p.sensitivity_tag <> 'NONE'
        RETURN DISTINCT p.name AS field_name,
               p.sensitivity_tag AS sensitivity,
               m.file_path AS module_path
        UNION
        MATCH (df:DataField)
        WHERE df.source_module STARTS WITH $dir_prefix
          AND df.sensitivity_tag <> 'NONE'
        RETURN DISTINCT df.name AS field_name,
               df.sensitivity_tag AS sensitivity,
               df.source_module AS module_path
        LIMIT 30
        """
        parts = file_path.rsplit("/", 1)
        dir_prefix = parts[0] + "/" if len(parts) > 1 else ""
        records = await self._run_query(query, {"dir_prefix": dir_prefix})

        # Build constraint text based on sensitivity level
        sensitivity_constraints: dict[str, list[str]] = {
            "PII": [
                "Must be encrypted at rest and in transit",
                "Never write to application logs",
                "Require user consent before processing",
            ],
            "PHI": [
                "HIPAA: Must be encrypted with AES-256",
                "Never store in unencrypted staging tables",
                "Require audit trail for all access",
                "Never transmit to external services without BAA",
            ],
            "PCI": [
                "PCI-DSS: Never store after authorization",
                "Must be encrypted with strong cryptography",
                "Never log, even partially",
                "Tokenize before passing to any service",
            ],
            "FINANCIAL": [
                "Must maintain decimal precision (use Decimal, not float)",
                "Require audit trail for all modifications",
                "Validate against business rules before persistence",
            ],
            "CREDENTIAL": [
                "Never store in plaintext",
                "Use bcrypt/argon2 for passwords (salt rounds >= 12)",
                "Never include in API responses",
                "Never log, even in debug mode",
            ],
        }

        return [
            SensitiveField(
                field_name=r["field_name"],
                sensitivity=SensitivityTag(r["sensitivity"]),
                constraints=sensitivity_constraints.get(r["sensitivity"], []),
                module_path=r.get("module_path", ""),
            )
            for r in records
        ]

    # ─── Dependency Queries ───

    async def get_approved_dependencies(self, repo_name: str = "") -> list[str]:
        """Get the list of approved packages for a repository."""
        query = """
        MATCH (r:Repository {name: $repo_name})-[:DEPENDS_ON]->(d:Dependency)
        WHERE d.is_approved = true
        RETURN d.package_name AS name
        ORDER BY d.package_name
        """
        records = await self._run_query(query, {"repo_name": repo_name})
        return [r["name"] for r in records]

    async def check_dependency(self, package_name: str) -> dict:
        """Check a specific dependency's trust status."""
        query = """
        MATCH (d:Dependency {package_name: $package_name})
        RETURN d.package_name AS name,
               d.version AS version,
               d.trust_score AS trust_score,
               d.is_phantom AS is_phantom,
               d.is_approved AS is_approved,
               d.cve_count AS cve_count,
               d.license AS license
        """
        records = await self._run_query(query, {"package_name": package_name})
        if records:
            return records[0]
        return {
            "name": package_name,
            "trust_score": 0,
            "is_phantom": None,
            "is_approved": False,
            "warning": "Package not found in Knowledge Graph. Verify it exists on the registry.",
        }


# Singleton instance
kg_service = KnowledgeGraphService()
