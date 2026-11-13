"""Optional AI runtime setup, dependency checks and model caches."""
from __future__ import annotations

import subprocess
import threading
from collections import OrderedDict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .ai_dependencies import AI_PACKAGE_REQUIREMENTS
from .ai_runtime import default_ai_nltk_dir, resolve_ai_runtime_python
from .ai_sync_lyrics_aligner import is_available as _lyrics_aligner_available

_INFERENCE_CACHE_LOCK = threading.Lock()
_WHISPERX_MODEL_CACHE: OrderedDict[
    tuple[str, str, str, str | None, tuple[tuple[str, float], ...]], object
] = OrderedDict()
_ALIGN_MODEL_CACHE: OrderedDict[tuple[str, str], tuple[object, object]] = OrderedDict()
_CACHE_STATS = {
    "whisperx_hits": 0,
    "whisperx_loads": 0,
    "whisperx_evictions": 0,
    "align_hits": 0,
    "align_loads": 0,
    "align_evictions": 0,
}


def _cuda_compute_capability() -> tuple[int, int] | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        capability = torch.cuda.get_device_capability()
        return int(capability[0]), int(capability[1])
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _preferred_whisper_compute_type(device: str) -> str:
    """Choose a CTranslate2 type supported by the selected accelerator."""
    if device != "cuda":
        return "int8"
    capability = _cuda_compute_capability()
    if capability is not None and capability[0] < 7:
        # Pascal and older GPUs cannot run CTranslate2's efficient FP16 path.
        return "int8_float32"
    return "float16"


def _clear_inference_caches() -> None:
    """Clear cached WhisperX/align models (used by tests)."""
    with _INFERENCE_CACHE_LOCK:
        _WHISPERX_MODEL_CACHE.clear()
        _ALIGN_MODEL_CACHE.clear()
        for key in _CACHE_STATS:
            _CACHE_STATS[key] = 0


def _cache_limit(name: str, default: int) -> int:
    import os

    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def get_inference_cache_stats() -> dict[str, int]:
    with _INFERENCE_CACHE_LOCK:
        return dict(_CACHE_STATS)


def _evict_whisperx_if_needed() -> None:
    limit = _cache_limit("PYLRCGET_AI_WHISPER_CACHE_SIZE", 4)
    while len(_WHISPERX_MODEL_CACHE) > limit:
        _WHISPERX_MODEL_CACHE.popitem(last=False)
        _CACHE_STATS["whisperx_evictions"] += 1


def _evict_align_if_needed() -> None:
    limit = _cache_limit("PYLRCGET_AI_ALIGN_CACHE_SIZE", 8)
    while len(_ALIGN_MODEL_CACHE) > limit:
        _ALIGN_MODEL_CACHE.popitem(last=False)
        _CACHE_STATS["align_evictions"] += 1


def _canonical_vad_options(vad_options: dict | None) -> tuple[tuple[str, float], ...]:
    if not vad_options:
        return ()
    normalized: list[tuple[str, float]] = []
    for key in sorted(vad_options):
        try:
            normalized.append((str(key), float(vad_options[key])))
        except (TypeError, ValueError):
            continue
    return tuple(normalized)


def _patch_whisperx_audio_loading() -> None:
    try:
        import shutil

        import whisperx.audio
        orig_load_audio = whisperx.audio.load_audio

        if getattr(orig_load_audio, "_patched_for_ffmpeg_fallback", False):
            return

        def _compat_load_audio(file: str, sr: int = 16000):
            if shutil.which("ffmpeg"):
                try:
                    return orig_load_audio(file, sr=sr)
                except Exception:  # noqa: BLE001, S110
                    pass

            try:
                import soundfile as sf
                data, sample_rate = sf.read(file, dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                if sample_rate != sr:
                    import torch
                    import torchaudio.transforms as T
                    tensor = torch.from_numpy(data).unsqueeze(0)
                    resampler = T.Resample(orig_freq=sample_rate, new_freq=sr)
                    data = resampler(tensor).squeeze(0).numpy()
                return data
            except Exception:  # noqa: BLE001, S110
                pass

            try:
                import torch
                import torchaudio
                import torchaudio.transforms as T
                waveform, sample_rate = torchaudio.load(file)
                if waveform.ndim > 1 and waveform.shape[0] > 1:
                    waveform = waveform.mean(dim=0, keepdim=True)
                if sample_rate != sr:
                    resampler = T.Resample(orig_freq=sample_rate, new_freq=sr)
                    waveform = resampler(waveform)
                return waveform.squeeze(0).numpy().astype("float32")
            except Exception:  # noqa: BLE001, S110
                pass

            return orig_load_audio(file, sr=sr)

        _compat_load_audio._patched_for_ffmpeg_fallback = True
        whisperx.audio.load_audio = _compat_load_audio
        try:
            import whisperx
            whisperx.load_audio = _compat_load_audio
        except Exception:  # noqa: BLE001, S110
            pass
    except Exception:  # noqa: BLE001, S110
        pass


def _patch_pyannote_compatibility() -> None:
    try:
        import pyannote.audio.core.inference
        orig_init = pyannote.audio.core.inference.Inference.__init__
        if getattr(orig_init, "_patched_for_whisperx", False):
            return

        def _compat_init(self, *args, **kwargs):
            kwargs.pop("use_auth_token", None)
            orig_init(self, *args, **kwargs)

        _compat_init._patched_for_whisperx = True
        pyannote.audio.core.inference.Inference.__init__ = _compat_init
    except Exception:  # noqa: BLE001, S110
        pass


def _patch_faster_whisper_compatibility() -> None:
    try:
        import faster_whisper.transcribe
        orig_init = faster_whisper.transcribe.TranscriptionOptions.__init__
        if getattr(orig_init, "_patched_for_whisperx", False):
            return

        def _compat_init(self, *args, **kwargs):
            if "multilingual" not in kwargs:
                kwargs["multilingual"] = False
            if "hotwords" not in kwargs:
                kwargs["hotwords"] = None
            orig_init(self, *args, **kwargs)

        _compat_init._patched_for_whisperx = True
        faster_whisper.transcribe.TranscriptionOptions.__init__ = _compat_init
    except Exception:  # noqa: BLE001, S110
        pass


def _get_cached_whisperx_model(
    whisperx_module: object,
    model_name: str,
    *,
    device: str,
    compute_type: str,
    vad_method: str | None = None,
    vad_options: dict | None = None,
) -> object:
    """
    Return WhisperX model from in-process cache to avoid repeated load_model cost.
    """
    _patch_whisperx_audio_loading()
    _patch_faster_whisper_compatibility()
    _patch_pyannote_compatibility()
    key = (
        str(model_name or "base"),
        str(device),
        str(compute_type),
        str(vad_method) if vad_method else None,
        _canonical_vad_options(vad_options),
    )
    with _INFERENCE_CACHE_LOCK:
        cached = _WHISPERX_MODEL_CACHE.get(key)
        if cached is not None:
            _WHISPERX_MODEL_CACHE.move_to_end(key)
            _CACHE_STATS["whisperx_hits"] += 1
            return cached

    import inspect
    load_model_params = set(inspect.signature(whisperx_module.load_model).parameters.keys())
    kwargs: dict = {
        "device": device,
        "compute_type": compute_type,
    }
    if vad_method and "vad_method" in load_model_params:
        kwargs["vad_method"] = vad_method
    if vad_options and "vad_options" in load_model_params:
        kwargs["vad_options"] = vad_options
    model = whisperx_module.load_model(model_name, **kwargs)
    with _INFERENCE_CACHE_LOCK:
        _WHISPERX_MODEL_CACHE[key] = model
        _WHISPERX_MODEL_CACHE.move_to_end(key)
        _CACHE_STATS["whisperx_loads"] += 1
        _evict_whisperx_if_needed()
    return model


def _get_cached_align_model(
    whisperx_module: object,
    *,
    language_code: str,
    device: str,
) -> tuple[object, object]:
    """
    Return align model/metadata from in-process cache by (language, device).
    """
    normalized_lang = str(language_code or "en").strip().lower() or "en"
    if normalized_lang == "auto":
        normalized_lang = "en"
    key = (normalized_lang, str(device))
    with _INFERENCE_CACHE_LOCK:
        cached = _ALIGN_MODEL_CACHE.get(key)
        if cached is not None:
            _ALIGN_MODEL_CACHE.move_to_end(key)
            _CACHE_STATS["align_hits"] += 1
            return cached
    align_model, metadata = whisperx_module.load_align_model(language_code=normalized_lang, device=device)
    with _INFERENCE_CACHE_LOCK:
        _ALIGN_MODEL_CACHE[key] = (align_model, metadata)
        _ALIGN_MODEL_CACHE.move_to_end(key)
        _CACHE_STATS["align_loads"] += 1
        _evict_align_if_needed()
    return align_model, metadata


def _module_available(module: str) -> bool:
    try:
        __import__(module)
    except (ImportError, OSError, AttributeError, RuntimeError):
        return False
    return True


def _supported_package_version(package: str) -> bool:
    expected = AI_PACKAGE_REQUIREMENTS[package].split("==", 1)[1]
    try:
        return version(package).split("+", 1)[0] == expected
    except PackageNotFoundError:
        return False


def _english_pronunciation_available(executable: Path | None) -> bool:
    script = (
        "import importlib.util,sys\n"
        "if any(importlib.util.find_spec(name) is None for name in ['g2p_en','librosa','nltk']):\n"
        "    raise SystemExit(1)\n"
        "import nltk\n"
        f"nltk.data.path.insert(0, {str(default_ai_nltk_dir())!r})\n"
        "for resource in ['corpora/cmudict', 'taggers/averaged_perceptron_tagger.zip', "
        "'taggers/averaged_perceptron_tagger_eng']:\n"
        "    nltk.data.find(resource)\n"
    )
    if executable is not None:
        try:
            result = subprocess.run([str(executable), "-c", script], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
    try:
        import importlib.util

        if any(importlib.util.find_spec(name) is None for name in ("g2p_en", "librosa", "nltk")):
            return False
        import nltk

        data_dir = str(default_ai_nltk_dir())
        if data_dir not in nltk.data.path:
            nltk.data.path.insert(0, data_dir)
        for resource in ("corpora/cmudict", "taggers/averaged_perceptron_tagger.zip", "taggers/averaged_perceptron_tagger_eng"):
            nltk.data.find(resource)
    except (ImportError, LookupError, ValueError):
        return False
    return True


def get_missing_ai_dependencies(
    *,
    prefer_cuda: bool = False,
    require_lyrics_aligner: bool = False,
    require_demucs: bool = False,
) -> list[str]:
    deps = [
        ("torch", "torch"),
        ("torchaudio", "torchaudio"),
        ("soundfile", "soundfile"),
        ("whisperx", "whisperx"),
    ]
    external_python = resolve_ai_runtime_python()
    if external_python is not None:
        packages = [package for _module, package in deps]
        expected = {package: AI_PACKAGE_REQUIREMENTS[package].split("==", 1)[1] for package in packages}
        probe = (
            "import importlib.util\n"
            "from importlib.metadata import version, PackageNotFoundError\n"
            f"expected={expected!r}\n"
            "missing=[]\n"
            "for name, pinned in expected.items():\n"
            "    try:\n"
            "        if importlib.util.find_spec(name) is None or version(name).split('+', 1)[0] != pinned:\n"
            "            missing.append(name)\n"
            "    except PackageNotFoundError:\n"
            "        missing.append(name)\n"
            "print('\\n'.join(missing))"
        )
        result = subprocess.run(
            [str(external_python), "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            missing = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if prefer_cuda and not _cuda_runtime_available(external_python):
                missing.append("torch-cuda")
            if require_lyrics_aligner and (
                not _lyrics_aligner_available() or not _english_pronunciation_available(external_python)
            ):
                missing.append("lyrics-aligner")
            if require_demucs and not _module_available_in_runtime(external_python, "demucs"):
                missing.append("demucs")
            return missing
        return packages

    missing: list[str] = []
    for module, package in deps:
        if not _module_available(module) or not _supported_package_version(package):
            missing.append(package)
    if prefer_cuda and not _cuda_runtime_available(None):
        missing.append("torch-cuda")
    if require_lyrics_aligner and (
        not _lyrics_aligner_available() or not _english_pronunciation_available(None)
    ):
        missing.append("lyrics-aligner")
    if require_demucs and not _module_available("demucs"):
        missing.append("demucs")
    return missing


def _module_available_in_runtime(executable: Path, module: str) -> bool:
    result = subprocess.run(
        [str(executable), "-c", f"import {module}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _cuda_runtime_available(external_python) -> bool:
    if external_python is None:
        try:
            import torch

            return bool(torch.version.cuda and torch.cuda.is_available())
        except (ImportError, AttributeError, RuntimeError):
            return False
    result = subprocess.run(
        [
            str(external_python),
            "-c",
            "import torch; print(bool(torch.version.cuda and torch.cuda.is_available()))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _check_ai_sync_available() -> tuple[bool, str]:
    """Check whether the required AI sync dependencies are installed."""
    missing = get_missing_ai_dependencies()
    if missing:
        return False, (
            f"Missing AI dependencies: {', '.join(missing)}.\n\n"
            "If you run PyLrcGet from source, install them in that environment:\n"
            "  pip install .[ai]\n\n"
            "If you use a packaged app, select Install missing dependencies in this "
            "dialog. PyLrcGet downloads and sets up everything automatically; "
            "you do not need to install Python separately. You can also open "
            "Settings > AI Sync > Manage AI runtime."
        )
    return True, ""


def is_ai_sync_available() -> bool:
    ok, _ = _check_ai_sync_available()
    return ok


__all__ = [
    "_canonical_vad_options",
    "_check_ai_sync_available",
    "_clear_inference_caches",
    "_get_cached_align_model",
    "_get_cached_whisperx_model",
    "_module_available",
    "_patch_faster_whisper_compatibility",
    "_patch_pyannote_compatibility",
    "_patch_whisperx_audio_loading",
    "_preferred_whisper_compute_type",
    "get_inference_cache_stats",
    "get_missing_ai_dependencies",
    "is_ai_sync_available",
]
