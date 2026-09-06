"""Persistent external AI runtime client.

The application keeps one local runtime process per Python/source/device
combination.  The service is intentionally line-delimited JSON over pipes;
there is no listening socket and no network server involved.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

AI_SYNC_PROTOCOL_VERSION = 1
_SERVICE_START_TIMEOUT = 30.0
_SERVICE_MESSAGE_TIMEOUT = 0.2


def build_runtime_environment(source_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for variable in (
        "PYTHONHOME",
        "PYTHONEXECUTABLE",
        "PYTHONUSERBASE",
        "PYTHONPATH",
    ):
        environment.pop(variable, None)
    environment["PYTHONPATH"] = str(source_root)
    return environment


class PersistentAIRuntime:
    """A serialized request client for one warm external AI process."""

    def __init__(
        self,
        python_path: Path,
        source_root: Path,
        *,
        device: str,
        process_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.python_path = Path(python_path)
        self.source_root = Path(source_root)
        self.device = str(device or "auto")
        self._process_factory = process_factory
        self._process: Any | None = None
        self._messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._capabilities: list[str] = []

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def capabilities(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._capabilities)

    def run(
        self,
        config: dict[str, Any],
        *,
        on_progress: Callable[[str], None],
        is_cancelled: Callable[[], bool],
    ) -> tuple[bool, str, str]:
        """Run one alignment and keep the process alive after completion."""
        with self._lock:
            self._ensure_started_locked()
            job_id = str(config.get("job_id") or uuid.uuid4().hex)
            request = dict(config)
            request["job_id"] = job_id
            self._send_locked({"type": "align", "job_id": job_id, "config": request})
            while True:
                if is_cancelled():
                    self._terminate_locked()
                    return False, "Cancelled.", ""
                message = self._next_message_locked()
                if message is None:
                    self._terminate_locked()
                    raise RuntimeError("Persistent AI runtime exited unexpectedly.")
                if message.get("job_id") not in (None, "", job_id):
                    logger.debug("Ignoring AI runtime message for another job: %s", message)
                    continue
                message_type = message.get("type")
                if message_type == "progress":
                    on_progress(str(message.get("message", "")))
                elif message_type == "completed":
                    return (
                        bool(message.get("ok")),
                        str(message.get("message", "")),
                        str(message.get("output", "")),
                    )
                elif message_type == "error":
                    return False, str(message.get("message", "")), ""

    def shutdown(self) -> None:
        with self._lock:
            if self._process is None:
                return
            try:
                if self._process.poll() is None:
                    self._send_locked(
                        {
                            "type": "shutdown",
                            "job_id": uuid.uuid4().hex,
                            "protocol_version": AI_SYNC_PROTOCOL_VERSION,
                        }
                    )
                    try:
                        self._process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self._terminate_locked()
            except (BrokenPipeError, OSError, RuntimeError):
                self._terminate_locked()
            finally:
                self._close_process_handles_locked()

    def terminate(self) -> None:
        """Hard-stop the runtime after cancellation or an IPC failure."""
        with self._lock:
            self._terminate_locked()

    def _ensure_started_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._close_process_handles_locked()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = self._process_factory(
                [
                    str(self.python_path),
                    "-m",
                    "ui.workers.ai_sync_external_entry",
                    "--serve",
                ],
                cwd=str(self.source_root.parent),
                env=build_runtime_environment(self.source_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start persistent AI runtime: {exc}") from exc
        self._process = process
        self._messages = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_output,
            args=(process,),
            name="pylrcget-ai-runtime-reader",
            daemon=True,
        )
        self._reader.start()
        try:
            self._send_locked(
                {
                    "type": "hello",
                    "job_id": uuid.uuid4().hex,
                    "protocol_version": AI_SYNC_PROTOCOL_VERSION,
                }
            )
            hello = self._wait_for_type_locked("hello", _SERVICE_START_TIMEOUT)
            if int(hello.get("protocol_version", 0)) != AI_SYNC_PROTOCOL_VERSION:
                raise RuntimeError("Persistent AI runtime protocol version mismatch.")
            capabilities = self._wait_for_type_locked("capabilities", _SERVICE_START_TIMEOUT)
            self._capabilities = [str(item) for item in capabilities.get("capabilities", [])]
        except Exception:
            self._terminate_locked()
            raise

    def _read_output(self, process: Any) -> None:
        stdout = getattr(process, "stdout", None)
        if stdout is None:
            self._messages.put(None)
            return
        try:
            for line in stdout:
                try:
                    message = json.loads(str(line))
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON persistent AI runtime output: %s", line.rstrip())
                    continue
                if isinstance(message, dict):
                    self._messages.put(message)
        finally:
            self._messages.put(None)

    def _send_locked(self, message: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Persistent AI runtime is not connected.")
        self._process.stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
        self._process.stdin.flush()

    def _next_message_locked(self) -> dict[str, Any] | None:
        while True:
            try:
                return self._messages.get(timeout=_SERVICE_MESSAGE_TIMEOUT)
            except queue.Empty:
                if self._process is None or self._process.poll() is not None:
                    return None

    def _wait_for_type_locked(self, expected: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                message = self._messages.get(timeout=min(_SERVICE_MESSAGE_TIMEOUT, remaining))
            except queue.Empty:
                if self._process is None or self._process.poll() is not None:
                    break
                continue
            if message is None:
                break
            if message.get("type") == expected:
                return message
        raise RuntimeError(f"Persistent AI runtime did not send {expected!r}.")

    def _terminate_locked(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self._close_process_handles_locked()

    def _close_process_handles_locked(self) -> None:
        process = self._process
        if process is None:
            return
        for stream_name in ("stdin", "stdout"):
            stream = getattr(process, stream_name, None)
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._process = None
        self._reader = None
        self._capabilities = []


_SERVICES_LOCK = threading.Lock()
_SERVICES: dict[tuple[str, str, str], PersistentAIRuntime] = {}


def get_persistent_ai_runtime(
    python_path: Path,
    source_root: Path,
    *,
    device: str,
) -> PersistentAIRuntime:
    key = (str(Path(python_path).resolve()), str(Path(source_root).resolve()), str(device or "auto"))
    with _SERVICES_LOCK:
        service = _SERVICES.get(key)
        if service is None:
            service = PersistentAIRuntime(Path(python_path), Path(source_root), device=device)
            _SERVICES[key] = service
        return service


def shutdown_all_ai_runtimes() -> None:
    with _SERVICES_LOCK:
        services = list(_SERVICES.values())
        _SERVICES.clear()
    for service in services:
        service.shutdown()


atexit.register(shutdown_all_ai_runtimes)


__all__ = [
    "AI_SYNC_PROTOCOL_VERSION",
    "PersistentAIRuntime",
    "build_runtime_environment",
    "get_persistent_ai_runtime",
    "shutdown_all_ai_runtimes",
]
