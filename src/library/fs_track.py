import os
import glob
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

# ---- Structuri ----
@dataclass
class FsTrack:
    file_path: str
    file_name: str
    title: str
    album: str
    artist: str
    album_artist: str
    duration: float
    txt_lyrics: Optional[str] = None
    lrc_lyrics: Optional[str] = None
    track_number: Optional[int] = None

    @staticmethod
    def new_from_path(path: str) -> Optional['FsTrack']:
        file_name = os.path.basename(path)
        try:
            audio = MutagenFile(path, easy=True)
            if audio is None:
                raise ValueError(f"Cannot parse file: {path}")

            title = audio.get('title', [None])[0]
            if not title:
                raise ValueError(f"No title found in: {path}")

            album = audio.get('album', [None])[0] or ''
            artist = audio.get('artist', [None])[0] or ''
            album_artist = audio.get('albumartist', [artist])[0]

            duration = float(audio.info.length) if audio.info else 0.0
            track_number = None
            if 'tracknumber' in audio:
                try:
                    track_number = int(audio['tracknumber'][0].split('/')[0])
                except Exception:
                    track_number = None

            track = FsTrack(
                file_path=path,
                file_name=file_name,
                title=title,
                album=album,
                artist=artist,
                album_artist=album_artist,
                duration=duration,
                track_number=track_number
            )
            track.txt_lyrics = track.get_txt_lyrics()
            track.lrc_lyrics = track.get_lrc_lyrics()
            return track
        except Exception as e:
            print(f"Error processing {path}: {e}")
            return None

    def get_txt_path(self) -> str:
        return str(Path(self.file_path).with_suffix('.txt'))

    def get_txt_lyrics(self) -> Optional[str]:
        txt_path = self.get_txt_path()
        if os.path.exists(txt_path):
            with open(txt_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def get_lrc_path(self) -> str:
        return str(Path(self.file_path).with_suffix('.lrc'))

    def get_lrc_lyrics(self) -> Optional[str]:
        lrc_path = self.get_lrc_path()
        if os.path.exists(lrc_path):
            with open(lrc_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None


@dataclass
class ScanProgress:
    progress: Optional[float]
    files_scanned: int
    files_count: Optional[int]


# ---- Funcții ----
def load_tracks_from_entry_batch(entry_batch: List[str]) -> List[FsTrack]:
    tracks = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(FsTrack.new_from_path, path): path for path in entry_batch}
        for future in as_completed(futures):
            track = future.result()
            if track:
                tracks.append(track)
    return tracks


def load_tracks_from_directories(directories: List[str], db_add_tracks_callback, emit_progress_callback):
    """
    db_add_tracks_callback(tracks: List[FsTrack])
    emit_progress_callback(progress: ScanProgress)
    """
    start_time = time.time()
    files_count = count_files_from_directories(directories)
    print(f"Files count: {files_count}")

    files_scanned = 0
    for directory in directories:
        entry_batch = []
        pattern = os.path.join(directory, "**", "*.*")
        for file_path in glob.glob(pattern, recursive=True):
            if file_path.lower().endswith(('.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav')):
                entry_batch.append(file_path)
                if len(entry_batch) == 100:
                    tracks = load_tracks_from_entry_batch(entry_batch)
                    db_add_tracks_callback(tracks)
                    files_scanned += len(entry_batch)
                    emit_progress_callback(ScanProgress(None, files_scanned, files_count))
                    entry_batch.clear()

        # Procesăm restul batch-ului
        if entry_batch:
            tracks = load_tracks_from_entry_batch(entry_batch)
            db_add_tracks_callback(tracks)
            files_scanned += len(entry_batch)
            emit_progress_callback(ScanProgress(None, files_scanned, files_count))

    print(f"==> Scanning tracks took: {int((time.time() - start_time)*1000)}ms")


def count_files_from_directories(directories: List[str]) -> int:
    files_count = 0
    for directory in directories:
        pattern = os.path.join(directory, "**", "*.*")
        files_count += sum(
            1 for f in glob.glob(pattern, recursive=True)
            if f.lower().endswith(('.mp3', '.m4a', '.flac', '.ogg', '.opus', '.wav'))
        )
    return files_count
