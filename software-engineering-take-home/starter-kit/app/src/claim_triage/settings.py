"""Configuration, and the two guards that keep the credential out of everything.

The credential reaches this process only through the environment (Compose `env_file`).
It is never printed, logged or returned: `Settings.__repr__` redacts it, and
`CredentialScrubber` rewrites any log record that happens to contain it (FR-036).
"""
from __future__ import annotations

import logging
from functools import cached_property
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REDACTED = "***"


class Settings(BaseSettings):
    """Runtime configuration. Field names match the environment variables, case-insensitively."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- Model access (research D1) ---
    portkey_api_key: SecretStr = SecretStr("")
    portkey_base_url: str = "https://portkey.bain.dev/v1"
    claude_model_route: str = "@anthropic---placeholder/claude-opus-5"

    # --- Infrastructure ---
    qdrant_url: str = "http://qdrant:6333"
    collection_name: str = "historical_claims"
    knowledge_base_dir: Path = Path("/app/data/knowledge-base")
    tools_dir: Path = Path("/app/tools")
    openapi_path: Path = Path("/app/api-contract/openapi.yaml")
    fastembed_cache_dir: Path = Path("/opt/fastembed")
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # --- Budgets. Caps, not expectations (plan.md Technical Context) ---
    max_tool_rounds: int = 6
    llm_timeout_s: float = 60.0
    request_budget_s: float = 110.0
    max_image_bytes: int = 10_485_760
    pdf_text_limit: int = 8_000
    llm_max_tokens: int = 2_000
    safety_max_tokens: int = 300

    app_env: str = Field(default="prod")

    @cached_property
    def gateway_root(self) -> str:
        """The Anthropic SDK wants the gateway ROOT; it appends /v1/messages itself.

        `check_claude_access.py` builds the same URL as `gateway.removesuffix("/v1")`.
        """
        return self.portkey_base_url.rstrip("/").removesuffix("/v1")

    @cached_property
    def provider_route(self) -> str:
        """The `@anthropic---xxxx` half of the route, sent as x-portkey-provider."""
        return self.claude_model_route.split("/", 1)[0]

    @cached_property
    def model_id(self) -> str:
        """The unprefixed model id. A prefixed route is wrong for this interface."""
        parts = self.claude_model_route.split("/", 1)
        return parts[1] if len(parts) == 2 else parts[0]

    @property
    def llm_configured(self) -> bool:
        key = self.portkey_api_key.get_secret_value()
        return bool(key) and "/" in self.claude_model_route

    def __repr__(self) -> str:  # pragma: no cover - exercised via tests through str()
        return (
            f"Settings(portkey_api_key={REDACTED}, portkey_base_url={self.portkey_base_url!r}, "
            f"claude_model_route={self.claude_model_route!r}, qdrant_url={self.qdrant_url!r}, "
            f"app_env={self.app_env!r})"
        )

    __str__ = __repr__


class CredentialScrubber(logging.Filter):
    """Replaces the credential with *** in any log record that carries it.

    A diagnostic may name the variable and whether it is set; it may never carry the value.
    """

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secret:
            return True
        if isinstance(record.msg, str) and self._secret in record.msg:
            record.msg = record.msg.replace(self._secret, REDACTED)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (v.replace(self._secret, REDACTED) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    v.replace(self._secret, REDACTED) if isinstance(v, str) else v
                    for v in record.args
                )
        return True


def install_credential_scrubber(settings: Settings) -> CredentialScrubber:
    """Attach the scrubber to the root logger and every existing handler."""
    scrubber = CredentialScrubber(settings.portkey_api_key.get_secret_value())
    root = logging.getLogger()
    root.addFilter(scrubber)
    for handler in root.handlers:
        handler.addFilter(scrubber)
    return scrubber
