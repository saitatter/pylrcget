import tomllib
from pathlib import Path

from ui.workers.ai import inference_runtime
from ui.workers.ai.package_requirements import AI_PACKAGE_REQUIREMENTS


def test_source_and_packaged_installers_use_the_same_ai_package_combination():
    project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(project["project"]["optional-dependencies"]["ai"]) == set(AI_PACKAGE_REQUIREMENTS.values())


def test_cuda_local_version_is_accepted_but_wrong_torch_generation_needs_repair(monkeypatch):
    monkeypatch.setattr(inference_runtime, "version", lambda _: "2.8.0+cu128")
    assert inference_runtime._supported_package_version("torch")
    monkeypatch.setattr(inference_runtime, "version", lambda _: "2.15.0")
    assert not inference_runtime._supported_package_version("torch")


def test_installed_but_incompatible_packages_are_reported_for_repair(monkeypatch):
    monkeypatch.setattr(inference_runtime, "resolve_ai_runtime_python", lambda: None)
    monkeypatch.setattr(inference_runtime, "_module_available", lambda _: True)
    monkeypatch.setattr(inference_runtime, "_supported_package_version", lambda name: name != "torchaudio")
    assert inference_runtime.get_missing_ai_dependencies() == ["torchaudio"]
