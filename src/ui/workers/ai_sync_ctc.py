"""Pluggable generic CTC alignment backend contracts.

This module deliberately contains no CTC engine dependency.  A research
adapter can inject an engine from a separately managed runtime, while model
metadata and licensing remain visible to the router.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Protocol

from .ai_sync_contracts import AlignmentRequest, AlignmentResult


@dataclass(slots=True, frozen=True)
class CtcModelSpec:
    model_id: str
    language: str
    license: str
    backend: Literal["torch", "ctranslate2"]
    revision: str | None = None
    size_mb: float | None = None
    sample_rate: int = 16_000
    tokenizer: str | None = None
    romanization_required: bool = False
    tested_on_singing: bool = False
    default_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "language": self.language,
            "license": self.license,
            "backend": self.backend,
            "revision": self.revision,
            "size_mb": self.size_mb,
            "sample_rate": self.sample_rate,
            "tokenizer": self.tokenizer,
            "romanization_required": self.romanization_required,
            "tested_on_singing": self.tested_on_singing,
            "default_enabled": self.default_enabled,
        }

    @property
    def license_eligible(self) -> bool:
        normalized = self.license.casefold()
        return not any(
            marker in normalized
            for marker in ("non-commercial", "noncommercial", "cc-by-nc", "cc by-nc")
        )


class CtcAlignmentEngine(Protocol):
    def align(self, request: AlignmentRequest, model: CtcModelSpec) -> AlignmentResult:
        ...


class GenericCtcBackend:
    """Backend-independent wrapper around an injected CTC implementation."""

    def __init__(self, model: CtcModelSpec, engine: CtcAlignmentEngine) -> None:
        self.model = model
        self.engine = engine
        self.name = f"generic-ctc:{model.model_id}"

    def supports_language(self, language: str) -> bool:
        return str(language or "").strip().lower() == self.model.language.casefold()

    def is_eligible(self, *, allow_experimental: bool = False) -> bool:
        return (
            self.model.license_eligible
            and self.model.tested_on_singing
            and (allow_experimental or self.model.default_enabled)
        )

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        result = self.engine.align(request, self.model)
        diagnostics = dict(result.diagnostics)
        diagnostics.update(
            {
                "ctc_model_id": self.model.model_id,
                "ctc_model_revision": self.model.revision,
                "ctc_engine": self.model.backend,
            }
        )
        return replace(result, backend=self.name, diagnostics=diagnostics)


class CtcModelRegistry:
    def __init__(self) -> None:
        self._models: dict[tuple[str, str], CtcModelSpec] = {}

    def register(self, model: CtcModelSpec) -> None:
        key = (model.language.casefold(), model.model_id)
        self._models[key] = model

    def get(self, language: str, model_id: str) -> CtcModelSpec | None:
        return self._models.get((str(language).casefold(), str(model_id)))

    def models_for_language(self, language: str) -> tuple[CtcModelSpec, ...]:
        normalized = str(language).casefold()
        return tuple(model for (model_language, _model_id), model in self._models.items() if model_language == normalized)

    def production_eligible(self, language: str) -> tuple[CtcModelSpec, ...]:
        return tuple(
            model
            for model in self.models_for_language(language)
            if model.license_eligible and model.tested_on_singing and model.default_enabled
        )


def build_research_ctc_registry() -> CtcModelRegistry:
    """Create an intentionally empty registry until a model passes evaluation."""
    return CtcModelRegistry()


__all__ = [
    "CtcAlignmentEngine",
    "CtcModelRegistry",
    "CtcModelSpec",
    "GenericCtcBackend",
    "build_research_ctc_registry",
]
