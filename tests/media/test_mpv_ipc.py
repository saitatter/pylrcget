from __future__ import annotations

import json
import queue
import unittest
from unittest.mock import Mock, patch

from player.mpv_ipc import MpvIpcBackend, _MpvJsonIpcTransport


class _FakeSocket:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        self.payloads.append(payload)


class _QueueTransport:
    def __init__(self, *messages: dict) -> None:
        self.messages = queue.Queue()
        for message in messages:
            self.messages.put(message)
        self.sent: list[dict] = []

    def send(self, payload: dict) -> None:
        self.sent.append(payload)

    def recv_nowait(self):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        return None


class MpvIpcTransportTests(unittest.TestCase):
    def test_send_serializes_one_json_line_on_unix_socket(self):
        transport = _MpvJsonIpcTransport("/tmp/test-mpv.sock")
        fake_socket = _FakeSocket()
        transport._sock = fake_socket

        with patch("player.mpv_ipc._is_windows", return_value=False):
            transport.send({"command": ["set_property", "volume", 50]})

        self.assertEqual(len(fake_socket.payloads), 1)
        self.assertEqual(
            json.loads(fake_socket.payloads[0].decode("utf-8")),
            {"command": ["set_property", "volume", 50]},
        )
        self.assertTrue(fake_socket.payloads[0].endswith(b"\n"))

    def test_process_messages_correlates_response_and_dispatches_property_event(self):
        transport = _QueueTransport(
            {"request_id": 7, "error": "success", "data": 42},
            {"event": "property-change", "name": "time-pos", "data": 12.5},
        )
        backend = MpvIpcBackend()
        backend._transport = transport
        response_queue = queue.Queue()
        backend._pending[7] = response_queue
        observed: list[object] = []
        backend._observers["time-pos"] = [observed.append]

        backend.process_messages()

        self.assertEqual(response_queue.get_nowait()["data"], 42)
        self.assertEqual(observed, [12.5])
        self.assertNotIn(7, backend._pending)

    def test_command_timeout_removes_pending_request(self):
        transport = _QueueTransport()
        backend = MpvIpcBackend()
        backend._transport = transport

        with self.assertRaises(TimeoutError):
            backend.command_wait("get_property", "duration", timeout_s=0.01)

        self.assertEqual(transport.sent[0]["command"], ["get_property", "duration"])
        self.assertEqual(backend._pending, {})

    def test_start_cleans_up_process_when_ipc_connection_fails(self):
        process = Mock()
        process.poll.return_value = None
        backend = MpvIpcBackend()

        with (
            patch("player.mpv_ipc.subprocess.Popen", return_value=process),
            patch.object(backend._transport, "connect", side_effect=OSError("pipe unavailable")),
            patch.object(backend._transport, "close") as close,
            self.assertRaisesRegex(OSError, "pipe unavailable"),
        ):
            backend.start()

        close.assert_called_once()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=2.0)
        self.assertIsNone(backend._proc)


if __name__ == "__main__":
    unittest.main()
