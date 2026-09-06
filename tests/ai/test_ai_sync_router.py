from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_router import LanguageAwareBackendRouter, build_default_router


def test_default_router_selects_english_backend_when_available() -> None:
    selection = build_default_router().select(
        "EN",
        device="cpu",
        available_backends={"lyrics-aligner": True},
    )

    assert selection.backend_name == "lyrics-aligner"
    assert selection.language == "en"


def test_default_router_keeps_legacy_fallback_for_non_english() -> None:
    selection = build_default_router().select(
        "ro",
        device="cpu",
        available_backends={"lyrics-aligner": True},
    )

    assert selection.backend_name == "legacy-whisperx"


def test_router_experimental_backend_requires_explicit_opt_in() -> None:
    router = LanguageAwareBackendRouter()
    router.register("multilingual-research", ["fr", "de"], experimental=True)

    default = router.select(
        "fr",
        device="cuda",
        available_backends={"multilingual-research": True},
    )
    opted_in = router.select(
        "fr",
        device="cuda",
        available_backends={"multilingual-research": True},
        allow_experimental=True,
    )

    assert default.backend_name == "legacy-whisperx"
    assert opted_in.backend_name == "multilingual-research"
    assert opted_in.experimental is True


def test_router_manual_override_cannot_bypass_unavailable_or_unlicensed_backend() -> None:
    router = LanguageAwareBackendRouter()
    router.register("restricted", ["en"], license_eligible=False)
    router.register("approved", ["en"])

    unavailable = router.select(
        "en",
        device="cpu",
        available_backends={"restricted": True},
        manual_override="restricted",
    )
    approved = router.select(
        "en",
        device="cpu",
        available_backends={"approved": True},
        manual_override="approved",
    )

    assert unavailable.backend_name == "legacy-whisperx"
    assert approved.backend_name == "approved"
