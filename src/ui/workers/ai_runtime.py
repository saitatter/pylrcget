"""Resolution helpers for the optional external AI Python runtime."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_SUPPORTED_PYTHON_MIN = (3, 10)
_SUPPORTED_PYTHON_MAX = (3, 13)


def _is_supported_python(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
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
        version = tuple(int(part) for part in result.stdout.strip().split(".", 2))
    except ValueError:
        return False
    return _SUPPORTED_PYTHON_MIN <= version[:2] <= _SUPPORTED_PYTHON_MAX


def default_ai_runtime_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "PyLrcGet" / "ai-runtime"


def default_lyrics_aligner_dir() -> Path:
    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    runtime_root = Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    return runtime_root.parent / "lyrics-aligner"


def resolve_ai_runtime_python() -> Path | None:
    """Return the configured external Python executable, if it exists."""
    configured = os.environ.get("PYLRCGET_AI_RUNTIME_PYTHON", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() and _is_supported_python(candidate) else None

    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    root = Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    executable_dir = root / ("Scripts" if sys.platform == "win32" else "bin")
    executables = (
        ("python.exe", "pythonw.exe")
        if sys.platform == "win32"
        else ("python",)
    )
    for executable in executables:
        candidate = executable_dir / executable
        if candidate.is_file() and _is_supported_python(candidate):
            return candidate
    return None


def resolve_ai_install_command(packages: list[str]) -> tuple[list[str] | None, str]:
    """Build a command that creates and populates the isolated AI runtime."""
    missing = [package for package in packages if str(package).strip()]
    if not missing:
        return None, "No missing AI dependencies were detected."

    bootstrap = os.environ.get("PYLRCGET_AI_BOOTSTRAP_PYTHON", "").strip()
    bootstrap_python = Path(bootstrap).expanduser() if bootstrap else None
    if bootstrap_python is None or not bootstrap_python.is_file():
        if not getattr(sys, "frozen", False) and Path(sys.executable).name.casefold().startswith("python"):
            bootstrap_python = Path(sys.executable)
        else:
            system_python = shutil.which("python")
            bootstrap_python = Path(system_python) if system_python else None
    if bootstrap_python is None:
        return None, "Install Python 3.10-3.13 and set PYLRCGET_AI_BOOTSTRAP_PYTHON."
    if not _is_supported_python(bootstrap_python):
        return None, (
            "The selected AI bootstrap interpreter is unsupported. "
            "Install Python 3.10-3.13 and set PYLRCGET_AI_BOOTSTRAP_PYTHON."
        )

    runtime_dir = os.environ.get("PYLRCGET_AI_RUNTIME_DIR", "").strip()
    runtime_root = Path(runtime_dir).expanduser() if runtime_dir else default_ai_runtime_dir()
    if not getattr(sys, "frozen", False) and tuple(sys.version_info[:2]) >= (3, 14):
        return None, (
            "AI dependencies currently support Python 3.10-3.13. "
            "Use a compatible interpreter via PYLRCGET_AI_BOOTSTRAP_PYTHON."
        )
    script = (
        "import os,subprocess,sys,venv\n"
        f"root={str(runtime_root)!r}\n"
        "venv.EnvBuilder(with_pip=True).create(root)\n"
        "python = root + ('\\\\Scripts\\\\python.exe' if sys.platform == 'win32' else '/bin/python')\n"
        "args=sys.argv[1:]\n"
        "aligner='lyrics-aligner' in args\n"
        "args=[arg for arg in args if arg != 'lyrics-aligner']\n"
        f"aligner_root={str(default_lyrics_aligner_dir())!r}\n"
        "if aligner:\n"
        "    if not os.path.isfile(os.path.join(aligner_root, 'align.py')):\n"
        "        os.makedirs(os.path.dirname(aligner_root), exist_ok=True)\n"
        "        subprocess.check_call(['git', 'clone', "
        "'https://github.com/schufo/lyrics-aligner.git', aligner_root])\n"
        "    subprocess.check_call([python, '-m', 'pip', 'install', 'g2p-en', 'librosa'])\n"
        "cuda='torch-cuda' in args\n"
        "args=[arg for arg in args if arg != 'torch-cuda']\n"
        "if cuda:\n"
        "    subprocess.check_call([python, '-m', 'pip', 'install', "
        "'torch==2.8.0', 'torchaudio==2.8.0', "
        "'--index-url', 'https://download.pytorch.org/whl/cu128'])\n"
        "if args:\n"
        "    raise SystemExit(subprocess.call([python, '-m', 'pip', 'install', *args]))\n"
        "raise SystemExit(0)"
    )
    return [str(bootstrap_python), "-c", script, *missing], ""


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
        candidates = [Path(__file__).resolve().parents[2]]
    for candidate in candidates:
        if (
            (candidate / "ui" / "workers" / "ai_sync_external_entry.py").is_file()
            and (candidate / "ui" / "workers" / "ai_sync_pipeline.py").is_file()
        ):
            return candidate
    return None


__all__ = [
    "available_torch_devices",
    "default_ai_runtime_dir",
    "nvidia_gpu_available",
    "resolve_ai_install_command",
    "resolve_ai_runtime_python",
    "resolve_ai_runtime_source",
    "resolve_torch_device",
]
