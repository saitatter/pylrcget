from __future__ import annotations

import json
import os
import platform
import queue
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


# -----------------------------
# Utilities
# -----------------------------

def _is_windows() -> bool:
    return os.name == "nt"


def _default_ipc_endpoint(app_name: str = "lrcget-mpv") -> str:
    """
    Returns a platform-appropriate IPC endpoint.
    Windows: named pipe path for mpv: \\.\pipe\<name>
    Unix:    filesystem path to a unix socket
    """
    if _is_windows():
        # mpv expects \\.\pipe\something
        return rf"\\.\pipe\{app_name}"
    else:
        # Use /tmp by default; safe for portable tooling.
        return f"/tmp/{app_name}.sock"


def _remove_unix_socket_if_exists(path: str) -> None:
    if _is_windows():
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        # If the socket is stale but locked, mpv will fail. Caller can handle.
        pass


def _find_mpv_binary(preferred_path: Optional[str] = None) -> Optional[str]:
    """
    Locate mpv binary. Priority:
      1) preferred_path if exists
      2) common bundled locations relative to cwd
      3) system PATH ("mpv")
    """
    candidates: list[str] = []

    if preferred_path:
        candidates.append(preferred_path)

    # Common portable layout (adjust to your repo):
    # third_party/mpv/windows/mpv.exe
    # third_party/mpv/linux/mpv
    # third_party/mpv/macos/mpv
    cwd = os.getcwd()
    sys_name = platform.system().lower()

    if _is_windows():
        candidates += [
            os.path.join(cwd, "third_party", "mpv", "windows", "mpv.exe"),
            os.path.join(cwd, "third_party", "mpv", "mpv.exe"),
        ]
    elif sys_name == "darwin":
        candidates += [
            os.path.join(cwd, "third_party", "mpv", "macos", "mpv"),
            os.path.join(cwd, "third_party", "mpv", "mpv"),
        ]
    else:
        candidates += [
            os.path.join(cwd, "third_party", "mpv", "linux", "mpv"),
            os.path.join(cwd, "third_party", "mpv", "mpv"),
        ]

    # Finally, rely on PATH
    candidates.append("mpv")

    for c in candidates:
        try:
            if c == "mpv":
                # Let subprocess resolve it from PATH
                return "mpv"
            if os.path.isfile(c):
                return c
        except OSError:
            continue

    return None


# -----------------------------
# IPC Client (transport layer)
# -----------------------------

class _MpvJsonIpcTransport:
    """
    A small transport that connects to mpv IPC endpoint and sends/receives JSON lines.

    On Unix: uses AF_UNIX socket
    On Windows: mpv uses named pipe paths; we still connect via AF_UNIX? No.
      mpv named pipe on Windows is not an AF_UNIX socket.
      The reliable approach is to open the named pipe as a file handle.

    So we implement:
      - Windows: open pipe with CreateFile semantics via builtin open() retry loop.
      - Unix: connect socket.
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._stop = threading.Event()

        self._rx_thread: Optional[threading.Thread] = None
        self._rx_queue: "queue.Queue[dict[str, Any]]" = queue.Queue()

        self._tx_lock = threading.Lock()

        # Windows pipe handle (file-like)
        self._pipe_fh = None

        # Unix socket
        self._sock: Optional[socket.socket] = None

    def connect(self, timeout_s: float = 3.0) -> None:
        deadline = time.time() + timeout_s

        if _is_windows():
            # Wait for pipe to appear, then open it as a file.
            # mpv pipe path looks like: \\.\pipe\name
            # Python open() can open this path directly in binary mode.
            last_err: Optional[Exception] = None
            while time.time() < deadline and not self._stop.is_set():
                try:
                    self._pipe_fh = open(self.endpoint, "r+b", buffering=0)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.05)
            if self._pipe_fh is None:
                raise OSError(f"Failed to open mpv named pipe: {self.endpoint}. Last error: {last_err!r}")
        else:
            last_err: Optional[Exception] = None
            while time.time() < deadline and not self._stop.is_set():
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(self.endpoint)
                    self._sock = s
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.05)
            if self._sock is None:
                raise OSError(f"Failed to connect mpv unix socket: {self.endpoint}. Last error: {last_err!r}")

        # Start RX thread
        self._rx_thread = threading.Thread(target=self._rx_loop, name="mpv-ipc-rx", daemon=True)
        self._rx_thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self._sock.close()
        finally:
            self._sock = None

        try:
            if self._pipe_fh:
                try:
                    self._pipe_fh.close()
                except Exception:
                    pass
        finally:
            self._pipe_fh = None

    def send(self, payload: dict[str, Any]) -> None:
        """
        Send a single JSON command line to mpv.
        """
        line = (json.dumps(payload) + "\n").encode("utf-8")

        with self._tx_lock:
            if _is_windows():
                if not self._pipe_fh:
                    raise RuntimeError("mpv pipe not connected")
                self._pipe_fh.write(line)
                self._pipe_fh.flush()
            else:
                if not self._sock:
                    raise RuntimeError("mpv socket not connected")
                self._sock.sendall(line)

    def recv_nowait(self) -> Optional[dict[str, Any]]:
        try:
            return self._rx_queue.get_nowait()
        except queue.Empty:
            return None

    def _rx_loop(self) -> None:
        """
        Read JSON lines and push them into a queue.
        """
        buf = b""
        try:
            while not self._stop.is_set():
                chunk = b""
                if _is_windows():
                    if not self._pipe_fh:
                        break
                    try:
                        chunk = self._pipe_fh.read(4096)
                    except Exception:
                        break
                else:
                    if not self._sock:
                        break
                    try:
                        chunk = self._sock.recv(4096)
                    except Exception:
                        break

                if not chunk:
                    # EOF
                    break

                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8", errors="replace"))
                        if isinstance(msg, dict):
                            self._rx_queue.put(msg)
                    except Exception:
                        # Ignore malformed line
                        continue
        finally:
            # If RX loop exits, signal close
            self._stop.set()


# -----------------------------
# Backend (mpv process + JSON protocol)
# -----------------------------

@dataclass
class MpvBackendConfig:
    mpv_path: Optional[str] = None
    ipc_endpoint: Optional[str] = None
    start_paused: bool = False

    # mpv tuning
    audio_only: bool = True
    keep_open: bool = False

    # If you bundle mpv, you might want to force a working directory for relative assets.
    cwd: Optional[str] = None


class MpvIpcBackend:
    """
    A minimal mpv backend controlled through JSON IPC.

    You can integrate this with your Qt Player wrapper by:
      - polling backend.process_messages() on a QTimer
      - using callbacks to emit signals
    """

    def __init__(self, config: Optional[MpvBackendConfig] = None):
        self.config = config or MpvBackendConfig()

        self._mpv_bin = _find_mpv_binary(self.config.mpv_path)
        if not self._mpv_bin:
            raise FileNotFoundError("mpv binary not found (bundled or on PATH).")

        self.ipc = self.config.ipc_endpoint or _default_ipc_endpoint()

        # Process handle
        self._proc: Optional[subprocess.Popen] = None

        # JSON request/response correlation
        self._req_id = 0
        self._pending: dict[int, "queue.Queue[dict[str, Any]]"] = {}

        # Property observers: name -> list of callbacks(value)
        self._observers: dict[str, list[Callable[[Any], None]]] = {}

        # Simple cached properties
        self._time_pos_s: float = 0.0
        self._duration_s: float = 0.0
        self._paused: bool = True
        self._idle: bool = True

        self._transport = _MpvJsonIpcTransport(self.ipc)

    # ---- lifecycle ----

    def start(self) -> None:
        if self._proc is not None:
            return

        # Ensure unix socket path is free
        if not _is_windows():
            _remove_unix_socket_if_exists(self.ipc)

        args = [self._mpv_bin]

        # Audio-only mode
        if self.config.audio_only:
            args += ["--no-video", "--audio-display=no"]

        # Keep-open controls whether mpv stays "loaded" at EOF
        args += [f"--keep-open={'yes' if self.config.keep_open else 'no'}"]

        # IPC
        args += [f"--input-ipc-server={self.ipc}"]

        # Reduce noisy console output (optional)
        args += ["--terminal=no", "--msg-level=all=warn"]

        # Start paused if requested
        if self.config.start_paused:
            args += ["--pause=yes"]

        # On Windows, hide console window if possible
        creationflags = 0
        startupinfo = None
        if _is_windows():
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=self.config.cwd or None,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )

        # Connect IPC
        self._transport.connect(timeout_s=3.0)

        # Observe core properties (mpv will emit "property-change" events)
        self.observe_property("time-pos", self._on_time_pos)
        self.observe_property("duration", self._on_duration)
        self.observe_property("pause", self._on_pause)
        self.observe_property("idle-active", self._on_idle)

        # Prime caches (best effort)
        self.get_property("pause")
        self.get_property("idle-active")
        self.get_property("duration")
        self.get_property("time-pos")

    def stop(self) -> None:
        """
        Stop playback and terminate mpv process.
        """
        try:
            self.command("stop")
        except Exception:
            pass

        self._transport.close()

        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and (self._proc.poll() is None)

    # ---- protocol helpers ----

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def command(self, *args: Any) -> None:
        """
        Fire-and-forget command (no explicit waiting).
        """
        payload = {"command": list(args)}
        self._transport.send(payload)

    def command_wait(self, *args: Any, timeout_s: float = 1.0) -> dict[str, Any]:
        """
        Send a command with request_id and wait for its response.
        """
        rid = self._next_id()
        q: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._pending[rid] = q

        payload = {"command": list(args), "request_id": rid}
        self._transport.send(payload)

        # Pump messages while waiting
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.process_messages(max_messages=50)
            try:
                return q.get_nowait()
            except queue.Empty:
                time.sleep(0.005)

        raise TimeoutError(f"mpv command timed out: {args!r}")

    def get_property(self, name: str, timeout_s: float = 1.0) -> Any:
        resp = self.command_wait("get_property", name, timeout_s=timeout_s)
        if resp.get("error") == "success":
            return resp.get("data")
        return None

    def set_property(self, name: str, value: Any) -> None:
        self.command("set_property", name, value)

    def observe_property(self, name: str, on_change: Callable[[Any], None]) -> None:
        """
        Register callback and ensure mpv observes the property.
        """
        if name not in self._observers:
            self._observers[name] = []
            # mpv: observe_property <id> <name>
            # id can be any int; we just reuse request_id space.
            obs_id = self._next_id()
            self.command("observe_property", obs_id, name)
        self._observers[name].append(on_change)

    def process_messages(self, max_messages: int = 200) -> None:
        """
        Drain incoming messages and dispatch:
          - request replies
          - property-change events
        Call this regularly (e.g., via Qt QTimer).
        """
        for _ in range(max_messages):
            msg = self._transport.recv_nowait()
            if msg is None:
                break

            # Response to a request_id
            if "request_id" in msg:
                rid = msg.get("request_id")
                if isinstance(rid, int) and rid in self._pending:
                    try:
                        self._pending[rid].put_nowait(msg)
                    except Exception:
                        pass
                    # Clean it up
                    self._pending.pop(rid, None)
                continue

            # Property change event
            if msg.get("event") == "property-change":
                name = msg.get("name")
                data = msg.get("data")
                if isinstance(name, str) and name in self._observers:
                    for cb in list(self._observers[name]):
                        try:
                            cb(data)
                        except Exception:
                            # Never let a bad observer break processing
                            continue

            # You can optionally handle other events like:
            # if msg.get("event") == "end-file": ...
            # if msg.get("event") == "file-loaded": ...

    # ---- cached property handlers ----

    def _on_time_pos(self, value: Any) -> None:
        try:
            self._time_pos_s = float(value) if value is not None else 0.0
        except Exception:
            self._time_pos_s = 0.0

    def _on_duration(self, value: Any) -> None:
        try:
            self._duration_s = float(value) if value is not None else 0.0
        except Exception:
            self._duration_s = 0.0

    def _on_pause(self, value: Any) -> None:
        self._paused = bool(value)

    def _on_idle(self, value: Any) -> None:
        self._idle = bool(value)

    # ---- high-level controls ----

    def load(self, path: str, *, start_playing: bool = True) -> None:
        # loadfile <path> [replace]
        self.command("loadfile", path, "replace")
        if start_playing:
            self.set_paused(False)

    def set_paused(self, paused: bool) -> None:
        self.set_property("pause", bool(paused))

    def pause(self) -> None:
        self.set_paused(True)

    def play(self) -> None:
        self.set_paused(False)

    def stop_playback(self) -> None:
        self.command("stop")

    def seek_seconds(self, sec: float, *, exact: bool = False) -> None:
        mode = "absolute+exact" if exact else "absolute"
        self.command("seek", float(sec), mode)

    def seek_ms(self, ms: int, *, exact: bool = False) -> None:
        ms = max(0, int(ms))
        self.seek_seconds(ms / 1000.0, exact=exact)

    def set_volume_0_to_1(self, volume: float) -> None:
        v = min(1.0, max(0.0, float(volume)))
        # mpv volume is 0..100
        self.set_property("volume", v * 100.0)

    # ---- convenience getters ----

    def position_ms(self) -> int:
        return int(self._time_pos_s * 1000.0)

    def duration_ms(self) -> int:
        return int(self._duration_s * 1000.0)

    def is_paused(self) -> bool:
        return self._paused

    def is_idle(self) -> bool:
        return self._idle
