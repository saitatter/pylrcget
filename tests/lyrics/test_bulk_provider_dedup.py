from __future__ import annotations

from ui.workers.bulk_lyrics_download_worker import (
    BulkLyricsDownloadWorker,
    _DownloadJob,
)


def _job(*, track_id: int, isrc: str | None = "USAAA0000001", provider_id: str = "lrclib") -> _DownloadJob:
    return _DownloadJob(
        track_id=track_id,
        label="Artist - Song",
        file_path=f"C:/Music/{track_id}.mp3",
        title="Song",
        artist="Artist",
        album="Album",
        album_artist="Artist",
        track_number=1,
        isrc=isrc,
        instrumental=False,
        duration_s=180,
        has_plain_lyrics=False,
        has_synced_lyrics=False,
        cached_tidal_track_id=None,
        cached_tidal_metadata_fingerprint=None,
        provider_id=provider_id,
    )


def test_bulk_grouping_deduplicates_equivalent_recordings():
    groups = BulkLyricsDownloadWorker._group_jobs([_job(track_id=1), _job(track_id=2)])

    assert len(groups) == 1
    assert [job.track_id for job in groups[0].jobs] == [1, 2]


def test_bulk_grouping_keeps_isrc_and_provider_boundaries():
    groups = BulkLyricsDownloadWorker._group_jobs(
        [
            _job(track_id=1),
            _job(track_id=2, isrc="USAAA0000002"),
            _job(track_id=3, provider_id="tidal"),
        ]
    )

    assert len(groups) == 3
