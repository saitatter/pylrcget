"""Conservative language-aware selection of AI alignment backends."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(slots=True, frozen=True)
class BackendRegistration:
    name: str
    languages: frozenset[str]
    experimental: bool = False
    license_eligible: bool = True


@dataclass(slots=True, frozen=True)
class BackendSelection:
    language: str
    backend_name: str
    device: str
    reason: str
    experimental: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "backend": self.backend_name,
            "device": self.device,
            "reason": self.reason,
            "experimental": self.experimental,
        }


class LanguageAwareBackendRouter:
    """Select the first eligible backend, keeping legacy fallback explicit."""

    def __init__(self, *, fallback_name: str = "legacy-whisperx") -> None:
        self.fallback_name = fallback_name
        self._registrations: list[BackendRegistration] = []

    def register(
        self,
        name: str,
        languages: Iterable[str],
        *,
        experimental: bool = False,
        license_eligible: bool = True,
    ) -> None:
        registration = BackendRegistration(
            name=str(name),
            languages=frozenset(_normalize_language(language) for language in languages),
            experimental=experimental,
            license_eligible=license_eligible,
        )
        self._registrations = [
            existing for existing in self._registrations if existing.name != registration.name
        ]
        self._registrations.append(registration)

    def select(
        self,
        language: str | None,
        *,
        device: str,
        available_backends: Mapping[str, bool] | None = None,
        manual_override: str | None = None,
        allow_experimental: bool = False,
    ) -> BackendSelection:
        normalized = _normalize_language(language)
        availability = available_backends or {}
        if manual_override:
            selected = self._find_registration(manual_override, normalized)
            if selected is not None and selected.license_eligible and (
                allow_experimental or not selected.experimental
            ) and availability.get(selected.name, False):
                return BackendSelection(
                    normalized,
                    selected.name,
                    str(device),
                    "manual override",
                    selected.experimental,
                )

        for registration in self._registrations:
            if normalized not in registration.languages:
                continue
            if not registration.license_eligible:
                continue
            if registration.experimental and not allow_experimental:
                continue
            if not availability.get(registration.name, False):
                continue
            return BackendSelection(
                normalized,
                registration.name,
                str(device),
                "registered backend",
                registration.experimental,
            )

        reason = "no eligible backend for language" if normalized not in {
            "en", "fr", "de", "it", "es", "ro"
        } else "registered backend unavailable"
        if manual_override:
            reason = "manual override unavailable; using legacy fallback"
        return BackendSelection(normalized, self.fallback_name, str(device), reason)

    def _find_registration(self, name: str, language: str) -> BackendRegistration | None:
        for registration in self._registrations:
            if registration.name == name and language in registration.languages:
                return registration
        return None


def _normalize_language(language: str | None) -> str:
    normalized = str(language or "unknown").strip().lower()
    return normalized if normalized and normalized != "auto" else "unknown"


def build_default_router() -> LanguageAwareBackendRouter:
    router = LanguageAwareBackendRouter()
    router.register("lyrics-aligner", ["en"])
    return router


__all__ = [
    "BackendRegistration",
    "BackendSelection",
    "LanguageAwareBackendRouter",
    "build_default_router",
]
