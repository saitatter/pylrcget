"""Resolution helpers for the optional external AI Python runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from .ai_bootstrap import (
    BootstrapRuntimeArtifact,
    bootstrap_python_path,
    resolve_bootstrap_artifact,
)
from .ai_dependencies import AI_PACKAGE_REQUIREMENTS

_SUPPORTED_PYTHON = (3, 13, 15)


@dataclass(frozen=True)
class AIInstallPlan:
    """Resolved direct install command or an on-demand Python bootstrap plan."""

    command: list[str] | None = None
    bootstrap_artifact: BootstrapRuntimeArtifact | None = None
    bootstrap_runtime_root: Path | None = None
    bootstrap_arguments: tuple[str, ...] = ()
    error: str = ""
    lyrics_aligner_root: Path | None = None

    @property
    def can_install(self) -> bool:
        return self.command is not None or self.bootstrap_artifact is not None


def _is_supported_python(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        version = tuple(int(part) for part in result.stdout.strip().split(".", 3))
    except ValueError:
        return False
    return version == _SUPPORTED_PYTHON


def default_ai_runtime_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "PyLrcGet" / "ai-runtime"


def default_ai_bootstrap_dir() -> Path:
    return default_ai_runtime_dir().parent / "python-bootstrap"


def default_ai_nltk_dir() -> Path:
    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    root = Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    return root.parent / "nltk_data"


def default_lyrics_aligner_dir() -> Path:
    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    runtime_root = (
        Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    )
    return runtime_root.parent / "lyrics-aligner"


def resolve_ai_runtime_python() -> Path | None:
    """Return the configured external Python executable, if it exists."""
    configured = os.environ.get("PYLRCGET_AI_RUNTIME_PYTHON", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return (
            candidate
            if candidate.is_file() and _is_supported_python(candidate)
            else None
        )

    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    root = Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    executable_dir = root / ("Scripts" if sys.platform == "win32" else "bin")
    executables = (
        ("python.exe", "pythonw.exe") if sys.platform == "win32" else ("python",)
    )
    for executable in executables:
        candidate = executable_dir / executable
        if candidate.is_file() and _is_supported_python(candidate):
            return candidate
    return None


def resolve_ai_install_plan(packages: list[str]) -> AIInstallPlan:
    """Resolve how optional AI packages can be installed on this host."""
    missing = [package for package in packages if str(package).strip()]
    if not missing:
        return AIInstallPlan(error="No missing AI dependencies were detected.")
    aligner_root = default_lyrics_aligner_dir() if "lyrics-aligner" in missing else None

    bootstrap = os.environ.get("PYLRCGET_AI_BOOTSTRAP_PYTHON", "").strip()
    if bootstrap:
        bootstrap_python = Path(bootstrap).expanduser()
        if not bootstrap_python.is_file():
            return AIInstallPlan(
                error=(
                    "The configured AI bootstrap interpreter was not found. "
                    "Check PYLRCGET_AI_BOOTSTRAP_PYTHON or clear it to use the "
                    "automatic setup."
                )
            )
        if not _is_supported_python(bootstrap_python):
            return AIInstallPlan(
                error=(
                    "The selected AI bootstrap interpreter is unsupported. "
                    "Use Python 3.13.15 or clear PYLRCGET_AI_BOOTSTRAP_PYTHON."
                )
            )
        if (
            not getattr(sys, "frozen", False)
            and tuple(sys.version_info[:3]) != _SUPPORTED_PYTHON
        ):
            return AIInstallPlan(
                error=(
                    "PyLrcGet requires Python 3.13.15. Run the app with that "
                    "interpreter or set PYLRCGET_AI_BOOTSTRAP_PYTHON to it."
                )
            )
        return AIInstallPlan(
            command=_build_ai_install_command(bootstrap_python, missing),
            lyrics_aligner_root=aligner_root,
        )

    if not getattr(sys, "frozen", False):
        if tuple(sys.version_info[:3]) != _SUPPORTED_PYTHON:
            return AIInstallPlan(
                error=(
                    "The selected AI bootstrap interpreter is unsupported. "
                    "Run the app with Python 3.13.15 or set "
                    "PYLRCGET_AI_BOOTSTRAP_PYTHON to it."
                )
            )
        return AIInstallPlan(
            command=_build_ai_install_command(Path(sys.executable), missing),
            lyrics_aligner_root=aligner_root,
        )

    artifact = resolve_bootstrap_artifact()
    if artifact is None:
        return AIInstallPlan(
            error=(
                "Automatic Python setup is not available for this operating system "
                "and processor architecture. Set PYLRCGET_AI_BOOTSTRAP_PYTHON to "
                "Python 3.13.15."
            )
        )

    bootstrap_root = default_ai_bootstrap_dir() / artifact.platform_key
    cached_python = bootstrap_python_path(bootstrap_root)
    return AIInstallPlan(
        command=(
            _build_ai_install_command(cached_python, missing)
            if cached_python.is_file()
            else None
        ),
        bootstrap_artifact=artifact,
        bootstrap_runtime_root=bootstrap_root,
        bootstrap_arguments=tuple(_build_ai_install_arguments(missing)),
        lyrics_aligner_root=aligner_root,
    )


def _build_ai_install_command(bootstrap_python: Path, packages: list[str]) -> list[str]:
    return [str(bootstrap_python), *_build_ai_install_arguments(packages)]


def _build_ai_install_arguments(packages: list[str]) -> list[str]:
    """Build Python arguments that populate the isolated AI runtime."""
    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    runtime_root = (
        Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    )
    missing = list(packages)
    constraints = "\n".join(AI_PACKAGE_REQUIREMENTS.values())
    nltk_setup = (
        "import nltk; root=" + repr(str(default_ai_nltk_dir())) + "; "
        "[nltk.download(name, download_dir=root, raise_on_error=True) for name in "
        "['cmudict', 'averaged_perceptron_tagger', 'averaged_perceptron_tagger_eng']]"
    )
    script = textwrap.dedent(f"""\
        import os, subprocess, sys, tempfile, venv
        from pathlib import Path
        root = {str(runtime_root)!r}
        venv.EnvBuilder(with_pip=True).create(root)
        python = os.path.join(root, 'Scripts', 'python.exe') if sys.platform == 'win32' else os.path.join(root, 'bin', 'python')
        requested = sys.argv[1:]
        aligner = 'lyrics-aligner' in requested
        cuda = 'torch-cuda' in requested
        requirements = {AI_PACKAGE_REQUIREMENTS!r}
        args = [requirements.get(arg, arg) for arg in requested if arg not in ('lyrics-aligner', 'torch-cuda')]
        with tempfile.TemporaryDirectory(prefix='pylrcget-ai-install-') as staging:
            constraint_file = Path(staging) / 'constraints.txt'
            constraint_file.write_text({constraints!r}, encoding='utf-8')
            pip = [python, '-m', 'pip', 'install', '--upgrade', '--constraint', str(constraint_file)]
            if cuda:
                subprocess.check_call(pip + [requirements['torch'], requirements['torchaudio'], '--index-url', 'https://download.pytorch.org/whl/cu128'])
                args = [arg for arg in args if arg not in (requirements['torch'], requirements['torchaudio'])]
            if aligner:
                subprocess.check_call(pip + [requirements['g2p-en'], requirements['librosa']])
                subprocess.check_call([python, '-c', {nltk_setup!r}])
            if args:
                subprocess.check_call(pip + args)
        """)
    return ["-c", script, *missing]


def resolve_ai_install_command(packages: list[str]) -> tuple[list[str] | None, str]:
    """Return a direct command when an interpreter has already been selected."""
    plan = resolve_ai_install_plan(packages)
    if plan.command is not None:
        return plan.command, ""
    return (
        None,
        plan.error or "Python 3.13.15 will be prepared automatically on install.",
    )


def nvidia_gpu_available() -> bool:
    """Return whether a usable NVIDIA adapter is visible to the host."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False
    result = subprocess.run(
        [executable, "-L"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def resolve_torch_device(requested: str = "auto") -> str:
    """Resolve a requested Torch device, preferring an available accelerator."""
    normalized = str(requested or "auto").strip().lower()
    if normalized not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError(f"Unsupported AI device: {requested!r}")

    import torch

    if normalized == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA was selected, but the active Torch runtime has no CUDA support. "
                "Install a CUDA-enabled Torch build or select Auto/CPU."
            )
        return "cuda"
    if normalized == "mps":
        if not hasattr(torch.backends, "mps") or not torch.backends.mps.is_available():
            raise RuntimeError(
                "MPS was selected, but the active Torch runtime has no MPS support. "
                "Select Auto/CPU or use a compatible Apple runtime."
            )
        return "mps"
    if normalized == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def available_torch_devices() -> list[str]:
    """Return devices usable by the active Torch runtime, in preference order."""
    try:
        import torch
    except ImportError:
        return ["cpu"]

    devices = ["cpu"]
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.insert(0, "mps")
    if torch.cuda.is_available():
        devices.insert(0, "cuda")
    return devices


def resolve_ai_runtime_source() -> Path | None:
    """Return the source tree imported by an external AI runtime."""
    configured = os.environ.get("PYLRCGET_AI_RUNTIME_SOURCE", "").strip()
    if configured:
        candidates = [Path(configured).expanduser()]
    elif getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        executable_dir = Path(sys.executable).resolve().parent
        candidates = [
            meipass / "ai_runtime_src",
            meipass / "_internal" / "ai_runtime_src",
            executable_dir / "ai_runtime_src",
            executable_dir / "_internal" / "ai_runtime_src",
        ]
    else:
        candidates = [Path(__file__).resolve().parents[3]]
    for candidate in candidates:
        if (
            candidate / "ui" / "workers" / "ai" / "ai_sync_external_entry.py"
        ).is_file() and (
            candidate / "ui" / "workers" / "ai" / "ai_sync_pipeline.py"
        ).is_file():
            return candidate
    return None


__all__ = [
    "AIInstallPlan",
    "available_torch_devices",
    "default_ai_bootstrap_dir",
    "default_ai_runtime_dir",
    "nvidia_gpu_available",
    "resolve_ai_install_command",
    "resolve_ai_install_plan",
    "resolve_ai_runtime_python",
    "resolve_ai_runtime_source",
    "resolve_torch_device",
]
