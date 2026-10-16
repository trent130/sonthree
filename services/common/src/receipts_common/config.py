"""Environment-backed configuration for local foundation components."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", case_sensitive=True, populate_by_name=True, frozen=True
    )

    mode: Literal["local"] = Field(
        default="local", validation_alias=AliasChoices("MODE", "RECEIPTS_MODE")
    )
    llm_mode: Literal["live", "record", "replay"] = Field(
        default="replay", validation_alias="LLM_MODE"
    )
    model_analyst: str = Field(default="", validation_alias="MODEL_ANALYST")
    model_narrator: str = Field(default="", validation_alias="MODEL_NARRATOR")
    model_judge: str = Field(default="", validation_alias="MODEL_JUDGE")
    model_translator: str = Field(default="", validation_alias="MODEL_TRANSLATOR")
    llm_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="LLM_TIMEOUT_SECONDS")
    llm_max_attempts: int = Field(default=3, ge=1, validation_alias="LLM_MAX_ATTEMPTS")
    llm_backoff_seconds: float = Field(default=0.1, ge=0, validation_alias="LLM_BACKOFF_SECONDS")
    cassette_dir: Path = Field(
        default=Path("tests/cassettes/local"), validation_alias="CASSETTE_DIR"
    )
    telemetry_exporter: Literal["console"] = Field(
        default="console", validation_alias="TELEMETRY_EXPORTER"
    )


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Load settings from explicit input or the process environment."""
    if environ is None:
        try:
            return Settings()
        except ValidationError as exc:
            raise ValueError(f"invalid Receipts configuration: {exc}") from exc
    aliases = {
        "MODE": "mode",
        "RECEIPTS_MODE": "mode",
        "LLM_MODE": "llm_mode",
        "MODEL_ANALYST": "model_analyst",
        "MODEL_NARRATOR": "model_narrator",
        "MODEL_JUDGE": "model_judge",
        "MODEL_TRANSLATOR": "model_translator",
        "LLM_TIMEOUT_SECONDS": "llm_timeout_seconds",
        "LLM_MAX_ATTEMPTS": "llm_max_attempts",
        "LLM_BACKOFF_SECONDS": "llm_backoff_seconds",
        "CASSETTE_DIR": "cassette_dir",
        "TELEMETRY_EXPORTER": "telemetry_exporter",
    }
    try:
        values = {aliases[name]: value for name, value in environ.items() if name in aliases}
        return Settings(**values)
    except ValidationError as exc:
        raise ValueError(f"invalid Receipts configuration: {exc}") from exc