from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import Mock, patch

HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    from PySide6.QtWidgets import QApplication

    from player.player import NowPlaying, Player, PlayerStatus


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)


class _FakeAudioOutput:
    def __init__(self) -> None:
        self.volume = 0.0

    def setVolume(self, value: float) -> None:
        self.volume = float(value)


class _FakeMediaPlayer:
    PlayingState = 1
    PausedState = 2

    def __init__(self) -> None:
        self.positionChanged = _FakeSignal()
        self.durationChanged = _FakeSignal()
        self.playbackStateChanged = _FakeSignal()
        self.mediaStatusChanged = _FakeSignal()
        self.audio_output = None
        self.source = None
        self.play_calls = 0
        self.pause_calls = 0
        self.position = 0

    def setAudioOutput(self, output) -> None:
        self.audio_output = output

    def setSource(self, source) -> None:
        self.source = source

    def play(self) -> None:
        self.play_calls += 1

    def pause(self) -> None:
        self.pause_calls += 1

    def stop(self) -> None:
        return None

    def setPosition(self, value: int) -> None:
        self.position = int(value)

    def playbackState(self) -> int:
        return self.PlayingState

    def duration(self) -> int:
        return 0

    def playbackRate(self) -> float:
        return 1.0

    def setPlaybackRate(self, _value: float) -> None:
        return None


@unittest.skipUnless(HAS_QT, "PySide6 is required for player tests")
class PlayerReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_play_file_restarts_same_track_without_reloading_source(self):
        with patch("player.player.QAudioOutput", _FakeAudioOutput), patch(
            "player.player.QMediaPlayer", _FakeMediaPlayer
        ), patch.object(Player, "_try_init_mpv", lambda self: None):
            player = Player()

        player.track = NowPlaying(
            track_id=7,
            title="Song",
            artist="Artist",
            path="C:/Music/song.mp3",
            album="Album",
        )
        player.status = PlayerStatus.PLAYING
        player.seek_ms = Mock()
        player.play = Mock()

        player.play_file(
            "C:/Music/song.mp3",
            NowPlaying(
                track_id=7,
                title="Song",
                artist="Artist",
                path="C:/Music/song.mp3",
                album="Album",
            ),
        )

        player.seek_ms.assert_called_once_with(0, exact=True)
        player.play.assert_called_once_with()
        self.assertIsNone(player.media.source)
        self.assertEqual(player.media.play_calls, 0)
