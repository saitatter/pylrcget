"""JSON-lines entry point for AI sync in an external Python runtime."""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

from .ai_sync_service import AI_SYNC_PROTOCOL_VERSION


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


class _Emitter:
    def __init__(self, callback):
        self._callback = callback

    def emit(self, *args) -> None:
        self._callback(*args)


class _ExternalWorkerContext:
    _PROGRESS_MARKER = "__AI_SYNC_PROGRESS__"

    def __init__(
        self,
        config: dict[str, object],
        *,
        emit_callback: Callable[[dict[str, object]], None] = _emit,
    ) -> None:
        self.job_id = str(config.get("job_id") or "")
        self._emit_callback = emit_callback
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
        self.progress = _Emitter(
            lambda message: self._emit_callback(
                {"type": "progress", "job_id": self.job_id, "message": message}
            )
        )
        self.completed = _Emitter(
            lambda ok, message, output: self._emit_callback(
                {
                    "type": "completed",
                    "job_id": self.job_id,
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


def _run_one_shot() -> int:
    os.environ["_PYLRCGET_AI_SYNC_CHILD"] = "1"
    config: dict[str, object] = {}
    try:
        config = json.loads(sys.stdin.readline())
        from .ai_sync_pipeline import run_ai_sync_pipeline

        run_ai_sync_pipeline(_ExternalWorkerContext(config))
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "job_id": str(config.get("job_id") or ""), "message": str(exc)})
        return 1
    return 0


def _run_service() -> int:
    os.environ["_PYLRCGET_AI_SYNC_CHILD"] = "1"
    for raw_line in sys.stdin:
        try:
            message: dict[str, Any] = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        message_type = message.get("type")
        job_id = str(message.get("job_id") or "")
        if message_type == "hello":
            _emit(
                {
                    "type": "hello",
                    "job_id": job_id,
                    "protocol_version": AI_SYNC_PROTOCOL_VERSION,
                }
            )
            _emit(
                {
                    "type": "capabilities",
                    "job_id": job_id,
                    "protocol_version": AI_SYNC_PROTOCOL_VERSION,
                    "runtime_python": sys.version.split()[0],
                    "available_devices": ["cpu"],
                    "available_backends": [
                        "legacy-whisperx",
                        "lyrics-aligner",
                    ],
                    "backend_versions": {
                        "legacy-whisperx": "current",
                        "lyrics-aligner": "warm-v1",
                    },
                    "loaded_model_cache": [],
                    "capabilities": [
                        "persistent_runtime",
                        "cached_whisperx_models",
                        "cached_alignment_models",
                        "cached_english_backend",
                    ],
                }
            )
        elif message_type == "align":
            config = dict(message.get("config") or message)
            config["job_id"] = job_id or str(config.get("job_id") or "")
            try:
                from .ai_sync_pipeline import run_ai_sync_pipeline

                run_ai_sync_pipeline(_ExternalWorkerContext(config))
            except Exception as exc:  # noqa: BLE001
                _emit({"type": "error", "job_id": job_id, "message": str(exc)})
        elif message_type == "shutdown":
            _emit(
                {
                    "type": "shutdown",
                    "job_id": job_id,
                    "protocol_version": AI_SYNC_PROTOCOL_VERSION,
                }
            )
            return 0
    return 0


def main() -> int:
    if "--serve" in sys.argv[1:]:
        return _run_service()
    return _run_one_shot()


if __name__ == "__main__":
    raise SystemExit(main())
