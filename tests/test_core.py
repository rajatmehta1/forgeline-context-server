"""
Tests for ForgeLine Context Server

Runs without Neo4j — tests policy logic and context assembly.
"""

from __future__ import annotations

import pytest
from src.models import PolicyCategory, FileContext, SensitiveField, SensitivityTag
from src.services.policies import policy_service, PolicyService
from src.services.knowledge_graph import KnowledgeGraphService


# ─── Policy Service Tests ───


class TestPolicyService:
    """Test policy loading and resolution."""

    def test_default_profile_exists(self) -> None:
        profile = policy_service.get_profile("default")
        assert profile.profile_id == "default"
        assert len(profile.rules) > 0

    def test_security_rules_exist(self) -> None:
        rules = policy_service.get_rules_for_layer(
            "controller", "default", [PolicyCategory.SECURITY]
        )
        assert len(rules) >= 5  # We defined 6 default security rules
        rule_ids = [r.rule_id for r in rules]
        assert "SEC-001" in rule_ids  # Parameterized queries
        assert "SEC-002" in rule_ids  # No eval

    def test_architecture_rules_exist(self) -> None:
        rules = policy_service.get_rules_for_layer(
            "controller", "default", [PolicyCategory.ARCHITECTURE]
        )
        assert len(rules) >= 1
        assert any(r.rule_id == "ARCH-001" for r in rules)

    def test_test_layer_gets_test_rules_only(self) -> None:
        rules = policy_service.get_rules_for_layer("test", "default")
        # Test layer should only have testing category rules
        categories = {r.category for r in rules}
        assert categories == {PolicyCategory.TESTING}

    def test_constraint_texts_are_nonempty(self) -> None:
        texts = policy_service.get_constraint_texts("service", PolicyCategory.SECURITY)
        assert all(len(t) > 10 for t in texts)

    def test_unknown_profile_falls_back_to_default(self) -> None:
        profile = policy_service.get_profile("nonexistent-profile")
        assert profile.profile_id == "default"


# ─── Knowledge Graph Layer Inference Tests ───


class TestLayerInference:
    """Test the path-based layer inference (works without Neo4j)."""

    def test_controller_detection(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("src/controllers/user.ts") == "controller"
        assert KnowledgeGraphService._infer_layer_from_path("app/routes/auth.py") == "controller"
        assert KnowledgeGraphService._infer_layer_from_path("api/handlers/payment.go") == "controller"

    def test_service_detection(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("src/services/payment.ts") == "service"

    def test_repository_detection(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("src/repositories/user.ts") == "repository"
        assert KnowledgeGraphService._infer_layer_from_path("src/dao/product.java") == "repository"

    def test_model_detection(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("src/models/user.py") == "model"

    def test_test_detection(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("tests/test_user.py") == "test"
        assert KnowledgeGraphService._infer_layer_from_path("src/__test__/user.spec.ts") == "test"

    def test_unknown_path(self) -> None:
        assert KnowledgeGraphService._infer_layer_from_path("random/file.txt") == "unknown"


# ─── FileContext Model Tests ───


class TestFileContext:
    """Test context model and prompt generation."""

    def test_empty_context_generates_empty_string(self) -> None:
        ctx = FileContext(file_path="test.py")
        text = ctx.to_prompt_context()
        assert text == ""

    def test_security_rules_in_prompt(self) -> None:
        ctx = FileContext(
            file_path="src/api/handler.py",
            security_rules=["Never use eval()", "Always validate inputs"],
        )
        text = ctx.to_prompt_context()
        assert "Security Requirements" in text
        assert "Never use eval()" in text
        assert "Always validate inputs" in text

    def test_sensitive_fields_in_prompt(self) -> None:
        ctx = FileContext(
            file_path="src/services/user.py",
            sensitive_fields=[
                SensitiveField(
                    field_name="email",
                    sensitivity=SensitivityTag.PII,
                    constraints=["Must be encrypted at rest"],
                ),
                SensitiveField(
                    field_name="card_number",
                    sensitivity=SensitivityTag.PCI,
                    constraints=["Never log", "Tokenize before storage"],
                ),
            ],
        )
        text = ctx.to_prompt_context()
        assert "Data Sensitivity" in text
        assert "email" in text
        assert "PII" in text
        assert "card_number" in text
        assert "PCI" in text

    def test_approved_packages_in_prompt(self) -> None:
        ctx = FileContext(
            file_path="src/index.ts",
            approved_packages=["express", "lodash", "zod"],
        )
        text = ctx.to_prompt_context()
        assert "Approved Packages" in text
        assert "express" in text

    def test_language_detection(self) -> None:
        from src.services.context_builder import ContextBuilder

        cb = ContextBuilder()
        assert cb._detect_language("app.py") == "python"
        assert cb._detect_language("index.ts") == "typescript"
        assert cb._detect_language("Main.java") == "java"
        assert cb._detect_language("server.go") == "go"
        assert cb._detect_language("README.md") == "unknown"
