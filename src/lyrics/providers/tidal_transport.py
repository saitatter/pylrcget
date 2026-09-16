from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .contracts import DownloadMode, TrackLookupContext


@dataclass(slots=True)
class TidalLyricsPayload:
    plain_lyrics: str | None
    synced_lyrics: str | None
    source: str | None = None


class TidalLyricsTransport(Protocol):
    """Lyrics transport kept independent from TIDAL catalogue resolution."""

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
        track: TrackLookupContext | None = None,
        requested_mode: DownloadMode = "prefer_synced",
    ) -> TidalLyricsPayload | None:
        ...


class ExternalTidalHelperError(RuntimeError):
    """Raised when an external TIDAL lyrics helper cannot be used safely."""


class ExternalTidalLyricsTransport:
    """Invoke a user-owned lyrics helper through a versioned JSON protocol."""

    provider_id = "external"
    protocol_version = 1

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_s: float = 30.0,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        poll_interval_s: float = 0.05,
    ) -> None:
        if isinstance(command, (str, bytes)):
            raise TypeError("Helper command must be an argv sequence, not a shell string")
        self.command = tuple(str(part) for part in command)
        if not self.command or any(not part for part in self.command):
            raise ValueError("Helper command must contain at least one non-empty argv item")
        self.timeout_s = max(0.01, float(timeout_s))
        self.cwd = cwd
        self.env = dict(env) if env is not None else None
        self.poll_interval_s = max(0.01, float(poll_interval_s))

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
        track: TrackLookupContext | None = None,
        requested_mode: DownloadMode = "prefer_synced",
    ) -> TidalLyricsPayload | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        request = self._build_request(
            tidal_track_id,
            track=track,
            requested_mode=requested_mode,
        )
        try:
            process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.cwd,
                env=self.env,
                shell=False,
            )
        except OSError as exc:
            raise ExternalTidalHelperError(f"Could not start TIDAL lyrics helper: {exc}") from exc

        request_text = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        result_holder: dict[str, object] = {}
        communication = threading.Thread(
            target=self._communicate,
            args=(process, result_holder, request_text + "\n"),
            daemon=True,
        )
        communication.start()
        deadline = time.monotonic() + self.timeout_s
        while communication.is_alive():
            if cancel_event is not None and cancel_event.is_set():
                self._stop_process(process)
                communication.join()
                return None
            if time.monotonic() >= deadline:
                self._stop_process(process)
                communication.join()
                raise ExternalTidalHelperError(
                    f"TIDAL lyrics helper timed out after {self.timeout_s:g}s"
                )
            communication.join(timeout=self.poll_interval_s)

        stdout = str(result_holder.get("stdout", ""))
        stderr = str(result_holder.get("stderr", ""))
        return self._parse_response(
            stdout,
            stderr=stderr,
            return_code=int(result_holder.get("return_code", process.returncode or 0)),
            tidal_track_id=str(tidal_track_id),
        )

    @staticmethod
    def _communicate(process: subprocess.Popen, result_holder: dict[str, object], input_text: str) -> None:
        stdout, stderr = process.communicate(input_text)
        result_holder.update(
            stdout=stdout or "",
            stderr=stderr or "",
            return_code=process.returncode if process.returncode is not None else 0,
        )

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _build_request(
        self,
        tidal_track_id: str,
        *,
        track: TrackLookupContext | None,
        requested_mode: DownloadMode,
    ) -> dict[str, object]:
        track_payload: dict[str, object] = {
            "title": track.title if track is not None else None,
            "artists": list(track.artists) if track is not None else [],
            "album": track.album if track is not None else None,
            "duration_seconds": track.duration_seconds if track is not None else None,
            "isrc": track.isrc if track is not None else None,
        }
        return {
            "protocol_version": self.protocol_version,
            "provider": "tidal",
            "track": track_payload,
            "provider_track_id": str(tidal_track_id),
            "requested_mode": requested_mode,
        }

    @staticmethod
    def _parse_response(
        stdout: str,
        *,
        stderr: str,
        return_code: int,
        tidal_track_id: str,
    ) -> TidalLyricsPayload | None:
        if return_code != 0:
            detail = stderr.strip()[:500] or f"exit code {return_code}"
            raise ExternalTidalHelperError(f"TIDAL lyrics helper failed: {detail}")
        try:
            payload = json.loads(stdout)
        except (TypeError, ValueError) as exc:
            raise ExternalTidalHelperError("TIDAL lyrics helper returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ExternalTidalHelperError("TIDAL lyrics helper returned a non-object JSON value")
        if payload.get("protocol_version") not in (None, 1):
            raise ExternalTidalHelperError("Unsupported TIDAL lyrics helper protocol version")
        if payload.get("provider") not in (None, "tidal"):
            raise ExternalTidalHelperError("TIDAL lyrics helper returned the wrong provider")
        if payload.get("ok") is False:
            error = str(payload.get("error") or "helper_error").casefold()
            if error in {"not_found", "no_lyrics", "unsupported"}:
                return None
            message = str(payload.get("message") or error).strip()[:500]
            raise ExternalTidalHelperError(f"TIDAL lyrics helper rejected request: {message}")
        if payload.get("ok") is not True:
            raise ExternalTidalHelperError("TIDAL lyrics helper response is missing ok=true")

        response_track_id = payload.get("provider_track_id", tidal_track_id)
        if str(response_track_id) != tidal_track_id:
            raise ExternalTidalHelperError("TIDAL lyrics helper returned a mismatched track id")
        plain = _optional_text(payload.get("plain_lyrics"))
        synced = _optional_text(payload.get("synced_lyrics"))
        if not plain and not synced:
            return None
        return TidalLyricsPayload(
            plain_lyrics=plain,
            synced_lyrics=synced,
            source=_optional_text(payload.get("source")) or "external",
        )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExternalTidalHelperError("TIDAL lyrics helper lyrics fields must be strings or null")
    return value.strip() or None
