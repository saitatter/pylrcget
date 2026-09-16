from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_policy import (
    LYRICS_ALIGNER_MANIFEST,
    MMS_RESEARCH_MANIFEST,
    BackendLicenseManifest,
    backend_can_be_default,
)


def test_lyrics_aligner_manifest_requires_checkpoint_license_verification() -> None:
    assert LYRICS_ALIGNER_MANIFEST.bundled is False
    assert LYRICS_ALIGNER_MANIFEST.license_verified is False
    assert backend_can_be_default(LYRICS_ALIGNER_MANIFEST) is False


def test_noncommercial_mms_manifest_can_never_be_default() -> None:
    assert MMS_RESEARCH_MANIFEST.commercial_use is False
    assert backend_can_be_default(MMS_RESEARCH_MANIFEST) is False


def test_verified_commercial_manifest_can_be_default() -> None:
    manifest = BackendLicenseManifest(
        backend="fixture",
        model="fixture/model",
        code_license="BSD-3-Clause",
        model_license="Apache-2.0",
        bundled=False,
        download_on_demand=True,
        size_mb=10,
        redistribution_rights="commercial redistribution permitted",
        commercial_use=True,
        supported_platforms=("windows",),
    )

    assert manifest.license_verified is True
    assert backend_can_be_default(manifest) is True
