"""
ForgeLine Context Server — Context Builder

Assembles the complete governance context for a given file location
by querying the Knowledge Graph and Policy Engine.
"""

from __future__ import annotations

import structlog

from src.models import FileContext, PolicyCategory
from src.services.knowledge_graph import kg_service
from src.services.policies import policy_service

logger = structlog.get_logger(__name__)


class ContextBuilder:
    """Builds enriched context for a file location."""

    async def build_context(
        self,
        file_path: str,
        repo_name: str = "",
        profile_id: str = "default",
        include_patterns: bool = True,
        include_sensitivity: bool = True,
    ) -> FileContext:
        """
        Build the complete context payload for a given file path.

        This is the core function that assembles everything the AI needs:
        - Security rules for this module's layer
        - Architecture constraints
        - Existing functions and classes to reuse
        - Data sensitivity rules
        - Testing requirements
        - Approved/forbidden dependencies
        """
        logger.info("Building context", file_path=file_path, repo=repo_name)

        # 1. Determine which architecture layer this file belongs to
        layer = await kg_service.get_layer_for_file(file_path)
        logger.debug("Resolved layer", file_path=file_path, layer=layer)

        # 2. Get language from file extension
        language = self._detect_language(file_path)

        # 3. Load policy rules for this layer
        security_rules = policy_service.get_constraint_texts(
            layer, PolicyCategory.SECURITY, profile_id
        )
        arch_constraints = policy_service.get_constraint_texts(
            layer, PolicyCategory.ARCHITECTURE, profile_id
        )
        style_rules = policy_service.get_constraint_texts(
            layer, PolicyCategory.STYLE, profile_id
        )
        testing_reqs = policy_service.get_constraint_texts(
            layer, PolicyCategory.TESTING, profile_id
        )

        # 4. Query Knowledge Graph for existing patterns
        existing_functions = []
        existing_classes = []
        if include_patterns:
            try:
                existing_functions = await kg_service.get_functions_in_module(
                    file_path, repo_name
                )
                existing_classes = await kg_service.get_classes_in_module(
                    file_path, repo_name
                )
            except Exception as e:
                logger.warning("KG pattern query failed, continuing without patterns", error=str(e))

        # 5. Query data sensitivity
        sensitive_fields = []
        if include_sensitivity:
            try:
                sensitive_fields = await kg_service.get_sensitive_fields_for_module(
                    file_path, repo_name
                )
            except Exception as e:
                logger.warning("KG sensitivity query failed", error=str(e))

        # 6. Get approved dependencies
        approved_packages = []
        try:
            approved_packages = await kg_service.get_approved_dependencies(repo_name)
        except Exception as e:
            logger.warning("KG dependency query failed", error=str(e))

        # 7. Add layer-specific architecture constraints
        try:
            boundaries = await kg_service.get_architecture_boundaries(repo_name)
            for b in boundaries:
                if b.layer_name == layer and b.forbidden_dependencies:
                    forbidden_text = (
                        f"This module is in the '{layer}' layer. "
                        f"It MUST NOT import from: {', '.join(b.forbidden_dependencies)} layers. "
                        f"It CAN import from: {', '.join(b.allowed_dependencies)} layers."
                    )
                    arch_constraints.append(forbidden_text)
        except Exception as e:
            logger.warning("Architecture boundary query failed", error=str(e))

        context = FileContext(
            file_path=file_path,
            language=language,
            layer=layer,
            security_rules=security_rules,
            architecture_constraints=arch_constraints,
            style_rules=style_rules,
            testing_requirements=testing_reqs,
            existing_functions=existing_functions,
            existing_classes=existing_classes,
            sensitive_fields=sensitive_fields,
            approved_packages=approved_packages,
        )

        logger.info(
            "Context built",
            file_path=file_path,
            layer=layer,
            security_rules=len(security_rules),
            patterns=len(existing_functions) + len(existing_classes),
            sensitive_fields=len(sensitive_fields),
        )

        return context

    @staticmethod
    def _detect_language(file_path: str) -> str:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".cs": "csharp",
            ".php": "php",
            ".kt": "kotlin",
            ".swift": "swift",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return "unknown"


# Singleton instance
context_builder = ContextBuilder()
