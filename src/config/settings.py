"""
ForgeLine Context Server — Configuration

Loads settings from environment variables and .env file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── Neo4j ───
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    # ─── PostgreSQL ───
    database_url: str = "postgresql+asyncpg://forgeline:password@localhost:5432/forgeline"

    # ─── Server ───
    server_name: str = "forgeline-context"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    transport: str = "stdio"  # "stdio" | "streamable-http" | "sse"
    log_level: str = "INFO"

    # ─── Cache ───
    cache_ttl_seconds: int = 300
    pattern_cache_max_size: int = 500

    # ─── ForgeLine API (optional cloud mode) ───
    forgeline_api_url: str = ""
    forgeline_api_key: str = ""


settings = Settings()
