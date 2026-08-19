"""Optional AI runtime setup, dependency checks and model caches."""
from __future__ import annotations

import threading

_INFERENCE_CACHE_LOCK = threading.Lock()
_WHISPERX_MODEL_CACHE: dict[tuple[str, str, str, str | None, tuple[tuple[str, float], ...]], object] = {}
_ALIGN_MODEL_CACHE: dict[tuple[str, str], tuple[object, object]] = {}


def _clear_inference_caches() -> None:
    """Clear cached WhisperX/align models (used by tests)."""
    with _INFERENCE_CACHE_LOCK:
        _WHISPERX_MODEL_CACHE.clear()
        _ALIGN_MODEL_CACHE.clear()


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
                except Exception:
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
            except Exception:
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
            except Exception:
                pass

            return orig_load_audio(file, sr=sr)

        _compat_load_audio._patched_for_ffmpeg_fallback = True
        whisperx.audio.load_audio = _compat_load_audio
        try:
            import whisperx
            whisperx.load_audio = _compat_load_audio
        except Exception:
            pass
    except Exception:
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
    except Exception:
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
    except Exception:
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
            return cached
    align_model, metadata = whisperx_module.load_align_model(language_code=normalized_lang, device=device)
    with _INFERENCE_CACHE_LOCK:
        _ALIGN_MODEL_CACHE[key] = (align_model, metadata)
    return align_model, metadata


def _module_available(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def get_missing_ai_dependencies() -> list[str]:
    deps = [
        ("torch", "torch"),
        ("torchaudio", "torchaudio"),
        ("soundfile", "soundfile"),
        ("whisperx", "whisperx"),
    ]
    missing: list[str] = []
    for module, package in deps:
        if not _module_available(module):
            missing.append(package)
    return missing


def _check_ai_sync_available() -> tuple[bool, str]:
    """Check whether the required AI sync dependencies are installed."""
    missing = get_missing_ai_dependencies()
    if missing:
        return False, (
            f"Missing AI dependencies: {', '.join(missing)}.\n\n"
            "If you run PyLrcGet from source, install them in that environment:\n"
            "  pip install .[ai]\n\n"
            "If you use the packaged .exe, install these packages in the app's bundled Python "
            "(installing into system Python is not enough)."
        )
    return True, ""


def is_ai_sync_available() -> bool:
    ok, _ = _check_ai_sync_available()
    return ok


__all__ = [
    "_clear_inference_caches",
    "_canonical_vad_options",
    "_patch_whisperx_audio_loading",
    "_patch_pyannote_compatibility",
    "_patch_faster_whisper_compatibility",
    "_get_cached_whisperx_model",
    "_get_cached_align_model",
    "get_missing_ai_dependencies",
    "_module_available",
    "_check_ai_sync_available",
    "is_ai_sync_available",
]
