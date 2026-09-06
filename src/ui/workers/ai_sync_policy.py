"""Packaging and model-license policy for optional AI backends."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class BackendLicenseManifest:
    backend: str
    model: str
    code_license: str
    model_license: str
    bundled: bool
    download_on_demand: bool
    size_mb: float | None
    redistribution_rights: str
    commercial_use: bool | None
    supported_platforms: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "model": self.model,
            "code_license": self.code_license,
            "model_license": self.model_license,
            "bundled": self.bundled,
            "download_on_demand": self.download_on_demand,
            "size_mb": self.size_mb,
            "redistribution_rights": self.redistribution_rights,
            "commercial_use": self.commercial_use,
            "supported_platforms": list(self.supported_platforms),
        }

    @property
    def license_verified(self) -> bool:
        values = (self.code_license, self.model_license, self.redistribution_rights)
        return all(value.strip() and "verify" not in value.casefold() for value in values)

    def default_eligible(self) -> bool:
        model_license = self.model_license.casefold()
        return (
            self.license_verified
            and self.commercial_use is True
            and "non-commercial" not in model_license
            and "noncommercial" not in model_license
            and (self.bundled or self.download_on_demand)
        )


LYRICS_ALIGNER_MANIFEST = BackendLicenseManifest(
    backend="lyrics-aligner",
    model="schufo/lyrics-aligner:model_parameters.pth",
    code_license="MIT",
    model_license="verify upstream checkpoint redistribution terms",
    bundled=False,
    download_on_demand=True,
    size_mb=None,
    redistribution_rights="verify upstream checkpoint redistribution terms",
    commercial_use=None,
    supported_platforms=("windows", "macos", "linux"),
)


MMS_RESEARCH_MANIFEST = BackendLicenseManifest(
    backend="generic-ctc",
    model="facebook/mms-1b-all",
    code_license="permissive code; verify adapter",
    model_license="CC-BY-NC 4.0",
    bundled=False,
    download_on_demand=True,
    size_mb=None,
    redistribution_rights="non-commercial research only",
    commercial_use=False,
    supported_platforms=("windows", "macos", "linux"),
)


def backend_can_be_default(manifest: BackendLicenseManifest) -> bool:
    return manifest.default_eligible()


__all__ = [
    "BackendLicenseManifest",
    "LYRICS_ALIGNER_MANIFEST",
    "MMS_RESEARCH_MANIFEST",
    "backend_can_be_default",
]
