"""JSON-lines entry point for AI sync in an external Python runtime."""
from __future__ import annotations

import json
import os
import sys


class _Emitter:
    def __init__(self, callback):
        self._callback = callback

    def emit(self, *args) -> None:
        self._callback(*args)


class _ExternalWorkerContext:
    _PROGRESS_MARKER = "__AI_SYNC_PROGRESS__"

    def __init__(self, config: dict[str, object]) -> None:
        self.audio_path = str(config["audio_path"])
        self.plain_lyrics = str(config.get("plain_lyrics") or "")
        self.manual_anchors = list(config.get("manual_anchors") or [])
        self.whisper_model = str(config.get("whisper_model") or "base")
        self._device = str(config.get("device") or "auto")
        self._language = str(config.get("language") or "auto")
        self._enable_fuzzy = bool(config.get("enable_fuzzy", True))
        self._fuzzy_threshold = int(config.get("fuzzy_threshold", 60))
        self._fuzzy_window_words = int(config.get("fuzzy_window_words", 12))
        self._enable_demucs_candidate = bool(config.get("enable_demucs_candidate", True))
        self.progress = _Emitter(lambda message: _emit({"type": "progress", "message": message}))
        self.completed = _Emitter(
            lambda ok, message, output: _emit(
                {
                    "type": "completed",
                    "ok": bool(ok),
                    "message": str(message),
                    "output": str(output),
                }
            )
        )

    def _resolve_device(self) -> str:
        import torch

        if self._device and self._device != "auto":
            if self._device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError(
                    "CUDA was selected, but the external Torch runtime has no CUDA support. "
                    "Install a CUDA-enabled Torch build or select Auto/CPU."
                )
            return self._device
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _emit_stage(self, current: int, total: int, message: str) -> None:
        self.progress.emit(f"{self._PROGRESS_MARKER}|{int(current)}|{int(total)}|{message}")

    def isInterruptionRequested(self) -> bool:
        return False


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main() -> int:
    os.environ["_PYLRCGET_AI_SYNC_CHILD"] = "1"
    try:
        config = json.loads(sys.stdin.readline())
        from .ai_sync_pipeline import run_ai_sync_pipeline

        run_ai_sync_pipeline(_ExternalWorkerContext(config))
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "message": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
