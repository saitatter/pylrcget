from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import requests

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


class OfficialTidalLyricsError(RuntimeError):
    """Raised when the official TIDAL lyrics relation cannot be read."""


class OfficialTidalLyricsTransport:
    """Read lyrics exposed by the official TIDAL catalogue API.

    TIDAL exposes lyrics as an optional relationship on the track resource.
    The public API may return an empty relationship for a track; that is a
    clean miss and lets the provider router continue to the next source.
    """

    provider_id = "tidal"
    base_url = "https://openapi.tidal.com/v2"

    def __init__(
        self,
        access_token: str,
        *,
        country_code: str | None = None,
        session: requests.Session | None = None,
        timeout_s: float = 10.0,
        on_rate_limit: Callable[[float], None] | None = None,
    ) -> None:
        self.access_token = str(access_token).strip()
        if not self.access_token:
            raise ValueError("TIDAL access token is required")
        self.country_code = country_code
        self.session = session or requests.Session()
        self.timeout_s = max(0.1, float(timeout_s))
        self.on_rate_limit = on_rate_limit

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
        track: TrackLookupContext | None = None,
        requested_mode: DownloadMode = "prefer_synced",
    ) -> TidalLyricsPayload | None:
        del track, requested_mode
        if cancel_event is not None and cancel_event.is_set():
            return None
        params: dict[str, object] = {"include": "lyrics"}
        country = (self.country_code or "").strip()
        if country and country.casefold() != "auto":
            params["countryCode"] = country.upper()
        try:
            response = self.session.get(
                f"{self.base_url}/tracks/{tidal_track_id}",
                params=params,
                headers={
                    "Accept": "application/vnd.api+json",
                    "Authorization": f"Bearer {self.access_token}",
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise OfficialTidalLyricsError(f"TIDAL lyrics request failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None and self.on_rate_limit is not None:
                self.on_rate_limit(retry_after)
        if response.status_code >= 400:
            detail = (response.text or "")[:300]
            raise OfficialTidalLyricsError(
                f"TIDAL lyrics request failed ({response.status_code}): {detail or 'HTTP error'}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OfficialTidalLyricsError("TIDAL lyrics response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise OfficialTidalLyricsError("TIDAL lyrics response was not a JSON object")
        return _parse_official_lyrics_payload(payload)


class ExternalTidalLyricsTransport:
    """Invoke a user-owned lyrics helper through a versioned JSON protocol."""

    provider_id = "external"
    protocol_version = 1
    default_max_output_bytes = 1_000_000

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_s: float = 30.0,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        poll_interval_s: float = 0.05,
        max_output_bytes: int = default_max_output_bytes,
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
        self.max_output_bytes = int(max_output_bytes)
        if self.max_output_bytes < 1:
            raise ValueError("Helper output limit must be positive")

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
            args=(process, result_holder, request_text + "\n", self.max_output_bytes),
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
        if bool(result_holder.get("output_too_large", False)):
            raise ExternalTidalHelperError(
                f"TIDAL lyrics helper output exceeded {self.max_output_bytes} bytes"
            )
        return self._parse_response(
            stdout,
            stderr=stderr,
            return_code=int(result_holder.get("return_code", process.returncode or 0)),
            tidal_track_id=str(tidal_track_id),
        )

    @staticmethod
    def _communicate(
        process: subprocess.Popen,
        result_holder: dict[str, object],
        input_text: str,
        max_output_bytes: int,
    ) -> None:
        stdout, stderr = process.communicate(input_text)
        output_too_large = any(
            len(value.encode("utf-8", errors="replace")) > max_output_bytes
            for value in (stdout or "", stderr or "")
        )
        result_holder.update(
            stdout=stdout or "",
            stderr=stderr or "",
            output_too_large=output_too_large,
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


def _parse_official_lyrics_payload(payload: dict[str, object]) -> TidalLyricsPayload | None:
    """Accept the JSON:API relationship shape and tolerate future field names."""

    objects: list[dict[str, object]] = []
    data = payload.get("data")
    if isinstance(data, dict):
        objects.append(data)
        relationships = data.get("relationships")
        if isinstance(relationships, dict):
            lyrics_relationship = relationships.get("lyrics")
            if isinstance(lyrics_relationship, dict):
                relation_data = lyrics_relationship.get("data")
                if isinstance(relation_data, dict):
                    objects.append(relation_data)
                elif isinstance(relation_data, list):
                    objects.extend(item for item in relation_data if isinstance(item, dict))
    included = payload.get("included")
    if isinstance(included, list):
        objects.extend(item for item in included if isinstance(item, dict))

    plain: str | None = None
    synced: str | None = None
    for item in objects:
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            attributes = item
        synced = synced or _first_text(
            attributes,
            "lrcText",
            "lrc_text",
            "syncedLyrics",
            "synced_lyrics",
            "subtitles",
        )
        plain = plain or _first_text(
            attributes,
            "plainText",
            "plain_text",
            "plainLyrics",
            "plain_lyrics",
        )
        if plain is None:
            generic = _first_text(attributes, "lyrics", "text")
            if generic:
                if _looks_synced(generic):
                    synced = synced or generic
                else:
                    plain = generic
    if not plain and not synced:
        return None
    return TidalLyricsPayload(plain_lyrics=plain, synced_lyrics=synced, source="official")


def _first_text(attributes: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = _optional_text(attributes.get(key))
        if value:
            return value
    return None


def _looks_synced(value: str) -> bool:
    return bool(re.search(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]", value))


def _retry_after_seconds(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
