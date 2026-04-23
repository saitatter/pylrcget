from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class LibraryRoute:
    tab: str
    mode: str
    artist_ids: tuple[int, ...] = ()
    album_ids: tuple[int, ...] = ()
    artist_label: str = ""
    album_label: str = ""


def serialize_route(route: LibraryRoute) -> str:
    return json.dumps(
        {
            "tab": route.tab,
            "mode": route.mode,
            "artist_ids": list(route.artist_ids),
            "album_ids": list(route.album_ids),
            "artist_label": route.artist_label,
            "album_label": route.album_label,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def deserialize_route(payload: str) -> LibraryRoute | None:
    if not (payload or "").strip():
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return LibraryRoute(
            tab=str(data.get("tab") or "tracks"),
            mode=str(data.get("mode") or "root"),
            artist_ids=tuple(int(v) for v in (data.get("artist_ids") or [])),
            album_ids=tuple(int(v) for v in (data.get("album_ids") or [])),
            artist_label=str(data.get("artist_label") or ""),
            album_label=str(data.get("album_label") or ""),
        )
    except (ValueError, TypeError, KeyError):
        return None


def route_breadcrumbs(route: LibraryRoute) -> list[tuple[str, LibraryRoute]]:
    if route.tab == "tracks":
        crumbs = [("Tracks", tracks_all())]
        if route.mode == "artist":
            crumbs.append((route.artist_label or "Artist", route))
        elif route.mode == "album":
            crumbs.append((route.album_label or "Album", route))
        return crumbs

    if route.tab == "albums":
        crumbs = [("Albums", albums_all())]
        if route.mode == "artist":
            crumbs.append((route.artist_label or "Artist", route))
        elif route.mode == "album":
            crumbs.append((route.album_label or "Album", route))
        elif route.mode == "artist_album":
            artist_route = albums_artist(route.artist_ids, label=route.artist_label)
            crumbs.append((route.artist_label or "Artist", artist_route))
            crumbs.append((route.album_label or "Album", route))
        return crumbs

    if route.tab == "artists":
        crumbs = [("Artists", artists_all())]
        if route.mode == "artist":
            crumbs.append((route.artist_label or "Artist", route))
        elif route.mode == "artist_album":
            artist_route = artists_detail(route.artist_ids, label=route.artist_label)
            crumbs.append((route.artist_label or "Artist", artist_route))
            crumbs.append((route.album_label or "Album", route))
        return crumbs

    return [(route.tab.title(), route)]


def tracks_all() -> LibraryRoute:
    return LibraryRoute(tab="tracks", mode="root")


def tracks_artist(artist_ids: tuple[int, ...], label: str = "") -> LibraryRoute:
    return LibraryRoute(tab="tracks", mode="artist", artist_ids=tuple(int(v) for v in artist_ids), artist_label=label)


def tracks_album(album_ids: tuple[int, ...], label: str = "") -> LibraryRoute:
    return LibraryRoute(tab="tracks", mode="album", album_ids=tuple(int(v) for v in album_ids), album_label=label)


def albums_all() -> LibraryRoute:
    return LibraryRoute(tab="albums", mode="root")


def albums_artist(artist_ids: tuple[int, ...], label: str = "") -> LibraryRoute:
    return LibraryRoute(tab="albums", mode="artist", artist_ids=tuple(int(v) for v in artist_ids), artist_label=label)


def albums_detail(album_ids: tuple[int, ...], label: str = "") -> LibraryRoute:
    return LibraryRoute(tab="albums", mode="album", album_ids=tuple(int(v) for v in album_ids), album_label=label)


def artists_all() -> LibraryRoute:
    return LibraryRoute(tab="artists", mode="root")


def artists_detail(artist_ids: tuple[int, ...], label: str = "") -> LibraryRoute:
    return LibraryRoute(tab="artists", mode="artist", artist_ids=tuple(int(v) for v in artist_ids), artist_label=label)


def artists_album(artist_ids: tuple[int, ...], album_ids: tuple[int, ...], artist_label: str = "", album_label: str = "") -> LibraryRoute:
    return LibraryRoute(
        tab="artists",
        mode="artist_album",
        artist_ids=tuple(int(v) for v in artist_ids),
        album_ids=tuple(int(v) for v in album_ids),
        artist_label=artist_label,
        album_label=album_label,
    )
